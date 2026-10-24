"""Stage handlers: ``enter()`` performs a stage's action, ``poll()`` reports its outcome.

``advance(ctx, run)`` drives one run: enter the stage when it has not been entered, poll it, and
apply the outcome (next stage, retry prompt or escalation). The agent-turn machinery shared with
the merge queue lives here too: ``send_turn`` prompts an agent and records what is awaited,
``poll_turn`` maps the agent's status and result file to an Outcome, ``handle_turn_outcome``
applies the generic outcomes (retry, re-provision, escalate).
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Any, Callable, NamedTuple

from . import follow_ups, prompts, results
from .model import (
    Escalation, EscalationKind, Outcome, Plan, Run, RunKind, RunState, RunStatus, Settings, Stage,
)
from .ports import Clock, Git, GitHub, Herdr, HerdrError, OpenIssue, Shell
from .store import Store
from .transitions import ACTIONS, next_stage

RESULT_DIR = ".herdr-spec"
BLOCKED_SCREEN_LINES = 60
TAB_KINDS = frozenset({RunKind.SPEC_REVIEW, RunKind.E2E, RunKind.FOLLOW_UPS})
# herdr errors meaning "the agent is not ready yet": the pane's shell is still booting
# (agent.start) or the agent is not registered as active yet (agent.prompt). Waited for, never
# charged to the retry budget, until ``Settings.agent_ready_timeout``.
NOT_READY_CODES = frozenset({"agent_pane_busy", "agent_not_ready"})
READY_POLL_SECONDS = 2.0

# Errors that are bugs in the engine, never a port failing: they propagate instead of being
# counted as attempts.
PROGRAMMING_ERRORS: tuple[type[BaseException], ...] = (
    KeyError, TypeError, AttributeError, NameError, AssertionError,
)


@dataclass
class Context:
    """Everything a stage handler needs: ports, plan, settings, store, paths and the state."""

    herdr: Herdr
    git: Git
    github: GitHub
    shell: Shell
    clock: Clock
    plan: Plan
    settings: Settings
    store: Store
    repo_root: str
    common_dir: str
    render: Callable[..., str] = prompts.render
    state: RunState | None = None  # set by Engine.startup()

    @property
    def spec_branch(self) -> str:
        return self.plan.branch

    def now(self) -> float:
        return self.clock.now()


# persistence and events ---------------------------------------------------------------------

def persist(ctx: Context) -> None:
    """Rewrite state.json; called after every transition."""
    ctx.state.updated_at = ctx.now()
    ctx.store.save_state(ctx.state)


def event(ctx: Context, run: Run | None, type: str, **data: Any) -> None:
    ctx.store.append_event(run.id if run else None, type, **data)


# escalations and attempts -------------------------------------------------------------------

def escalate(
    ctx: Context, run: Run, kind: EscalationKind, summary: str, details: str = "",
    awaiting: dict | None = None,
) -> Escalation:
    """Open an escalation for ``run``; the run stops being polled until it is resolved."""
    state = ctx.state
    state.seq += 1
    esc = Escalation(
        id=f"e{state.seq}", run=run.id, kind=kind, stage=run.stage, created_at=ctx.now(),
        summary=summary, details=details, actions=list(ACTIONS[kind]),
    )
    state.escalations[esc.id] = esc
    run.status = RunStatus.ESCALATED
    run.escalation = esc.id
    run.retry_at = 0.0  # a resolution acts at once, with a fresh readiness window
    run.ready_wait = None
    if awaiting is not None:
        run.awaiting = awaiting
    event(ctx, run, "escalation", id=esc.id, kind=kind.value, summary=summary)
    persist(ctx)
    return esc


def can_retry(ctx: Context, run: Run) -> bool:
    return run.attempts.get(run.stage, 0) < ctx.settings.retry_budget


def bump(run: Run) -> None:
    run.attempts[run.stage] = run.attempts.get(run.stage, 0) + 1


def is_not_ready(exc: BaseException) -> bool:
    return isinstance(exc, HerdrError) and exc.code in NOT_READY_CODES


def not_ready(agent: str, why: str) -> HerdrError:
    return HerdrError("agent_not_ready", f"agent {agent} {why}")


def backoff(ctx: Context, attempt: int) -> float:
    """Delay before retry number ``attempt`` (1-based): doubling from ``retry_backoff``, capped."""
    s = ctx.settings
    return min(s.retry_backoff_max, s.retry_backoff * 2 ** max(0, attempt - 1))


def ready_waiting(ctx: Context, run: Run) -> bool:
    """True while ``run`` must not be stepped yet (backoff or readiness poll pending)."""
    return ctx.now() < run.retry_at


def agent_ready(ctx: Context, run: Run) -> None:
    """A step went through: end the run's readiness wait, if any."""
    if run.ready_wait is not None:
        event(ctx, run, "agent_ready", stage=run.stage.value,
              waited=round(ctx.now() - run.ready_wait["since"], 3))
        run.ready_wait = None


