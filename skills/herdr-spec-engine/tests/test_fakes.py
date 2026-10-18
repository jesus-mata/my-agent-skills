import json
import os
import subprocess
import tempfile
import unittest

from spec_engine.ports import HerdrError, MergeResult, ShellResult
from tests.fakes import (
    FakeClock, FakeGit, FakeGitHub, FakeHerdr, FakeShell, find_result_path, make_git_repo,
    make_issue, ref,
)


class FakeHerdrTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clock = FakeClock(100)
        self.herdr = FakeHerdr(os.path.join(self.tmp.name, "wt"), clock=self.clock)

    def test_script_turn_writes_result_and_sets_status(self):
        wt = self.herdr.create_worktree("/repo", "s7-ticket-1", "spec-7", "s7-ticket-1")
        self.assertTrue(os.path.isdir(wt.path))
        self.herdr.start_agent("s7-ticket-1", wt.pane_id, ["--model", "opus"])
        result = os.path.join(wt.path, ".herdr-spec", "s7-ticket-1.implement.json")
        self.herdr.script_turn("s7-ticket-1", {"status": "implemented", "summary": "s",
                                            "denied_actions": []}, status_after="done")
        self.herdr.prompt_agent("s7-ticket-1", f"Do it. Write the result to `{result}` when done.")
        with open(result) as f:
            self.assertEqual(json.load(f)["status"], "implemented")
        self.assertEqual(self.herdr.agent_status("s7-ticket-1"), "done")
        self.assertEqual(len(self.herdr.prompts["s7-ticket-1"]), 1)

        # next prompt has no script -> agent is working
        self.herdr.prompt_agent("s7-ticket-1", "again")
        self.assertEqual(self.herdr.agent_status("s7-ticket-1"), "working")

    def test_script_turn_raw_string_and_explicit_path(self):
        self.herdr.start_agent("a", "p0", [])
        target = os.path.join(self.tmp.name, "out.json")
        self.herdr.script_turn("a", "{broken", write_to=target)
        self.herdr.prompt_agent("a", "no path here")
        with open(target) as f:
            self.assertEqual(f.read(), "{broken")
        self.assertEqual(self.herdr.agent_status("a"), "idle")

    def test_on_prompt_and_status(self):
        seen = []
        self.herdr.start_agent("a", "p0", [])
        self.herdr.on_prompt("a", lambda fake, name, text: (seen.append(text),
                                                            fake.set_status(name, "blocked")))
        self.herdr.prompt_agent("a", "hi")
        self.assertEqual(seen, ["hi"])
        self.assertEqual(self.herdr.agent_status("a"), "blocked")
        self.assertEqual(self.herdr.agent_status("nobody"), "missing")
        self.herdr.set_status("a", "missing")
        self.assertEqual(self.herdr.agent_status("a"), "missing")
        with self.assertRaises(HerdrError):
            self.herdr.prompt_agent("a", "hi")

    def test_fail_next_and_calls(self):
        self.herdr.fail_next("create_tab", HerdrError("boom", "nope"))
        with self.assertRaises(HerdrError) as cm:
            self.herdr.create_tab("/repo", "s7-review")
        self.assertEqual(cm.exception.code, "boom")
        pane = self.herdr.create_tab("/repo", "s7-review")
        self.assertTrue(pane.startswith("p"))
        self.assertEqual(self.herdr.calls_to("create_tab"),
                         [{"cwd": "/repo", "label": "s7-review"}] * 2)

    def test_worktrees_ids_and_removal(self):
        a = self.herdr.create_worktree("/repo", "s7-ticket-1", "spec-7", "s7-ticket-1")
        b = self.herdr.create_worktree("/repo", "s7-ticket-2", "spec-7", "s7-ticket-2")
        self.assertNotEqual(a.workspace_id, b.workspace_id)
        self.assertEqual(self.herdr.open_worktree("/repo", "s7-ticket-1", "s7-ticket-1"), a)
        self.herdr.remove_worktree(a.workspace_id)
        self.assertFalse(os.path.exists(a.path))
        self.assertEqual(self.herdr.removed_worktrees, [a.workspace_id])

    def test_wait_for_change_advances_clock(self):
        self.herdr.wait_for_change(10)
        self.assertEqual(self.clock.now(), 110)
        self.clock.sleep(5)
        self.clock.advance(5)
        self.assertEqual(self.clock.now(), 120)

    def test_find_result_path(self):
        self.assertEqual(find_result_path('write JSON to "/a/b/.herdr-spec/fix-1-2.review.json".'),
                         "/a/b/.herdr-spec/fix-1-2.review.json")
        self.assertIsNone(find_result_path("nothing"))


