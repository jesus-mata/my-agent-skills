"""Spec phases: spec review, fix-run creation, e2e, follow-ups and the final report.

The scheduler decides *when* each function runs (phase transitions); this module decides *what*
each phase creates or records. Callers persist the state afterwards.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from . import follow_ups
from .model import EscalationStatus, Phase, Run, RunKind, RunStatus, run_id_for
from .stages import e2e_lines, format_finding, pending_spec_findings, ticket_title

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
    """One fix run per ``hard`` finding (``finding`` = the entry); phase ``fixes``.

    Idempotent: a finding that already has a fix run gets no second one.
    """
    state = engine.state
    existing = [r.finding for r in state.runs.values() if r.kind is RunKind.FIX]
    created = []
    for finding in (result or {}).get("hard", []):
        if finding in existing:
            continue
        state.fix_seq += 1
        run_id = run_id_for(RunKind.FIX, spec=state.spec, k=state.fix_seq)
        fix = Run.new(RunKind.FIX, run_id, finding=finding)
        state.runs[run_id] = fix
        created.append(fix)
        engine.event(fix, "fix_run", title=finding.get("title", ""))
    state.phase = Phase.FIXES
    engine.event(run, "phase", phase=state.phase.value, fix_runs=[r.id for r in created])
    return created


def maybe_start_e2e(engine: Engine) -> Run | None:
    """Once every fix run is terminal (or there are none), create the e2e run; phase ``e2e``."""
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


def on_e2e(engine: Engine, run: Run, result: dict) -> Run:
    """E2E finished: on to the follow-ups."""
    return start_follow_ups(engine)


def start_follow_ups(engine: Engine) -> Run:
    """Create the follow-ups run; phase ``follow_ups``. Once it is terminal the scheduler moves
    to ``complete`` and writes the report."""
    state = engine.state
    run_id = run_id_for(RunKind.FOLLOW_UPS, spec=state.spec)
    run = state.runs.get(run_id) or Run.new(RunKind.FOLLOW_UPS, run_id)
    state.runs[run_id] = run
    state.phase = Phase.FOLLOW_UPS
    engine.event(run, "phase", phase=state.phase.value)
    return run


# report -------------------------------------------------------------------------------------

def write_report(engine: Engine) -> str:
    """The final report as Markdown (written to ``report.md`` by the scheduler)."""
    state = engine.state
    ctx = engine.ctx
    runs = list(state.runs.values())
    lines = [f"# Spec #{state.spec}: {ctx.plan.title}", "",
             f"Spec branch: `{state.branch}` (base `{ctx.plan.base}`)", ""]
    lines += _tickets_section(engine, runs)
    lines += _spec_review_section(runs)
    lines += _fix_runs_section(runs)
    lines += _e2e_section(runs)
    lines += _follow_ups_section(runs)
    lines += _escalations_section(engine)
    lines += ["", f"Spec branch `{state.branch}` is local; nothing was pushed.", ""]
    return "\n".join(lines)


def _bullets(items: list[str], empty: str = "none") -> list[str]:
    return [f"- {i}" for i in items] if items else [f"- {empty}"]


def _reason(run: Run, lead: str = " — ") -> str:
    return f"{lead}{'; '.join(run.notes)}" if run.notes else ""


def _review_findings(run: Run) -> list[str]:
    """Sub-bullets for a run's review: pending findings, then dismissed ones (never blocking)."""
    review = run.review or {}
    return ([f"  - pending [{p['kind']}] {p['title']}: {p['reason']}"
             for p in review.get("pending", [])]
            + [f"  - dismissed [{d['kind']}] {d['title']}: {d['reason']}"
               for d in review.get("dismissed", [])])


def _tickets_section(engine: Engine, runs: list[Run]) -> list[str]:
    ctx = engine.ctx
    tickets = sorted((r for r in runs if r.kind in (RunKind.TICKET, RunKind.HUMAN)),
                     key=lambda r: r.ticket or 0)
    planned_done = [t for t in ctx.plan.tickets if t.klass.value == "done"]
    done, left_open, skipped, other = [], [], [], []
    for run in tickets:
        label = f"#{run.ticket} {ticket_title(ctx, run.ticket)}".rstrip()
        if run.status is RunStatus.DONE:
            how = "done by a human" if run.kind is RunKind.HUMAN else (
                f"merged as {run.merge_commit}" if run.merge_commit else "done")
            item = f"{label} — {how}{_reason(run, '; ')}"
            done.append(item)
            done.extend(_review_findings(run))
            if pending_spec_findings(run):
                done.append("  - left open on GitHub until the pending spec finding is addressed")
        elif run.status is RunStatus.LEFT_OPEN:
            left_open.append(f"{label}{_reason(run)}")
        elif run.status is RunStatus.SKIPPED:
            skipped.append(f"{label}{_reason(run)}")
        else:
            other.append(f"{label} — {run.status.value} at {run.stage.value}{_reason(run)}")
    out = ["## Tickets", ""]
    if planned_done:
        out += [f"Already closed before the run: "
                + ", ".join(f"#{t.number}" for t in planned_done), ""]
    out += [f"Done ({sum(1 for r in tickets if r.status is RunStatus.DONE)}):", *_bullets(done),
            "", f"Left open ({len(left_open)}):", *_bullets(left_open),
            "", f"Skipped ({len(skipped)}):", *_bullets(skipped)]
    if other:
        out += ["", f"Not finished ({len(other)}):", *_bullets(other)]
    return out + [""]


