"""Follow-ups: review findings that deserve their own issue instead of a fix in this spec.

Ticket, fix and spec reviews report them in their result's ``follow_ups`` list. Once E2E is
over the engine collects them (``collect``), merges duplicates found by several reviews, marks
those already open on GitHub, and proposes the rest to the supervisor in one ``follow-ups``
escalation. Nothing is created on GitHub until the user confirms (``create``).

Each collected entry is the finding plus ``id`` (``f<k>``), ``found_by`` (run ids), ``state``
(one of ``STATES``) and ``issue`` (``{"number", "url"}`` once created or found open, else None).
"""
from __future__ import annotations

import re
from typing import Iterable

from .model import Plan, Run, RunKind
from .ports import GitHub, OpenIssue

PROPOSED = "proposed"
ALREADY_OPEN = "already_open"
CREATED = "created"
DISCARDED = "discarded"
STATES = (PROPOSED, ALREADY_OPEN, CREATED, DISCARDED)

REVIEW_KINDS = (RunKind.TICKET, RunKind.FIX, RunKind.SPEC_REVIEW)
# Issues needing a decision go to a human; the rest need triage before any spec takes them.
LABELS_BY_CATEGORY = {"needs-decision": ["ready-for-human"]}
CATEGORY_TEXT = {
    "pre-existing": "the bug predates this spec",
    "out-of-scope": "fixing it would break a scope rule of the spec",
    "needs-decision": "fixing it needs a product, API or design decision",
    "too-large": "too large for a fix inside the spec",
    "tech-debt": "debt that spans beyond this spec",
}
_ID_RE = re.compile(r"\bf\d+\b")


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def collect(runs: Iterable[Run], open_issues: Iterable[OpenIssue]) -> list[dict]:
    """Every review's follow-ups, merged by (file, title) and matched by title against
    ``open_issues``. Order: first seen first (tickets, spec review, fix runs)."""
    open_by_title = {_norm(i.title): i for i in open_issues}
    entries: dict[tuple[str, str], dict] = {}
    for run in runs:
        if run.kind not in REVIEW_KINDS:
            continue
        for finding in (run.review or {}).get("follow_ups", []):
            key = (_norm(finding.get("file", "")), _norm(finding.get("title", "")))
            if key in entries:
                if run.id not in entries[key]["found_by"]:
                    entries[key]["found_by"].append(run.id)
                continue
            entry = {**finding, "id": f"f{len(entries) + 1}", "found_by": [run.id],
                     "state": PROPOSED, "issue": None}
            match = open_by_title.get(key[1])
            if match is not None:
                entry["state"] = ALREADY_OPEN
                entry["issue"] = {"number": match.number, "url": match.url}
            entries[key] = entry
    return list(entries.values())


def proposed(entries: list[dict]) -> list[dict]:
    return [e for e in entries if e["state"] == PROPOSED]


def where(entry: dict) -> str:
    loc = entry.get("file", "")
    if entry.get("line") is not None:
        loc = f"{loc}:{entry['line']}"
    return loc


def line(entry: dict) -> str:
    """``f1 [high] pre-existing: Title (src/x.py:3)``."""
    loc = where(entry)
    return (f"{entry['id']} [{entry.get('severity', '')}] {entry.get('category', '')}: "
            f"{entry.get('title', '')}" + (f" ({loc})" if loc else ""))


def details(entries: list[dict]) -> str:
    """The escalation details: every follow-up, then how each action treats them."""
    out = []
    for e in entries:
        out.append(line(e) + f" — found by {', '.join(e['found_by'])}")
        if e["state"] == ALREADY_OPEN:
            out.append(f"    already open as #{e['issue']['number']}: not created again")
            continue
        out.append(f"    problem: {e.get('problem', '')}")
        out.append(f"    why separate: {e.get('why_separate', '')}")
    ids = " ".join(e["id"] for e in proposed(entries))
    out += ["", f"create-all creates {ids}; create-selected creates only the ids in --note "
                f"(e.g. --note \"{proposed(entries)[0]['id']}\"); discard creates none."]
    return "\n".join(out)


def parse_selection(note: str, entries: list[dict]) -> tuple[list[str], str | None]:
    """The proposed ids named in ``note`` (``f1 f3`` or ``f1,f3``), or an error."""
    ids = list(dict.fromkeys(_ID_RE.findall(note or "")))
    if not ids:
        return [], "create-selected needs the follow-up ids in --note, e.g. --note \"f1 f3\""
    known = {e["id"]: e for e in entries}
    unknown = [i for i in ids if i not in known]
    if unknown:
        return [], f"unknown follow-up ids: {', '.join(unknown)}"
    not_proposed = [i for i in ids if known[i]["state"] not in (PROPOSED, CREATED)]
    if not_proposed:
        return [], f"not proposed for creation: {', '.join(not_proposed)}"
    return ids, None


def issue_body(entry: dict, plan: Plan) -> str:
    category = entry.get("category", "")
    loc = where(entry)
    lines = [f"Follow-up from spec #{plan.spec} ({plan.title}), found by herdr-spec-engine "
             f"({', '.join(entry['found_by'])}).", "",
             f"**Category:** {category} ({CATEGORY_TEXT.get(category, '')})",
             f"**Severity:** {entry.get('severity', '')}"]
    if loc:
        lines.append(f"**Where:** `{loc}`")
    lines += ["", "## Problem", "", entry.get("problem", ""),
              "", "## Why a separate issue", "", entry.get("why_separate", ""),
              "", "## Evidence", "", entry.get("evidence", "")]
    acceptance = entry.get("acceptance") or []
    if acceptance:
        lines += ["", "## Acceptance criteria", "", *[f"- [ ] {a}" for a in acceptance]]
    return "\n".join(lines) + "\n"


def create(github: GitHub, plan: Plan, entries: list[dict], ids: list[str] | None) -> None:
    """Create the issues for ``ids`` (None: every proposed one); the other proposed ones are
    discarded. Resumable: an entry is marked ``created`` as soon as its issue exists, so a
    retry after a failure never creates it twice."""
    chosen = set(ids) if ids is not None else {e["id"] for e in proposed(entries)}
    for entry in entries:
        if entry["state"] != PROPOSED or entry["id"] not in chosen:
            continue
        issue = github.create_issue(entry.get("title", ""), issue_body(entry, plan),
                                    LABELS_BY_CATEGORY.get(entry.get("category", ""), []))
        entry["state"] = CREATED
        entry["issue"] = {"number": issue.number, "url": issue.url}
    discard(entries)


def discard(entries: list[dict]) -> None:
    for entry in proposed(entries):
        entry["state"] = DISCARDED
