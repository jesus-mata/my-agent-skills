import json
import unittest

from spec_engine import transitions
from spec_engine.model import (
    STAGES_BY_KIND, Escalation, EscalationKind, EscalationStatus, Phase, Plan, PlanTicket, Run,
    RunKind, RunState, RunStatus, Settings, Stage, TicketClass, resolver_agent_name, run_id_for,
)


def roundtrip(obj):
    return type(obj).from_dict(json.loads(json.dumps(obj.to_dict())))


class ModelTest(unittest.TestCase):
    def test_run_state_round_trips_through_json(self):
        run = Run.new(RunKind.TICKET, "ticket-3", ticket=3)
        run.status = RunStatus.ESCALATED
        run.stage = Stage.REVIEW
        run.attempts = {Stage.IMPLEMENT: 1, Stage.REVIEW: 0}
        run.awaiting = {"type": "agent_turn", "agent": "ticket-3", "result": "review",
                        "path": "/x/.herdr-spec/ticket-3.review.json", "prompted_at": 5.0}
        run.notes = ["hello"]
        fix = Run.new(RunKind.FIX, "fix-7-1", finding={"title": "t", "line": None})
        esc = Escalation(id="e1", run="ticket-3", kind=EscalationKind.AGENT_BLOCKED,
                         stage=Stage.REVIEW, created_at=1.5, summary="blocked",
                         actions=list(transitions.ACTIONS[EscalationKind.AGENT_BLOCKED]))
        state = RunState(spec=7, branch="spec-7", settings=Settings(max_agents=2),
                         runs={run.id: run, fix.id: fix}, queue=["fix-7-1"],
                         escalations={"e1": esc}, consumed_resolutions=["e0"], seq=1,
                         fix_seq=1, phase=Phase.FIXES, started_at=1.0, updated_at=2.0)
        back = roundtrip(state)
        self.assertEqual(back, state)
        self.assertTrue(all(isinstance(k, Stage) for k in back.runs["ticket-3"].attempts))
        d = state.to_dict()
        self.assertEqual(d["runs"]["ticket-3"]["status"], "escalated")
        self.assertEqual(d["escalations"]["e1"]["kind"], "agent-blocked")
        self.assertEqual(d["escalations"]["e1"]["status"], "open")
        self.assertEqual(d["phase"], "fixes")
        self.assertEqual(d["version"], 1)

    def test_plan_round_trips(self):
        plan = Plan(spec=1, title="S", branch="spec-1", gate=["make test"], tickets=[
            PlanTicket(2, "a", TicketClass.AGENT, blockers=[3], labels=["ready-for-agent"]),
            PlanTicket(3, "b", TicketClass.DONE, external_blockers=["x/y#4"]),
        ])
        self.assertEqual(roundtrip(plan), plan)
        self.assertEqual(plan.to_dict()["tickets"][0]["klass"], "agent")
        self.assertEqual(plan.ticket(3).title, "b")

    def test_settings_defaults(self):
        s = Settings()
        self.assertEqual((s.max_agents, s.model, s.stage_timeout, s.retry_budget,
                          s.gate_retry_budget, s.gate_timeout, s.poll_seconds,
                          s.settle_seconds, s.unknown_grace),
                         (3, "opus", 7200, 1, 2, 1800, 10, 15, 120))
        self.assertEqual(s.agent_args, ["--permission-mode", "auto", "--model", "opus"])
        self.assertEqual(roundtrip(Escalation("e2", "r", EscalationKind.REPO_DIRTY, None, 0, "s",
                                              status=EscalationStatus.HANDED_OFF)).stage, None)

    def test_run_ids(self):
        self.assertEqual(run_id_for(RunKind.TICKET, ticket=4), "ticket-4")
        self.assertEqual(run_id_for(RunKind.HUMAN, ticket=4), "human-4")
        self.assertEqual(run_id_for(RunKind.FIX, spec=9, k=2), "fix-9-2")
        self.assertEqual(run_id_for(RunKind.SPEC_REVIEW, spec=9), "review-spec-9")
        self.assertEqual(run_id_for(RunKind.E2E, spec=9), "e2e-spec-9")
        with self.assertRaises(ValueError):
            run_id_for(RunKind.TICKET)
        self.assertEqual(resolver_agent_name("ticket-12"), "resolve-ticket-12")
        long = resolver_agent_name("fix-123456789-123456789012345")
        self.assertLessEqual(len(long), 32)
        self.assertTrue(long.startswith("resolve-fix-"))

    def test_new_run_starts_at_first_stage(self):
        for kind, stages in STAGES_BY_KIND.items():
            self.assertEqual(Run.new(kind, "x").stage, stages[0])
            self.assertEqual(Run.new(kind, "x").status, RunStatus.PENDING)


class TransitionsTest(unittest.TestCase):
    def test_next_stage(self):
        self.assertEqual(transitions.next_stage(RunKind.TICKET, Stage.CLAIM), Stage.PROVISION)
        self.assertEqual(transitions.next_stage(RunKind.FIX, Stage.INTEGRATE), Stage.CLOSE)
        self.assertIsNone(transitions.next_stage(RunKind.TICKET, Stage.CLOSE))
        self.assertEqual(transitions.next_stage("e2e", "provision_tab"), Stage.E2E)
        self.assertIsNone(transitions.next_stage(RunKind.HUMAN, Stage.AWAIT_HUMAN))

    def test_actions(self):
        self.assertEqual(len(transitions.ACTIONS), 10)
        self.assertEqual(set(transitions.ACTIONS), set(EscalationKind))
        self.assertTrue(transitions.is_valid_action("agent-blocked", "hand-to-human"))
        self.assertTrue(transitions.is_valid_action(EscalationKind.HITL_TICKET, "done"))
        self.assertFalse(transitions.is_valid_action(EscalationKind.HITL_TICKET, "retry"))
        self.assertFalse(transitions.is_valid_action("nope", "retry"))
        self.assertIs(transitions.EscalationKind, EscalationKind)


if __name__ == "__main__":
    unittest.main()
