"""The engine loop: resolutions, run advancement, merge queue, readiness, spec phases, completion.

``Engine(ctx).run_forever()`` = ``startup()`` then ``tick()`` until it returns False, waiting on
``Herdr.wait_for_change`` between ticks. ``tick()`` is one deterministic loop iteration, which is
what the tests drive.
"""
from __future__ import annotations

import math
import os
from typing import Any, Callable

from . import merge_queue, spec_phases, stages
from .model import (
    EngineStatus, Escalation, EscalationKind, EscalationStatus, Phase, Run, RunKind, RunState,
    RunStatus, TicketClass, run_id_for,
)
from .stages import PROGRAMMING_ERRORS, Context
from .transitions import HANDED_OFF_ACTION

EXCLUDE_ENTRY = ".herdr-spec/"
AGENT_KINDS = frozenset({RunKind.TICKET, RunKind.FIX, RunKind.SPEC_REVIEW, RunKind.E2E})
TICKET_KINDS = frozenset({RunKind.TICKET, RunKind.HUMAN})
READY_FOR_AGENT = "ready-for-agent"
READY_FOR_HUMAN = "ready-for-human"


def classify(labels: list[str] | tuple[str, ...]) -> TicketClass:
    agent, human = READY_FOR_AGENT in labels, READY_FOR_HUMAN in labels
    if agent and not human:
        return TicketClass.AGENT
    if human and not agent:
        return TicketClass.HUMAN
    return TicketClass.UNREFINED


