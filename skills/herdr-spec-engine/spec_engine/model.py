"""Domain model: enums, the plan, runs, escalations, settings and the persisted run state.

Every dataclass round-trips through JSON via ``to_dict()`` / ``from_dict()``; enums serialise
as their string values.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, fields
from enum import Enum
from typing import Any

STATE_VERSION = 1
AGENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


class Stage(str, Enum):
    CLAIM = "claim"
    PROVISION = "provision"
    IMPLEMENT = "implement"
    VERIFY = "verify"
    REVIEW = "review"
    INTEGRATE = "integrate"
    CLOSE = "close"
    AWAIT_HUMAN = "await_human"
    PROVISION_TAB = "provision_tab"
    SPEC_REVIEW = "spec_review"
    E2E = "e2e"


class Outcome(str, Enum):
    OK = "ok"
    RESULT_INVALID = "result_invalid"
    AGENT_BLOCKED = "agent_blocked"
    TIMEOUT = "timeout"
    AGENT_UNKNOWN = "agent_unknown"
    AGENT_LOST = "agent_lost"
    VERIFY_FAILED = "verify_failed"
    INTEGRATED = "integrated"


class RunKind(str, Enum):
    TICKET = "ticket"
    HUMAN = "human"
    FIX = "fix"
    SPEC_REVIEW = "spec_review"
    E2E = "e2e"


class RunStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    ESCALATED = "escalated"
    DONE = "done"
    LEFT_OPEN = "left_open"
    SKIPPED = "skipped"
    ABORTED = "aborted"

    @property
    def terminal(self) -> bool:
        return self in TERMINAL_STATUSES


TERMINAL_STATUSES = frozenset(
    {RunStatus.DONE, RunStatus.LEFT_OPEN, RunStatus.SKIPPED, RunStatus.ABORTED}
)


class Phase(str, Enum):
    TICKETS = "tickets"
    SPEC_REVIEW = "spec_review"
    FIXES = "fixes"
    E2E = "e2e"
    COMPLETE = "complete"


class EngineStatus(str, Enum):
    RUNNING = "running"
    COMPLETE = "complete"
    ABORTED = "aborted"


class TicketClass(str, Enum):
    AGENT = "agent"
    HUMAN = "human"
    UNREFINED = "unrefined"
    DONE = "done"


class EscalationKind(str, Enum):
    AGENT_BLOCKED = "agent-blocked"
    AGENT_UNKNOWN = "agent-unknown"
    STAGE_TIMEOUT = "stage-timeout"
    BUDGET_EXHAUSTED = "budget-exhausted"
    RESOLVER_ESCALATED = "resolver-escalated"
    OUTWARD_ACTION_DENIED = "outward-action-denied"
    HITL_TICKET = "hitl-ticket"
    UNREFINED_TICKET = "unrefined-ticket"
    EXTERNAL_BLOCKER = "external-blocker"
    REPO_DIRTY = "repo-dirty"


class EscalationStatus(str, Enum):
    OPEN = "open"
    HANDED_OFF = "handed_off"
    RESOLVED = "resolved"


STAGES_BY_KIND: dict[RunKind, tuple[Stage, ...]] = {
    RunKind.TICKET: (
        Stage.CLAIM, Stage.PROVISION, Stage.IMPLEMENT, Stage.VERIFY,
        Stage.REVIEW, Stage.INTEGRATE, Stage.CLOSE,
    ),
    RunKind.HUMAN: (Stage.AWAIT_HUMAN,),
    RunKind.FIX: (
        Stage.PROVISION, Stage.IMPLEMENT, Stage.VERIFY,
        Stage.REVIEW, Stage.INTEGRATE, Stage.CLOSE,
    ),
    RunKind.SPEC_REVIEW: (Stage.PROVISION_TAB, Stage.SPEC_REVIEW),
    RunKind.E2E: (Stage.PROVISION_TAB, Stage.E2E),
}


def run_id_for(
    kind: RunKind, *, spec: int | None = None, ticket: int | None = None, k: int | None = None
) -> str:
    """The run id (also agent and branch name) for a run of ``kind``."""
    kind = RunKind(kind)
    if kind is RunKind.TICKET:
        return f"ticket-{_need(ticket, 'ticket')}"
    if kind is RunKind.HUMAN:
        return f"human-{_need(ticket, 'ticket')}"
    if kind is RunKind.FIX:
        return f"fix-{_need(spec, 'spec')}-{_need(k, 'k')}"
    if kind is RunKind.SPEC_REVIEW:
        return f"review-spec-{_need(spec, 'spec')}"
    return f"e2e-spec-{_need(spec, 'spec')}"


def _need(value: int | None, name: str) -> int:
    if value is None:
        raise ValueError(f"run_id_for: {name} is required")
    return value


def resolver_agent_name(run_id: str) -> str:
    """``resolve-<run_id>`` truncated to herdr's 32-char agent name limit."""
    name = f"resolve-{run_id}"[:32].rstrip("-_")
    if not AGENT_NAME_RE.match(name):
        raise ValueError(f"invalid herdr agent name: {name!r}")
    return name


