"""Preflight: the tools, auth and skills a spec run needs, checked before `plan` and `run`.

Missing tools, an unauthenticated ``gh``, no herdr socket or an outdated herdr claude integration
are errors: the run cannot work. A skill the engine's agents invoke that cannot be found is only a
warning, since skills can live in places this lookup does not know about.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from typing import Callable, Mapping

from .adapters.gh_cli import authenticated
from .adapters.herdr_socket import default_socket_path
from .adapters.system import herdr_integration_status

REQUIRED_TOOLS: tuple[str, ...] = ("git", "gh", "herdr", "claude")

REQUIRED_SKILLS: tuple[str, ...] = (
    "implement-ticket", "e2e", "code-review", "mattpocock-skills:code-review",
    "mattpocock-skills:tdd",
)
"""Every skill a prompt template invokes (``tests/test_preflight.py`` keeps them in step)."""

BUILTIN_SKILLS: frozenset[str] = frozenset({"code-review"})

COMMAND_SKILLS: frozenset[str] = frozenset({"e2e"})
"""Skills a prompt template starts with as its slash command, sent alone on one line. Only these
may set ``disable-model-invocation``: the others are asked for in the text, and the Skill tool
refuses such a skill."""

# herdr's claude integration is the hook that reports an agent's real status; outdated or
# missing, `agent.get` and the status events lag or never fire, and every stage waits on them.
INTEGRATION_RE = re.compile(r"^\s*claude:\s*(.+?)\s*$", re.MULTILINE)
INTEGRATION_BROKEN = ("outdated", "not installed")
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---", re.DOTALL)
NO_MODEL_INVOCATION_RE = re.compile(r"^disable-model-invocation:\s*true\s*$", re.MULTILINE)


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def check(
    repo_root: str, *, env: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    gh_authenticated: Callable[[], bool] = authenticated,
    integration_status: Callable[[], str | None] = herdr_integration_status,
) -> Report:
    """Everything a spec run needs that is missing from this machine."""
    env = os.environ if env is None else env
    report = Report()
    missing = [t for t in REQUIRED_TOOLS if which(t) is None]
    for tool in missing:
        report.errors.append(f"`{tool}` not found on PATH")
    if "gh" not in missing and not gh_authenticated():
        report.errors.append("`gh` is not authenticated; run `gh auth login`")
    socket = default_socket_path(dict(env))
    if not os.path.exists(socket):
        report.errors.append(f"no herdr socket at {socket}; run the engine inside herdr")
    if "herdr" not in missing:
        _check_integration(report, integration_status())
    config_dir = env.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    for skill in REQUIRED_SKILLS:
        if skill in BUILTIN_SKILLS:
            continue
        path = skill_file(skill, repo_root, config_dir)
        if path is None:
            report.warnings.append(
                f"skill `/{skill}` not found in {config_dir}/skills, {repo_root}/.claude/skills "
                "or an enabled plugin; the engine's agents invoke it")
        elif skill not in COMMAND_SKILLS and model_invocation_disabled(path):
            report.warnings.append(
                f"skill `/{skill}` sets disable-model-invocation ({path}); the engine's agents "
                "ask for it in their prompt text, so the Skill tool will refuse to load it")
    return report


def _check_integration(report: Report, status: str | None) -> None:
    m = INTEGRATION_RE.search(status or "")
    if m is None:
        report.warnings.append("could not read the claude line of `herdr integration status`; "
                               "if agent statuses lag, run `herdr integration install claude`")
    elif m.group(1).startswith(INTEGRATION_BROKEN):
        report.errors.append(f"herdr's claude integration is {m.group(1)}; the engine relies on "
                             "it for agent status: run `herdr integration install claude`")


def model_invocation_disabled(skill_md: str) -> bool:
    """Whether the SKILL.md at ``skill_md`` sets ``disable-model-invocation: true``."""
    try:
        with open(skill_md, encoding="utf-8") as f:
            m = FRONTMATTER_RE.match(f.read())
    except OSError:
        return False
    return bool(m and NO_MODEL_INVOCATION_RE.search(m.group(1)))


def skill_installed(skill: str, repo_root: str, config_dir: str) -> bool:
    """Whether ``skill`` (``name`` or ``plugin:name``) is a personal, project or plugin skill."""
    return skill_file(skill, repo_root, config_dir) is not None


def skill_file(skill: str, repo_root: str, config_dir: str) -> str | None:
    """The SKILL.md of ``skill`` as a personal, project or enabled plugin skill, or None."""
    if ":" not in skill:
        return next((p for p in (os.path.join(base, "skills", skill, "SKILL.md")
                                 for base in (config_dir, os.path.join(repo_root, ".claude")))
                     if os.path.isfile(p)), None)
    plugin, name = skill.split(":", 1)
    installed = _read_json(os.path.join(config_dir, "plugins", "installed_plugins.json"))
    enabled = _read_json(os.path.join(config_dir, "settings.json")).get("enabledPlugins", {})
    for key, entries in installed.get("plugins", {}).items():
        if key.split("@", 1)[0] != plugin or enabled.get(key) is False:
            continue
        for entry in entries:
            path = _plugin_skill_file(entry.get("installPath", ""), name)
            if path is not None:
                return path
    return None


def _plugin_skill_file(install_path: str, name: str) -> str | None:
    manifest = _read_json(os.path.join(install_path, ".claude-plugin", "plugin.json"))
    dirs = [os.path.join(install_path, d) for d in manifest.get("skills", [])
            if os.path.basename(os.path.normpath(d)) == name]
    dirs.append(os.path.join(install_path, "skills", name))
    return next((p for p in (os.path.join(d, "SKILL.md") for d in dirs) if os.path.isfile(p)),
                None)


def _read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
