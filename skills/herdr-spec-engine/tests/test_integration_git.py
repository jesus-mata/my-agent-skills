"""The git-facing path of the engine against real git: CliGit, SubprocessShell and real linked
worktrees (``git worktree add``, like herdr's ``worktree.create``). Agents are scripted on a
FakeHerdr whose worktree calls run real git, so only herdr and Claude are faked."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

from spec_engine.adapters.git_cli import CliGit
from spec_engine.adapters.system import SubprocessShell
from spec_engine.model import (
    EscalationKind, Plan, PlanTicket, RunStatus, Settings, TicketClass,
)
from spec_engine.ports import HerdrError, Worktree
from spec_engine.scheduler import Engine
from spec_engine.stages import Context
from spec_engine.store import Store, state_dir_for
from tests.fakes import FakeClock, FakeGitHub, FakeHerdr, find_result_path, make_git_repo, make_issue

SPEC = 9
BRANCH = "spec-9"
IMPLEMENTED = {"status": "implemented", "summary": "done", "denied_actions": []}
REVIEW_CLEAN = {"fixed": [], "pending": [], "scope_creep": []}


def git(cwd: str, *args: str) -> str:
    return subprocess.run(["git", "-C", cwd, *args], check=True, capture_output=True,
                          text=True).stdout.strip()


class GitWorktreeHerdr(FakeHerdr):
    """FakeHerdr whose worktree calls run real git, like herdr does.

    ``worktree.create`` = ``git worktree add -b <branch> <path> <base>``; ``worktree.open`` finds
    the branch's existing worktree; ``worktree.remove`` = ``git worktree remove [--force]``
    (without force git refuses a worktree with untracked or modified files).
    """

    def create_worktree(self, cwd: str, branch: str, base: str, label: str) -> Worktree:
        self._call("create_worktree", cwd=cwd, branch=branch, base=base, label=label)
        path = os.path.join(self.worktree_root, branch)
        git(cwd, "worktree", "add", "-q", "-b", branch, path, base)
        return self._register(path)

    def open_worktree(self, cwd: str, branch: str, label: str) -> Worktree:
        self._call("open_worktree", cwd=cwd, branch=branch, label=label)
        for wt in self.worktrees.values():
            if os.path.basename(wt.path) == branch:
                return wt
        path = os.path.join(self.worktree_root, branch)
        if not os.path.isdir(path):
            raise HerdrError("worktree_not_found", f"no worktree for {branch}")
        return self._register(path)

    def _register(self, path: str) -> Worktree:
        wt = Worktree(workspace_id=self._next("w"), pane_id=self._next("p"), path=path)
        self.worktrees[wt.workspace_id] = wt
        self.panes[wt.pane_id] = path
        return wt

    def remove_worktree(self, workspace_id: str, force: bool = False) -> None:
        self._call("remove_worktree", workspace_id=workspace_id, force=force)
        wt = self.worktrees.get(workspace_id)
        if wt is None:
            raise HerdrError("workspace_not_found", f"no workspace {workspace_id}")
        args = ["worktree", "remove"] + (["--force"] if force else []) + [wt.path]
        proc = subprocess.run(["git", "-C", wt.path, *args], capture_output=True, text=True)
        if proc.returncode != 0:
            raise HerdrError("worktree_remove_failed", proc.stderr.strip())
        del self.worktrees[workspace_id]
        self.removed_worktrees.append(workspace_id)


class RealGitEngineTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        # A bare origin so `pull --ff-only` on main works like in a real clone.
        origin = os.path.join(self.tmp, "origin.git")
        seed = make_git_repo(self.tmp, "seed")
        subprocess.run(["git", "clone", "-q", "--bare", seed, origin], check=True)
        subprocess.run(["git", "clone", "-q", origin, os.path.join(self.tmp, "repo")], check=True)
        shutil.rmtree(seed)
        self.root = os.path.join(self.tmp, "repo")
        for k, v in (("user.name", "Test"), ("user.email", "t@example.com"),
                     ("commit.gpgsign", "false")):
            git(self.root, "config", k, v)
        self.clock = FakeClock(1000)
        self.herdr = GitWorktreeHerdr(os.path.join(self.tmp, "wt"), clock=self.clock)
        self.git = CliGit()

    def engine(self, tickets: list[PlanTicket], gate: list[str]) -> Engine:
        common = self.git.common_dir(self.root)
        plan = Plan(spec=SPEC, title="Spec nine", branch=BRANCH, gate=gate, tickets=tickets)
        github = FakeGitHub([make_issue(t.number, title=t.title, labels=["ready-for-agent"])
                             for t in tickets])
        self.github = github
        ctx = Context(herdr=self.herdr, git=self.git, github=github, shell=SubprocessShell(),
                      clock=self.clock, plan=plan, settings=Settings(), repo_root=self.root,
                      common_dir=common, store=Store(state_dir_for(common, SPEC),
                                                     now=self.clock.now))
        eng = Engine(ctx)
        eng.startup()
        return eng

    def worktree_of(self, agent: str) -> str:
        return self.herdr.panes[self.herdr.agent_panes[agent]]

    def turn(self, agent: str, result: dict, files: dict[str, str] | None = None,
             wt_agent: str | None = None, shell: list[list[str]] | None = None) -> None:
        """On the next prompt to ``agent``: commit ``files`` in its worktree, run ``shell``
        (git args) there, then write the result file."""

        def handler(fake, name, text):
            wt = self.worktree_of(wt_agent or name)
            for path, content in (files or {}).items():
                with open(os.path.join(wt, path), "w", encoding="utf-8") as f:
                    f.write(content)
                git(wt, "add", path)
            if files:
                git(wt, "commit", "-q", "-m", f"{name}: work")
            for args in shell or []:
                git(wt, *args)
            out = find_result_path(text)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                json.dump(result, f)
            fake.set_status(name, "idle")

        self.herdr.on_prompt(agent, handler)

    def run_until(self, eng: Engine, pred, ticks: int = 80) -> None:
        for _ in range(ticks):
            if pred():
                return
            if not eng.tick():
                break
            self.clock.advance(20)
        self.assertTrue(pred(), {r.id: (r.status.value, r.stage.value, r.awaiting)
                                 for r in eng.state.runs.values()}
                        | {"escalations": [e.summary + "\n" + e.details
                                           for e in eng.state.escalations.values()]})

    def t(self, n: int) -> PlanTicket:
        return PlanTicket(number=n, title=f"Ticket {n}", klass=TicketClass.AGENT)

    def test_ticket_merges_into_spec_branch_with_gate_artifacts(self):
        # The gate leaves an untracked artifact in the worktree (a build log, coverage, ...).
        eng = self.engine([self.t(1)], gate=["test -f feature1.txt", "echo built > build.log"])
        self.assertEqual(self.git.current_branch(self.root), BRANCH)
        self.turn("ticket-1", IMPLEMENTED, files={"feature1.txt": "one\n"})
        self.turn("ticket-1", REVIEW_CLEAN)
        run = eng.state.runs["ticket-1"]
        self.run_until(eng, lambda: run.status is RunStatus.DONE)

        log = git(self.root, "log", "--format=%s", "-n", "1", BRANCH)
        self.assertEqual(log, "Merge #1: Ticket 1")
        self.assertEqual(git(self.root, "rev-list", "--count", f"{BRANCH}^1..{BRANCH}^2"), "1")
        self.assertTrue(os.path.exists(os.path.join(self.root, "feature1.txt")))
        self.assertEqual(run.merge_commit, git(self.root, "rev-parse", BRANCH))
        self.assertEqual(self.herdr.worktrees, {})
        self.assertEqual(self.github.closed, [1])
        self.assertEqual(eng.state.escalations, {})

    def test_result_files_never_dirty_a_linked_worktree(self):
        eng = self.engine([self.t(1)], gate=["git diff --quiet"])
        wt_files = {}

        def check_clean():
            wt = self.worktree_of("ticket-1")
            wt_files["clean"] = self.git.is_clean(wt)

        self.turn("ticket-1", IMPLEMENTED, files={"a.txt": "a\n"})
        self.turn("ticket-1", REVIEW_CLEAN)
        run = eng.state.runs["ticket-1"]
        self.run_until(eng, lambda: run.stage.value == "review")
        os.makedirs(os.path.join(self.worktree_of("ticket-1"), ".herdr-spec"), exist_ok=True)
        with open(os.path.join(self.worktree_of("ticket-1"), ".herdr-spec", "x.json"), "w") as f:
            f.write("{}")
        check_clean()
        self.assertTrue(wt_files["clean"])
        self.run_until(eng, lambda: run.status is RunStatus.DONE)

    def test_conflict_resolved_by_resolver_then_merged(self):
        eng = self.engine([self.t(1), self.t(2)], gate=["true"])
        self.turn("ticket-1", IMPLEMENTED, files={"shared.txt": "from one\n"})
        self.turn("ticket-1", REVIEW_CLEAN)
        self.turn("ticket-2", IMPLEMENTED, files={"shared.txt": "from two\n"})
        self.turn("ticket-2", REVIEW_CLEAN)

        # The resolver settles the conflict in ticket-2's worktree and commits the merge.
        def resolve(fake, name, text):
            wt = self.worktree_of("ticket-2")
            with open(os.path.join(wt, "shared.txt"), "w", encoding="utf-8") as f:
                f.write("from one\nfrom two\n")
            git(wt, "add", "shared.txt")
            git(wt, "commit", "-q", "--no-edit")
            out = find_result_path(text)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                json.dump({"verdict": "RESOLVED", "summary": "kept both"}, f)
            fake.set_status(name, "idle")

        self.herdr.on_prompt("resolve-ticket-2", resolve)
        r1, r2 = eng.state.runs["ticket-1"], eng.state.runs["ticket-2"]
        self.run_until(eng, lambda: r1.status is RunStatus.DONE and r2.status is RunStatus.DONE)
        with open(os.path.join(self.root, "shared.txt"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "from one\nfrom two\n")
        self.assertEqual(eng.state.escalations, {})
        self.assertIn("resolve-ticket-2", self.herdr.agent_panes)

    def test_conflict_escalated_then_resolved_manually(self):
        eng = self.engine([self.t(1), self.t(2)], gate=["true"])
        self.turn("ticket-1", IMPLEMENTED, files={"shared.txt": "from one\n"})
        self.turn("ticket-1", REVIEW_CLEAN)
        self.turn("ticket-2", IMPLEMENTED, files={"shared.txt": "from two\n"})
        self.turn("ticket-2", REVIEW_CLEAN)
        self.turn("resolve-ticket-2", {"verdict": "ESCALATE", "summary": "too big"},
                  wt_agent="ticket-2")
        r2 = eng.state.runs["ticket-2"]
        self.run_until(eng, lambda: r2.status is RunStatus.ESCALATED)
        esc = eng.state.escalations[r2.escalation]
        self.assertIs(esc.kind, EscalationKind.RESOLVER_ESCALATED)
        wt = self.worktree_of("ticket-2")
        self.assertEqual(self.git.unmerged_paths(wt), ["shared.txt"])

        # Refused while the merge is unfinished.
        eng.ctx.store.append_resolution(esc.id, "resolved-manually", "")
        eng.tick()
        self.assertIn("resolved-manually refused", esc.details)

        # The human finishes the merge in the worktree.
        with open(os.path.join(wt, "shared.txt"), "w", encoding="utf-8") as f:
            f.write("merged by hand\n")
        git(wt, "add", "shared.txt")
        git(wt, "commit", "-q", "--no-edit")
        self.clock.advance(1)
        eng.ctx.store.append_resolution(esc.id, "resolved-manually", "")
        self.run_until(eng, lambda: r2.status is RunStatus.DONE)
        with open(os.path.join(self.root, "shared.txt"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "merged by hand\n")

    def test_dirty_repo_root_escalates_then_retry_merges(self):
        eng = self.engine([self.t(1)], gate=["true"])
        with open(os.path.join(self.root, "scratch.txt"), "w", encoding="utf-8") as f:
            f.write("user's work\n")
        self.turn("ticket-1", IMPLEMENTED, files={"b.txt": "b\n"})
        self.turn("ticket-1", REVIEW_CLEAN)
        run = eng.state.runs["ticket-1"]
        self.run_until(eng, lambda: run.status is RunStatus.ESCALATED)
        esc = eng.state.escalations[run.escalation]
        self.assertIs(esc.kind, EscalationKind.REPO_DIRTY)
        os.remove(os.path.join(self.root, "scratch.txt"))
        eng.ctx.store.append_resolution(esc.id, "retry", "")
        self.run_until(eng, lambda: run.status is RunStatus.DONE)


if __name__ == "__main__":
    unittest.main()
