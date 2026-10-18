"""The plan: read a spec's tickets from GitHub, classify them, validate the graph, discover the gate.

See ``docs/design.md`` ("Plan"). Everything here is pure except ``discover_gate`` (reads files)
and ``build_plan`` (reads issues through the GitHub port and, with ``--from``, a local file).
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from .model import Plan, PlanTicket, TicketClass
from .ports import GitHub, Issue, IssueRef

AGENT_LABEL = "ready-for-agent"
HUMAN_LABEL = "ready-for-human"

_REPO_URL_RE = re.compile(r"github\.com/([^/\s]+/[^/\s]+)/(?:issues|pull)/\d+")


# build ------------------------------------------------------------------------------------------

def classify(issue: Issue) -> TicketClass:
    """``done`` if closed; else ``agent``/``human`` by exactly one ready label, else ``unrefined``."""
    if issue.state.upper() == "CLOSED":
        return TicketClass.DONE
    agent, human = AGENT_LABEL in issue.labels, HUMAN_LABEL in issue.labels
    if agent and not human:
        return TicketClass.AGENT
    if human and not agent:
        return TicketClass.HUMAN
    return TicketClass.UNREFINED


def _repo_of(issue: Issue) -> str:
    m = _REPO_URL_RE.search(issue.url)
    return m.group(1) if m else ""


def _ref_name(ref: IssueRef) -> str:
    return f"{ref.repo}#{ref.number}"


def read_from_file(path: str) -> list[tuple[int, list[int]]]:
    """``[(number, blocked_by)]`` from a ``{"tickets": [{"number", "blocked_by"}]}`` file."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not isinstance(data.get("tickets"), list):
        raise ValueError(f'{path}: expected {{"tickets": [{{"number": int, "blocked_by": [int]}}]}}')
    out: list[tuple[int, list[int]]] = []
    for i, t in enumerate(data["tickets"]):
        if not isinstance(t, dict) or not _is_int(t.get("number")):
            raise ValueError(f"{path}: tickets[{i}].number must be an integer")
        blocked_by = t.get("blocked_by", [])
        if not isinstance(blocked_by, list) or not all(_is_int(b) for b in blocked_by):
            raise ValueError(f"{path}: tickets[{i}].blocked_by must be a list of integers")
        out.append((t["number"], list(blocked_by)))
    return out


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def build_plan(
    github: GitHub, spec: int, branch: str, gate: list[str], from_file: str | None = None,
    spec_issue: Issue | None = None,
) -> Plan:
    """Read spec ``spec`` and its tickets into an (unvalidated) Plan.

    ``spec_issue`` is the already-read spec issue, if the caller has it.
    """
    spec_issue = spec_issue or github.issue(spec)
    repo = _repo_of(spec_issue)

    if from_file is not None:
        listed = read_from_file(from_file)
        numbers = [n for n, _ in listed]
        file_blockers = dict(listed)
    else:
        # Sub-issues in another repository cannot be read by number; they are not tickets.
        numbers = [r.number for r in spec_issue.sub_issues if not repo or r.repo == repo]
        file_blockers = None
    members = set(numbers)

    tickets: list[PlanTicket] = []
    for number in dict.fromkeys(numbers):  # de-duplicated, order kept
        issue = github.issue(number)
        blockers: list[int] = []
        external: list[str] = []
        for b in issue.blocked_by:
            in_spec = b.number in members and (not repo or b.repo == repo)
            if in_spec:
                if file_blockers is None:
                    blockers.append(b.number)
            elif b.state.upper() != "CLOSED":
                external.append(_ref_name(b))
        if file_blockers is not None:
            blockers = list(file_blockers[number])
        tickets.append(PlanTicket(
            number=number,
            title=issue.title,
            klass=classify(issue),
            blockers=sorted(dict.fromkeys(blockers)),
            external_blockers=sorted(dict.fromkeys(external)),
            labels=list(issue.labels),
        ))
    tickets.sort(key=lambda t: t.number)
    return Plan(spec=spec, title=spec_issue.title, branch=branch, gate=list(gate),
                tickets=tickets)


# validate ---------------------------------------------------------------------------------------