def port_failure(ctx: Context, run: Run, exc: BaseException) -> None:
    """A port raised. "Not ready yet" errors are polled again shortly, uncharged, until
    ``agent_ready_timeout``; anything else (or readiness past the deadline) counts an attempt
    retried after a backoff, or escalates when the budget is spent."""
    now = ctx.now()
    error = str(exc)
    if is_not_ready(exc):
        wait = run.ready_wait or {"since": now}
        first = run.ready_wait is None
        wait.update(code=exc.code, error=error)
        run.ready_wait = wait
        waited = now - wait["since"]
        if waited < ctx.settings.agent_ready_timeout:
            run.retry_at = now + READY_POLL_SECONDS
            if first:
                event(ctx, run, "agent_not_ready", stage=run.stage.value, error=error)
            persist(ctx)
            return
        error = f"agent not ready after {waited:g}s: {exc}"
    if can_retry(ctx, run):
        bump(run)
        delay = backoff(ctx, run.attempts[run.stage])
        run.retry_at = now + delay
        event(ctx, run, "port_error", stage=run.stage.value, error=error, retry_in=delay)
        persist(ctx)
        return
    escalate(ctx, run, EscalationKind.BUDGET_EXHAUSTED,
             f"{run.stage.value} failed after {run.attempts.get(run.stage, 0) + 1} attempts: {error}",
             details=f"{type(exc).__name__}: {exc}")


# agents and result files ----------------------------------------------------------------------

def result_path(run: Run, name: str) -> str:
    """``<agent_cwd>/.herdr-spec/<run_id>.<name>.json``."""
    return os.path.join(run.worktree or "", RESULT_DIR, f"{run.id}.{name}.json")


def instructions_path(path: str) -> str:
    """``<run_id>.<name>.prompt.md`` next to the result file ``path``."""
    return path[:-len(".json")] + ".prompt.md" if path.endswith(".json") else path + ".prompt.md"


def as_sent(path: str, text: str) -> str:
    """The prompt as typed into the agent: a rendered prompt starting with a slash command goes
    as that command on one short line, the rest written to the instructions file beside the
    result file (kept, so a re-sent prompt still finds it)."""
    split = prompts.split_command(text)
    if split is None:
        return text
    command, rest = split
    file = instructions_path(path)
    os.makedirs(os.path.dirname(file), exist_ok=True)
    with open(file, "w", encoding="utf-8") as f:
        f.write(rest)
    return prompts.command_line(command, file)


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def reprovision(ctx: Context, run: Run) -> None:
    """Give ``run`` a fresh agent: reopen its worktree (or a new tab) and start the agent.

    Resumable: once the new pane exists ``run.agent`` is None, so a start that fails (e.g. the
    pane's shell is still booting) is retried in that pane, not in yet another one."""
    if run.agent is not None:
        if run.kind in TAB_KINDS:
            run.pane_id = ctx.herdr.create_tab(ctx.repo_root, run.id)
            run.worktree = ctx.repo_root
        else:
            wt = ctx.herdr.open_worktree(ctx.repo_root, run.id, run.id)
            run.workspace_id, run.pane_id, run.worktree = wt.workspace_id, wt.pane_id, wt.path
        run.agent = None
        persist(ctx)
    start_run_agent(ctx, run)
    event(ctx, run, "reprovisioned", pane=run.pane_id)


def ensure_agent(ctx: Context, run: Run) -> None:
    """Re-provision the run's own agent when herdr no longer knows it. A just-started agent
    herdr has not registered yet is waited for (``agent_ready_timeout``) instead."""
    if run.agent is not None:
        if ctx.herdr.agent_status(run.agent) != "missing":
            run.agent_pending_since = None
            return
        if run.agent_pending_since is not None and \
                ctx.now() - run.agent_pending_since < ctx.settings.agent_ready_timeout:
            raise not_ready(run.agent, "is not registered yet")
    reprovision(ctx, run)


def common_vars(ctx: Context, path: str, schema: str) -> dict[str, Any]:
    return {"spec": ctx.plan.spec, "spec_title": ctx.plan.title, "result_path": path,
            "result_example": results.example(schema)}


def send_turn(
    ctx: Context, run: Run, *, template: str, schema: str, name: str, agent: str | None = None,
    extra: dict | None = None, **vars: Any,
) -> None:
    """Prompt an agent with ``template`` and await its ``schema`` result at ``name``'s path."""
    if agent is None or agent == run.id:
        ensure_agent(ctx, run)
        agent = run.agent
    path = result_path(run, name)
    text = as_sent(path, ctx.render(template, **common_vars(ctx, path, schema), **vars))
    _remove(path)
    ctx.herdr.prompt_agent(agent, text)
    now = ctx.now()
    run.stage_started_at = now
    run.awaiting = {"type": "agent_turn", "agent": agent, "result": schema, "path": path,
                    "prompted_at": now, "text": text, **(extra or {})}
    event(ctx, run, "prompt", template=template, agent=agent)


