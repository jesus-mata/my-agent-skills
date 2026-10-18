"""Spec phases: spec review, fix-run creation, e2e and the final report.

The scheduler decides *when* each function runs (phase transitions); this module decides *what*
each phase creates or records. Callers persist the state afterwards.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .model import EscalationStatus, Phase, Run, RunKind, run_id_for

if TYPE_CHECKING:
    from .scheduler import Engine


def start_spec_review(engine: Engine) -> Run:
    """Create the spec review run (started by the scheduler like any other run)."""
    state = engine.state
    run_id = run_id_for(RunKind.SPEC_REVIEW, spec=state.spec)
    run = state.runs.get(run_id) or Run.new(RunKind.SPEC_REVIEW, run_id)
    state.runs[run_id] = run
    state.phase = Phase.SPEC_REVIEW
    engine.event(run, "phase", phase=state.phase.value)
    return run


def on_spec_review(engine: Engine, run: Run, result: dict) -> list[Run]:
    """One fix run per ``hard`` finding; phase ``fixes``."""
    state = engine.state
    created = []
    for finding in (result or {}).get("hard", []):
        state.fix_seq += 1
        run_id = run_id_for(RunKind.FIX, spec=state.spec, k=state.fix_seq)
        fix = Run.new(RunKind.FIX, run_id, finding=finding)
        state.runs[run_id] = fix
        created.append(fix)
    state.phase = Phase.FIXES
    engine.event(run, "phase", phase=state.phase.value, fix_runs=[r.id for r in created])
    return created


def maybe_start_e2e(engine: Engine) -> Run | None:
    """Once every fix run is terminal, create the e2e run; phase ``e2e``."""
    state = engine.state
    fixes = [r for r in state.runs.values() if r.kind is RunKind.FIX]
    if state.phase is not Phase.FIXES or any(not r.terminal for r in fixes):
        return None
    run_id = run_id_for(RunKind.E2E, spec=state.spec)
    run = state.runs.get(run_id) or Run.new(RunKind.E2E, run_id)
    state.runs[run_id] = run
    state.phase = Phase.E2E
    engine.event(run, "phase", phase=state.phase.value)
    return run


def on_e2e(engine: Engine, run: Run, result: dict) -> None:
    """E2E finished: phase ``complete``."""
    engine.state.phase = Phase.COMPLETE
    engine.event(run, "phase", phase=Phase.COMPLETE.value)


def write_report(engine: Engine) -> str:
    """The final report as Markdown (minimal; written to ``report.md`` by the scheduler)."""
    state = engine.state
    plan = engine.ctx.plan
    lines = [f"# Spec #{state.spec}: {plan.title}", "", f"Spec branch: `{state.branch}`", ""]
    lines += ["## Tickets", ""]
    for run in state.runs.values():
        if run.kind in (RunKind.TICKET, RunKind.HUMAN, RunKind.FIX):
            label = f"#{run.ticket}" if run.ticket is not None else run.id
            notes = f" — {'; '.join(run.notes)}" if run.notes else ""
            lines.append(f"- {label}: {run.status.value}{notes}")
    for kind, title in ((RunKind.SPEC_REVIEW, "Spec review"), (RunKind.E2E, "E2E")):
        run = next((r for r in state.runs.values() if r.kind is kind), None)
        if run is not None:
            lines += ["", f"## {title}", "", f"- status: {run.status.value}"]
            for key, items in (run.review or {}).items():
                lines.append(f"- {key}: {len(items) if isinstance(items, list) else items}")
    open_escalations = [e for e in state.escalations.values()
                        if e.status is not EscalationStatus.RESOLVED]
    if open_escalations:
        lines += ["", "## Unresolved escalations", ""]
        lines += [f"- {e.id} ({e.run}, {e.kind.value}, {e.status.value}): {e.summary}"
                  for e in open_escalations]
    lines += ["", "The spec branch is local; nothing pushed.", ""]
    return "\n".join(lines)

