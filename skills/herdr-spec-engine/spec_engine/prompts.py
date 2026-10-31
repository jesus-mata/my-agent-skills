"""Prompt templates: ``prompts/<name>.md`` rendered strictly with ``string.Template``."""
from __future__ import annotations

import os
import re
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
    "dedup",
)


# A rendered prompt that starts with a slash command (``/e2e ...``) must reach Claude as that
# command, alone on a short line: a multi-line prompt enters the TUI as pasted text, and pasted
# text is never run as a command. A skill with ``disable-model-invocation`` can only be
# loaded that way; asked for in the text, the Skill tool refuses it. e2e is sent the same way.
COMMAND_RE = re.compile(r"^(/[a-z][a-z0-9:_-]*)[ \t]*")


def split_command(text: str) -> tuple[str, str] | None:
    """``(command, rest)`` when ``text`` starts with a slash command, else None."""
    m = COMMAND_RE.match(text)
    return (m.group(1), text[m.end():].lstrip("\n")) if m else None


def command_line(command: str, instructions_path: str) -> str:
    """The one-line prompt that runs ``command`` and points it at the rest of the prompt."""
    return (f"{command} Your full instructions for this command are in {instructions_path} "
            f"— read that whole file first and follow it.")


def template_path(name: str) -> str:
    return os.path.join(PROMPTS_DIR, f"{name}.md")


def render(name: str, **vars: object) -> str:
    """Render template ``name``; a missing variable raises KeyError (a bug, not a runtime case)."""
    if name not in TEMPLATE_NAMES:
        raise KeyError(f"unknown prompt template: {name}")
    with open(template_path(name), encoding="utf-8") as f:
        return Template(f.read()).substitute(**vars)