def resend_turn(ctx: Context, run: Run) -> None:
    """Re-send the awaited turn's original prompt (re-provisioning the run's agent if gone).

    ``awaiting["resend"]`` marks the resend as pending until the prompt went through, so a
    resend interrupted by a not-ready agent is completed by the next ``poll_turn``."""
    aw = run.awaiting
    aw["resend"] = True
    if aw["agent"] == run.id:
        ensure_agent(ctx, run)
    _remove(aw["path"])
    ctx.herdr.prompt_agent(aw["agent"], aw["text"])
    aw.pop("resend", None)
    _restart_turn_clock(ctx, run)
    event(ctx, run, "prompt_resent", agent=aw["agent"])


def _retry_result(ctx: Context, run: Run) -> None:
    aw = run.awaiting
    text = ctx.render("result_retry", **common_vars(ctx, aw["path"], aw["result"]),
                      error=aw.get("error", ""))
    _remove(aw["path"])
    ctx.herdr.prompt_agent(aw["agent"], text)
    _restart_turn_clock(ctx, run)
    event(ctx, run, "prompt", template="result_retry", agent=aw["agent"])


def _restart_turn_clock(ctx: Context, run: Run) -> None:
    now = ctx.now()
    run.stage_started_at = now
    run.awaiting["prompted_at"] = now
    run.awaiting.pop("unknown_since", None)
    run.awaiting.pop("error", None)


def _archive(ctx: Context, run: Run, name: str, value: dict) -> None:
    attempt = 1
    while os.path.exists(os.path.join(ctx.store.paths.out, f"{run.id}.{name}.{attempt}.json")):
        attempt += 1
    ctx.store.archive_result(run.id, name, attempt, value)


def poll_turn(ctx: Context, run: Run) -> Outcome | None:
    """The outcome of the awaited agent turn, or None while it is still running."""
    aw = run.awaiting
    if aw.get("resend"):
        resend_turn(ctx, run)
        return None
    now = ctx.now()
    status = ctx.herdr.agent_status(aw["agent"])
    if status != "unknown":
        aw.pop("unknown_since", None)
    if status == "missing":
        return Outcome.AGENT_LOST
    if status == "blocked":
        # Right after an `answered` resolution herdr's screen-based status can still say
        # blocked; only a block that outlives the settle window is a new one.
        if now - aw.get("answered_at", -math.inf) < ctx.settings.settle_seconds:
            return None
        return Outcome.AGENT_BLOCKED
    if status == "unknown":
        since = aw.setdefault("unknown_since", now)
        return Outcome.AGENT_UNKNOWN if now - since >= ctx.settings.unknown_grace else None
    if status in ("idle", "done"):
        if now - aw["prompted_at"] < ctx.settings.settle_seconds:
            return None
        value, error = results.read_result(aw["path"], aw["result"])
        if error:
            aw["error"] = error
            return Outcome.RESULT_INVALID
        name = os.path.basename(aw["path"]).split(".")[-2]
        _archive(ctx, run, name, value)
        _remove(aw["path"])
        aw["value"] = value
        return Outcome.OK
    if now - run.stage_started_at > ctx.settings.stage_timeout:
        return Outcome.TIMEOUT
    return None


def handle_turn_outcome(ctx: Context, run: Run, outcome: Outcome) -> None:
    """Apply a non-OK agent-turn outcome: retry within budget, re-provision, or escalate."""
    aw = run.awaiting
    stage = run.stage.value
    if outcome is Outcome.RESULT_INVALID:
        if can_retry(ctx, run):
            _retry_result(ctx, run)
            bump(run)
        else:
            escalate(ctx, run, EscalationKind.BUDGET_EXHAUSTED,
                     f"{stage}: result file still invalid after retries", details=aw.get("error", ""))
    elif outcome is Outcome.AGENT_BLOCKED:
        escalate(ctx, run, EscalationKind.AGENT_BLOCKED, f"{aw['agent']} is blocked in {stage}",
                 details=_screen(ctx, aw["agent"]))
    elif outcome is Outcome.TIMEOUT:
        escalate(ctx, run, EscalationKind.STAGE_TIMEOUT,
                 f"{aw['agent']} still working on {stage} after {ctx.settings.stage_timeout:g}s",
                 details=_screen(ctx, aw["agent"]))
    elif outcome is Outcome.AGENT_UNKNOWN:
        escalate(ctx, run, EscalationKind.AGENT_UNKNOWN,
                 f"{aw['agent']} status unknown for {ctx.settings.unknown_grace:g}s in {stage}",
                 details=_screen(ctx, aw["agent"]))
    elif outcome is Outcome.AGENT_LOST:
        if can_retry(ctx, run):
            bump(run)
            event(ctx, run, "agent_lost", agent=aw["agent"])
            resend_turn(ctx, run)
        else:
            escalate(ctx, run, EscalationKind.BUDGET_EXHAUSTED,
                     f"{aw['agent']} lost in {stage} and the retry budget is spent")
    else:
        raise AssertionError(f"unexpected turn outcome {outcome}")
    persist(ctx)


def _screen(ctx: Context, agent: str) -> str:
    try:
        return ctx.herdr.read_agent(agent, BLOCKED_SCREEN_LINES)
    except Exception as exc:  # noqa: BLE001 - details are best effort
        if isinstance(exc, PROGRAMMING_ERRORS):
            raise
        return f"(could not read agent screen: {exc})"


