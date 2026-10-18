"""In-memory fakes for every port, plus helpers to build issues and real git repos for tests."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections import defaultdict, deque
from dataclasses import replace
from typing import Any, Callable, Iterable

from spec_engine.ports import HerdrError, Issue, IssueRef, MergeResult, ShellResult, Worktree

# Absolute path of a result file inside a prompt: .../.herdr-spec/<run_id>.<stage>.json
RESULT_PATH_RE = re.compile(r"(/[^\s`'\"<>()]*/\.herdr-spec/[^\s`'\"<>()/]+\.json)")

PromptHandler = Callable[["FakeHerdr", str, str], None]


class _Recorder:
    """Records calls and raises errors injected with ``fail_next``."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._failures: dict[str, deque[Exception]] = defaultdict(deque)

    def fail_next(self, method: str, error: Exception) -> None:
        """Make the next call to ``method`` raise ``error`` (queued; one error per call)."""
        self._failures[method].append(error)

    def _call(self, method: str, **kwargs: Any) -> None:
        self.calls.append((method, kwargs))
        if self._failures[method]:
            raise self._failures[method].popleft()

    def calls_to(self, method: str) -> list[dict[str, Any]]:
        return [kw for m, kw in self.calls if m == method]


class FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self._now = float(now)

    def now(self) -> float:
        return self._now

    def sleep(self, seconds: float) -> None:
        self._now += seconds

    def advance(self, seconds: float) -> None:
        self._now += seconds


def find_result_path(text: str) -> str | None:
    """The first ``/abs/.../.herdr-spec/<name>.json`` path in a prompt, or None."""
    m = RESULT_PATH_RE.search(text)
    return m.group(1) if m else None


