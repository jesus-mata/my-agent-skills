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

from . import prompts, results
from .model import (
    Escalation, EscalationKind, Outcome, Plan, Run, RunKind, RunState, RunStatus, Settings, Stage,
)
from .ports import Clock, Git, GitHub, Herdr, Shell
from .store import Store
from .transitions import ACTIONS, next_stage

RESULT_DIR = ".herdr-spec"
BLOCKED_SCREEN_LINES = 60
TAB_KINDS = frozenset({RunKind.SPEC_REVIEW, RunKind.E2E})

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
    if awaiting is not None:
        run.awaiting = awaiting
    event(ctx, run, "escalation", id=esc.id, kind=kind.value, summary=summary)
    persist(ctx)
    return esc


def can_retry(ctx: Context, run: Run) -> bool:
    return run.attempts.get(run.stage, 0) < ctx.settings.retry_budget


def bump(run: Run) -> None:
    run.attempts[run.stage] = run.attempts.get(run.stage, 0) + 1


def port_failure(ctx: Context, run: Run, exc: BaseException) -> None:
    """A port raised: count an attempt and retry next tick, or escalate when exhausted."""
    if can_retry(ctx, run):
        bump(run)
        event(ctx, run, "port_error", stage=run.stage.value, error=str(exc))
        persist(ctx)
        return
    escalate(ctx, run, EscalationKind.BUDGET_EXHAUSTED,
             f"{run.stage.value} failed after {run.attempts.get(run.stage, 0) + 1} attempts: {exc}",
             details=f"{type(exc).__name__}: {exc}")


# agents and result files ----------------------------------------------------------------------

def result_path(run: Run, name: str) -> str:
    """``<agent_cwd>/.herdr-spec/<run_id>.<name>.json``."""
    return os.path.join(run.worktree or "", RESULT_DIR, f"{run.id}.{name}.json")


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def reprovision(ctx: Context, run: Run) -> None:
    """Give ``run`` a fresh agent: reopen its worktree (or a new tab) and start the agent."""
    if run.kind in TAB_KINDS:
        run.pane_id = ctx.herdr.create_tab(ctx.repo_root, run.id)
        run.worktree = ctx.repo_root
    else:
        wt = ctx.herdr.open_worktree(ctx.repo_root, run.id, run.id)
        run.workspace_id, run.pane_id, run.worktree = wt.workspace_id, wt.pane_id, wt.path
    ctx.herdr.start_agent(run.id, run.pane_id, ctx.settings.agent_args)
    run.agent = run.id
    event(ctx, run, "reprovisioned", pane=run.pane_id)


def ensure_agent(ctx: Context, run: Run) -> None:
    """Re-provision the run's own agent when herdr no longer knows it."""
    if run.agent and ctx.herdr.agent_status(run.agent) == "missing":
        reprovision(ctx, run)


def common_vars(ctx: Context, path: str, schema: str) -> dict[str, Any]:
    return {"spec": ctx.plan.spec, "spec_title": ctx.plan.title, "result_path": path,
            "result_example": results.example(schema)}


def send_turn(
    ctx: Context, run: Run, *, template: str, schema: str, name: str, agent: str | None = None,
    extra: dict | None = None, **vars: Any,
) -> None:
    """Prompt an agent with ``template`` and await its ``schema`` result at ``name``'s path."""
    agent = agent or run.agent
    if agent == run.agent:
        ensure_agent(ctx, run)
    path = result_path(run, name)
    text = ctx.render(template, **common_vars(ctx, path, schema), **vars)
    _remove(path)
    ctx.herdr.prompt_agent(agent, text)
    now = ctx.now()
    run.stage_started_at = now
    run.awaiting = {"type": "agent_turn", "agent": agent, "result": schema, "path": path,
                    "prompted_at": now, "text": text, **(extra or {})}
    event(ctx, run, "prompt", template=template, agent=agent)


