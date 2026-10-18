import os
import unittest

from spec_engine.model import EscalationKind, EscalationStatus, RunStatus, Settings, Stage
from spec_engine.ports import MergeResult, ShellResult
from tests.engine_harness import BRANCH, GATE_FIXED, Harness, ticket

CONFLICT = MergeResult(ok=False, conflict=True, commit=None, output="CONFLICT (content)")
FAIL = ShellResult(code=1, output="\n".join(f"line {i}" for i in range(1, 201)))
PASS = ShellResult(code=0, output="ok")


class MergeQueueTest(unittest.TestCase):
    def harness(self, tickets=None, **kw) -> Harness:
        h = Harness(tickets or [ticket(1, title="Alpha")], **kw)
        self.addCleanup(h.cleanup)
        return h.start()

    def worktree(self, h, run_id="ticket-1"):
        return os.path.join(h.herdr.worktree_root, run_id)

    def worktree_merges(self, h, run_id="ticket-1"):
        return [c for c in h.git.calls_to("merge") if c["cwd"] == self.worktree(h, run_id)]

    def root_merges(self, h):
        return [c for c in h.git.calls_to("merge") if c["cwd"] == h.root]

    def test_clean_merge_runs_gate_in_worktree_then_merges_no_ff(self):
        h = self.harness(gate=("pnpm install", "pnpm run test"))
        h.script_ticket("ticket-1")
        h.run_until(lambda: h.status("ticket-1") is RunStatus.DONE)
        wt = self.worktree(h)
        self.assertEqual(self.worktree_merges(h)[0]["ref"], BRANCH)
        self.assertEqual([(c["cmd"], c["cwd"], c["timeout"]) for c in h.shell.calls_to("run")],
                         [("pnpm install", wt, 1800), ("pnpm run test", wt, 1800)])
        self.assertEqual(self.root_merges(h), [{"cwd": h.root, "ref": "ticket-1", "no_ff": True,
                                                "message": "Merge #1: Alpha"}])
        self.assertEqual(h.state.queue, [])

    def test_conflict_resolver_resolved_then_gate_and_merge(self):
        h = self.harness()
        wt = self.worktree(h)
        h.git.script_merge(wt, BRANCH, CONFLICT)
        h.git.set_unmerged(wt, ["src/a.py"])
        h.script_ticket("ticket-1")
        h.turn("resolve-ticket-1", {"verdict": "RESOLVED", "summary": "kept both"},
               also=lambda: h.git.set_unmerged(wt, []))
        h.run_until(lambda: h.status("ticket-1") is RunStatus.DONE)

        split = h.herdr.calls_to("split_pane")[0]
        self.assertEqual(split["cwd"], wt)
        self.assertEqual(split["pane_id"], h.herdr.agent_panes["ticket-1"])
        resolver_pane = h.herdr.agent_panes["resolve-ticket-1"]
        self.assertIn(resolver_pane, h.herdr.closed_panes)
        resolver = [v for n, v in h.rendered if n == "resolver"][0]
        self.assertEqual(resolver["conflicts"], "src/a.py")
        self.assertTrue(resolver["result_path"].endswith("ticket-1.resolve.json"))
        self.assertEqual(len(self.root_merges(h)), 1)
        self.assertEqual(len(h.shell.calls_to("run")), 1)

    def test_resolver_escalate_then_resolved_manually_runs_gate(self):
        h = self.harness()
        wt = self.worktree(h)
        h.git.script_merge(wt, BRANCH, CONFLICT)
        h.script_ticket("ticket-1")
        h.turn("resolve-ticket-1", {"verdict": "ESCALATE", "summary": "logic rewrite"})
        h.run_until(lambda: h.open_escalations())
        esc = h.only_escalation()
        self.assertEqual(esc.kind, EscalationKind.RESOLVER_ESCALATED)
        self.assertTrue(esc.details.startswith("logic rewrite"))
        self.assertIn(f"Worktree: {wt}", esc.details)
        self.assertEqual(h.git.calls_to("merge_abort"), [])  # the merge stays for the human
        self.assertIn(h.herdr.agent_panes["resolve-ticket-1"], h.herdr.closed_panes)
        self.assertEqual(h.shell.calls_to("run"), [])

        h.resolve(esc.id, "resolved-manually")
        h.run_until(lambda: h.status("ticket-1") is RunStatus.DONE)
        self.assertEqual(len(self.worktree_merges(h)), 1)  # straight to the gate
        self.assertEqual(len(h.shell.calls_to("run")), 1)

    def test_resolved_manually_refused_until_the_merge_is_committed(self):
        h = self.harness()
        wt = self.worktree(h)
        h.git.script_merge(wt, BRANCH, CONFLICT)
        h.script_ticket("ticket-1")
        h.turn("resolve-ticket-1", {"verdict": "ESCALATE", "summary": "logic rewrite"},
               also=lambda: h.git.set_unmerged(wt, ["src/a.py"]))
        h.run_until(lambda: h.open_escalations())
        esc = h.only_escalation()

        h.resolve(esc.id, "resolved-manually")
        h.tick()
        esc = h.state.escalations[esc.id]
        self.assertEqual(esc.status, EscalationStatus.OPEN)
        self.assertIn("unmerged paths: src/a.py", esc.details)
        self.assertEqual(h.status("ticket-1"), RunStatus.ESCALATED)
        self.assertEqual(h.shell.calls_to("run"), [])

        h.git.set_unmerged(wt, [])  # the human committed the merge
        h.clock.advance(1)
        h.resolve(esc.id, "resolved-manually")
        h.run_until(lambda: h.status("ticket-1") is RunStatus.DONE)
        self.assertEqual(len(h.shell.calls_to("run")), 1)

    def test_resolved_but_still_unmerged_is_treated_as_escalate(self):
        h = self.harness()
        wt = self.worktree(h)
        h.git.script_merge(wt, BRANCH, CONFLICT)
        h.git.set_unmerged(wt, ["src/a.py"])
        h.script_ticket("ticket-1")
        h.turn("resolve-ticket-1", {"verdict": "RESOLVED", "summary": "done?"})
        h.run_until(lambda: h.open_escalations())
        self.assertEqual(h.only_escalation().kind, EscalationKind.RESOLVER_ESCALATED)

    def test_gate_failure_prompts_gate_failed_then_passes(self):
        h = self.harness()
        h.shell.results["make test"] = [FAIL, PASS]
        h.script_ticket("ticket-1")
        h.turn("ticket-1", GATE_FIXED)
        h.run_until(lambda: h.status("ticket-1") is RunStatus.DONE)
        gate = [v for n, v in h.rendered if n == "gate_failed"][0]
        self.assertEqual((gate["command"], gate["exit_code"]), ("make test", 1))
        lines = gate["output"].splitlines()
        self.assertEqual((len(lines), lines[0], lines[-1]), (150, "line 51", "line 200"))
        self.assertTrue(gate["result_path"].endswith("ticket-1.gate_fix.json"))
        self.assertEqual(h.run("ticket-1").gate_attempts, 1)
        self.assertEqual(len(self.worktree_merges(h)), 2)  # back to step 1 after the fix
        self.assertEqual(len(self.root_merges(h)), 1)

    def test_gate_failure_beyond_budget_escalates_and_retry_resets(self):
        h = self.harness(settings=Settings(gate_retry_budget=1))
        h.shell.results["make test"] = [FAIL, FAIL, FAIL, PASS]
        h.script_ticket("ticket-1")
        h.turn("ticket-1", GATE_FIXED)
        h.run_until(lambda: h.open_escalations())
        esc = h.only_escalation()
        self.assertEqual((esc.kind, esc.stage), (EscalationKind.BUDGET_EXHAUSTED, Stage.INTEGRATE))
        self.assertIn("make test", esc.summary)
        self.assertEqual(h.templates().count("gate_failed"), 1)

        h.turn("ticket-1", GATE_FIXED)
        h.resolve(esc.id, "retry")
        h.run_until(lambda: h.status("ticket-1") is RunStatus.DONE)
        self.assertEqual(h.templates().count("gate_failed"), 2)
        self.assertEqual(h.run("ticket-1").gate_attempts, 1)

    def test_spec_branch_moved_during_gate_remerges(self):
        h = self.harness()
        moved = []

        def run(cmd, cwd, timeout):
            result = type(h.shell).run(h.shell, cmd, cwd, timeout)
            if not moved:
                moved.append(cmd)
                h.git.add_commits(BRANCH)  # someone moved the spec branch meanwhile
            return result

        h.shell.run = run
        h.script_ticket("ticket-1")
        h.run_until(lambda: h.status("ticket-1") is RunStatus.DONE)
        self.assertEqual(len(self.worktree_merges(h)), 2)
        self.assertEqual(len(h.shell.calls_to("run")), 2)
        self.assertEqual(len(self.root_merges(h)), 1)

    def test_repo_dirty_escalates_then_retry_merges(self):
        h = self.harness()
        h.git.set_clean(h.root, False)
        h.script_ticket("ticket-1")
        h.run_until(lambda: h.open_escalations())
        esc = h.only_escalation()
        self.assertEqual(esc.kind, EscalationKind.REPO_DIRTY)
        self.assertEqual(esc.actions, ["retry", "hand-to-human"])
        h.git.set_clean(h.root, True)
        h.resolve(esc.id, "retry")
        h.run_until(lambda: h.status("ticket-1") is RunStatus.DONE)
        self.assertEqual(len(h.shell.calls_to("run")), 1)  # gate not re-run

    def test_queue_is_fifo_and_escalated_head_does_not_block(self):
        h = self.harness([ticket(1), ticket(2)], settings=Settings(max_agents=2))
        h.git.script_merge(self.worktree(h, "ticket-1"), BRANCH, CONFLICT)
        h.script_ticket("ticket-1")
        h.script_ticket("ticket-2")
        h.turn("resolve-ticket-1", {"verdict": "ESCALATE", "summary": "too big"})
        h.run_until(lambda: h.status("ticket-2") is RunStatus.DONE)
        self.assertEqual(h.status("ticket-1"), RunStatus.ESCALATED)
        self.assertEqual(h.state.queue, ["ticket-1"])
        h.resolve(h.only_escalation().id, "resolved-manually")
        h.run_until(lambda: h.status("ticket-1") is RunStatus.DONE)
        # ticket-1's gate passed against an old base, so it re-merged the moved spec branch
        self.assertEqual(len(self.worktree_merges(h, "ticket-1")), 2)
        self.assertEqual([c["ref"] for c in self.root_merges(h)], ["ticket-2", "ticket-1"])

    def test_skip_ticket_in_queue_closes_resolver_and_leaves_queue(self):
        h = self.harness(settings=Settings(stage_timeout=100))
        h.git.script_merge(self.worktree(h), BRANCH, CONFLICT)
        h.script_ticket("ticket-1")
        h.herdr.on_prompt("resolve-ticket-1", lambda f, n, t: f.set_status(n, "working"))
        h.run_until(lambda: h.open_escalations())
        esc = h.only_escalation()
        self.assertEqual(esc.kind, EscalationKind.STAGE_TIMEOUT)
        self.assertIn("resolve-ticket-1", esc.summary)
        h.resolve(esc.id, "skip-ticket")
        h.tick()
        self.assertEqual(h.status("ticket-1"), RunStatus.SKIPPED)
        self.assertEqual(h.state.queue, [])
        self.assertIn(h.herdr.agent_panes["resolve-ticket-1"], h.herdr.closed_panes)
        self.assertIn("ticket-1", h.herdr.interrupted)
        self.assertEqual(len(h.herdr.removed_worktrees), 1)

    def test_blocked_resolver_answered_resumes(self):
        h = self.harness()
        h.git.script_merge(self.worktree(h), BRANCH, CONFLICT)
        h.script_ticket("ticket-1")
        h.herdr.on_prompt("resolve-ticket-1", lambda f, n, t: f.set_status(n, "blocked"))
        h.run_until(lambda: h.open_escalations())
        esc = h.only_escalation()
        self.assertEqual(esc.kind, EscalationKind.AGENT_BLOCKED)
        path = h.run("ticket-1").awaiting["path"]
        with open(path, "w") as f:
            f.write('{"verdict": "RESOLVED", "summary": "ok"}')
        h.herdr.set_status("resolve-ticket-1", "idle")
        h.resolve(esc.id, "answered")
        h.run_until(lambda: h.status("ticket-1") is RunStatus.DONE)


if __name__ == "__main__":
    unittest.main()