class FakeGitHubTest(unittest.TestCase):
    def test_issues(self):
        gh = FakeGitHub({1: make_issue(1, "Spec", sub_issues=[2, 3]),
                         2: make_issue(2, labels=["ready-for-agent"],
                                       blocked_by=[3, ref(9, "CLOSED", repo="x/y")])})
        spec = gh.issue(1)
        self.assertEqual([r.number for r in spec.sub_issues], [2, 3])
        self.assertEqual(spec.sub_issues[0].url, "https://github.com/o/r/issues/2")
        self.assertEqual(spec.sub_issues[0].repo, "o/r")
        t2 = gh.issue(2)
        self.assertEqual(t2.blocked_by[1].repo, "x/y")
        self.assertEqual(t2.blocked_by[1].state, "CLOSED")
        gh.assign_self(2)
        gh.comment(2, "merged")
        gh.close(2)
        self.assertEqual(gh.issue(2).state, "CLOSED")
        self.assertEqual((gh.assigned, dict(gh.comments), gh.closed), ([2], {2: ["merged"]}, [2]))
        with self.assertRaises(LookupError):
            gh.issue(99)


class FakeShellTest(unittest.TestCase):
    def test_results(self):
        sh = FakeShell({"make test": [ShellResult(1, "fail"), ShellResult(0, "ok")],
                        "make lint": ShellResult(2, "lint")})
        self.assertEqual(sh.run("make test", "/w", 60).code, 1)
        self.assertEqual(sh.run("make test", "/w", 60).code, 0)
        self.assertEqual(sh.run("make test", "/w", 60).code, 0)
        self.assertEqual(sh.run("make lint", "/w", 60).code, 2)
        self.assertEqual(sh.run("other", "/w", 60), ShellResult(0, ""))
        self.assertEqual(sh.calls[0], ("run", {"cmd": "make test", "cwd": "/w", "timeout": 60}))


class FakeGitTest(unittest.TestCase):
    def test_branches_and_merges(self):
        git = FakeGit(root="/repo")
        git.checkout("/repo", "spec-7", create_from="main")
        self.assertEqual(git.current_branch("/repo"), "spec-7")
        self.assertTrue(git.branch_exists("/repo", "spec-7"))
        self.assertEqual(git.commits_ahead("/wt/s7-ticket-1", "spec-7", "s7-ticket-1"), 0)
        git.add_commits("s7-ticket-1", 2, base="spec-7")
        self.assertEqual(git.commits_ahead("/wt/s7-ticket-1", "spec-7", "s7-ticket-1"), 2)

        before = git.rev_parse("/repo", "spec-7")
        git.script_merge("/wt/s7-ticket-1", "spec-7", MergeResult(False, True, None, "CONFLICT"))
        r = git.merge("/wt/s7-ticket-1", "spec-7")
        self.assertTrue(r.conflict)
        self.assertEqual(git.rev_parse("/repo", "spec-7"), before)
        r = git.merge("/repo", "s7-ticket-1", no_ff=True, message="Merge #1: t")
        self.assertTrue(r.ok)
        self.assertIsNotNone(r.commit)
        self.assertNotEqual(git.rev_parse("/repo", "spec-7"), before)
        self.assertEqual(git.commits_ahead("/repo", "spec-7", "s7-ticket-1"), 0)

    def test_clean_and_unmerged(self):
        git = FakeGit()
        self.assertTrue(git.is_clean("/w"))
        git.set_clean("/w", False)
        git.set_unmerged("/w", ["a.py"])
        self.assertFalse(git.is_clean("/w"))
        self.assertEqual(git.unmerged_paths("/w"), ["a.py"])
        git.script_merge(None, "x", MergeResult(False, False, None, "err"))
        self.assertFalse(git.merge("/anywhere", "x").ok)


class MakeGitRepoTest(unittest.TestCase):
    def test_real_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_git_repo(tmp)
            out = subprocess.run(["git", "-C", path, "rev-parse", "--abbrev-ref", "HEAD"],
                                 capture_output=True, text=True, check=True).stdout.strip()
            self.assertEqual(out, "main")
            status = subprocess.run(["git", "-C", path, "status", "--porcelain"],
                                    capture_output=True, text=True, check=True).stdout
            self.assertEqual(status, "")


if __name__ == "__main__":
    unittest.main()
