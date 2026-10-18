"""Prompt templates: ``prompts/<name>.md`` rendered strictly with ``string.Template``."""
from __future__ import annotations

import os
from string import Template

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")

TEMPLATE_NAMES: tuple[str, ...] = (
    "implement",
    "verify_failed",
    "review",
    "result_retry",
    "gate_failed",
    "resolver",
    "spec_review",
    "fix_implement",
    "fix_review",
    "e2e",
)


def template_path(name: str) -> str:
    return os.path.join(PROMPTS_DIR, f"{name}.md")


def render(name: str, **vars: object) -> str:
    """Render template ``name``; a missing variable raises KeyError (a bug, not a runtime case)."""
    if name not in TEMPLATE_NAMES:
        raise KeyError(f"unknown prompt template: {name}")
    with open(template_path(name), encoding="utf-8") as f:
        return Template(f.read()).substitute(**vars)