# best-effort teardown -----------------------------------------------------------------------

def best_effort(ctx: Context, run: Run, what: str, fn: Callable[[], Any]) -> None:
    try:
        fn()
    except PROGRAMMING_ERRORS:
        raise
    except Exception as exc:  # noqa: BLE001
        event(ctx, run, "cleanup_error", what=what, error=str(exc))


def remove_worktree(ctx: Context, run: Run, force: bool = False) -> None:
    """Remove the run's worktree (branch kept). ``force`` drops untracked/modified files: only
    after the branch is merged, when leftovers are gate artifacts (build output, logs)."""
    if run.workspace_id:
        ctx.herdr.remove_worktree(run.workspace_id, force=force)
        event(ctx, run, "worktree_removed", workspace=run.workspace_id)
        run.workspace_id = None


def close_resolver(ctx: Context, run: Run) -> None:
    aw = run.awaiting or {}
    if aw.get("type") == "resolver" and aw.get("pane_id"):
        best_effort(ctx, run, "close resolver pane", lambda: ctx.herdr.close_pane(aw["pane_id"]))


def teardown(ctx: Context, run: Run) -> None:
    """Interrupt the agent, close a resolver pane, remove the worktree, leave the queue."""
    close_resolver(ctx, run)
    if run.agent:
        best_effort(ctx, run, "interrupt", lambda: ctx.herdr.interrupt_agent(run.agent))
    best_effort(ctx, run, "remove worktree", lambda: remove_worktree(ctx, run))
    if run.id in ctx.state.queue:
        ctx.state.queue.remove(run.id)


def reenter(ctx: Context, run: Run) -> None:
    """Reset the stage's attempts and enter it again (``retry`` on budget-exhausted)."""
    aw = run.awaiting or {}
    if aw.get("type") == "resolver":
        close_resolver(ctx, run)
        best_effort(ctx, run, "merge --abort", lambda: ctx.git.merge_abort(run.worktree))
    run.attempts[run.stage] = 0
    run.status = RunStatus.ACTIVE
    run.stage_started_at = ctx.now()
    if run.stage is Stage.INTEGRATE:
        run.gate_attempts = 0
        run.awaiting = {"type": "queue"}
        if run.id not in ctx.state.queue:
            ctx.state.queue.append(run.id)
    elif (run.stage, aw.get("type")) in ((Stage.CLOSE, "close"), (Stage.E2E_REPORT, "e2e_report")):
        pass  # keep the finished steps: a retry never comments or closes twice
    else:
        run.awaiting = None


# prompt variables ---------------------------------------------------------------------------

def ticket_title(ctx: Context, number: int | None) -> str:
    t = ctx.plan.ticket(number) if number is not None else None
    return t.title if t else ""


def format_finding(finding: dict | None) -> str:
    f = finding or {}
    where = f.get("file", "")
    if f.get("line") is not None:
        where = f"{where}:{f['line']}"
    return (f"{f.get('title', '')} ({f.get('severity', '')})\n"
            f"File: {where}\nFailure scenario: {f.get('failure_scenario', '')}")


def _ticket_list(ctx: Context, runs: list[Run]) -> str:
    lines = [f"- #{r.ticket} {ticket_title(ctx, r.ticket)} ({r.id})" for r in runs]
    return "\n".join(lines) or "none"


def _integrated(ctx: Context) -> str:
    return _ticket_list(ctx, [r for r in ctx.state.runs.values()
                              if r.kind is RunKind.TICKET and r.merge_commit])


def _siblings(ctx: Context, run: Run) -> str:
    return _ticket_list(ctx, [r for r in ctx.state.runs.values()
                              if r.kind is RunKind.TICKET and r.id != run.id
                              and r.status in (RunStatus.ACTIVE, RunStatus.ESCALATED)
                              and r.stage is not Stage.CLAIM])


# stage handlers -----------------------------------------------------------------------------

SYNC = {"type": "sync"}


def _poll_sync(ctx: Context, run: Run) -> Outcome | None:
    return Outcome.OK


def _enter_claim(ctx: Context, run: Run) -> None:
    ctx.github.assign_self(run.ticket)
    run.awaiting = dict(SYNC)


def start_run_agent(ctx: Context, run: Run) -> None:
    """Start the run's own agent in its pane, or adopt it when herdr already runs it in that pane
    (an earlier ``agent.start`` failed on our side — socket timeout, Ctrl-C — after herdr
    started it). A same-named agent in another pane is not ours: names are global to herdr."""
    if run.pane_id is not None and ctx.herdr.agent_pane(run.id) == run.pane_id:
        event(ctx, run, "agent_adopted", agent=run.id)
    else:
        ctx.herdr.start_agent(run.id, run.pane_id, ctx.settings.agent_args)
    run.agent = run.id
    run.agent_pending_since = ctx.now()


