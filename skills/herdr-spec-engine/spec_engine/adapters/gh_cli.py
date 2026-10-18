"""GitHub via the ``gh`` CLI."""
from __future__ import annotations

import json
import re
import subprocess
from typing import Any

from ..ports import Issue, IssueRef

ISSUE_FIELDS = "number,title,state,labels,url,subIssues,blockedBy"
REPO_RE = re.compile(r"^https?://[^/]+/([^/]+/[^/]+)/(?:issues|pull)/\d+")
NOT_FOUND_MARKERS = ("could not resolve to an issue", "not found", "no issue")


class GhError(RuntimeError):
    """A ``gh`` command exited non-zero."""


def repo_of(url: str) -> str:
    """``owner/name`` from an issue or PR url ("" if it can't be parsed)."""
    m = REPO_RE.match(url or "")
    return m.group(1) if m else ""


def _refs(value: Any) -> tuple[IssueRef, ...]:
    """Refs from gh's ``{"nodes": [...], "totalCount": n}`` connection (or a bare list)."""
    nodes = value.get("nodes") if isinstance(value, dict) else value
    refs = []
    for n in nodes or []:
        url = str(n.get("url", ""))
        refs.append(IssueRef(number=int(n["number"]), state=str(n.get("state", "OPEN")).upper(),
                             url=url, repo=repo_of(url)))
    return tuple(refs)


def parse_issue(data: dict) -> Issue:
    """An Issue from ``gh issue view --json number,title,state,labels,url,subIssues,blockedBy``."""
    labels = tuple(l["name"] if isinstance(l, dict) else str(l) for l in data.get("labels") or [])
    return Issue(
        number=int(data["number"]), title=str(data.get("title", "")),
        state=str(data.get("state", "OPEN")).upper(), labels=labels, url=str(data.get("url", "")),
        sub_issues=_refs(data.get("subIssues")), blocked_by=_refs(data.get("blockedBy")),
    )


class CliGitHub:
    """The GitHub port, running ``gh`` in ``cwd`` (so it targets that checkout's repo)."""

    def __init__(self, cwd: str, timeout: float = 120.0) -> None:
        self.cwd = cwd
        self.timeout = timeout

    def _gh(self, *args: str, input: str | None = None) -> str:
        proc = subprocess.run(
            ["gh", *args], cwd=self.cwd, input=input, capture_output=True, text=True,
            timeout=self.timeout,
        )
        if proc.returncode != 0:
            msg = (proc.stderr or proc.stdout).strip()
            if args[:2] == ("issue", "view") and any(m in msg.lower() for m in NOT_FOUND_MARKERS):
                raise LookupError(f"issue #{args[2]} not found: {msg}")
            raise GhError(f"gh {' '.join(args)} failed ({proc.returncode}): {msg}")
        return proc.stdout

    def issue(self, number: int) -> Issue:
        return parse_issue(json.loads(self._gh("issue", "view", str(number), "--json",
                                               ISSUE_FIELDS)))

    def assign_self(self, number: int) -> None:
        self._gh("issue", "edit", str(number), "--add-assignee", "@me")

    def comment(self, number: int, body: str) -> None:
        self._gh("issue", "comment", str(number), "--body-file", "-", input=body)

    def close(self, number: int) -> None:
        self._gh("issue", "close", str(number))
