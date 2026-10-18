import os
import subprocess
import tempfile
import unittest

from spec_engine.adapters.git_cli import CliGit, GitError
from tests.fakes import make_git_repo


class CliGitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmpdir = os.path.realpath(self.tmp.name)
        self.repo = make_git_repo(self.tmpdir)
        self.git = CliGit()

    def sh(self, *args: str, cwd: str | None = None) -> str:
        return subprocess.run(["git", "-C", cwd or self.repo, *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, name: str, content: str, msg: str, cwd: str | None = None) -> None:
        with open(os.path.join(cwd or self.repo, name), "w", encoding="utf-8") as f:
            f.write(content)
        self.sh("add", name, cwd=cwd)
        self.sh("commit", "-q", "-m", msg, cwd=cwd)

    def test_roots_and_branches(self):
        self.assertEqual(self.git.repo_root(self.repo), self.repo)
        self.assertEqual(self.git.common_dir(self.repo), os.path.join(self.repo, ".git"))
        self.assertEqual(self.git.current_branch(self.repo), "main")
        self.assertTrue(self.git.branch_exists(self.repo, "main"))
        self.assertFalse(self.git.branch_exists(self.repo, "spec-7"))

        self.git.checkout(self.repo, "spec-7", create_from="main")
        self.assertEqual(self.git.current_branch(self.repo), "spec-7")
        self.assertTrue(self.git.branch_exists(self.repo, "spec-7"))
        self.git.checkout(self.repo, "main")
        self.assertEqual(self.git.current_branch(self.repo), "main")
        with self.assertRaises(GitError):
            self.git.checkout(self.repo, "no-such-branch")
        with self.assertRaises(RuntimeError):  # GitError is a RuntimeError, like FakeGit's
            self.git.checkout(self.repo, "x", create_from="no-such-ref")

    def test_common_dir_from_linked_worktree(self):
        wt = os.path.join(self.tmpdir, "wt")
        self.sh("worktree", "add", "-q", "-b", "s7-ticket-1", wt, "main")
        self.assertEqual(self.git.common_dir(wt), os.path.join(self.repo, ".git"))
        self.assertEqual(self.git.repo_root(wt), wt)
        self.assertEqual(self.git.current_branch(wt), "s7-ticket-1")

    def test_common_dir_from_subdirectory(self):
        sub = os.path.join(self.repo, "a", "b")
        os.makedirs(sub)
        self.assertEqual(self.git.common_dir(sub), os.path.join(self.repo, ".git"))
        self.assertEqual(self.git.repo_root(sub), self.repo)

    def test_rev_parse_and_commits_ahead(self):
        main_sha = self.git.rev_parse(self.repo, "main")
        self.assertEqual(main_sha, self.sh("rev-parse", "HEAD"))
        self.assertEqual(len(main_sha), 40)
        self.git.checkout(self.repo, "s7-ticket-1", create_from="main")
        self.commit("a.txt", "a\n", "a")
        self.commit("b.txt", "b\n", "b")
        self.assertEqual(self.git.commits_ahead(self.repo, "main", "s7-ticket-1"), 2)
        self.assertEqual(self.git.commits_ahead(self.repo, "s7-ticket-1", "main"), 0)
        self.assertNotEqual(self.git.rev_parse(self.repo, "s7-ticket-1"), main_sha)
        with self.assertRaises(GitError):
            self.git.rev_parse(self.repo, "no-such-ref")

    def test_is_clean_honors_info_exclude(self):
        self.assertTrue(self.git.is_clean(self.repo))
        os.makedirs(os.path.join(self.repo, ".herdr-spec"))
        with open(os.path.join(self.repo, ".herdr-spec", "r.json"), "w") as f:
            f.write("{}")
        self.assertFalse(self.git.is_clean(self.repo))  # untracked counts
        with open(os.path.join(self.repo, ".git", "info", "exclude"), "a") as f:
            f.write(".herdr-spec/\n")
        self.assertTrue(self.git.is_clean(self.repo))
        with open(os.path.join(self.repo, "README.md"), "a") as f:
            f.write("more\n")
        self.assertFalse(self.git.is_clean(self.repo))  # modified tracked file

    def test_is_clean_tracked_only(self):
        with open(os.path.join(self.repo, "build.log"), "w") as f:
            f.write("artifact\n")
        self.assertFalse(self.git.is_clean(self.repo))
        self.assertTrue(self.git.is_clean(self.repo, untracked=False))
        with open(os.path.join(self.repo, "README.md"), "a") as f:
            f.write("more\n")
        self.assertFalse(self.git.is_clean(self.repo, untracked=False))

    def _diverge(self, conflicting: bool) -> None:
        self.git.checkout(self.repo, "s7-ticket-1", create_from="main")
        self.commit("README.md" if conflicting else "t.txt", "ticket\n", "ticket change")
        self.git.checkout(self.repo, "main")
        self.commit("README.md" if conflicting else "m.txt", "main\n", "main change")

    def test_merge_clean(self):
        self._diverge(conflicting=False)
        result = self.git.merge(self.repo, "s7-ticket-1")
        self.assertTrue(result.ok)
        self.assertFalse(result.conflict)
        self.assertEqual(result.commit, self.sh("rev-parse", "HEAD"))
        self.assertTrue(os.path.exists(os.path.join(self.repo, "t.txt")))
        self.assertTrue(self.git.is_clean(self.repo))

    def test_merge_no_ff_with_message(self):
        self.git.checkout(self.repo, "s7-ticket-1", create_from="main")
        self.commit("t.txt", "t\n", "ticket")
        self.git.checkout(self.repo, "main")
        result = self.git.merge(self.repo, "s7-ticket-1", no_ff=True, message="Merge #1: Thing")
        self.assertTrue(result.ok)
        self.assertEqual(result.commit, self.sh("rev-parse", "HEAD"))
        self.assertEqual(self.sh("log", "-1", "--format=%s"), "Merge #1: Thing")
        self.assertEqual(len(self.sh("log", "-1", "--format=%P").split()), 2)  # a merge commit

    def test_merge_fast_forward_by_default(self):
        self.git.checkout(self.repo, "s7-ticket-1", create_from="main")
        self.commit("t.txt", "t\n", "ticket")
        self.git.checkout(self.repo, "main")
        result = self.git.merge(self.repo, "s7-ticket-1")
        self.assertTrue(result.ok)
        self.assertEqual(result.commit, self.git.rev_parse(self.repo, "s7-ticket-1"))

    def test_merge_conflict_unmerged_paths_and_abort(self):
        self._diverge(conflicting=True)
        before = self.git.rev_parse(self.repo, "HEAD")
        result = self.git.merge(self.repo, "s7-ticket-1", no_ff=True, message="Merge #1")
        self.assertFalse(result.ok)
        self.assertTrue(result.conflict)
        self.assertIsNone(result.commit)
        self.assertIn("CONFLICT", result.output)
        self.assertEqual(self.git.unmerged_paths(self.repo), ["README.md"])
        self.assertFalse(self.git.is_clean(self.repo))
        self.git.merge_abort(self.repo)
        self.assertEqual(self.git.unmerged_paths(self.repo), [])
        self.assertTrue(self.git.is_clean(self.repo))
        self.assertEqual(self.git.rev_parse(self.repo, "HEAD"), before)

    def test_merge_failure_without_conflict(self):
        result = self.git.merge(self.repo, "no-such-branch")
        self.assertFalse(result.ok)
        self.assertFalse(result.conflict)
        self.assertTrue(result.output)

    def test_merge_abort_without_merge_raises(self):
        with self.assertRaises(GitError):
            self.git.merge_abort(self.repo)

    def test_pull_ff_only(self):
        clone = os.path.join(self.tmpdir, "clone")
        subprocess.run(["git", "clone", "-q", self.repo, clone], check=True, capture_output=True)
        self.commit("new.txt", "n\n", "upstream change")
        self.git.pull_ff_only(clone)
        self.assertEqual(self.git.rev_parse(clone, "HEAD"), self.git.rev_parse(self.repo, "main"))


if __name__ == "__main__":
    unittest.main()
