import json
import os
import unittest

from spec_engine.model import EscalationKind, EscalationStatus, RunStatus, Settings, Stage
from spec_engine.stages import format_finding, result_path
from tests.engine_harness import IMPLEMENTED, REVIEW_CLEAN, Harness, ticket

PENDING_SPEC = {"fixed": [], "scope_creep": ["renamed helper"],
                "pending": [{"kind": "spec", "title": "Empty state", "reason": "needs copy"}]}


def idle(fake, name, text):
    fake.set_status(name, "idle")


def working(fake, name, text):
    fake.set_status(name, "working")


class StagesTest(unittest.TestCase):
    def harness(self, tickets=None, **kw) -> Harness:
        h = Harness(tickets or [ticket(1)], **kw)
        self.addCleanup(h.cleanup)
        return h.start()

    def test_first_tick_claims_provisions_and_prompts(self):
        h = self.harness()
        h.herdr.on_prompt("ticket-1", working)
        h.tick()
        run = h.run("ticket-1")
        self.assertEqual(h.github.assigned, [1])
        wt = h.herdr.calls_to("create_worktree")[0]
        self.assertEqual((wt["branch"], wt["base"], wt["label"]), ("ticket-1", "spec-7", "ticket-1"))
        self.assertEqual(h.herdr.agent_args["ticket-1"],
                         ["--permission-mode", "auto", "--model", "opus"])
        self.assertEqual(run.stage, Stage.IMPLEMENT)
        self.assertEqual(run.awaiting["type"], "agent_turn")
        self.assertEqual(run.awaiting["result"], "implement")
        self.assertEqual(run.awaiting["path"],
                         os.path.join(run.worktree, ".herdr-spec", "ticket-1.implement.json"))
        self.assertEqual(run.awaiting["path"], result_path(run, "implement"))

    def test_provision_opens_existing_branch(self):
        h = Harness([ticket(1)])
        self.addCleanup(h.cleanup)
        h.git.add_commits("ticket-1", 1)
        h.start()
        h.herdr.on_prompt("ticket-1", working)
        h.tick()
        self.assertEqual(len(h.herdr.calls_to("open_worktree")), 1)
        self.assertEqual(h.herdr.calls_to("create_worktree"), [])

    def test_settle_window_ignores_early_idle(self):
        h = self.harness()
        h.herdr.on_prompt("ticket-1", idle)  # idle at once, no result written yet
        h.tick(2)  # t+0, t+10: inside the 15 s settle window
        self.assertEqual(h.templates(), ["implement"])
        h.tick()  # t+20: idle counts now -> result missing -> retry prompt
        self.assertEqual(h.templates(), ["implement", "result_retry"])

    def test_result_missing_then_retry_then_valid(self):
        h = self.harness()
        h.herdr.on_prompt("ticket-1", idle)
        h.turn("ticket-1", IMPLEMENTED, commits=1)
        h.turn("ticket-1", REVIEW_CLEAN)
        h.run_until(lambda: h.run("ticket-1").stage is Stage.INTEGRATE
                    or h.status("ticket-1") is RunStatus.DONE)
        retry = [v for n, v in h.rendered if n == "result_retry"][0]
        self.assertIn("not found", retry["error"])
        self.assertIn('"status"', retry["result_example"])
        self.assertEqual(h.run("ticket-1").attempts[Stage.IMPLEMENT], 1)

    def test_result_accepted_is_archived_and_deleted(self):
        h = self.harness()
        h.turn("ticket-1", IMPLEMENTED, commits=1)
        h.herdr.on_prompt("ticket-1", working)
        h.run_until(lambda: h.run("ticket-1").stage is Stage.REVIEW)
        archived = os.path.join(h.store.paths.out, "ticket-1.implement.1.json")
        with open(archived) as f:
            self.assertEqual(json.load(f), IMPLEMENTED)
        run = h.run("ticket-1")
        self.assertFalse(os.path.exists(result_path(run, "implement")))

    def test_invalid_result_twice_escalates_budget_exhausted_then_retry(self):
        h = self.harness()
        h.turn("ticket-1", '{"status": "maybe"}')
        h.turn("ticket-1", "not json")
        h.run_until(lambda: h.open_escalations())
        esc = h.only_escalation()
        self.assertEqual(esc.kind, EscalationKind.BUDGET_EXHAUSTED)
        self.assertIn("invalid JSON", esc.details)
        self.assertEqual(esc.actions, ["retry", "skip-ticket", "hand-to-human"])
        self.assertEqual(h.status("ticket-1"), RunStatus.ESCALATED)
        h.tick(3)
        self.assertEqual(len(h.herdr.prompts["ticket-1"]), 2)  # not polled while escalated

        h.script_ticket("ticket-1")
        h.resolve(esc.id, "retry")
        h.run_until(lambda: h.status("ticket-1") is RunStatus.DONE)
        self.assertEqual(h.templates()[:4], ["implement", "result_retry", "implement", "review"])
        self.assertEqual(esc.status, EscalationStatus.RESOLVED)

    def test_blocked_escalates_with_screen_then_answered_resumes_same_turn(self):
        h = self.harness()
        h.herdr.screens["ticket-1"] = "Allow rm -rf? (y/n)"
        h.herdr.on_prompt("ticket-1", lambda f, n, t: f.set_status(n, "blocked"))
        h.tick()
        esc = h.only_escalation()
        self.assertEqual(esc.kind, EscalationKind.AGENT_BLOCKED)
        self.assertIn("Allow rm -rf?", esc.details)
        self.assertEqual(h.herdr.calls_to("read_agent")[0]["lines"], 60)

        # supervisor answers in the pane; the agent then finishes the same turn
        run = h.run("ticket-1")
        path = run.awaiting["path"]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(IMPLEMENTED, f)
        h.git.add_commits("ticket-1", 1, base="spec-7")
        h.herdr.set_status("ticket-1", "idle")
        h.turn("ticket-1", REVIEW_CLEAN)
        h.resolve(esc.id, "answered")
        h.run_until(lambda: h.status("ticket-1") is RunStatus.DONE)
        self.assertEqual(h.templates().count("implement"), 1)

    def test_answered_tolerates_a_lagging_blocked_status(self):
        # herdr detects status from the screen: right after the supervisor answers, the agent
        # can still read as blocked for a few seconds. That is not a new block.
        h = self.harness()
        h.herdr.on_prompt("ticket-1", lambda f, n, t: f.set_status(n, "blocked"))
        h.tick()
        esc = h.only_escalation()
        h.resolve(esc.id, "answered")
        h.tick()  # consumes `answered`; herdr still says blocked
        self.assertEqual(h.open_escalations(), [])
        h.herdr.set_status("ticket-1", "working")
        h.tick()
        h.herdr.set_status("ticket-1", "blocked")  # a genuinely new block later on
        h.tick()
        self.assertEqual(h.only_escalation().kind, EscalationKind.AGENT_BLOCKED)

    def test_answered_but_still_blocked_after_settle_escalates_again(self):
        h = self.harness()
        h.herdr.on_prompt("ticket-1", lambda f, n, t: f.set_status(n, "blocked"))
        h.tick()
        h.resolve(h.only_escalation().id, "answered")
        h.tick(3)  # t+0 .. t+20: past the settle window, still blocked
        self.assertEqual(h.only_escalation().kind, EscalationKind.AGENT_BLOCKED)

    def test_timeout_escalates_and_retry_resets_timer(self):
        h = self.harness(settings=Settings(stage_timeout=100))
        h.herdr.on_prompt("ticket-1", working)
        h.tick(10)  # 100 s at 10 s per tick
        self.assertEqual(h.open_escalations(), [])
        h.tick(2)
        esc = h.only_escalation()
        self.assertEqual(esc.kind, EscalationKind.STAGE_TIMEOUT)
        h.resolve(esc.id, "retry")
        h.tick(5)
        self.assertEqual(h.status("ticket-1"), RunStatus.ACTIVE)
        self.assertEqual(len(h.herdr.prompts["ticket-1"]), 1)  # no re-prompt
        h.tick(8)
        self.assertEqual(h.only_escalation().kind, EscalationKind.STAGE_TIMEOUT)

    def test_unknown_waits_for_grace_then_escalates_and_retry_resends(self):
        h = self.harness()
        h.herdr.on_prompt("ticket-1", lambda f, n, t: f.set_status(n, "unknown"))
        h.tick(12)  # unknown since t+0; 110 s later still within the 120 s grace
        self.assertEqual(h.open_escalations(), [])
        h.tick(2)
        esc = h.only_escalation()
        self.assertEqual(esc.kind, EscalationKind.AGENT_UNKNOWN)
        h.script_ticket("ticket-1")
        h.resolve(esc.id, "retry")
        h.run_until(lambda: h.status("ticket-1") is RunStatus.DONE)
        prompts = h.herdr.prompts["ticket-1"]
        self.assertEqual(prompts[0], prompts[1])  # the stage prompt was re-sent

    def test_agent_lost_reprovisions_once_then_escalates(self):
        h = self.harness()
        h.herdr.on_prompt("ticket-1", working)
        h.tick()
        h.herdr.remove_agent("ticket-1")
        h.herdr.on_prompt("ticket-1", working)
        h.tick()
        self.assertEqual(len(h.herdr.calls_to("open_worktree")), 1)
        self.assertEqual([c["name"] for c in h.herdr.calls_to("start_agent")],
                         ["ticket-1", "ticket-1"])
        self.assertEqual(len(h.herdr.prompts["ticket-1"]), 2)
        self.assertEqual(h.run("ticket-1").attempts[Stage.IMPLEMENT], 1)
        self.assertEqual(h.open_escalations(), [])

        h.herdr.remove_agent("ticket-1")
        h.tick()
        self.assertEqual(h.only_escalation().kind, EscalationKind.BUDGET_EXHAUSTED)

    def test_verify_failed_no_commits_prompts_then_passes(self):
        h = self.harness()
        h.turn("ticket-1", IMPLEMENTED, commits=0)
        h.turn("ticket-1", IMPLEMENTED, commits=1)  # the verify_failed turn commits
        h.turn("ticket-1", REVIEW_CLEAN)
        h.run_until(lambda: h.status("ticket-1") is RunStatus.DONE)
        verify = [v for n, v in h.rendered if n == "verify_failed"][0]
        self.assertIn("no commits ahead of spec-7", verify["problem"])
        self.assertTrue(verify["result_path"].endswith("ticket-1.verify.json"))
        self.assertEqual(h.templates()[:3], ["implement", "verify_failed", "review"])

    def test_verify_failed_dirty_tree(self):
        h = self.harness()
        wt = os.path.join(h.herdr.worktree_root, "ticket-1")
        h.turn("ticket-1", IMPLEMENTED, commits=1, also=lambda: h.git.set_clean(wt, False))
        h.turn("ticket-1", IMPLEMENTED, also=lambda: h.git.set_clean(wt, True))
        h.turn("ticket-1", REVIEW_CLEAN)
        h.run_until(lambda: h.status("ticket-1") is RunStatus.DONE)
        verify = [v for n, v in h.rendered if n == "verify_failed"][0]
        self.assertIn("uncommitted changes", verify["problem"])

    def test_verify_failing_twice_escalates(self):
        h = self.harness()
        h.turn("ticket-1", IMPLEMENTED)
        h.turn("ticket-1", IMPLEMENTED)
        h.run_until(lambda: h.open_escalations())
        esc = h.only_escalation()
        self.assertEqual((esc.kind, esc.stage), (EscalationKind.BUDGET_EXHAUSTED, Stage.VERIFY))

    def test_port_exception_counts_as_attempt_then_escalates(self):
        h = Harness([ticket(1)])
        self.addCleanup(h.cleanup)
        h.start()
        h.github.fail_next("assign_self", RuntimeError("gh: rate limited"))
        h.github.fail_next("assign_self", RuntimeError("gh: rate limited"))
        h.tick()
        run = h.run("ticket-1")
        self.assertEqual((run.status, run.stage), (RunStatus.ACTIVE, Stage.CLAIM))
        self.assertEqual(run.attempts[Stage.CLAIM], 1)
        h.tick()
        esc = h.only_escalation()
        self.assertEqual(esc.kind, EscalationKind.BUDGET_EXHAUSTED)
        self.assertIn("rate limited", esc.summary)
        h.herdr.on_prompt("ticket-1", working)
        h.resolve(esc.id, "retry")
        h.tick()
        self.assertEqual(h.run("ticket-1").stage, Stage.IMPLEMENT)

    def test_provision_failure_after_worktree_is_retried_without_new_worktree(self):
        h = self.harness()
        h.herdr.fail_next("start_agent", RuntimeError("socket closed"))
        h.herdr.on_prompt("ticket-1", working)
        h.tick(2)
        self.assertEqual(len(h.herdr.calls_to("create_worktree")), 1)
        self.assertEqual(h.run("ticket-1").stage, Stage.IMPLEMENT)

    def test_outward_denied_leave_open_and_dependents_skipped(self):
        h = self.harness([ticket(1), ticket(2, blockers=[1]), ticket(3)])
        h.turn("ticket-1", {"status": "outward-denied", "summary": "needs a deploy",
                            "denied_actions": ["deploy to staging"]})
        h.script_ticket("ticket-3")
        h.run_until(lambda: h.open_escalations())
        esc = h.only_escalation()
        self.assertEqual(esc.kind, EscalationKind.OUTWARD_ACTION_DENIED)
        self.assertIn("deploy to staging", esc.details)
        h.resolve(esc.id, "leave-open", note="ops will do it")
        h.run_until(lambda: h.status("ticket-3") is RunStatus.DONE)
        h.tick()
        self.assertEqual(h.status("ticket-1"), RunStatus.LEFT_OPEN)
        self.assertIn("deploy to staging", h.github.comments[1][0])
        self.assertIn("ops will do it", h.github.comments[1][0])
        self.assertNotIn(1, h.github.closed)
        self.assertEqual(h.status("ticket-2"), RunStatus.SKIPPED)
        self.assertIn("blocked by #1", h.run("ticket-2").notes)
        self.assertNotIn("ticket-2", h.herdr.agents)
        self.assertEqual(h.state.phase.value, "spec_review")

    def test_leave_open_survives_a_worktree_that_cannot_be_removed(self):
        # e.g. herdr refuses to remove a worktree with uncommitted changes.
        h = self.harness()
        h.turn("ticket-1", {"status": "outward-denied", "summary": "s", "denied_actions": ["x"]})
        h.run_until(lambda: h.open_escalations())
        esc = h.only_escalation()
        h.herdr.fail_next("remove_worktree", RuntimeError("worktree has modified files"))
        h.resolve(esc.id, "leave-open")
        h.tick()
        self.assertEqual(esc.status, EscalationStatus.RESOLVED)
        self.assertEqual(h.status("ticket-1"), RunStatus.LEFT_OPEN)
        self.assertEqual(len(h.github.comments[1]), 1)

    def test_outward_denied_retry_reprompts_implement(self):
        h = self.harness()
        h.turn("ticket-1", {"status": "outward-denied", "summary": "s", "denied_actions": ["x"]})
        h.run_until(lambda: h.open_escalations())
        h.script_ticket("ticket-1")
        h.resolve(h.only_escalation().id, "retry")
        h.run_until(lambda: h.status("ticket-1") is RunStatus.DONE)
        self.assertEqual(h.templates()[:3], ["implement", "implement", "review"])

    def test_pending_spec_finding_comments_without_close_and_unblocks(self):
        h = self.harness([ticket(1), ticket(2, blockers=[1])])
        h.script_ticket("ticket-1", review=PENDING_SPEC)
        h.script_ticket("ticket-2")
        h.run_until(lambda: h.status("ticket-2") is RunStatus.DONE)
        self.assertEqual(h.status("ticket-1"), RunStatus.DONE)
        self.assertEqual(h.github.closed, [2])
        comment = h.github.comments[1][0]
        self.assertIn("[spec] Empty state: needs copy", comment)
        self.assertIn("renamed helper", comment)
        self.assertIn("Left open", comment)
        self.assertEqual(h.run("ticket-1").review, PENDING_SPEC)

    def test_close_retries_only_missing_steps(self):
        h = self.harness()
        h.script_ticket("ticket-1")
        h.github.fail_next("close", RuntimeError("gh down"))
        h.run_until(lambda: h.status("ticket-1") is RunStatus.DONE)
        self.assertEqual(len(h.github.comments[1]), 1)
        self.assertEqual(h.github.closed, [1])

    def test_close_retry_after_budget_exhausted_never_comments_twice(self):
        h = self.harness()
        h.script_ticket("ticket-1")
        h.herdr.fail_next("remove_worktree", RuntimeError("herdr down"))
        h.herdr.fail_next("remove_worktree", RuntimeError("herdr down"))
        h.run_until(lambda: h.open_escalations())
        esc = h.only_escalation()
        self.assertEqual((esc.kind, esc.stage), (EscalationKind.BUDGET_EXHAUSTED, Stage.CLOSE))
        h.resolve(esc.id, "retry")
        h.run_until(lambda: h.status("ticket-1") is RunStatus.DONE)
        self.assertEqual(len(h.github.comments[1]), 1)
        self.assertEqual(h.github.closed, [1])
        self.assertEqual(h.herdr.worktrees, {})

    def test_format_finding(self):
        text = format_finding({"severity": "high", "title": "T", "file": "a.py", "line": 4,
                               "failure_scenario": "boom"})
        self.assertIn("a.py:4", text)
        self.assertIn("boom", text)


if __name__ == "__main__":
    unittest.main()
