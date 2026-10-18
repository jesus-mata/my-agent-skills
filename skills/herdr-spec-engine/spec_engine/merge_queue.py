"""The merge queue: one run at a time absorbs the spec branch, passes the gate and is merged.

The queue is ``state.queue`` (run ids, FIFO). ``process(ctx)`` steps the first queued run that is
not escalated (an escalated run keeps its place but does not block the runs behind it). Where a
run is in the three steps lives in ``run.awaiting``:

- ``{"type": "queue"}`` — start at step 1 (merge the spec branch into the worktree);
  ``"resume": "gate"|"final"`` with ``"base"`` restarts at step 2 or 3.
- ``{"type": "resolver", ...}`` — a resolver agent is settling a conflict (step 1).
- ``{"type": "agent_turn", "result": "gate_fix", ...}`` — the run's agent is fixing the gate.
- ``{"type": "integrated"}`` — merged; the run has left the queue.
"""
from __future__ import annotations

from .model import EscalationKind, Outcome, Run, RunKind, RunStatus, resolver_agent_name
from .stages import (
    PROGRAMMING_ERRORS, Context, close_resolver, escalate, event, handle_turn_outcome, persist,
    poll_turn, port_failure, send_turn, ticket_title,
)

GATE_OUTPUT_LINES = 150


def head(ctx: Context) -> Run | None:
    """The run the queue processes now: the first queued run that is active."""
    for run_id in ctx.state.queue:
        run = ctx.state.runs.get(run_id)
        if run is not None and run.status is RunStatus.ACTIVE:
            return run
    return None


def process(ctx: Context) -> None:
    """Advance the head of the queue by as much as can happen without waiting."""
    run = head(ctx)
    if run is None:
        return
    try:
        _step(ctx, run)
    except PROGRAMMING_ERRORS:
        raise
    except Exception as exc:  # noqa: BLE001 - port failures count as integrate attempts
        port_failure(ctx, run, exc)
    persist(ctx)


def _step(ctx: Context, run: Run) -> None:
    aw = run.awaiting or {"type": "queue"}
    kind = aw.get("type")
    if kind == "resolver":
        _poll_resolver(ctx, run)
    elif kind == "agent_turn":
        _poll_gate_fix(ctx, run)
    elif kind == "queue":
        resume = aw.get("resume")
        if resume == "gate":
            _gate(ctx, run, aw["base"])
        elif resume == "final":
            _final(ctx, run, aw["base"])
        else:
            _merge(ctx, run)


# step 1: absorb the spec branch -------------------------------------------------------------

def _merge(ctx: Context, run: Run) -> None:
    base = ctx.git.rev_parse(ctx.repo_root, ctx.spec_branch)
    result = ctx.git.merge(run.worktree, ctx.spec_branch)
    event(ctx, run, "queue_merge", base=base, ok=result.ok, conflict=result.conflict)
    if result.conflict:
        _start_resolver(ctx, run, base)
        return
    if not result.ok:
        raise RuntimeError(f"merging {ctx.spec_branch} into {run.id} failed: {result.output}")
    _gate(ctx, run, base)


def _start_resolver(ctx: Context, run: Run, base: str) -> None:
    conflicts = ctx.git.unmerged_paths(run.worktree)
    pane = ctx.herdr.split_pane(run.pane_id, cwd=run.worktree)
    name = resolver_agent_name(run.id)
    ctx.herdr.start_agent(name, pane, ctx.settings.agent_args)
    send_turn(ctx, run, template="resolver", schema="resolve", name="resolve", agent=name,
              extra={"type": "resolver", "pane_id": pane, "base": base},
              run_id=run.id, branch=run.id, spec_branch=ctx.spec_branch,
              conflicts="\n".join(conflicts))