class FakeHerdr(_Recorder):
    """Herdr in memory. Worktrees are real directories under ``worktree_root``.

    An agent's prompt is handled by the next queued ``on_prompt`` / ``script_turn`` handler for
    that agent; with none queued the agent just becomes ``working``.
    """

    def __init__(self, worktree_root: str, clock: FakeClock | None = None) -> None:
        super().__init__()
        self.worktree_root = worktree_root
        self.clock = clock
        self._seq = 0
        self.worktrees: dict[str, Worktree] = {}  # workspace_id -> Worktree
        self.removed_worktrees: list[str] = []
        self.tabs: dict[str, str] = {}  # pane_id -> label
        self.panes: dict[str, str] = {}  # pane_id -> cwd
        self.closed_panes: list[str] = []
        self.agents: dict[str, str] = {}  # name -> status
        self.agent_panes: dict[str, str] = {}  # name -> pane_id
        self.agent_args: dict[str, list[str]] = {}
        self.prompts: dict[str, list[str]] = defaultdict(list)
        self.screens: dict[str, str] = {}  # name -> text returned by read_agent
        self.interrupted: list[str] = []
        self._handlers: dict[str, deque[PromptHandler]] = defaultdict(deque)

    def _next(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}{self._seq}"

    # scripting -------------------------------------------------------------------------------

    def on_prompt(self, name: str, handler: PromptHandler) -> None:
        """Queue ``handler(fake, name, text)`` for the next prompt to agent ``name``."""
        self._handlers[name].append(handler)

    def script_turn(
        self,
        name: str,
        result_json: dict | str | None,
        status_after: str = "idle",
        write_to: str | Callable[[str], str] | None = None,
    ) -> None:
        """On the next prompt to ``name``: write ``result_json`` and set ``status_after``.

        The result goes to the ``.herdr-spec/*.json`` path found in the prompt text, or to
        ``write_to`` (a path, or a callable taking the prompt text). A ``str`` result is written
        verbatim (for invalid-JSON cases); ``None`` writes nothing.
        """

        def handler(fake: FakeHerdr, agent: str, text: str) -> None:
            if result_json is not None:
                if callable(write_to):
                    path = write_to(text)
                elif write_to is not None:
                    path = write_to
                else:
                    path = find_result_path(text)
                if not path:
                    raise AssertionError(f"no .herdr-spec result path in prompt to {agent}:\n{text}")
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(result_json if isinstance(result_json, str) else json.dumps(result_json))
            fake.set_status(agent, status_after)

        self.on_prompt(name, handler)

    def set_status(self, name: str, status: str) -> None:
        """Set an agent's status; ``"missing"`` removes the agent."""
        if status == "missing":
            self.agents.pop(name, None)
        else:
            self.agents[name] = status

    def remove_agent(self, name: str) -> None:
        self.agents.pop(name, None)

    # Herdr protocol --------------------------------------------------------------------------

    def ping(self) -> dict:
        self._call("ping")
        return {"version": "fake"}

    def create_worktree(self, cwd: str, branch: str, base: str, label: str) -> Worktree:
        self._call("create_worktree", cwd=cwd, branch=branch, base=base, label=label)
        return self._make_worktree(branch)

    def open_worktree(self, cwd: str, branch: str, label: str) -> Worktree:
        self._call("open_worktree", cwd=cwd, branch=branch, label=label)
        for wt in self.worktrees.values():
            if os.path.basename(wt.path) == branch:
                return wt
        return self._make_worktree(branch)

    def _make_worktree(self, branch: str) -> Worktree:
        path = os.path.join(self.worktree_root, branch)
        os.makedirs(path, exist_ok=True)
        wt = Worktree(workspace_id=self._next("w"), pane_id=self._next("p"), path=path)
        self.worktrees[wt.workspace_id] = wt
        self.panes[wt.pane_id] = path
        return wt

    def remove_worktree(self, workspace_id: str, force: bool = False) -> None:
        self._call("remove_worktree", workspace_id=workspace_id, force=force)
        wt = self.worktrees.pop(workspace_id, None)
        if wt is None:
            raise HerdrError("workspace_not_found", f"no workspace {workspace_id}")
        shutil.rmtree(wt.path, ignore_errors=True)
        self.removed_worktrees.append(workspace_id)

    def create_tab(self, cwd: str, label: str) -> str:
        self._call("create_tab", cwd=cwd, label=label)
        pane = self._next("p")
        self.tabs[pane] = label
        self.panes[pane] = cwd
        return pane

    def split_pane(self, pane_id: str, cwd: str) -> str:
        self._call("split_pane", pane_id=pane_id, cwd=cwd)
        pane = self._next("p")
        self.panes[pane] = cwd
        return pane

    def close_pane(self, pane_id: str) -> None:
        self._call("close_pane", pane_id=pane_id)
        self.panes.pop(pane_id, None)
        self.closed_panes.append(pane_id)

    def start_agent(self, name: str, pane_id: str, args: list[str]) -> None:
        self._call("start_agent", name=name, pane_id=pane_id, args=list(args))
        self.agents[name] = "idle"
        self.agent_panes[name] = pane_id
        self.agent_args[name] = list(args)

    def prompt_agent(self, name: str, text: str) -> None:
        self._call("prompt_agent", name=name, text=text)
        if name not in self.agents:
            raise HerdrError("agent_not_found", f"no agent {name}")
        self.prompts[name].append(text)
        if self._handlers[name]:
            self._handlers[name].popleft()(self, name, text)
        else:
            self.agents[name] = "working"

    def agent_status(self, name: str) -> str:
        self._call("agent_status", name=name)
        return self.agents.get(name, "missing")

    def read_agent(self, name: str, lines: int) -> str:
        self._call("read_agent", name=name, lines=lines)
        if name not in self.agents:
            raise HerdrError("agent_not_found", f"no agent {name}")
        return self.screens.get(name, "")

    def interrupt_agent(self, name: str) -> None:
        self._call("interrupt_agent", name=name)
        self.interrupted.append(name)
        if name in self.agents:
            self.agents[name] = "idle"

    def wait_for_change(self, timeout: float) -> None:
        self._call("wait_for_change", timeout=timeout)
        if self.clock is not None:
            self.clock.advance(timeout)


def ref(number: int, state: str = "OPEN", repo: str = "o/r") -> IssueRef:
    return IssueRef(number=number, state=state, url=f"https://github.com/{repo}/issues/{number}",
                    repo=repo)