class Engine:
    """Owns the RunState and every transition of one spec run."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx

    @property
    def state(self) -> RunState:
        return self.ctx.state

    # persistence ----------------------------------------------------------------------------

    def persist(self) -> None:
        stages.persist(self.ctx)

    def event(self, run: Run | None, type: str, **data: Any) -> None:
        stages.event(self.ctx, run, type, **data)

    # lifecycle ------------------------------------------------------------------------------

    def startup(self) -> None:
        """Ping herdr, ensure the spec branch and exclude entry, load or init state, write pid."""
        ctx = self.ctx
        # The pid goes first: `watch` reports a pid-less engine as dead after ~5 s, and creating
        # the spec branch (`git pull`) can take longer.
        ctx.store.write_pid()
        try:
            ctx.herdr.ping()
            self._ensure_spec_branch()
            self._ensure_exclude()
            state = ctx.store.load_state()
            resumed = state is not None
            ctx.state = state if resumed else self._init_state()
            ctx.state.settings = ctx.settings
            ctx.store.clear_stop()
            self.event(None, "resumed" if resumed else "started")
            self.persist()
            if resumed:
                self._reconcile()
        except BaseException:
            ctx.store.clear_pid()
            raise

    def run_forever(self) -> int:
        self.startup()
        try:
            while self.tick():
                self.ctx.herdr.wait_for_change(self.ctx.settings.poll_seconds)
        finally:
            self.ctx.store.clear_pid()
        return 0

    def tick(self) -> bool:
        """One loop iteration; False when the engine should exit (complete, stopped)."""
        if self.state.status is not EngineStatus.RUNNING:
            self.ctx.store.clear_pid()
            return False
        self._consume_resolutions()
        for run in list(self.state.runs.values()):
            if run.status is RunStatus.ACTIVE:
                stages.advance(self.ctx, run)
        merge_queue.process(self.ctx)
        self._advance_phases()
        self._start_ready()
        if self.state.status is EngineStatus.COMPLETE:
            self.ctx.store.clear_pid()
            return False
        if self.ctx.store.stop_requested():
            self.event(None, "stopped")
            self.persist()
            self.ctx.store.clear_stop()
            self.ctx.store.clear_pid()
            return False
        return True

    # startup helpers ------------------------------------------------------------------------

    def _ensure_spec_branch(self) -> None:
        git, root, plan = self.ctx.git, self.ctx.repo_root, self.ctx.plan
        if git.current_branch(root) == plan.branch:
            return
        if git.branch_exists(root, plan.branch):
            git.checkout(root, plan.branch)
            return
        git.checkout(root, plan.base)
        git.pull_ff_only(root)
        git.checkout(root, plan.branch, create_from=plan.base)

    def _ensure_exclude(self) -> None:
        path = os.path.join(self.ctx.common_dir, "info", "exclude")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except FileNotFoundError:
            text = ""
        if EXCLUDE_ENTRY in text.splitlines():
            return
        with open(path, "a", encoding="utf-8") as f:
            if text and not text.endswith("\n"):
                f.write("\n")
            f.write(EXCLUDE_ENTRY + "\n")

    def _init_state(self) -> RunState:
        plan = self.ctx.plan
        now = self.ctx.now()
        state = RunState(spec=plan.spec, branch=plan.branch, settings=self.ctx.settings,
                         started_at=now, updated_at=now)
        for t in sorted(plan.tickets, key=lambda t: t.number):
            if t.klass is TicketClass.DONE:
                continue
            kind = RunKind.HUMAN if t.klass is TicketClass.HUMAN else RunKind.TICKET
            run_id = run_id_for(kind, spec=plan.spec, ticket=t.number)
            state.runs[run_id] = Run.new(kind, run_id, ticket=t.number)
        return state

    def _reconcile(self) -> None:
        """Log what each awaited agent is doing; missing agents take the AGENT_LOST path when
        polled, live ones keep being polled (a working agent is never re-prompted)."""
        for run in self.state.runs.values():
            aw = run.awaiting or {}
            if run.status is RunStatus.ACTIVE and aw.get("type") in ("agent_turn", "resolver"):
                status = self.ctx.herdr.agent_status(aw["agent"])
                self.event(run, "reconcile", agent=aw["agent"], status=status)

    # readiness and starting -----------------------------------------------------------------

    def run_for_ticket(self, number: int) -> Run | None:
        return next((r for r in self.state.runs.values()
                     if r.ticket == number and r.kind in TICKET_KINDS), None)

    def _blockers_done(self, run: Run) -> bool:
        ticket = self.ctx.plan.ticket(run.ticket)
        for b in ticket.blockers if ticket else []:
            planned = self.ctx.plan.ticket(b)
            if planned is not None and planned.klass is TicketClass.DONE:
                continue
            blocker = self.run_for_ticket(b)
            if blocker is None or blocker.status is not RunStatus.DONE:
                return False
        return True

    def dead_blocker(self, run: Run, seen: frozenset[str] = frozenset()) -> int | None:
        """The blocker that keeps ``run`` from ever starting (skipped, left open, or itself
        dead), or None."""
        ticket = self.ctx.plan.ticket(run.ticket) if run.ticket is not None else None
        for b in ticket.blockers if ticket else []:
            blocker = self.run_for_ticket(b)
            if blocker is None or blocker.id in seen:
                continue
            if blocker.terminal and blocker.status is not RunStatus.DONE:
                return b
            if blocker.status is RunStatus.PENDING and \
                    self.dead_blocker(blocker, seen | {run.id}) is not None:
                return b
        return None

    def _holds_agent(self, run: Run) -> bool:
        if run.kind not in AGENT_KINDS:
            return False
        if run.status is RunStatus.ACTIVE:
            return True
        return run.status is RunStatus.ESCALATED and \
            (run.awaiting or {}).get("type") != "escalation"

    def _start_key(self, item: tuple[int, Run]) -> tuple[float, int]:
        index, run = item
        return (run.ticket if run.ticket is not None else math.inf, index)

    def _start_ready(self) -> None:
        """Start ready runs in ascending ticket number, up to ``max_agents`` agents."""
        slots = self.ctx.settings.max_agents - sum(
            1 for r in self.state.runs.values() if self._holds_agent(r))
        pending = [(i, r) for i, r in enumerate(self.state.runs.values())
                   if r.status is RunStatus.PENDING]
        for _, run in sorted(pending, key=self._start_key):
            if run.kind in TICKET_KINDS and not self._blockers_done(run):
                continue
            if run.kind is RunKind.HUMAN:
                self._activate(run)
                continue
            if slots <= 0:
                continue
            if run.kind is RunKind.TICKET and not self._ticket_gates_pass(run):
                continue
            self._activate(run)
            slots -= 1

    def _activate(self, run: Run) -> None:
        run.status = RunStatus.ACTIVE
        run.stage_started_at = self.ctx.now()
        self.event(run, "started", stage=run.stage.value)
        self.persist()
        stages.advance(self.ctx, run)

    def _ticket_gates_pass(self, run: Run) -> bool:
        """Re-read an unrefined or externally blocked ticket; escalate if it may not start."""
        ticket = self.ctx.plan.ticket(run.ticket)
        if ticket is None or (ticket.klass is not TicketClass.UNREFINED
                              and not ticket.external_blockers):
            return True
        try:
            issue = self.ctx.github.issue(run.ticket)
        except PROGRAMMING_ERRORS:
            raise
        except Exception as exc:  # noqa: BLE001 - retried next tick
            self.event(run, "port_error", error=str(exc))
            return False
        if issue.state == "CLOSED":
            run.status = RunStatus.DONE
            run.notes.append("closed on GitHub before it started")
            self.persist()
            return False
        klass = classify(issue.labels)
        if klass is TicketClass.UNREFINED:
            stages.escalate(self.ctx, run, EscalationKind.UNREFINED_TICKET,
                            f"#{run.ticket} {ticket.title} is not labeled "
                            f"{READY_FOR_AGENT} or {READY_FOR_HUMAN}",
                            details=f"labels: {', '.join(issue.labels) or 'none'}",
                            awaiting={"type": "escalation"})
            return False
        if klass is TicketClass.HUMAN:
            ticket.klass = TicketClass.HUMAN
            self._replace_with_human_run(run)
            return False
        ticket.klass = TicketClass.AGENT
        numbers = {t.number for t in self.ctx.plan.tickets}
        external = [r for r in issue.blocked_by if r.state == "OPEN" and r.number not in numbers]
        if external:
            stages.escalate(self.ctx, run, EscalationKind.EXTERNAL_BLOCKER,
                            f"#{run.ticket} {ticket.title} is blocked outside the spec",
                            details="\n".join(f"{r.repo}#{r.number} {r.url}" for r in external),
                            awaiting={"type": "escalation"})
            return False
        ticket.external_blockers = []
        return True

    def _replace_with_human_run(self, run: Run) -> None:
        del self.state.runs[run.id]
        run_id = run_id_for(RunKind.HUMAN, spec=self.state.spec, ticket=run.ticket)
        self.state.runs[run_id] = Run.new(RunKind.HUMAN, run_id, ticket=run.ticket)
        self.event(run, "reclassified", to=run_id)
        self.persist()

    # spec phases ----------------------------------------------------------------------------

    def _runs_of(self, *kinds: RunKind) -> list[Run]:
        return [r for r in self.state.runs.values() if r.kind in kinds]

    def _advance_phases(self) -> None:
        state = self.state
        before = state.phase
        if state.phase is Phase.TICKETS:
            self._maybe_finish_tickets()
        if state.phase is Phase.SPEC_REVIEW:
            run = next(iter(self._runs_of(RunKind.SPEC_REVIEW)), None)
            if run is not None and run.terminal:
                if run.status is RunStatus.DONE:
                    spec_phases.on_spec_review(self, run, run.review or {})
                else:
                    state.phase = Phase.FIXES
        if state.phase is Phase.FIXES:
            spec_phases.maybe_start_e2e(self)
        if state.phase is Phase.E2E:
            run = next(iter(self._runs_of(RunKind.E2E)), None)
            if run is not None and run.terminal:
                if run.status is RunStatus.DONE:
                    spec_phases.on_e2e(self, run, run.review or {})
                else:
                    state.phase = Phase.COMPLETE
        if state.phase is Phase.COMPLETE and state.status is EngineStatus.RUNNING:
            self.ctx.store.write_report(spec_phases.write_report(self))
            state.status = EngineStatus.COMPLETE
            self.event(None, "complete")
        if state.phase is not before or state.status is not EngineStatus.RUNNING:
            self.persist()

    def _maybe_finish_tickets(self) -> None:
        runs = self._runs_of(RunKind.TICKET, RunKind.HUMAN)
        dead = {r.id: self.dead_blocker(r) for r in runs if r.status is RunStatus.PENDING}
        if any(not r.terminal and dead.get(r.id) is None for r in runs):
            return
        for run in runs:
            if dead.get(run.id) is not None:
                run.status = RunStatus.SKIPPED
                run.notes.append(f"blocked by #{dead[run.id]}")
                self.event(run, "skipped", blocker=dead[run.id])
        spec_phases.start_spec_review(self)

    # resolutions ----------------------------------------------------------------------------

    def _consume_resolutions(self) -> None:
        consumed = set(self.state.consumed_resolutions)
        for item in self.ctx.store.read_resolutions():
            key = f"{item.get('escalation_id')}@{item.get('ts')}"
            if key in consumed:
                continue
            consumed.add(key)
            self.state.consumed_resolutions.append(key)
            esc = self.state.escalations.get(item.get("escalation_id", ""))
            action = item.get("action", "")
            if esc is None or esc.status is EscalationStatus.RESOLVED or action not in esc.actions:
                self.event(None, "resolution_ignored", escalation=item.get("escalation_id"),
                           action=action)
            else:
                self.apply_resolution(esc, action, item.get("note") or "")
            self.persist()

    def apply_resolution(self, esc: Escalation, action: str, note: str = "") -> None:
        """Apply one allowed action to an unresolved escalation."""
        run = self.state.runs.get(esc.run)
        esc.note = note
        self.event(run, "resolution", escalation=esc.id, action=action, note=note)
        if action == HANDED_OFF_ACTION:
            esc.status = EscalationStatus.HANDED_OFF
            return
        resolved = True
        if run is not None:
            try:
                resolved = self._action(action, esc)(esc, run)
            except PROGRAMMING_ERRORS:
                raise
            except Exception as exc:  # noqa: BLE001 - leave the escalation open
                esc.status = EscalationStatus.OPEN
                esc.details = f"{esc.details}\nresolution '{action}' failed: {exc}".strip()
                return
        if resolved is False:
            esc.status = EscalationStatus.OPEN
            return
        esc.status = EscalationStatus.RESOLVED
        esc.resolution = action
        if run is not None and run.escalation == esc.id:
            run.escalation = None

    def _action(self, action: str, esc: Escalation) -> Callable[[Escalation, Run], bool | None]:
        if action == "retry":
            return {
                EscalationKind.AGENT_UNKNOWN: self._retry_resend,
                EscalationKind.STAGE_TIMEOUT: self._retry_timer,
                EscalationKind.REPO_DIRTY: self._resume,
            }.get(esc.kind, self._retry_reenter)
        return {
            "answered": self._answered,
            "skip-ticket": self._skip,
            "resolved-manually": self._resolved_manually,
            "leave-open": self._leave_open,
            "done": self._human_done,
            "relabeled": self._recheck,
            "cleared": self._recheck,
        }[action]

    def _resume(self, esc: Escalation, run: Run) -> None:
        run.status = RunStatus.ACTIVE

    def _resolved_manually(self, esc: Escalation, run: Run) -> bool:
        """Resume at the gate once the human committed the merge in the run's worktree."""
        problem = merge_queue.manual_merge_problem(self.ctx, run)
        if problem:
            esc.details = f"{esc.details}\nresolved-manually refused: {problem}".strip()
            return False
        run.status = RunStatus.ACTIVE
        return True

    def _answered(self, esc: Escalation, run: Run) -> None:
        run.status = RunStatus.ACTIVE
        run.stage_started_at = self.ctx.now()
        if run.awaiting and "prompted_at" in run.awaiting:
            run.awaiting["prompted_at"] = run.awaiting["answered_at"] = self.ctx.now()
            run.awaiting.pop("unknown_since", None)

    def _retry_resend(self, esc: Escalation, run: Run) -> None:
        stages.resend_turn(self.ctx, run)
        run.status = RunStatus.ACTIVE

    def _retry_timer(self, esc: Escalation, run: Run) -> None:
        run.status = RunStatus.ACTIVE
        run.stage_started_at = self.ctx.now()

    def _retry_reenter(self, esc: Escalation, run: Run) -> None:
        stages.reenter(self.ctx, run)

    def _skip(self, esc: Escalation, run: Run) -> None:
        stages.teardown(self.ctx, run)
        run.status = RunStatus.SKIPPED
        run.awaiting = None
        run.notes.append(f"skipped by supervisor ({esc.kind.value})"
                         + (f": {esc.note}" if esc.note else ""))

    def _leave_open(self, esc: Escalation, run: Run) -> None:
        if run.ticket is not None:
            body = (f"herdr-spec-engine left this ticket open: the agent needed actions it may "
                    f"not take.\n\n{esc.details}")
            if esc.note:
                body += f"\n\nSupervisor note: {esc.note}"
            self.ctx.github.comment(run.ticket, body)
        # Best effort: a worktree with uncommitted work is refused (and kept) by herdr; failing
        # here would leave the escalation open and re-post the comment on the next attempt.
        stages.best_effort(self.ctx, run, "remove worktree",
                            lambda: stages.remove_worktree(self.ctx, run))
        run.status = RunStatus.LEFT_OPEN
        run.awaiting = None
        run.notes.append("left open: outward action denied")

    def _human_done(self, esc: Escalation, run: Run) -> bool:
        issue = self.ctx.github.issue(run.ticket)
        if issue.state != "CLOSED":
            esc.details = f"{esc.details}\n#{run.ticket} is still open on GitHub.".strip()
            return False
        run.status = RunStatus.DONE
        run.awaiting = None
        self.event(run, "done", stage=run.stage.value)
        return True

    def _recheck(self, esc: Escalation, run: Run) -> None:
        run.status = RunStatus.PENDING
        run.awaiting = None