def _fix_run_for(runs: list[Run], finding: dict) -> Run | None:
    return next((r for r in runs if r.kind is RunKind.FIX and r.finding == finding), None)


def _finding_line(f: dict) -> str:
    where = f.get("file", "")
    if f.get("line") is not None:
        where = f"{where}:{f['line']}"
    return f"[{f.get('severity', '')}] {f.get('title', '')}" + (f" ({where})" if where else "")


def _spec_review_section(runs: list[Run]) -> list[str]:
    run = next((r for r in runs if r.kind is RunKind.SPEC_REVIEW), None)
    out = ["## Spec review", ""]
    if run is None:
        return out + ["- not run", ""]
    if run.status is not RunStatus.DONE:
        return out + [f"- did not finish: {run.status.value}{_reason(run)}", ""]
    review = run.review or {}
    fixed = [f"[{f['severity']}] {f['title']} ({f['commit']})" for f in review.get("fixed", [])]
    pending = []
    for f in review.get("hard", []):
        fix = _fix_run_for(runs, f)
        if fix is None or fix.status is not RunStatus.DONE:
            state = f"{fix.id} {fix.status.value}{_reason(fix)}" if fix else "no fix run"
            pending.append(f"{_finding_line(f)} — {state}")
    not_fixed = [f"[{f['severity']}] {f['title']}"
                 + (f" — {f['reason']}" if f.get("reason") else "")
                 for f in review.get("not_fixed", [])]
    return out + [f"Fixed in review ({len(fixed)}):", *_bullets(fixed),
                  "", f"Hard findings still pending ({len(pending)}):", *_bullets(pending),
                  "", f"Not fixed, medium/low ({len(not_fixed)}):", *_bullets(not_fixed), ""]


def _fix_runs_section(runs: list[Run]) -> list[str]:
    fixes = [r for r in runs if r.kind is RunKind.FIX]
    out = ["## Fix runs", ""]
    if not fixes:
        return out + ["- none", ""]
    for run in fixes:
        title = (run.finding or {}).get("title", "")
        how = f"merged as {run.merge_commit}" if run.merge_commit else run.status.value
        out.append(f"- {run.id} {title} — {how}{_reason(run, '; ')}")
        out.append("  - finding: " + format_finding(run.finding).replace("\n", "; "))
        out.extend(_review_findings(run))
    return out + [""]


def _e2e_section(runs: list[Run]) -> list[str]:
    run = next((r for r in runs if r.kind is RunKind.E2E), None)
    out = ["## E2E", ""]
    if run is None:
        return out + ["- not run", ""]
    if run.review is None:
        return out + [f"- did not finish: {run.status.value}{_reason(run)}", ""]
    if run.status is not RunStatus.DONE:
        out += [f"- not posted on the spec issue: {run.status.value}{_reason(run)}", ""]
    return out + e2e_lines(run.review) + [""]


def _follow_ups_section(runs: list[Run]) -> list[str]:
    run = next((r for r in runs if r.kind is RunKind.FOLLOW_UPS), None)
    out = ["## Follow-ups", ""]
    if run is None:
        return out + ["- not run", ""]
    entries = (run.review or {}).get("follow_ups")
    if entries is None:
        return out + [f"- not collected: {run.status.value}{_reason(run)}", ""]
    if not entries:
        return out + ["- none proposed by the reviews", ""]
    by_state = {state: [e for e in entries if e["state"] == state] for state in follow_ups.STATES}

    def issue_line(e: dict) -> str:
        return f"{follow_ups.line(e)} — #{e['issue']['number']} {e['issue']['url']}"

    created = [issue_line(e) for e in by_state[follow_ups.CREATED]]
    already = [issue_line(e) for e in by_state[follow_ups.ALREADY_OPEN]]
    discarded = [follow_ups.line(e) for e in by_state[follow_ups.DISCARDED]]
    undecided = [follow_ups.line(e) for e in by_state[follow_ups.PROPOSED]]
    out += [f"Created ({len(created)}):", *_bullets(created),
            "", f"Already open ({len(already)}):", *_bullets(already),
            "", f"Discarded ({len(discarded)}):", *_bullets(discarded)]
    if undecided:
        out += ["", f"Not decided ({len(undecided)}):", *_bullets(undecided)]
    if run.notes:
        out += ["", "Notes:", *_bullets(run.notes)]
    return out + [""]


def _escalations_section(engine: Engine) -> list[str]:
    unresolved = [e for e in engine.state.escalations.values()
                  if e.status is not EscalationStatus.RESOLVED]
    items = [f"{e.id} {e.kind.value} on {e.run} ({e.status.value.replace('_', ' ')}): {e.summary}"
             for e in unresolved]
    return ["## Open or handed-off escalations", "", *_bullets(items)]