def _enter_provision(ctx: Context, run: Run) -> None:
    if run.workspace_id is None:
        if ctx.git.branch_exists(ctx.repo_root, run.id):
            wt = ctx.herdr.open_worktree(ctx.repo_root, run.id, run.id)
        else:
            wt = ctx.herdr.create_worktree(ctx.repo_root, run.id, ctx.spec_branch, run.id)
        run.workspace_id, run.pane_id, run.worktree = wt.workspace_id, wt.pane_id, wt.path
    if run.agent is None:
        start_run_agent(ctx, run)
    run.awaiting = {"type": "agent_ready"}


def _poll_agent_ready(ctx: Context, run: Run) -> Outcome | None:
    """Provision is done once herdr has registered the started agent; until then (bounded by
    ``agent_ready_timeout``) the first prompt would fail with ``agent_not_ready``."""
    status = ctx.herdr.agent_status(run.agent)
    if status != "missing":
        run.agent_pending_since = None
        return Outcome.OK
    if ctx.now() - (run.agent_pending_since or 0.0) < ctx.settings.agent_ready_timeout:
        raise not_ready(run.agent, "is not registered yet")
    run.agent = None  # gone: start it again on re-entry
    run.awaiting = None
    raise not_ready(run.id, f"not registered {ctx.settings.agent_ready_timeout:g}s after start")


def _enter_provision_tab(ctx: Context, run: Run) -> None:
    if run.pane_id is None:
        run.pane_id = ctx.herdr.create_tab(ctx.repo_root, run.id)
        run.worktree = ctx.repo_root
    if run.agent is None:
        start_run_agent(ctx, run)
    run.awaiting = {"type": "agent_ready"}


def _enter_implement(ctx: Context, run: Run) -> None:
    if run.kind is RunKind.FIX:
        send_turn(ctx, run, template="fix_implement", schema="implement", name="implement",
                  branch=run.id, spec_branch=ctx.spec_branch, finding=format_finding(run.finding))
    else:
        send_turn(ctx, run, template="implement", schema="implement", name="implement",
                  ticket=run.ticket, ticket_title=ticket_title(ctx, run.ticket), branch=run.id,
                  spec_branch=ctx.spec_branch, integrated=_integrated(ctx),
                  siblings=_siblings(ctx, run))


def _complete_implement(ctx: Context, run: Run, value: dict) -> None:
    if value.get("status") == "outward-denied":
        denied = "\n".join(f"- {a}" for a in value.get("denied_actions", []))
        escalate(ctx, run, EscalationKind.OUTWARD_ACTION_DENIED,
                 f"{run.id} needs outward actions it may not take",
                 details=f"{value.get('summary', '')}\n{denied}".strip())
        return
    goto_next(ctx, run)


def _enter_verify(ctx: Context, run: Run) -> None:
    run.awaiting = {"type": "verify"}


def _poll_verify(ctx: Context, run: Run) -> Outcome | None:
    if run.awaiting.get("type") == "agent_turn":
        outcome = poll_turn(ctx, run)
        if outcome is not Outcome.OK:
            return outcome
        run.awaiting = {"type": "verify"}
    problem = verify_problem(ctx, run)
    if problem:
        run.awaiting["problem"] = problem
        return Outcome.VERIFY_FAILED
    return Outcome.OK


def verify_problem(ctx: Context, run: Run) -> str | None:
    """Why the run's branch is not ready for review, or None."""
    problems = []
    if ctx.git.commits_ahead(run.worktree, ctx.spec_branch, run.id) <= 0:
        problems.append(f"branch {run.id} has no commits ahead of {ctx.spec_branch}")
    if not ctx.git.is_clean(run.worktree):
        problems.append(f"the worktree {run.worktree} has uncommitted changes")
    return "; ".join(problems) or None


def _verify_failed(ctx: Context, run: Run) -> None:
    problem = run.awaiting.get("problem", "")
    if not can_retry(ctx, run):
        escalate(ctx, run, EscalationKind.BUDGET_EXHAUSTED,
                 f"{run.id} still fails verification", details=problem)
        return
    work = (f"ticket #{run.ticket}" if run.ticket is not None
            else f"the spec review finding \"{(run.finding or {}).get('title', '')}\"")
    send_turn(ctx, run, template="verify_failed", schema="implement", name="verify",
              ticket=work, branch=run.id,
              spec_branch=ctx.spec_branch, problem=problem)
    bump(run)  # after the prompt went through: a not-ready agent is not an attempt


def _enter_review(ctx: Context, run: Run) -> None:
    if run.kind is RunKind.FIX:
        send_turn(ctx, run, template="fix_review", schema="review", name="review",
                  spec_branch=ctx.spec_branch, finding=format_finding(run.finding))
    else:
        send_turn(ctx, run, template="review", schema="review", name="review",
                  ticket=run.ticket, spec_branch=ctx.spec_branch)


def _store_result(ctx: Context, run: Run, value: dict) -> None:
    run.review = value
    goto_next(ctx, run)


def _enter_integrate(ctx: Context, run: Run) -> None:
    if run.id not in ctx.state.queue:
        ctx.state.queue.append(run.id)
    run.awaiting = {"type": "queue"}
    event(ctx, run, "enqueued", position=ctx.state.queue.index(run.id))


