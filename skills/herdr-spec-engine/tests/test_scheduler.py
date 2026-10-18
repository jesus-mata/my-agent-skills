import os
import unittest
from dataclasses import replace

from spec_engine.model import (
    EngineStatus, EscalationKind, EscalationStatus, Phase, RunStatus, Settings, Stage,
)
from tests.engine_harness import (
    BRANCH, IMPLEMENTED, REVIEW_CLEAN, Harness, ticket,
)
from tests.fakes import make_issue, ref

SPEC_REVIEW_CLEAN = {"fixed": [], "hard": [], "not_fixed": []}
E2E_OK = {"passed": ["flow works"], "fixed": [], "pending": []}
HARD = {"severity": "blocker", "title": "Race on save", "file": "src/save.py", "line": 3,
        "failure_scenario": "two saves lose one"}


class SchedulerTest(unittest.TestCase):
    def harness(self, tickets, **kw) -> Harness:
        h = Harness(tickets, **kw)
        self.addCleanup(h.cleanup)
        return h

    # startup --------------------------------------------------------------------------------

    def test_startup_creates_spec_branch_exclude_entry_and_pid(self):
        h = self.harness([ticket(1)]).start()
        self.assertEqual(h.git.cwd_branch[h.root], BRANCH)
        self.assertEqual(h.git.calls_to("checkout")[-1]["create_from"], "main")
        self.assertEqual(len(h.git.calls_to("pull_ff_only")), 1)
        exclude = os.path.join(h.common_dir, "info", "exclude")
        h.new_engine().startup()  # second startup does not duplicate the entry
        with open(exclude) as f:
            self.assertEqual(f.read().splitlines().count(".herdr-spec/"), 1)
        self.assertEqual(h.store.read_pid(), os.getpid())
        self.assertIsNotNone(h.store.load_state())
        self.assertEqual(h.herdr.calls_to("ping"), [{}, {}])

    def test_pid_is_written_before_slow_startup_steps(self):
        # `watch` declares the engine dead after two pid-less polls 5 s apart; `git pull` while
        # creating the spec branch can take longer than that.
        h = self.harness([ticket(1)])
        seen = []
        h.git.pull_ff_only = lambda cwd: seen.append(h.store.read_pid())
        h.start()
        self.assertEqual(seen, [os.getpid()])

    def test_failed_startup_clears_the_pid(self):
        h = self.harness([ticket(1)])
        h.git.fail_next("pull_ff_only", RuntimeError("no tracking information"))
        with self.assertRaises(RuntimeError):
            h.engine.run_forever()
        self.assertIsNone(h.store.read_pid())

    def test_done_tickets_get_no_run_and_satisfy_blockers(self):
        h = self.harness([ticket(1, klass="done"), ticket(2, blockers=[1])]).start()
        self.assertNotIn("s7-ticket-1", h.state.runs)
        h.script_ticket("s7-ticket-2")
        h.run_until(lambda: h.status("s7-ticket-2") is RunStatus.DONE)

    # happy path -----------------------------------------------------------------------------

    def test_chain_a_then_b_reaches_close(self):
        h = self.harness([ticket(1, title="Alpha"), ticket(2, blockers=[1], title="Beta")]).start()
        h.script_ticket("s7-ticket-1")
        h.script_ticket("s7-ticket-2")
        h.tick()
        self.assertEqual(h.status("s7-ticket-1"), RunStatus.ACTIVE)
        self.assertEqual(h.status("s7-ticket-2"), RunStatus.PENDING)
        h.run_until(lambda: h.run("s7-ticket-1").merge_commit is not None)
        self.assertEqual(h.status("s7-ticket-2"), RunStatus.PENDING)  # starts once A is done
        self.assertNotIn("s7-ticket-2", h.herdr.agents)
        h.run_until(lambda: h.status("s7-ticket-2") is RunStatus.DONE)

        self.assertEqual(h.github.assigned, [1, 2])
        self.assertEqual(h.github.closed, [1, 2])
        self.assertIn("Merged into `spec-7`", h.github.comments[1][0])
        root_merges = [c for c in h.git.calls_to("merge") if c["cwd"] == h.root]
        self.assertEqual([c["message"] for c in root_merges],
                         ["Merge #1: Alpha", "Merge #2: Beta"])
        self.assertTrue(all(c["no_ff"] for c in root_merges))
        self.assertEqual(len(h.herdr.removed_worktrees), 2)
        b_impl = [v for n, v in h.rendered if n == "implement" and v["ticket"] == 2][0]
        self.assertIn("#1 Alpha", b_impl["integrated"])
        self.assertEqual(h.run("s7-ticket-1").merge_commit, "spec-7@1")
        # every transition is persisted
        self.assertEqual(h.store.load_state().runs["s7-ticket-2"].status, RunStatus.DONE)
        h.tick()
        self.assertEqual(h.state.phase, Phase.SPEC_REVIEW)

    def _two_independent(self, max_agents):
        h = self.harness([ticket(1), ticket(2)],
                         settings=Settings(max_agents=max_agents)).start()
        h.herdr.on_prompt("s7-ticket-1", lambda f, n, t: f.set_status(n, "working"))
        h.herdr.on_prompt("s7-ticket-2", lambda f, n, t: f.set_status(n, "working"))
        h.tick(3)
        return h

    def test_max_agents_one_runs_tickets_one_at_a_time(self):
        h = self._two_independent(1)
        self.assertEqual(h.status("s7-ticket-1"), RunStatus.ACTIVE)
        self.assertEqual(h.status("s7-ticket-2"), RunStatus.PENDING)

    def test_max_agents_two_runs_tickets_concurrently_in_ascending_order(self):
        h = self._two_independent(2)
        self.assertEqual(h.status("s7-ticket-1"), RunStatus.ACTIVE)
        self.assertEqual(h.status("s7-ticket-2"), RunStatus.ACTIVE)
        starts = [c["name"] for c in h.herdr.calls_to("start_agent")]
        self.assertEqual(starts, ["s7-ticket-1", "s7-ticket-2"])
        b_impl = [v for n, v in h.rendered if n == "implement" and v["ticket"] == 2][0]
        self.assertIn("s7-ticket-1", b_impl["siblings"])

    # escalation kinds before CLAIM -------------------------------------------------------------

    def test_human_ticket_hitl_then_done_after_issue_closed(self):
        h = self.harness([ticket(1, klass="human"), ticket(2, blockers=[1])]).start()
        h.script_ticket("s7-ticket-2")
        h.tick()
        esc = h.only_escalation()
        self.assertEqual(esc.kind, EscalationKind.HITL_TICKET)
        self.assertEqual(esc.run, "s7-human-1")
        self.assertEqual(h.status("s7-human-1"), RunStatus.ESCALATED)

        h.resolve(esc.id, "done")  # still open on GitHub -> stays escalated
        h.tick()
        self.assertEqual(h.status("s7-human-1"), RunStatus.ESCALATED)
        self.assertEqual(esc.status, EscalationStatus.OPEN)
        self.assertIn("still open", esc.details)
        self.assertEqual(h.status("s7-ticket-2"), RunStatus.PENDING)

        h.github.close(1)
        h.resolve(esc.id, "done")
        h.tick()
        self.assertEqual(esc.status, EscalationStatus.RESOLVED)
        self.assertEqual(h.status("s7-human-1"), RunStatus.DONE)
        h.run_until(lambda: h.status("s7-ticket-2") is RunStatus.DONE)

    def test_unrefined_ticket_relabeled_then_starts(self):
        h = self.harness([ticket(1, klass="unrefined")]).start()
        h.script_ticket("s7-ticket-1")
        h.tick()
        esc = h.only_escalation()
        self.assertEqual(esc.kind, EscalationKind.UNREFINED_TICKET)
        self.assertNotIn("s7-ticket-1", h.herdr.agents)
        h.github.add(replace(h.github.issues[1], labels=("ready-for-agent",)))
        h.resolve(esc.id, "relabeled")
        h.tick()
        self.assertEqual(esc.status, EscalationStatus.RESOLVED)
        self.assertEqual(h.status("s7-ticket-1"), RunStatus.ACTIVE)
        h.run_until(lambda: h.status("s7-ticket-1") is RunStatus.DONE)

    def test_unrefined_ticket_relabeled_human_becomes_human_run(self):
        h = self.harness([ticket(1, klass="unrefined")]).start()
        h.tick()
        h.github.add(replace(h.github.issues[1], labels=("ready-for-human",)))
        h.resolve(h.only_escalation().id, "relabeled")
        h.tick(2)
        self.assertNotIn("s7-ticket-1", h.state.runs)
        self.assertEqual(h.status("s7-human-1"), RunStatus.ESCALATED)
        self.assertEqual(h.only_escalation().kind, EscalationKind.HITL_TICKET)

    def test_external_blocker_cleared_then_starts(self):
        h = self.harness([ticket(1, external=["o/other#99"])])
        h.github.add(make_issue(1, labels=["ready-for-agent"],
                                blocked_by=[ref(99, repo="o/other")]))
        h.start()
        h.script_ticket("s7-ticket-1")
        h.tick()
        esc = h.only_escalation()
        self.assertEqual(esc.kind, EscalationKind.EXTERNAL_BLOCKER)
        self.assertIn("o/other#99", esc.details)

        h.resolve(esc.id, "cleared")  # still open -> escalates again
        h.tick()
        self.assertEqual(h.only_escalation().kind, EscalationKind.EXTERNAL_BLOCKER)
        self.assertNotEqual(h.only_escalation().id, esc.id)

        h.github.add(make_issue(1, labels=["ready-for-agent"],
                                blocked_by=[ref(99, state="CLOSED", repo="o/other")]))
        h.resolve(h.only_escalation().id, "cleared")
        h.run_until(lambda: h.status("s7-ticket-1") is RunStatus.DONE)

    def test_skip_unrefined_ticket_skips_dependents_at_end(self):
        h = self.harness([ticket(1, klass="unrefined"), ticket(2, blockers=[1]),
                          ticket(3, blockers=[2])]).start()
        h.tick()
        h.resolve(h.only_escalation().id, "skip-ticket")
        h.tick()
        self.assertEqual(h.status("s7-ticket-1"), RunStatus.SKIPPED)
        self.assertEqual(h.status("s7-ticket-2"), RunStatus.SKIPPED)
        self.assertEqual(h.status("s7-ticket-3"), RunStatus.SKIPPED)
        self.assertIn("blocked by #1", h.run("s7-ticket-2").notes)
        self.assertIn("blocked by #2", h.run("s7-ticket-3").notes)
        self.assertEqual(h.state.phase, Phase.SPEC_REVIEW)

    # resolutions ----------------------------------------------------------------------------

    def test_hand_to_human_is_not_resolved_until_another_action(self):
        h = self.harness([ticket(1)]).start()
        h.herdr.on_prompt("s7-ticket-1", lambda f, n, t: f.set_status(n, "blocked"))
        h.tick()
        esc = h.only_escalation()
        self.assertEqual(esc.kind, EscalationKind.AGENT_BLOCKED)
        h.resolve(esc.id, "hand-to-human")
        h.tick(3)
        self.assertEqual(esc.status, EscalationStatus.HANDED_OFF)
        self.assertEqual(h.status("s7-ticket-1"), RunStatus.ESCALATED)
        self.assertEqual(h.store.load_state().escalations[esc.id].status,
                         EscalationStatus.HANDED_OFF)

        h.herdr.set_status("s7-ticket-1", "working")
        h.resolve(esc.id, "answered")
        h.tick()
        self.assertEqual(esc.status, EscalationStatus.RESOLVED)
        self.assertEqual(esc.resolution, "answered")
        self.assertEqual(h.status("s7-ticket-1"), RunStatus.ACTIVE)

    def test_invalid_or_duplicate_resolutions_are_ignored(self):
        h = self.harness([ticket(1, klass="unrefined")]).start()
        h.tick()
        esc = h.only_escalation()
        h.resolve(esc.id, "retry")  # not allowed for unrefined-ticket
        h.resolve("e999", "relabeled")
        h.tick()
        self.assertEqual(esc.status, EscalationStatus.OPEN)
        self.assertEqual(len(h.state.consumed_resolutions), 2)
        h.tick()
        self.assertEqual(len(h.state.consumed_resolutions), 2)

    def test_skip_ticket_interrupts_removes_worktree_and_skips(self):
        h = self.harness([ticket(1), ticket(2, blockers=[1])],
                         settings=Settings(stage_timeout=100)).start()
        h.herdr.on_prompt("s7-ticket-1", lambda f, n, t: f.set_status(n, "working"))
        h.run_until(lambda: h.open_escalations())
        esc = h.only_escalation()
        self.assertEqual(esc.kind, EscalationKind.STAGE_TIMEOUT)
        h.resolve(esc.id, "skip-ticket", note="too big")
        h.tick()
        self.assertEqual(h.status("s7-ticket-1"), RunStatus.SKIPPED)
        self.assertIn("s7-ticket-1", h.herdr.interrupted)
        self.assertEqual(len(h.herdr.removed_worktrees), 1)
        self.assertIn("skipped by supervisor (stage-timeout): too big", h.run("s7-ticket-1").notes)
        self.assertEqual(h.status("s7-ticket-2"), RunStatus.SKIPPED)

    # stop and resume ------------------------------------------------------------------------

    def test_stop_file_persists_and_exits(self):
        h = self.harness([ticket(1)]).start()
        h.herdr.on_prompt("s7-ticket-1", lambda f, n, t: f.set_status(n, "working"))
        h.tick()
        h.store.request_stop()
        self.assertFalse(h.engine.tick())
        self.assertFalse(h.store.stop_requested())
        self.assertIsNone(h.store.read_pid())
        self.assertEqual(h.store.load_state().runs["s7-ticket-1"].stage, Stage.IMPLEMENT)

    def test_run_forever_waits_between_ticks_until_stopped(self):
        h = self.harness([ticket(1)])
        h.herdr.on_prompt("s7-ticket-1", lambda f, n, t: f.set_status(n, "working"))
        original = h.herdr.wait_for_change
        calls = []

        def wait(timeout):
            calls.append(timeout)
            original(timeout)
            if len(calls) == 3:
                h.store.request_stop()

        h.herdr.wait_for_change = wait
        self.assertEqual(h.engine.run_forever(), 0)
        self.assertEqual(calls, [10, 10, 10])
        self.assertIsNone(h.store.read_pid())

    def test_resume_with_working_agent_does_not_reprompt(self):
        h = self.harness([ticket(1)]).start()
        h.herdr.on_prompt("s7-ticket-1", lambda f, n, t: f.set_status(n, "working"))
        h.tick(2)
        self.assertEqual(len(h.herdr.prompts["s7-ticket-1"]), 1)
        h.store.request_stop()
        h.tick()

        h.engine = h.new_engine()
        h.start()
        h.tick(3)
        self.assertEqual(len(h.herdr.prompts["s7-ticket-1"]), 1)
        self.assertEqual(h.status("s7-ticket-1"), RunStatus.ACTIVE)

        # the agent finishes the turn it was working on
        path = h.run("s7-ticket-1").awaiting["path"]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write('{"status": "implemented", "summary": "s", "denied_actions": []}')
        h.git.add_commits("s7-ticket-1", 1, base=BRANCH)
        h.turn("s7-ticket-1", REVIEW_CLEAN)
        h.herdr.set_status("s7-ticket-1", "idle")
        h.run_until(lambda: h.status("s7-ticket-1") is RunStatus.DONE)

    def test_resume_with_missing_agent_reprovisions(self):
        h = self.harness([ticket(1)]).start()
        h.herdr.on_prompt("s7-ticket-1", lambda f, n, t: f.set_status(n, "working"))
        h.tick(2)
        h.store.request_stop()
        h.tick()
        h.herdr.remove_agent("s7-ticket-1")  # herdr restarted while the engine was down

        h.engine = h.new_engine()
        h.start()
        h.script_ticket("s7-ticket-1")
        h.tick()
        self.assertEqual(len(h.herdr.calls_to("open_worktree")), 1)
        self.assertEqual(len(h.herdr.calls_to("start_agent")), 2)
        self.assertEqual(len(h.herdr.prompts["s7-ticket-1"]), 2)
        self.assertEqual(h.herdr.prompts["s7-ticket-1"][0], h.herdr.prompts["s7-ticket-1"][1])
        self.assertEqual(h.run("s7-ticket-1").attempts[Stage.IMPLEMENT], 1)
        h.run_until(lambda: h.status("s7-ticket-1") is RunStatus.DONE)

    # spec phases ----------------------------------------------------------------------------

    def test_full_flow_spec_review_fix_e2e_complete(self):
        h = self.harness([ticket(1)]).start()
        h.script_ticket("s7-ticket-1")
        h.turn("s7-review", {"fixed": [], "hard": [HARD], "not_fixed": []})
        h.turn("s7-fix-1", IMPLEMENTED, commits=1)
        h.turn("s7-fix-1", REVIEW_CLEAN)
        h.turn("s7-e2e", E2E_OK)
        h.run_until(lambda: h.state.status is EngineStatus.COMPLETE, max_ticks=80)

        self.assertEqual(h.state.phase, Phase.COMPLETE)
        fix = h.run("s7-fix-1")
        self.assertEqual(fix.status, RunStatus.DONE)
        self.assertEqual(fix.finding, HARD)
        self.assertEqual(h.templates().count("fix_implement"), 1)
        self.assertIn("Race on save", [v for n, v in h.rendered if n == "fix_review"][0]["finding"])
        root_merges = [c["message"] for c in h.git.calls_to("merge") if c["cwd"] == h.root]
        self.assertEqual(root_merges, ["Merge #1: Ticket 1", "Merge s7-fix-1: Race on save"])
        self.assertEqual([c["label"] for c in h.herdr.calls_to("create_tab")],
                         ["s7-review", "s7-e2e"])
        self.assertEqual(h.herdr.closed_panes, [])  # spec review and e2e tabs stay open
        self.assertEqual(h.github.closed, [1])  # fix runs touch no issue
        with open(h.store.paths.report) as f:
            report = f.read()
        self.assertIn("nothing was pushed", report)
        self.assertIsNone(h.store.read_pid())
        self.assertFalse(h.engine.tick())
        self.assertEqual(h.store.load_state().status, EngineStatus.COMPLETE)

    def test_spec_review_without_hard_findings_goes_straight_to_e2e(self):
        h = self.harness([ticket(1)]).start()
        h.script_ticket("s7-ticket-1")
        h.turn("s7-review", SPEC_REVIEW_CLEAN)
        h.turn("s7-e2e", E2E_OK)
        h.run_until(lambda: h.state.status is EngineStatus.COMPLETE, max_ticks=80)
        self.assertFalse([r for r in h.state.runs if r.startswith("s7-fix-")])
        spec_review = [v for n, v in h.rendered if n == "spec_review"][0]
        self.assertEqual(spec_review["base"], "main")
        self.assertTrue(spec_review["result_path"].startswith(h.root))


if __name__ == "__main__":
    unittest.main()