def resend_turn(ctx: Context, run: Run) -> None:
    """Re-send the awaited turn's original prompt (re-provisioning the run's agent if gone)."""
    aw = run.awaiting
    if aw["agent"] == run.agent:
        ensure_agent(ctx, run)
    _remove(aw["path"])
    ctx.herdr.prompt_agent(aw["agent"], aw["text"])
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
            bump(run)
            _retry_result(ctx, run)
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
    elif run.stage is Stage.CLOSE and aw.get("type") == "close":
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


def _enter_provision(ctx: Context, run: Run) -> None:
    if run.workspace_id is None:
        if ctx.git.branch_exists(ctx.repo_root, run.id):
            wt = ctx.herdr.open_worktree(ctx.repo_root, run.id, run.id)
        else:
            wt = ctx.herdr.create_worktree(ctx.repo_root, run.id, ctx.spec_branch, run.id)
        run.workspace_id, run.pane_id, run.worktree = wt.workspace_id, wt.pane_id, wt.path
    if run.agent is None:
        start_run_agent(ctx, run)
    run.awaiting = dict(SYNC)


def _enter_provision_tab(ctx: Context, run: Run) -> None:
    if run.pane_id is None:
        run.pane_id = ctx.herdr.create_tab(ctx.repo_root, run.id)
        run.worktree = ctx.repo_root
    if run.agent is None:
        start_run_agent(ctx, run)
    run.awaiting = dict(SYNC)


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
    bump(run)
    work = (f"ticket #{run.ticket}" if run.ticket is not None
            else f"the spec review finding \"{(run.finding or {}).get('title', '')}\"")
    send_turn(ctx, run, template="verify_failed", schema="implement", name="verify",
              ticket=work, branch=run.id,
              spec_branch=ctx.spec_branch, problem=problem)


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


def _poll_await_human(ctx: Context, run: Run) -> Outcome | None:
    return Outcome.OK if run.awaiting.get("type") == "sync" else None


def _enter_spec_review(ctx: Context, run: Run) -> None:
    send_turn(ctx, run, template="spec_review", schema="spec_review", name="spec_review",
              spec_branch=ctx.spec_branch, base=ctx.plan.base)


def _enter_e2e(ctx: Context, run: Run) -> None:
    send_turn(ctx, run, template="e2e", schema="e2e", name="e2e", spec_branch=ctx.spec_branch)


class Handler(NamedTuple):
    enter: Callable[[Context, Run], None]
    poll: Callable[[Context, Run], Outcome | None]
    complete: Callable[[Context, Run, dict], None] | None = None


HANDLERS: dict[Stage, Handler] = {
    Stage.CLAIM: Handler(_enter_claim, _poll_sync),
    Stage.PROVISION: Handler(_enter_provision, _poll_sync),
    Stage.IMPLEMENT: Handler(_enter_implement, poll_turn, _complete_implement),
    Stage.VERIFY: Handler(_enter_verify, _poll_verify),
    Stage.REVIEW: Handler(_enter_review, poll_turn, _store_result),
    Stage.INTEGRATE: Handler(_enter_integrate, _poll_integrate),
    Stage.CLOSE: Handler(_enter_close, _poll_close),
    Stage.AWAIT_HUMAN: Handler(_enter_await_human, _poll_await_human),
    Stage.PROVISION_TAB: Handler(_enter_provision_tab, _poll_sync),
    Stage.SPEC_REVIEW: Handler(_enter_spec_review, poll_turn, _store_result),
    Stage.E2E: Handler(_enter_e2e, poll_turn, _store_result),
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
        if outcome is None:
            return False
        apply_outcome(ctx, run, outcome)
    except PROGRAMMING_ERRORS:
        raise
    except Exception as exc:  # noqa: BLE001 - any port failure counts as an attempt
        port_failure(ctx, run, exc)
        return False
    return run.stage is not stage and run.status is RunStatus.ACTIVE


def advance(ctx: Context, run: Run, max_steps: int = 10) -> None:
    """Advance an active run until it waits; synchronous stages chain within one call."""
    for _ in range(max_steps):
        if run.status is not RunStatus.ACTIVE or not _step(ctx, run):
            return