def _poll_integrate(ctx: Context, run: Run) -> Outcome | None:
    if run.merge_commit and run.id not in ctx.state.queue:
        return Outcome.INTEGRATED
    return None


def _enter_close(ctx: Context, run: Run) -> None:
    run.awaiting = {"type": "close", "done": []}


def _poll_close(ctx: Context, run: Run) -> Outcome | None:
    done = run.awaiting.setdefault("done", [])

    def step(name: str, fn: Callable[[], Any]) -> None:
        if name not in done:
            fn()
            done.append(name)

    if run.kind is RunKind.TICKET:
        step("comment", lambda: ctx.github.comment(run.ticket, close_comment(ctx, run)))
        if pending_spec_findings(run):
            step("note", lambda: run.notes.append("left open on GitHub: pending spec finding"))
        else:
            step("close", lambda: ctx.github.close(run.ticket))
    step("remove_worktree", lambda: remove_worktree(ctx, run, force=True))
    return Outcome.OK


def pending_spec_findings(run: Run) -> list[dict]:
    return [p for p in (run.review or {}).get("pending", []) if p.get("kind") == "spec"]


def close_comment(ctx: Context, run: Run) -> str:
    review = run.review or {}
    lines = [f"Merged into `{ctx.spec_branch}` as {run.merge_commit} by herdr-spec-engine "
             f"(spec #{ctx.plan.spec})."]
    if review.get("pending"):
        lines += ["", "Pending review findings:"]
        lines += [f"- [{p['kind']}] {p['title']}: {p['reason']}" for p in review["pending"]]
    if review.get("scope_creep"):
        lines += ["", "Scope creep noted:"] + [f"- {s}" for s in review["scope_creep"]]
    if pending_spec_findings(run):
        lines += ["", "Left open: a pending spec finding must be addressed before closing."]
    return "\n".join(lines)


def _enter_await_human(ctx: Context, run: Run) -> None:
    issue = ctx.github.issue(run.ticket)
    if issue.state == "CLOSED":
        run.awaiting = dict(SYNC)
        return
    escalate(ctx, run, EscalationKind.HITL_TICKET,
             f"#{run.ticket} {ticket_title(ctx, run.ticket)} must be done by a human",
             details=issue.url, awaiting={"type": "escalation"})


def _poll_synced(ctx: Context, run: Run) -> Outcome | None:
    """OK once a resolution set ``awaiting`` to sync (stages that wait on the supervisor)."""
    return Outcome.OK if run.awaiting.get("type") == "sync" else None


def _enter_spec_review(ctx: Context, run: Run) -> None:
    send_turn(ctx, run, template="spec_review", schema="spec_review", name="spec_review",
              spec_branch=ctx.spec_branch, base=ctx.plan.base)


def _e2e_tickets(ctx: Context) -> tuple[str, str]:
    """Bullet lists of the tickets whose criteria E2E tests (closed before the run, merged or
    done by a human) and of those it must not (left open, skipped)."""
    integrated, not_integrated = [], []
    runs = {r.ticket: r for r in ctx.state.runs.values()
            if r.kind in (RunKind.TICKET, RunKind.HUMAN)}
    for t in sorted(ctx.plan.tickets, key=lambda t: t.number):
        run = runs.get(t.number)
        line = f"- #{t.number} {t.title}"
        if run is None or run.status is RunStatus.DONE:
            (integrated if run is not None or t.klass.value == "done" else not_integrated
             ).append(line)
        else:
            not_integrated.append(f"{line} ({run.status.value})")
    return "\n".join(integrated) or "none", "\n".join(not_integrated) or "none"


def _enter_e2e(ctx: Context, run: Run) -> None:
    tickets, not_integrated = _e2e_tickets(ctx)
    send_turn(ctx, run, template="e2e", schema="e2e", name="e2e", spec_branch=ctx.spec_branch,
              tickets=tickets, not_integrated=not_integrated)


def _enter_e2e_report(ctx: Context, run: Run) -> None:
    run.awaiting = {"type": "e2e_report", "done": []}


def _poll_e2e_report(ctx: Context, run: Run) -> Outcome | None:
    """Post the E2E verdict and AC table on the spec issue, once (a retry never re-posts)."""
    done = run.awaiting.setdefault("done", [])
    if "comment" not in done:
        ctx.github.comment(ctx.plan.spec, e2e_comment(ctx, run.review or {}))
        done.append("comment")
    return Outcome.OK


