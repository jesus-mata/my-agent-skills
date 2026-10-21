"""Static transition tables: stage successors and the allowed actions per escalation kind."""
from __future__ import annotations

from .model import STAGES_BY_KIND, EscalationKind, RunKind, Stage

__all__ = ["ACTIONS", "HANDED_OFF_ACTION", "EscalationKind", "is_valid_action", "next_stage"]

HANDED_OFF_ACTION = "hand-to-human"

ACTIONS: dict[EscalationKind, tuple[str, ...]] = {
    EscalationKind.AGENT_BLOCKED: ("answered", HANDED_OFF_ACTION),
    EscalationKind.AGENT_UNKNOWN: ("answered", "retry", HANDED_OFF_ACTION),
    EscalationKind.STAGE_TIMEOUT: ("retry", "skip-ticket", HANDED_OFF_ACTION),
    EscalationKind.BUDGET_EXHAUSTED: ("retry", "skip-ticket", HANDED_OFF_ACTION),
    EscalationKind.RESOLVER_ESCALATED: ("resolved-manually", HANDED_OFF_ACTION),
    EscalationKind.OUTWARD_ACTION_DENIED: ("leave-open", "retry", HANDED_OFF_ACTION),
    EscalationKind.HITL_TICKET: ("done", HANDED_OFF_ACTION),
    EscalationKind.UNREFINED_TICKET: ("relabeled", "skip-ticket", HANDED_OFF_ACTION),
    EscalationKind.EXTERNAL_BLOCKER: ("cleared", "skip-ticket", HANDED_OFF_ACTION),
    EscalationKind.REPO_DIRTY: ("retry", HANDED_OFF_ACTION),
    EscalationKind.FOLLOW_UPS: ("create-all", "create-selected", "discard", HANDED_OFF_ACTION),
}
"""Every kind allows ``hand-to-human``: the supervisor parks an escalation that waits on the user
so ``watch`` stops reporting it, and resolves it later with one of the other actions."""


def is_valid_action(kind: EscalationKind | str, action: str) -> bool:
    """Whether ``action`` may resolve an escalation of ``kind``."""
    try:
        return action in ACTIONS[EscalationKind(kind)]
    except ValueError:
        return False


def next_stage(kind: RunKind | str, stage: Stage | str) -> Stage | None:
    """The stage after ``stage`` for a run of ``kind``; None when it is the last stage."""
    stages = STAGES_BY_KIND[RunKind(kind)]
    i = stages.index(Stage(stage))
    return stages[i + 1] if i + 1 < len(stages) else None