def make_issue(
    number: int,
    title: str = "",
    state: str = "OPEN",
    labels: Iterable[str] = (),
    sub_issues: Iterable[int | IssueRef] = (),
    blocked_by: Iterable[int | IssueRef] = (),
    repo: str = "o/r",
) -> Issue:
    """An Issue in ``repo``; int refs become OPEN refs in ``repo`` (pass ``ref(...)`` otherwise)."""
    as_ref = lambda r: r if isinstance(r, IssueRef) else ref(r, repo=repo)  # noqa: E731
    return Issue(
        number=number, title=title or f"Issue {number}", state=state, labels=tuple(labels),
        url=f"https://github.com/{repo}/issues/{number}",
        sub_issues=tuple(as_ref(r) for r in sub_issues),
        blocked_by=tuple(as_ref(r) for r in blocked_by),
    )


class FakeGitHub(_Recorder):
    def __init__(self, issues: dict[int, Issue] | Iterable[Issue] = ()) -> None:
        super().__init__()
        if not isinstance(issues, dict):
            issues = {i.number: i for i in issues}
        self.issues: dict[int, Issue] = dict(issues)
        self.assigned: list[int] = []
        self.comments: dict[int, list[str]] = defaultdict(list)
        self.closed: list[int] = []

    def add(self, issue: Issue) -> None:
        self.issues[issue.number] = issue

    def issue(self, number: int) -> Issue:
        self._call("issue", number=number)
        if number not in self.issues:
            raise LookupError(f"issue #{number} not found")
        return self.issues[number]

    def assign_self(self, number: int) -> None:
        self._call("assign_self", number=number)
        self.assigned.append(number)

    def comment(self, number: int, body: str) -> None:
        self._call("comment", number=number, body=body)
        self.comments[number].append(body)

    def close(self, number: int) -> None:
        self._call("close", number=number)
        self.closed.append(number)
        if number in self.issues:
            self.issues[number] = replace(self.issues[number], state="CLOSED")


class FakeShell(_Recorder):
    """``results[cmd]`` is a ShellResult or a list consumed in order (the last one repeats)."""

    def __init__(self, results: dict[str, ShellResult | list[ShellResult]] | None = None) -> None:
        super().__init__()
        self.results: dict[str, ShellResult | list[ShellResult]] = dict(results or {})
        self.default = ShellResult(code=0, output="")

    def run(self, cmd: str, cwd: str, timeout: float) -> ShellResult:
        self._call("run", cmd=cmd, cwd=cwd, timeout=timeout)
        r = self.results.get(cmd, self.default)
        if isinstance(r, list):
            if not r:
                return self.default
            return r.pop(0) if len(r) > 1 else r[0]
        return r