def _cell(text: Any) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def e2e_lines(result: dict) -> list[str]:
    """The E2E result as Markdown: verdict, the AC table, fixes, pending, collateral, notes.
    Shared by the spec issue comment and report.md. Results from before per-AC verdicts
    (``passed``) are listed as they were."""
    lines = [f"Verdict: **{result.get('verdict', 'unknown')}**"]
    if result.get("blocked_by"):
        lines.append(f"Blocked by: {result['blocked_by']}")
    acs = result.get("acs") or []
    if acs:
        lines += ["", "| Ticket | AC | Criterion | Verdict | Evidence |",
                  "| --- | --- | --- | --- | --- |"]
        lines += [f"| #{a['ticket']} | {_cell(a['ac'])}{' (derived)' if a.get('derived') else ''}"
                  f" | {_cell(a['criterion'])} | {a['verdict']} | {_cell(a['evidence'])} |"
                  for a in acs]
    if result.get("passed"):
        lines += ["", f"Passed ({len(result['passed'])}):"] + [f"- {p}" for p in result["passed"]]
    sections = (
        ("Fixed", [f"{f['title']} ({f['commit']})" for f in result.get("fixed", [])]),
        ("Pending", [f"{p['title']}: {p['reason']}" for p in result.get("pending", [])]),
        ("Collateral", [f"[{c['severity']}] {c['title']} — {c['action']}"
                        f"{'' if c.get('caused_by_spec') else ' (pre-existing)'}: {c['detail']}"
                        for c in result.get("collateral", [])]),
        ("Notes", list(result.get("notes", []))),
    )
    for title, items in sections:
        if items or title in ("Fixed", "Pending"):
            lines += ["", f"{title} ({len(items)}):"] + ([f"- {i}" for i in items] or ["- none"])
    return lines


def e2e_comment(ctx: Context, result: dict) -> str:
    return "\n".join([f"E2E of spec #{ctx.plan.spec} on `{ctx.spec_branch}` by "
                      f"herdr-spec-engine.", "", *e2e_lines(result), "",
                      f"The spec branch `{ctx.spec_branch}` is local; nothing was pushed."])


def _collect(ctx: Context, run: Run) -> None:
    if run.review is None:
        entries = follow_ups.collect(ctx.state.runs.values(), ctx.github.open_issues())
        run.review = {"follow_ups": entries}


def _enter_collect(ctx: Context, run: Run) -> None:
    """Collect the reviews' follow-ups once (merged, matched by title against open issues)."""
    _collect(ctx, run)
    run.awaiting = dict(SYNC)


def _complete_collect(ctx: Context, run: Run, value: dict) -> None:
    """Nothing left to propose: no dedup agent, straight to FOLLOW_UPS."""
    goto_next(ctx, run)
    if not follow_ups.proposed(run.review["follow_ups"]):
        event(ctx, run, "stage", frm=run.stage.value, to=Stage.FOLLOW_UPS.value,
              reason="nothing to dedup")
        run.stage = Stage.FOLLOW_UPS


def _enter_dedup(ctx: Context, run: Run) -> None:
    """Open the dedup agent's tab and prompt it. Any failure but a not-ready wait drops the
    dedup (``_dedup_fallback``): it only refines the title match, so it never blocks the run."""
    try:
        if run.pane_id is None:
            run.pane_id = ctx.herdr.create_tab(ctx.repo_root, run.id)
            run.worktree = ctx.repo_root
            persist(ctx)
        if run.agent is None:
            start_run_agent(ctx, run)
            persist(ctx)
        send_turn(ctx, run, template="dedup", schema="dedup", name="dedup",
                  candidates=follow_ups.candidates(run.review["follow_ups"]))
    except PROGRAMMING_ERRORS:
        raise
    except Exception as exc:  # noqa: BLE001
        since = (run.ready_wait or {}).get("since", ctx.now())
        if is_not_ready(exc) and ctx.now() - since < ctx.settings.agent_ready_timeout:
            raise  # port_failure waits for the agent, uncharged
        _dedup_fallback(ctx, run, f"{type(exc).__name__}: {exc}")


def _poll_dedup(ctx: Context, run: Run) -> Outcome | None:
    if run.awaiting.get("type") == "sync":
        return Outcome.OK
    outcome = poll_turn(ctx, run)
    if outcome is None:
        if ctx.now() - run.stage_started_at > ctx.settings.dedup_timeout:
            _dedup_fallback(ctx, run, f"no result after {ctx.settings.dedup_timeout:g}s")
            return Outcome.OK
        return None
    if outcome is Outcome.OK:
        return outcome
    if outcome is Outcome.RESULT_INVALID and can_retry(ctx, run):
        return outcome  # the generic retry prompt
    if outcome is Outcome.AGENT_LOST and can_retry(ctx, run):
        return outcome  # the generic re-provision and resend
    _dedup_fallback(ctx, run, f"{outcome.value}: {run.awaiting.get('error', '')}".rstrip(": "))
    return Outcome.OK


def _dedup_fallback(ctx: Context, run: Run, reason: str) -> None:
    run.notes.append(f"follow-up dedup dropped ({reason}); matched by title only")
    event(ctx, run, "dedup_dropped", reason=reason)
    _close_dedup_tab(ctx, run)
    run.awaiting = {"type": "sync", "value": {}}


def _close_dedup_tab(ctx: Context, run: Run) -> None:
    if run.agent:
        best_effort(ctx, run, "interrupt", lambda: ctx.herdr.interrupt_agent(run.agent))
    if run.pane_id:
        best_effort(ctx, run, "close dedup tab", lambda: ctx.herdr.close_pane(run.pane_id))
    run.agent = run.pane_id = None