def _plain(value: Any) -> Any:
    """Recursively convert enums, tuples and dataclasses into JSON-ready values."""
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, dict):
        return {_plain(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


class _Serialisable:
    def to_dict(self) -> dict[str, Any]:
        return {f.name: _plain(getattr(self, f.name)) for f in fields(self)}  # type: ignore[arg-type]


@dataclass
class PlanTicket(_Serialisable):
    number: int
    title: str
    klass: TicketClass
    blockers: list[int] = field(default_factory=list)
    external_blockers: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PlanTicket:
        return cls(
            number=int(d["number"]),
            title=d.get("title", ""),
            klass=TicketClass(d["klass"]),
            blockers=[int(b) for b in d.get("blockers", [])],
            external_blockers=list(d.get("external_blockers", [])),
            labels=list(d.get("labels", [])),
        )


@dataclass
class Plan(_Serialisable):
    spec: int
    title: str
    branch: str
    base: str = "main"
    gate: list[str] = field(default_factory=list)
    tickets: list[PlanTicket] = field(default_factory=list)

    def ticket(self, number: int) -> PlanTicket | None:
        return next((t for t in self.tickets if t.number == number), None)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Plan:
        return cls(
            spec=int(d["spec"]),
            title=d.get("title", ""),
            branch=d["branch"],
            base=d.get("base", "main"),
            gate=list(d.get("gate", [])),
            tickets=[PlanTicket.from_dict(t) for t in d.get("tickets", [])],
        )


@dataclass
class Settings(_Serialisable):
    max_agents: int = 3
    model: str = "opus"
    stage_timeout: float = 7200
    retry_budget: int = 1
    gate_retry_budget: int = 2
    gate_timeout: float = 1800
    poll_seconds: float = 10
    settle_seconds: float = 15
    unknown_grace: float = 120

    @property
    def agent_args(self) -> list[str]:
        return ["--permission-mode", "auto", "--model", self.model]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Settings:
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


@dataclass
class Run(_Serialisable):
    id: str
    kind: RunKind
    stage: Stage
    ticket: int | None = None
    finding: dict | None = None
    status: RunStatus = RunStatus.PENDING
    attempts: dict[Stage, int] = field(default_factory=dict)
    gate_attempts: int = 0
    agent: str | None = None
    pane_id: str | None = None
    workspace_id: str | None = None
    worktree: str | None = None
    awaiting: dict | None = None
    stage_started_at: float = 0.0
    escalation: str | None = None
    review: dict | None = None
    merge_commit: str | None = None
    notes: list[str] = field(default_factory=list)

    @classmethod
    def new(
        cls, kind: RunKind, run_id: str, ticket: int | None = None, finding: dict | None = None
    ) -> Run:
        """A pending run positioned at the first stage of its kind."""
        kind = RunKind(kind)
        return cls(id=run_id, kind=kind, stage=STAGES_BY_KIND[kind][0], ticket=ticket,
                   finding=finding)

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Run:
        return cls(
            id=d["id"],
            kind=RunKind(d["kind"]),
            stage=Stage(d["stage"]),
            ticket=d.get("ticket"),
            finding=d.get("finding"),
            status=RunStatus(d.get("status", "pending")),
            attempts={Stage(k): int(v) for k, v in d.get("attempts", {}).items()},
            gate_attempts=int(d.get("gate_attempts", 0)),
            agent=d.get("agent"),
            pane_id=d.get("pane_id"),
            workspace_id=d.get("workspace_id"),
            worktree=d.get("worktree"),
            awaiting=d.get("awaiting"),
            stage_started_at=float(d.get("stage_started_at", 0.0)),
            escalation=d.get("escalation"),
            review=d.get("review"),
            merge_commit=d.get("merge_commit"),
            notes=list(d.get("notes", [])),
        )


@dataclass
class Escalation(_Serialisable):
    id: str
    run: str
    kind: EscalationKind
    stage: Stage | None
    created_at: float
    summary: str
    details: str = ""
    actions: list[str] = field(default_factory=list)
    status: EscalationStatus = EscalationStatus.OPEN
    resolution: str | None = None
    note: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Escalation:
        stage = d.get("stage")
        return cls(
            id=d["id"],
            run=d["run"],
            kind=EscalationKind(d["kind"]),
            stage=Stage(stage) if stage else None,
            created_at=float(d.get("created_at", 0.0)),
            summary=d.get("summary", ""),
            details=d.get("details", ""),
            actions=list(d.get("actions", [])),
            status=EscalationStatus(d.get("status", "open")),
            resolution=d.get("resolution"),
            note=d.get("note") or "",
        )


@dataclass
class RunState(_Serialisable):
    spec: int
    branch: str
    version: int = STATE_VERSION
    status: EngineStatus = EngineStatus.RUNNING
    settings: Settings = field(default_factory=Settings)
    runs: dict[str, Run] = field(default_factory=dict)
    queue: list[str] = field(default_factory=list)
    escalations: dict[str, Escalation] = field(default_factory=dict)
    consumed_resolutions: list[str] = field(default_factory=list)
    seq: int = 0
    fix_seq: int = 0
    phase: Phase = Phase.TICKETS
    started_at: float = 0.0
    updated_at: float = 0.0

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RunState:
        return cls(
            spec=int(d["spec"]),
            branch=d["branch"],
            version=int(d.get("version", STATE_VERSION)),
            status=EngineStatus(d.get("status", "running")),
            settings=Settings.from_dict(d.get("settings", {})),
            runs={k: Run.from_dict(v) for k, v in d.get("runs", {}).items()},
            queue=list(d.get("queue", [])),
            escalations={k: Escalation.from_dict(v) for k, v in d.get("escalations", {}).items()},
            consumed_resolutions=list(d.get("consumed_resolutions", [])),
            seq=int(d.get("seq", 0)),
            fix_seq=int(d.get("fix_seq", 0)),
            phase=Phase(d.get("phase", "tickets")),
            started_at=float(d.get("started_at", 0.0)),
            updated_at=float(d.get("updated_at", 0.0)),
        )