def find_cycle(plan: Plan) -> list[int] | None:
    """A blocker cycle as ``[a, b, ..., a]`` (a blocked by b ...), or None."""
    graph = {t.number: [b for b in t.blockers if plan.ticket(b) is not None] for t in plan.tickets}
    WHITE, GREY, BLACK = 0, 1, 2
    color = dict.fromkeys(graph, WHITE)
    stack: list[int] = []

    def visit(n: int) -> list[int] | None:
        color[n] = GREY
        stack.append(n)
        for b in graph[n]:
            if color[b] == GREY:
                return stack[stack.index(b):] + [b]
            if color[b] == WHITE:
                found = visit(b)
                if found:
                    return found
        stack.pop()
        color[n] = BLACK
        return None

    for n in sorted(graph):
        if color[n] == WHITE:
            found = visit(n)
            if found:
                return found
    return None


def validate_plan(plan: Plan) -> list[str]:
    """Human-readable problems that make the plan unrunnable; empty when runnable."""
    problems: list[str] = []
    cycle = find_cycle(plan)
    if cycle:
        problems.append("blocker cycle: " + " -> ".join(f"#{n}" for n in cycle))
    for t in plan.tickets:
        for b in t.blockers:
            if plan.ticket(b) is None:
                problems.append(f"#{t.number} is blocked by #{b}, which is not in the plan")
    unrefined = [t for t in plan.tickets if t.klass is TicketClass.UNREFINED]
    if unrefined:
        problems.append(
            f"unrefined tickets (label each {AGENT_LABEL} or {HUMAN_LABEL}): "
            + ", ".join(f"#{t.number}" for t in unrefined)
        )
    return problems


def plan_runnable(plan: Plan) -> bool:
    return not validate_plan(plan)


# gate -------------------------------------------------------------------------------------------