def _complete_dedup(ctx: Context, run: Run, value: dict) -> None:
    """Apply the dedup verdicts; an issue that cannot be confirmed open is not trusted."""

    def open_issue(number: int) -> OpenIssue | None:
        try:
            issue = ctx.github.issue(number)
        except PROGRAMMING_ERRORS:
            raise
        except Exception:  # noqa: BLE001 - unconfirmed: the follow-up stays proposed
            return None
        if issue.state != "OPEN":
            return None
        return OpenIssue(number=issue.number, title=issue.title, url=issue.url)

    if value:
        run.notes += follow_ups.apply_dedup(run.review["follow_ups"], value, open_issue)
        _close_dedup_tab(ctx, run)
    goto_next(ctx, run)


def _enter_follow_ups(ctx: Context, run: Run) -> None:
    """Propose the new follow-ups to the supervisor (collected by COLLECT; a state saved
    before that stage existed collects here)."""
    _collect(ctx, run)
    entries = run.review["follow_ups"]
    new = follow_ups.proposed(entries)
    if not new:
        run.awaiting = dict(SYNC)
        return
    escalate(ctx, run, EscalationKind.FOLLOW_UPS,
             f"{len(new)} follow-up issue(s) proposed by the reviews; create them?",
             details=follow_ups.details(entries), awaiting={"type": "escalation"})


class Handler(NamedTuple):
    enter: Callable[[Context, Run], None]
    poll: Callable[[Context, Run], Outcome | None]
    complete: Callable[[Context, Run, dict], None] | None = None


HANDLERS: dict[Stage, Handler] = {
    Stage.CLAIM: Handler(_enter_claim, _poll_sync),
    Stage.PROVISION: Handler(_enter_provision, _poll_agent_ready),
    Stage.IMPLEMENT: Handler(_enter_implement, poll_turn, _complete_implement),
    Stage.VERIFY: Handler(_enter_verify, _poll_verify),
    Stage.REVIEW: Handler(_enter_review, poll_turn, _store_result),
    Stage.INTEGRATE: Handler(_enter_integrate, _poll_integrate),
    Stage.CLOSE: Handler(_enter_close, _poll_close),
    Stage.AWAIT_HUMAN: Handler(_enter_await_human, _poll_synced),
    Stage.PROVISION_TAB: Handler(_enter_provision_tab, _poll_agent_ready),
    Stage.SPEC_REVIEW: Handler(_enter_spec_review, poll_turn, _store_result),
    Stage.E2E: Handler(_enter_e2e, poll_turn, _store_result),
    Stage.E2E_REPORT: Handler(_enter_e2e_report, _poll_e2e_report),
    Stage.COLLECT: Handler(_enter_collect, _poll_sync, _complete_collect),
    Stage.DEDUP: Handler(_enter_dedup, _poll_dedup, _complete_dedup),
    Stage.FOLLOW_UPS: Handler(_enter_follow_ups, _poll_synced),
}


# driving a run ------------------------------------------------------------------------------

def goto_next(ctx: Context, run: Run) -> None:
    """Move to the kind's next stage, or finish the run as ``done`` after its last stage."""
    nxt = next_stage(run.kind, run.stage)
    run.awaiting = None
    run.stage_started_at = ctx.now()
    if nxt is None:
        run.status = RunStatus.DONE
        event(ctx, run, "done", stage=run.stage.value)
    else:
        event(ctx, run, "stage", frm=run.stage.value, to=nxt.value)
        run.stage = nxt


def apply_outcome(ctx: Context, run: Run, outcome: Outcome) -> None:
    event(ctx, run, "outcome", stage=run.stage.value, outcome=outcome.value)
    if outcome in (Outcome.OK, Outcome.INTEGRATED):
        handler = HANDLERS[run.stage]
        value = (run.awaiting or {}).get("value") or {}
        if handler.complete:
            handler.complete(ctx, run, value)
        else:
            goto_next(ctx, run)
    elif outcome is Outcome.VERIFY_FAILED:
        _verify_failed(ctx, run)
    else:
        handle_turn_outcome(ctx, run, outcome)
    persist(ctx)


def _step(ctx: Context, run: Run) -> bool:
    """One enter/poll/transition; True when the run moved on to a new stage."""
    stage = run.stage
    try:
        handler = HANDLERS[stage]
        if run.awaiting is None:
            handler.enter(ctx, run)
            persist(ctx)
            if run.status is not RunStatus.ACTIVE:
                return False
        outcome = handler.poll(ctx, run)
        if outcome is not None:
            apply_outcome(ctx, run, outcome)
        agent_ready(ctx, run)
        if outcome is None:
            return False
    except PROGRAMMING_ERRORS:
        raise
    except Exception as exc:  # noqa: BLE001 - any port failure counts as an attempt
        port_failure(ctx, run, exc)
        return False
    return run.stage is not stage and run.status is RunStatus.ACTIVE


def advance(ctx: Context, run: Run, max_steps: int = 10) -> None:
    """Advance an active run until it waits; synchronous stages chain within one call."""
    for _ in range(max_steps):
        if run.status is not RunStatus.ACTIVE or ready_waiting(ctx, run) or not _step(ctx, run):
            return
