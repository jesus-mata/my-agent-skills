"""The merge queue: one run at a time absorbs the spec branch, passes the gate and is merged.

The queue is ``state.queue`` (run ids, FIFO). ``process(ctx)`` steps the first queued run that is
not escalated (an escalated run keeps its place but does not block the runs behind it). Where a
run is in the three steps lives in ``run.awaiting``:

- ``{"type": "queue"}`` — start at step 1 (merge the spec branch into the worktree);
  ``"resume": "gate"|"final"`` with ``"base"`` restarts at step 2 or 3.
- ``{"type": "resolver", ...}`` — a resolver agent is settling a conflict (step 1); until its
  prompt went through (no ``"path"`` yet) the resolver is still being started.
- ``{"type": "agent_turn", "result": "gate_fix", ...}`` — the run's agent is fixing the gate.
- ``{"type": "integrated"}`` — merged; the run has left the queue.
"""
from __future__ import annotations

import re

from .model import (
    EscalationKind, EscalationStatus, Outcome, Run, RunKind, RunStatus, resolver_agent_name,
)
from .stages import (
    PROGRAMMING_ERRORS, Context, agent_ready, close_resolver, escalate, event, handle_turn_outcome,
    persist, poll_turn, port_failure, ready_waiting, send_turn, ticket_title,
)

GATE_OUTPUT_LINES = 150
NO_TESTS_EXIT = 5
_NO_TESTS_RUNNER_RE = re.compile(r"\bunittest\b.*\bdiscover\b|\bpytest\b|\bpy\.test\b")


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
    if run is None or ready_waiting(ctx, run):
        return
    try:
        _step(ctx, run)
        agent_ready(ctx, run)
    except PROGRAMMING_ERRORS:
        raise
    except Exception as exc:  # noqa: BLE001 - port failures count as integrate attempts
        port_failure(ctx, run, exc)
    persist(ctx)


def _step(ctx: Context, run: Run) -> None:
    aw = run.awaiting or {"type": "queue"}
    kind = aw.get("type")
    if kind == "resolver" and "path" not in aw:
        _launch_resolver(ctx, run)
    elif kind == "resolver":
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
    run.awaiting = {"type": "resolver", "agent": resolver_agent_name(run.id), "pane_id": pane,
                    "base": base, "conflicts": conflicts, "started": False}
    persist(ctx)
    _launch_resolver(ctx, run)


def _launch_resolver(ctx: Context, run: Run) -> None:
    """Start the resolver agent in its pane and prompt it; resumable after a not-ready (or any
    port) error at either step, without splitting another pane."""
    aw = run.awaiting
    name, pane = aw["agent"], aw["pane_id"]
    if not aw.get("started"):
        if ctx.herdr.agent_pane(name) != pane:
            ctx.herdr.start_agent(name, pane, ctx.settings.agent_args)
        aw["started"] = True
        persist(ctx)
    send_turn(ctx, run, template="resolver", schema="resolve", name="resolve", agent=name,
              extra={"type": "resolver", "pane_id": pane, "base": aw["base"]},
              run_id=run.id, branch=run.id, spec_branch=ctx.spec_branch,
              conflicts="\n".join(aw["conflicts"]))


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
                 details=f"{value['summary']}\n\n{manual_merge_hint(ctx, run)}", awaiting=after)
    elif outcome is Outcome.AGENT_LOST:
        close_resolver(ctx, run)
        escalate(ctx, run, EscalationKind.RESOLVER_ESCALATED,
                 f"resolver for {run.id} was lost mid-merge",
                 details=manual_merge_hint(ctx, run), awaiting=after)
    else:
        handle_turn_outcome(ctx, run, outcome)


def manual_merge_hint(ctx: Context, run: Run) -> str:
    return (f"Worktree: {run.worktree}\nFinish merging `{ctx.spec_branch}` into `{run.id}` there "
            f"(if no merge is in progress, run `git merge {ctx.spec_branch}` first), commit it and "
            f"leave the tree clean; then resolve with `resolved-manually`. The engine resumes "
            f"at the gate.")


def manual_merge_problem(ctx: Context, run: Run) -> str | None:
    """Why a `resolved-manually` merge is not finished in the run's worktree, or None."""
    base = (run.awaiting or {}).get("base") or ctx.spec_branch
    problems = []
    unmerged = ctx.git.unmerged_paths(run.worktree)
    if unmerged:
        problems.append("unmerged paths: " + ", ".join(unmerged))
    if not ctx.git.is_clean(run.worktree):
        problems.append(f"{run.worktree} has uncommitted changes (merge not committed?)")
    if ctx.git.commits_ahead(run.worktree, run.id, base) > 0:
        problems.append(f"`{ctx.spec_branch}` ({base}) is not merged into `{run.id}`")
    return "; ".join(problems) or None


# step 2: gate -------------------------------------------------------------------------------