_MAKE_TARGET_RE = re.compile(r"^([A-Za-z0-9_.-]+)\s*:(?!=)", re.MULTILINE)
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^\s*(```+|~~~+)")
_GATE_LINE_RE = re.compile(r"^\s*(?:[-*]\s+)?(?:\*\*|__)?gate(?:\*\*|__)?\s*:", re.IGNORECASE)
_CODE_SPAN_RE = re.compile(r"`([^`]+)`")

GATE_HINT = ("declare the gate in the spec issue body (a `## Gate` section with the commands in a "
             "fenced code block, or a line Gate: `cmd`), or pass --gate.")


def gate_from_spec(body: str) -> list[str]:
    """Gate commands declared in a spec issue body, or ``[]``.

    A ``Gate`` heading (any level) whose section holds a fenced code block: each non-blank,
    non-comment line of the first such block is a command. Otherwise every line ``Gate: `cmd```
    adds the code spans on it.
    """
    lines = (body or "").splitlines()
    in_section = False
    for i, line in enumerate(lines):
        heading = _HEADING_RE.match(line)
        if heading:
            in_section = re.match(r"gate\b", heading.group(1), re.IGNORECASE) is not None
            continue
        fence = _FENCE_RE.match(line)
        if in_section and fence:
            cmds = []
            for inner in lines[i + 1:]:
                if inner.strip().startswith(fence.group(1)):
                    break
                cmd = inner.strip()
                if cmd.startswith("$ "):
                    cmd = cmd[2:].strip()
                if cmd and not cmd.startswith("#"):
                    cmds.append(cmd)
            if cmds:
                return cmds
            in_section = False
    cmds = []
    for line in lines:
        if _GATE_LINE_RE.match(line):
            cmds.extend(c.strip() for c in _CODE_SPAN_RE.findall(line) if c.strip())
    return cmds


def choose_gate(explicit: list[str] | None, spec_body: str, spec: int,
                repo_root: str) -> tuple[list[str], str]:
    """The gate and where it came from: ``--gate`` > the spec issue body > repository discovery.

    The source is ``""`` when the gate is empty.
    """
    if explicit:
        return list(explicit), "--gate"
    from_spec = gate_from_spec(spec_body)
    if from_spec:
        return from_spec, f"spec #{spec} body"
    discovered = discover_gate(repo_root)
    return discovered, "discovered from repository files" if discovered else ""


def discover_gate(repo_root: str) -> list[str]:
    """Gate commands inferred from the repository's build files (first ecosystem found wins)."""
    def path(name: str) -> str:
        return os.path.join(repo_root, name)

    def exists(name: str) -> bool:
        return os.path.isfile(path(name))

    if exists("package.json"):
        try:
            with open(path("package.json"), encoding="utf-8") as f:
                scripts = json.load(f).get("scripts") or {}
        except (json.JSONDecodeError, AttributeError, OSError):
            scripts = {}
        if not isinstance(scripts, dict):
            scripts = {}
        if exists("pnpm-lock.yaml"):
            pm, install = "pnpm", "pnpm install --frozen-lockfile"
        elif exists("yarn.lock"):
            pm, install = "yarn", "yarn install --frozen-lockfile"
        elif exists("bun.lockb") or exists("bun.lock"):
            pm, install = "bun", "bun install"
        elif exists("package-lock.json"):
            pm, install = "npm", "npm ci"
        else:
            pm, install = "npm", "npm install"
        gate = [install]
        typecheck = next((s for s in ("typecheck", "type-check") if s in scripts), None)
        for script in ("lint", typecheck, "format:check", "build", "test"):
            if script and script in scripts:
                gate.append(f"{pm} run {script}")
        return gate

    if exists("Makefile"):
        with open(path("Makefile"), encoding="utf-8", errors="replace") as f:
            targets = set(_MAKE_TARGET_RE.findall(f.read()))
        gate = [f"make {t}" for t in ("lint", "test", "build") if t in targets]
        if gate:
            return gate

    if exists("go.mod"):
        return ["go vet ./...", "go build ./...", "go test ./..."]
    if exists("Cargo.toml"):
        return ["cargo build", "cargo test"]
    if exists("pyproject.toml"):
        return ["python3 -m pytest"]
    return []


# display ----------------------------------------------------------------------------------------

def depths(plan: Plan) -> dict[int, int]:
    """Display wave per ticket: 0 without in-plan blockers, else 1 + the deepest blocker.

    Tickets on (or behind) a cycle are left out. Blockers missing from the plan are ignored.
    """
    memo: dict[int, int | None] = {}
    visiting: set[int] = set()

    def depth(n: int) -> int | None:
        if n in memo:
            return memo[n]
        if n in visiting:
            return None
        visiting.add(n)
        ticket = plan.ticket(n)
        result: int | None = 0
        for b in ticket.blockers if ticket else []:
            if plan.ticket(b) is None:
                continue
            d = depth(b)
            if d is None:
                result = None
                break
            result = max(result, d + 1)
        visiting.discard(n)
        memo[n] = result
        return result

    out = {}
    for t in plan.tickets:
        d = depth(t.number)
        if d is not None:
            out[t.number] = d
    return out


def _ticket_line(t: PlanTicket) -> str:
    line = f"  #{t.number} [{t.klass.value}] {t.title}"
    if t.blockers:
        line += "  blocked by " + ", ".join(f"#{b}" for b in t.blockers)
    if t.external_blockers:
        line += "  external: " + ", ".join(t.external_blockers)
    return line


def format_plan(plan: Plan, problems: list[str], gate_source: str = "") -> str:
    """The plan as text: waves, unrefined tickets, branch, gate with its source, problems."""
    lines = [f"Spec #{plan.spec}: {plan.title}", f"Spec branch: {plan.branch} (base {plan.base})", ""]
    waves = depths(plan)
    if not plan.tickets:
        lines.append("No tickets.")
    for wave in sorted(set(waves.values())):
        lines.append(f"Wave {wave}:")
        lines.extend(_ticket_line(t) for t in plan.tickets if waves.get(t.number) == wave)
    stuck = [t for t in plan.tickets if t.number not in waves]
    if stuck:
        lines.append("In a cycle:")
        lines.extend(_ticket_line(t) for t in stuck)

    unrefined = [t for t in plan.tickets if t.klass is TicketClass.UNREFINED]
    if unrefined:
        lines += ["", "Unrefined tickets (need exactly one of "
                  f"{AGENT_LABEL} / {HUMAN_LABEL}):"]
        lines.extend(f"  #{t.number} {t.title}  labels: {', '.join(t.labels) or '(none)'}"
                     for t in unrefined)

    lines += ["", f"Gate ({gate_source}):" if plan.gate and gate_source else "Gate:"]
    if plan.gate:
        lines.extend(f"  {cmd}" for cmd in plan.gate)
    else:
        lines.append("  (none)")
        lines.append("WARNING: the gate is empty; runs will integrate without any checks.")
        lines.append(f"Hint: {GATE_HINT}")

    lines.append("")
    if problems:
        lines.append("NOT RUNNABLE:")
        lines.extend(f"  - {p}" for p in problems)
    else:
        lines.append("Plan is runnable.")
    return "\n".join(lines) + "\n"