class FakeGit(_Recorder):
    """Git in memory.

    ``branches`` maps branch -> commit count; ``commits_ahead`` is the count difference. Each
    branch has a revision counter behind ``rev_parse`` that bumps on ``add_commits`` and on a
    successful merge into it. The branch of a ``cwd`` is ``set_branch``/``checkout``'s value,
    else ``head`` for ``root``, else the cwd's basename (FakeHerdr worktrees are
    ``<worktree_root>/<branch>``).
    """

    def __init__(self, root: str = "/repo", branches: dict[str, int] | None = None,
                 head: str = "main") -> None:
        super().__init__()
        self.root = root
        self.branches: dict[str, int] = dict(branches or {"main": 1})
        self.head = head
        self.revs: dict[str, int] = defaultdict(int)
        self.cwd_branch: dict[str, str] = {}
        self.clean: dict[str, bool] = {}
        self.unmerged: dict[str, list[str]] = {}
        self._merges: dict[tuple[str, str], deque[MergeResult]] = defaultdict(deque)

    # scripting -------------------------------------------------------------------------------

    def set_branch(self, cwd: str, branch: str) -> None:
        self.cwd_branch[cwd] = branch

    def set_clean(self, cwd: str, clean: bool) -> None:
        self.clean[cwd] = clean

    def set_unmerged(self, cwd: str, paths: list[str]) -> None:
        self.unmerged[cwd] = list(paths)

    def add_commits(self, branch: str, n: int = 1, base: str | None = None) -> None:
        """Add ``n`` commits to ``branch`` (created from ``base``/``head`` if missing)."""
        if branch not in self.branches:
            self.branches[branch] = self.branches.get(base or self.head, 0)
        self.branches[branch] += n
        self.revs[branch] += 1

    def script_merge(self, cwd: str | None, ref: str, result: MergeResult) -> None:
        """Queue ``result`` for the next merge of ``ref`` in ``cwd`` (None = any cwd)."""
        self._merges[(cwd or "*", ref)].append(result)

    # Git protocol ----------------------------------------------------------------------------

    def common_dir(self, cwd: str) -> str:
        self._call("common_dir", cwd=cwd)
        return os.path.join(self.root, ".git")

    def repo_root(self, cwd: str) -> str:
        self._call("repo_root", cwd=cwd)
        return self.root

    def _branch_of(self, cwd: str) -> str:
        if cwd in self.cwd_branch:
            return self.cwd_branch[cwd]
        if os.path.normpath(cwd) == os.path.normpath(self.root):
            return self.head
        return os.path.basename(os.path.normpath(cwd))

    def current_branch(self, cwd: str) -> str:
        self._call("current_branch", cwd=cwd)
        return self._branch_of(cwd)

    def branch_exists(self, cwd: str, branch: str) -> bool:
        self._call("branch_exists", cwd=cwd, branch=branch)
        return branch in self.branches

    def checkout(self, cwd: str, branch: str, create_from: str | None = None) -> None:
        self._call("checkout", cwd=cwd, branch=branch, create_from=create_from)
        if create_from is not None:
            if create_from not in self.branches:
                raise RuntimeError(f"unknown ref {create_from}")
            self.branches[branch] = self.branches[create_from]
        elif branch not in self.branches:
            raise RuntimeError(f"unknown branch {branch}")
        self.cwd_branch[cwd] = branch

    def pull_ff_only(self, cwd: str) -> None:
        self._call("pull_ff_only", cwd=cwd)

    def rev_parse(self, cwd: str, ref: str) -> str:
        self._call("rev_parse", cwd=cwd, ref=ref)
        return f"{ref}@{self.revs[ref]}"

    def commits_ahead(self, cwd: str, base: str, branch: str) -> int:
        self._call("commits_ahead", cwd=cwd, base=base, branch=branch)
        b = self.branches.get(base, 0)
        return max(0, self.branches.get(branch, b) - b)

    def is_clean(self, cwd: str, untracked: bool = True) -> bool:
        self._call("is_clean", cwd=cwd)
        return self.clean.get(cwd, True)

    def unmerged_paths(self, cwd: str) -> list[str]:
        self._call("unmerged_paths", cwd=cwd)
        return list(self.unmerged.get(cwd, []))

    def merge(self, cwd: str, ref: str, no_ff: bool = False,
              message: str | None = None) -> MergeResult:
        self._call("merge", cwd=cwd, ref=ref, no_ff=no_ff, message=message)
        queue = self._merges.get((cwd, ref)) or self._merges.get(("*", ref))
        result = queue.popleft() if queue else MergeResult(ok=True, conflict=False, commit=None,
                                                           output="")
        if not result.ok:
            return result
        target = self._branch_of(cwd)
        self.branches[target] = max(self.branches.get(target, 0), self.branches.get(ref, 0)) + 1
        self.revs[target] += 1
        return replace(result, commit=result.commit or f"{target}@{self.revs[target]}")

    def merge_abort(self, cwd: str) -> None:
        self._call("merge_abort", cwd=cwd)


def make_git_repo(tmpdir: str, name: str = "repo") -> str:
    """Init a real git repo at ``<tmpdir>/<name>`` with one commit on ``main``; returns its path."""
    path = os.path.join(tmpdir, name)
    os.makedirs(path, exist_ok=True)

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", path, *args], check=True, capture_output=True, text=True)

    git("init", "-q", "-b", "main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.com")
    git("config", "commit.gpgsign", "false")
    with open(os.path.join(path, "README.md"), "w", encoding="utf-8") as f:
        f.write("# test\n")
    git("add", "README.md")
    git("commit", "-q", "-m", "initial")
    return path