def _poll_resolver(ctx: Context, run: Run) -> None:
    outcome = poll_turn(ctx, run)
    if outcome is None:
        return
    base = run.awaiting["base"]
    after = {"type": "queue", "resume": "gate", "base": base}
    if outcome is Outcome.OK:
        value = run.awaiting["value"]
        if (value["verdict"] == "RESOLVED" and ctx.git.is_clean(run.worktree)
                and not ctx.git.unmerged_paths(run.worktree)):
            close_resolver(ctx, run)
            event(ctx, run, "resolved", summary=value["summary"])
            _gate(ctx, run, base)
            return
        close_resolver(ctx, run)
        escalate(ctx, run, EscalationKind.RESOLVER_ESCALATED,
                 f"merge conflict in {run.id} needs a human ({value['verdict']})",
                 details=value["summary"], awaiting=after)
    elif outcome is Outcome.AGENT_LOST:
        close_resolver(ctx, run)
        escalate(ctx, run, EscalationKind.RESOLVER_ESCALATED,
                 f"resolver for {run.id} was lost mid-merge", awaiting=after)
    else:
        handle_turn_outcome(ctx, run, outcome)


# step 2: gate -------------------------------------------------------------------------------

def _gate(ctx: Context, run: Run, base: str) -> None:
    for cmd in ctx.plan.gate:
        result = ctx.shell.run(cmd, cwd=run.worktree, timeout=ctx.settings.gate_timeout)
        event(ctx, run, "gate", cmd=cmd, code=result.code)
        if result.code != 0:
            _gate_failed(ctx, run, base, cmd, result.code, last_lines(result.output))
            return
    _final(ctx, run, base)


def last_lines(text: str, n: int = GATE_OUTPUT_LINES) -> str:
    return "\n".join(text.splitlines()[-n:])


def _gate_failed(ctx: Context, run: Run, base: str, cmd: str, code: int, output: str) -> None:
    if run.gate_attempts < ctx.settings.gate_retry_budget:
        run.gate_attempts += 1
        send_turn(ctx, run, template="gate_failed", schema="gate_fix", name="gate_fix",
                  extra={"base": base}, command=cmd, exit_code=code, output=output)
        return
    escalate(ctx, run, EscalationKind.BUDGET_EXHAUSTED,
             f"gate still failing for {run.id} after {run.gate_attempts} fix attempts: "
             f"`{cmd}` exited {code}", details=output, awaiting={"type": "queue"})


def _poll_gate_fix(ctx: Context, run: Run) -> None:
    outcome = poll_turn(ctx, run)
    if outcome is None:
        return
    if outcome is Outcome.OK:
        _merge(ctx, run)
    else:
        handle_turn_outcome(ctx, run, outcome)


# step 3: merge into the spec branch ---------------------------------------------------------

def _final(ctx: Context, run: Run, base: str) -> None:
    if ctx.git.rev_parse(ctx.repo_root, ctx.spec_branch) != base:
        event(ctx, run, "spec_branch_moved", base=base)
        _merge(ctx, run)
        return
    resume = {"type": "queue", "resume": "final", "base": base}
    branch = ctx.git.current_branch(ctx.repo_root)
    if branch != ctx.spec_branch or not ctx.git.is_clean(ctx.repo_root):
        escalate(ctx, run, EscalationKind.REPO_DIRTY,
                 f"repo root must be clean with {ctx.spec_branch} checked out to merge {run.id}",
                 details=f"{ctx.repo_root} is on {branch}", awaiting=resume)
        return
    result = ctx.git.merge(ctx.repo_root, run.id, no_ff=True, message=merge_message(ctx, run))
    if not result.ok:
        try:
            ctx.git.merge_abort(ctx.repo_root)
        finally:
            escalate(ctx, run, EscalationKind.REPO_DIRTY,
                     f"merging {run.id} into {ctx.spec_branch} failed", details=result.output,
                     awaiting=resume)
        return
    run.merge_commit = result.commit
    ctx.state.queue.remove(run.id)
    run.awaiting = {"type": "integrated"}
    event(ctx, run, "integrated", commit=result.commit)


def merge_message(ctx: Context, run: Run) -> str:
    if run.kind is RunKind.FIX:
        return f"Merge {run.id}: {(run.finding or {}).get('title', '')}"
    return f"Merge #{run.ticket}: {ticket_title(ctx, run.ticket)}"
