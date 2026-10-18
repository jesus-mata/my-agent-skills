import unittest

from spec_engine import spec_phases
from spec_engine.model import (
    Escalation, EscalationKind, EscalationStatus, Phase, Run, RunKind, RunStatus, Stage,
)
from tests.engine_harness import Harness, ticket

DISMISSED_SPEC = {"fixed": [], "pending": [], "scope_creep": [],
                  "dismissed": [{"kind": "spec", "title": "Greeting module absent",
                                 "reason": "false positive: merged into the spec branch later"}]}

HARD_A = {"severity": "blocker", "title": "Race on save", "file": "src/save.py", "line": 3,
          "failure_scenario": "two saves lose one"}
HARD_B = {"severity": "high", "title": "Leaky cache", "file": "src/cache.py", "line": None,
          "failure_scenario": "memory grows"}


def run(kind, run_id, status, ticket=None, **kw):
    r = Run.new(kind, run_id, ticket=ticket, finding=kw.pop("finding", None))
    r.status = status
    for k, v in kw.items():
        setattr(r, k, v)
    return r


class SpecPhasesTest(unittest.TestCase):
    def setUp(self):
        self.h = Harness([ticket(1, title="Alpha"), ticket(2, title="Beta"),
                          ticket(3, blockers=[2], title="Gamma"), ticket(4, klass="human",
                                                                          title="Delta"),
                          ticket(5, klass="done", title="Old")])
        self.addCleanup(self.h.cleanup)
        self.h.start()
        self.engine = self.h.engine

    def test_on_spec_review_creates_one_fix_run_per_hard_finding_once(self):
        review = run(RunKind.SPEC_REVIEW, "s7-review", RunStatus.DONE)
        created = spec_phases.on_spec_review(self.engine, review, {"hard": [HARD_A, HARD_B]})
        self.assertEqual([r.id for r in created], ["s7-fix-1", "s7-fix-2"])
        self.assertEqual(self.h.state.runs["s7-fix-2"].finding, HARD_B)
        self.assertEqual(self.h.state.runs["s7-fix-1"].stage, Stage.PROVISION)
        self.assertEqual(self.h.state.phase, Phase.FIXES)
        self.assertEqual(spec_phases.on_spec_review(self.engine, review, {"hard": [HARD_A]}), [])

    def test_e2e_waits_for_every_fix_run(self):
        state = self.h.state
        state.phase = Phase.FIXES
        state.runs["s7-fix-1"] = run(RunKind.FIX, "s7-fix-1", RunStatus.ACTIVE, finding=HARD_A)
        self.assertIsNone(spec_phases.maybe_start_e2e(self.engine))
        state.runs["s7-fix-1"].status = RunStatus.SKIPPED
        self.assertEqual(spec_phases.maybe_start_e2e(self.engine).id, "s7-e2e")
        self.assertEqual(state.phase, Phase.E2E)

    def test_report_covers_every_outcome(self):
        state = self.h.state
        state.runs.clear()
        state.runs.update({r.id: r for r in [
            run(RunKind.TICKET, "s7-ticket-1", RunStatus.DONE, 1, merge_commit="c1", review={
                "fixed": [], "scope_creep": [],
                "pending": [{"kind": "spec", "title": "Empty state", "reason": "needs design"}]},
                notes=["left open on GitHub: pending spec finding"]),
            run(RunKind.TICKET, "s7-ticket-2", RunStatus.LEFT_OPEN, 2,
                notes=["left open: outward action denied"]),
            run(RunKind.TICKET, "s7-ticket-3", RunStatus.SKIPPED, 3, notes=["blocked by #2"]),
            run(RunKind.HUMAN, "s7-human-4", RunStatus.DONE, 4),
            run(RunKind.SPEC_REVIEW, "s7-review", RunStatus.DONE, review={
                "fixed": [{"severity": "high", "title": "Off by one", "commit": "f1"}],
                "hard": [HARD_A, HARD_B],
                "not_fixed": [{"severity": "medium", "title": "Naming"}]}),
            run(RunKind.FIX, "s7-fix-1", RunStatus.DONE, finding=HARD_A, merge_commit="c2"),
            run(RunKind.FIX, "s7-fix-2", RunStatus.SKIPPED, finding=HARD_B,
                notes=["skipped by supervisor (budget-exhausted)"]),
            run(RunKind.E2E, "s7-e2e", RunStatus.SKIPPED, notes=["skipped by supervisor"]),
        ]})
        state.escalations["e4"] = Escalation(
            id="e4", run="s7-human-4", kind=EscalationKind.HITL_TICKET, stage=Stage.AWAIT_HUMAN,
            created_at=1, summary="#4 Delta must be done by a human",
            status=EscalationStatus.HANDED_OFF)
        report = spec_phases.write_report(self.engine)

        for expected in (
            "# Spec #7: Spec seven",
            "Already closed before the run: #5",
            "Done (2):",
            "- #1 Alpha — merged as c1; left open on GitHub: pending spec finding",
            "  - pending [spec] Empty state: needs design",
            "- #4 Delta — done by a human",
            "Left open (1):\n- #2 Beta — left open: outward action denied",
            "Skipped (1):\n- #3 Gamma — blocked by #2",
            "Fixed in review (1):\n- [high] Off by one (f1)",
            "Hard findings still pending (1):\n- [high] Leaky cache (src/cache.py) — s7-fix-2 "
            "skipped — skipped by supervisor (budget-exhausted)",
            "Not fixed, medium/low (1):\n- [medium] Naming",
            "- s7-fix-1 Race on save — merged as c2",
            "  - finding: Race on save (blocker); File: src/save.py:3; "
            "Failure scenario: two saves lose one",
            "- s7-fix-2 Leaky cache — skipped; skipped by supervisor (budget-exhausted)",
            "## E2E\n\n- did not finish: skipped — skipped by supervisor",
            "- e4 hitl-ticket on s7-human-4 (handed off): #4 Delta must be done by a human",
            "Spec branch `spec-7` is local; nothing was pushed.",
        ):
            self.assertIn(expected, report)

    def test_report_when_spec_review_did_not_finish(self):
        state = self.h.state
        state.runs["s7-review"] = run(RunKind.SPEC_REVIEW, "s7-review",
                                          RunStatus.SKIPPED, notes=["skipped by supervisor"])
        report = spec_phases.write_report(self.engine)
        self.assertIn("## Spec review\n\n- did not finish: skipped — skipped by supervisor",
                      report)
        self.assertIn("## Fix runs\n\n- none", report)
        self.assertIn("## E2E\n\n- not run", report)
        self.assertIn("## Open or handed-off escalations\n\n- none", report)


class DismissedFindingTest(unittest.TestCase):
    def test_dismissed_spec_finding_closes_the_ticket_and_is_reported(self):
        h = Harness([ticket(1, title="Readme")])
        self.addCleanup(h.cleanup)
        h.start()
        h.script_ticket("s7-ticket-1", review=DISMISSED_SPEC)
        h.run_until(lambda: h.status("s7-ticket-1") is RunStatus.DONE)
        self.assertEqual(h.github.closed, [1])
        self.assertEqual(h.run("s7-ticket-1").notes, [])
        self.assertNotIn("Left open", h.github.comments[1][0])
        report = spec_phases.write_report(h.engine)
        self.assertIn("  - dismissed [spec] Greeting module absent: false positive: merged into "
                      "the spec branch later", report)
        self.assertNotIn("left open on GitHub", report)


if __name__ == "__main__":
    unittest.main()
