"""Agent readiness: a pane still booting or an agent not yet registered is waited for, never
charged to the retry budget; real port-error retries are spaced by a backoff."""
import json
import os
import unittest

from spec_engine.model import EscalationKind, RunStatus, Settings, Stage
from spec_engine.ports import HerdrError, MergeResult
from tests.engine_harness import BRANCH, IMPLEMENTED, REVIEW_CLEAN, Harness, ticket

CONFLICT = MergeResult(ok=False, conflict=True, commit=None, output="CONFLICT (content)")


def pane_busy(pane="w1:p1"):
    return HerdrError("agent_pane_busy", f"agent target pane {pane} is not an available shell")


def not_ready(name="s7-ticket-1"):
    return HerdrError("agent_not_ready", f"agent {name} is not an active named agent")


def working(fake, name, text):
    fake.set_status(name, "working")


class AgentReadinessTest(unittest.TestCase):
    def harness(self, tickets=None, **kw) -> Harness:
        h = Harness(tickets or [ticket(1)], **kw)
        self.addCleanup(h.cleanup)
        return h.start()

    def burst(self, h, ticks=3, then=1.0, rounds=20):
        """Ticks fired back-to-back (no clock advance, as when woken by other agents' events),
        then a short pause; repeated."""
        for _ in range(rounds):
            h.tick(ticks, dt=0)
            h.clock.advance(then)

    def port_errors(self, h, run_id):
        with open(h.store.paths.events, encoding="utf-8") as f:
            events = [json.loads(line) for line in f if line.strip()]
        return [e for e in events if e.get("run") == run_id and e.get("type") == "port_error"]

    # provision and the first prompt ---------------------------------------------------------

    def test_pane_busy_and_agent_not_ready_never_charge_the_retry_budget(self):
        h = self.harness(settings=Settings(retry_budget=1))
        for _ in range(3):
            h.herdr.fail_next("start_agent", pane_busy())
        for _ in range(4):
            h.herdr.fail_next("prompt_agent", not_ready())
        h.herdr.on_prompt("s7-ticket-1", working)
        self.burst(h)
        run = h.run("s7-ticket-1")
        self.assertEqual(h.open_escalations(), [])
        self.assertEqual((run.status, run.stage), (RunStatus.ACTIVE, Stage.IMPLEMENT))
        self.assertEqual(run.awaiting["type"], "agent_turn")
        self.assertEqual(run.attempts, {})
        self.assertEqual(self.port_errors(h, run.id), [])
        self.assertEqual(len(h.herdr.calls_to("create_worktree")), 1)
        self.assertEqual(len(h.herdr.calls_to("start_agent")), 4)
        self.assertEqual(len(h.herdr.calls_to("prompt_agent")), 5)
        self.assertEqual(len(h.herdr.prompts["s7-ticket-1"]), 1)
        self.assertIsNone(run.ready_wait)

    def test_back_to_back_ticks_do_not_hammer_a_booting_pane(self):
        h = self.harness()
        for _ in range(50):
            h.herdr.fail_next("start_agent", pane_busy())
        h.tick(20, dt=0)
        self.assertEqual(len(h.herdr.calls_to("start_agent")), 1)
        self.assertEqual(h.open_escalations(), [])

    def test_provision_waits_until_the_started_agent_is_registered(self):
        h = self.harness()
        real_status = h.herdr.agent_status
        registered_at = h.clock.now() + 6
        h.herdr.agent_status = lambda name: (
            "missing" if h.clock.now() < registered_at else real_status(name))
        h.herdr.on_prompt("s7-ticket-1", working)
        h.tick(dt=0)
        self.assertEqual(h.run("s7-ticket-1").stage, Stage.PROVISION)
        self.assertEqual(h.herdr.prompts["s7-ticket-1"], [])
        self.burst(h, rounds=10)
        run = h.run("s7-ticket-1")
        self.assertEqual((run.stage, run.awaiting["type"]), (Stage.IMPLEMENT, "agent_turn"))
        self.assertEqual(len(h.herdr.calls_to("start_agent")), 1)
        self.assertEqual(run.attempts, {})

    def test_readiness_past_the_deadline_becomes_attempts_then_escalates(self):
        h = self.harness(settings=Settings(agent_ready_timeout=30))
        for _ in range(500):
            h.herdr.fail_next("start_agent", pane_busy())
        t0 = h.clock.now()
        h.run_until(lambda: h.open_escalations(), max_ticks=200, dt=1)
        esc = h.only_escalation()
        self.assertEqual((esc.kind, esc.stage), (EscalationKind.BUDGET_EXHAUSTED, Stage.PROVISION))
        self.assertIn("not ready", esc.summary)
        self.assertIn("agent_pane_busy", esc.summary)
        self.assertGreaterEqual(esc.created_at - t0, 30)
        self.assertEqual(len(self.port_errors(h, "s7-ticket-1")), 1)  # one charged attempt

        # a supervisor retry gets a fresh readiness window
        h.herdr._failures["start_agent"].clear()
        h.herdr.on_prompt("s7-ticket-1", working)
        h.resolve(esc.id, "retry")
        h.tick()
        run = h.run("s7-ticket-1")
        self.assertEqual((run.status, run.stage), (RunStatus.ACTIVE, Stage.IMPLEMENT))

    # backoff for real port errors -----------------------------------------------------------

    def test_port_error_retries_are_spaced_by_a_doubling_backoff(self):
        h = self.harness(settings=Settings(retry_budget=2, retry_backoff=5, retry_backoff_max=60))
        h.github.fail_next("assign_self", RuntimeError("gh: rate limited"))
        h.github.fail_next("assign_self", RuntimeError("gh: rate limited"))
        h.herdr.on_prompt("s7-ticket-1", working)
        h.tick(5, dt=0)
        self.assertEqual(len(h.github.calls_to("assign_self")), 1)
        h.clock.advance(4.9)
        h.tick(3, dt=0)
        self.assertEqual(len(h.github.calls_to("assign_self")), 1)
        h.clock.advance(0.1)
        h.tick(3, dt=0)  # 5 s after the first error: second attempt (fails, backoff now 10 s)
        self.assertEqual(len(h.github.calls_to("assign_self")), 2)
        h.clock.advance(9.9)
        h.tick(3, dt=0)
        self.assertEqual(len(h.github.calls_to("assign_self")), 2)
        h.clock.advance(0.1)
        h.tick(dt=0)
        self.assertEqual(len(h.github.calls_to("assign_self")), 3)
        self.assertEqual(h.open_escalations(), [])
        self.assertEqual(h.run("s7-ticket-1").stage, Stage.IMPLEMENT)

    def test_backoff_is_capped(self):
        h = self.harness(settings=Settings(retry_budget=5, retry_backoff=5, retry_backoff_max=12))
        for _ in range(4):
            h.github.fail_next("assign_self", RuntimeError("gh down"))
        h.tick(dt=0)
        h.clock.advance(5)
        h.tick(dt=0)
        h.clock.advance(10)
        h.tick(dt=0)  # third failure: backoff would be 20 s, capped at 12
        run = h.run("s7-ticket-1")
        self.assertEqual(run.attempts[Stage.CLAIM], 3)
        self.assertAlmostEqual(run.retry_at - h.clock.now(), 12)

    def test_resume_respects_the_persisted_backoff(self):
        h = self.harness()
        h.github.fail_next("assign_self", RuntimeError("gh: rate limited"))
        h.tick(dt=0)
        self.assertEqual(len(h.github.calls_to("assign_self")), 1)
        h.engine = h.new_engine()
        h.engine.startup()
        self.assertGreater(h.run("s7-ticket-1").retry_at, h.clock.now())
        h.tick(3, dt=0)
        self.assertEqual(len(h.github.calls_to("assign_self")), 1)
        h.clock.advance(5)
        h.herdr.on_prompt("s7-ticket-1", working)
        h.tick(dt=0)
        self.assertEqual(len(h.github.calls_to("assign_self")), 2)
        self.assertEqual(h.run("s7-ticket-1").stage, Stage.IMPLEMENT)

    # re-provision, resolver and tab agents --------------------------------------------------

    def test_reprovisioned_agent_is_waited_for_not_charged(self):
        h = self.harness()
        h.herdr.on_prompt("s7-ticket-1", working)
        h.tick()
        h.herdr.remove_agent("s7-ticket-1")
        for _ in range(2):
            h.herdr.fail_next("start_agent", pane_busy())
        for _ in range(2):
            h.herdr.fail_next("prompt_agent", not_ready())
        h.herdr.on_prompt("s7-ticket-1", working)
        self.burst(h)
        run = h.run("s7-ticket-1")
        self.assertEqual(h.open_escalations(), [])
        self.assertEqual(run.attempts[Stage.IMPLEMENT], 1)  # the loss itself, nothing more
        self.assertEqual(len(h.herdr.calls_to("open_worktree")), 1)
        self.assertEqual(len(h.herdr.prompts["s7-ticket-1"]), 2)
        self.assertEqual(h.herdr.agents["s7-ticket-1"], "working")
        self.assertEqual(run.awaiting.get("resend"), None)

    def test_resolver_agent_readiness_is_waited_for(self):
        h = self.harness([ticket(1, title="Alpha")])
        wt = os.path.join(h.herdr.worktree_root, "s7-ticket-1")
        h.git.script_merge(wt, BRANCH, CONFLICT)
        h.git.set_unmerged(wt, ["src/a.py"])
        h.turn("s7-ticket-1", IMPLEMENTED, commits=1)
        h.turn("s7-ticket-1", REVIEW_CLEAN)
        h.turn("s7-resolve-ticket-1", {"verdict": "RESOLVED", "summary": "kept both"},
               also=lambda: h.git.set_unmerged(wt, []))
        h.run_until(lambda: h.run("s7-ticket-1").stage is Stage.INTEGRATE, dt=10)
        for _ in range(2):
            h.herdr.fail_next("start_agent", pane_busy("w1:p9"))
        for _ in range(2):
            h.herdr.fail_next("prompt_agent", not_ready("s7-resolve-ticket-1"))
        self.burst(h, rounds=40)
        h.run_until(lambda: h.status("s7-ticket-1") is RunStatus.DONE)
        self.assertEqual(h.open_escalations(), [])
        self.assertEqual(len(h.herdr.calls_to("split_pane")), 1)
        self.assertEqual(len(h.herdr.prompts["s7-resolve-ticket-1"]), 1)
        self.assertEqual(h.run("s7-ticket-1").attempts.get(Stage.INTEGRATE, 0), 0)

    def test_spec_review_tab_agent_readiness_is_waited_for(self):
        h = self.harness([ticket(1, klass="done")], settings=Settings(retry_budget=1))
        for _ in range(3):
            h.herdr.fail_next("start_agent", pane_busy())
        for _ in range(3):
            h.herdr.fail_next("prompt_agent", not_ready("s7-review"))
        h.herdr.on_prompt("s7-review", working)
        self.burst(h)
        run = h.run("s7-review")
        self.assertEqual(h.open_escalations(), [])
        self.assertEqual((run.stage, run.awaiting["type"]), (Stage.SPEC_REVIEW, "agent_turn"))
        self.assertEqual(len(h.herdr.calls_to("create_tab")), 1)
        self.assertEqual(run.attempts, {})


if __name__ == "__main__":
    unittest.main()