def _gate(ctx: Context, run: Run, base: str) -> None:
    # The gate checks the working tree but only commits get merged: uncommitted changes to
    # tracked files would pass the gate and never reach the spec branch. Untracked files are
    # allowed (a previous gate run's artifacts).
    if not ctx.git.is_clean(run.worktree, untracked=False):
        _gate_failed(ctx, run, base, "git status --porcelain --untracked-files=no", 1,
                     f"{run.worktree} has uncommitted changes to tracked files; commit them "
                     f"on your branch (or discard them) so the gate checks what gets merged")
        return
    for cmd in ctx.plan.gate:
        result = ctx.shell.run(cmd, cwd=run.worktree, timeout=ctx.settings.gate_timeout)
        no_tests = is_no_tests(cmd, result.code)
        event(ctx, run, "gate", cmd=cmd, code=result.code,
              **({"no_tests": True} if no_tests else {}))
        if result.code != 0 and not no_tests:
            _gate_failed(ctx, run, base, cmd, result.code, last_lines(result.output))
            return
    _final(ctx, run, base)


def is_no_tests(cmd: str, code: int) -> bool:
    """``unittest discover`` (Python >= 3.12) and ``pytest`` exit 5 when they find no tests: a
    ticket without tests that lands before a sibling's tests broke nothing, so it passes."""
    return code == NO_TESTS_EXIT and _NO_TESTS_RUNNER_RE.search(cmd) is not None


def last_lines(text: str, n: int = GATE_OUTPUT_LINES) -> str:
    return "\n".join(text.splitlines()[-n:])


def _gate_failed(ctx: Context, run: Run, base: str, cmd: str, code: int, output: str) -> None:
    if run.gate_attempts < ctx.settings.gate_retry_budget:
        send_turn(ctx, run, template="gate_failed", schema="gate_fix", name="gate_fix",
                  extra={"base": base}, command=cmd, exit_code=code, output=output)
        run.gate_attempts += 1  # after the prompt went through
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
    problem = _repo_root_problem(ctx, run, branch)
    if problem:
        if _open_repo_dirty(ctx, run):
            run.awaiting = resume  # one escalation per cause: re-checked each tick
            return
        escalate(ctx, run, EscalationKind.REPO_DIRTY,
                 f"repo root must be clean with {ctx.spec_branch} checked out to merge {run.id}",
                 details=problem, awaiting=resume)
        return
    result = ctx.git.merge(ctx.repo_root, run.id, no_ff=True, message=merge_message(ctx, run))
    if not result.ok:
        details = result.output
        if result.conflict:  # a failure before git started merging leaves nothing to abort
            try:
                ctx.git.merge_abort(ctx.repo_root)
            except PROGRAMMING_ERRORS:
                raise
            except Exception as exc:  # noqa: BLE001 - reported in the escalation instead
                details += f"\n`git merge --abort` failed: {exc}"
        escalate(ctx, run, EscalationKind.REPO_DIRTY,
                 f"merging {run.id} into {ctx.spec_branch} failed", details=details,
                 awaiting=resume)
        return
    run.merge_commit = result.commit
    ctx.state.queue.remove(run.id)
    run.awaiting = {"type": "integrated"}
    event(ctx, run, "integrated", commit=result.commit)


CACHE_DIRS = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"})
CACHE_SUFFIXES = (".pyc", ".pyo")
STATUS_LINES = 30


def is_cache_path(path: str) -> bool:
    """A tool cache that is safe to delete: it is regenerated on the next run."""
    parts = path.rstrip("/").split("/")
    return bool(CACHE_DIRS.intersection(parts[:-1])) or parts[-1].endswith(CACHE_SUFFIXES)


def _repo_root_problem(ctx: Context, run: Run, branch: str) -> str | None:
    """Why the repo root cannot take the merge, or None. Untracked tool caches alone (left by
    agents or a check run in the root, or un-ignored by switching spec branches) are deleted."""
    root = ctx.repo_root
    if branch != ctx.spec_branch:
        return f"{root} is on {branch}, not {ctx.spec_branch}"
    if ctx.git.is_clean(root):
        return None
    entries = ctx.git.status_entries(root)
    caches = [e[3:] for e in entries if e.startswith("?? ") and is_cache_path(e[3:])]
    if caches and len(caches) == len(entries):
        ctx.git.clean_untracked(root, caches)
        event(ctx, run, "repo_caches_cleaned", paths=caches)
        if ctx.git.is_clean(root):
            return None
        entries = ctx.git.status_entries(root)
    listing = "\n".join(entries[:STATUS_LINES])
    more = f"\n... and {len(entries) - STATUS_LINES} more" if len(entries) > STATUS_LINES else ""
    return f"{root} has changes (git status --short):\n{listing}{more}"



def _open_repo_dirty(ctx: Context, run: Run) -> bool:
    """Another run already has an unresolved repo-dirty escalation (same root, same cause)."""
    return any(e.kind is EscalationKind.REPO_DIRTY and e.run != run.id
               and e.status is not EscalationStatus.RESOLVED
               for e in ctx.state.escalations.values())


def merge_message(ctx: Context, run: Run) -> str:
    if run.kind is RunKind.FIX:
        return f"Merge {run.id}: {(run.finding or {}).get('title', '')}"
    return f"Merge #{run.ticket}: {ticket_title(ctx, run.ticket)}"
