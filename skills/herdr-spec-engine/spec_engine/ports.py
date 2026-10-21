"""Ports: every external effect of the engine goes through one of these protocols."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

AgentStatus = Literal["idle", "working", "blocked", "done", "unknown", "missing"]


class HerdrError(Exception):
    """An error response from the herdr API."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Worktree:
    workspace_id: str
    pane_id: str
    path: str


@dataclass(frozen=True)
class IssueRef:
    number: int
    state: str
    url: str
    repo: str  # "owner/name"


@dataclass(frozen=True)
class Issue:
    number: int
    title: str
    state: str  # "OPEN" | "CLOSED"
    labels: tuple[str, ...]
    url: str
    sub_issues: tuple[IssueRef, ...]
    blocked_by: tuple[IssueRef, ...]
    body: str = ""


@dataclass(frozen=True)
class OpenIssue:
    number: int
    title: str
    url: str


@dataclass(frozen=True)
class MergeResult:
    ok: bool
    conflict: bool
    commit: str | None
    output: str


@dataclass(frozen=True)
class ShellResult:
    code: int
    output: str  # stdout+stderr merged


class Herdr(Protocol):
    def ping(self) -> dict: ...
    def create_worktree(self, cwd: str, branch: str, base: str, label: str) -> Worktree: ...
    def open_worktree(self, cwd: str, branch: str, label: str) -> Worktree: ...
    def remove_worktree(self, workspace_id: str, force: bool = False) -> None: ...
    def create_tab(self, cwd: str, label: str) -> str: ...  # returns root pane id
    def split_pane(self, pane_id: str, cwd: str) -> str: ...  # returns new pane id
    def close_pane(self, pane_id: str) -> None: ...
    def start_agent(self, name: str, pane_id: str, args: list[str]) -> None: ...  # kind claude
    def prompt_agent(self, name: str, text: str) -> None: ...
    def agent_status(self, name: str) -> AgentStatus: ...
    def agent_pane(self, name: str) -> str | None: ...  # None when herdr has no such agent
    def read_agent(self, name: str, lines: int) -> str: ...
    def interrupt_agent(self, name: str) -> None: ...  # ctrl+c
    def wait_for_change(self, timeout: float) -> None: ...  # may return early


class Git(Protocol):
    def common_dir(self, cwd: str) -> str: ...
    def repo_root(self, cwd: str) -> str: ...
    def current_branch(self, cwd: str) -> str: ...
    def branch_exists(self, cwd: str, branch: str) -> bool: ...
    def checkout(self, cwd: str, branch: str, create_from: str | None = None) -> None: ...
    def pull_ff_only(self, cwd: str) -> None: ...
    def rev_parse(self, cwd: str, ref: str) -> str: ...
    def commits_ahead(self, cwd: str, base: str, branch: str) -> int: ...
    def is_clean(self, cwd: str, untracked: bool = True) -> bool: ...  # respects excludes
    def status_entries(self, cwd: str) -> list[str]: ...  # "XY path", untracked files one by one
    def clean_untracked(self, cwd: str, paths: list[str]) -> None: ...
    def unmerged_paths(self, cwd: str) -> list[str]: ...
    def merge(
        self, cwd: str, ref: str, no_ff: bool = False, message: str | None = None
    ) -> MergeResult: ...
    def merge_abort(self, cwd: str) -> None: ...


class GitHub(Protocol):
    def issue(self, number: int) -> Issue: ...
    def assign_self(self, number: int) -> None: ...
    def comment(self, number: int, body: str) -> None: ...
    def close(self, number: int) -> None: ...
    def open_issues(self) -> list[OpenIssue]: ...
    def create_issue(self, title: str, body: str, labels: list[str]) -> OpenIssue: ...


class Shell(Protocol):
    def run(self, cmd: str, cwd: str, timeout: float) -> ShellResult: ...


class Clock(Protocol):
    def now(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...
