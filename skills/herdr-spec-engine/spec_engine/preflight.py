"""Preflight: the tools, auth and skills a spec run needs, checked before `plan` and `run`.

Missing tools, an unauthenticated ``gh`` or no herdr socket are errors: the run cannot work.
A skill the engine's agents invoke that cannot be found is only a warning, since skills can live
in places this lookup does not know about.
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from typing import Callable, Mapping

from .adapters.gh_cli import authenticated
from .adapters.herdr_socket import default_socket_path

REQUIRED_TOOLS: tuple[str, ...] = ("git", "gh", "herdr", "claude")

REQUIRED_SKILLS: tuple[str, ...] = (
    "implement-ticket", "e2e", "code-review", "mattpocock-skills:code-review",
    "mattpocock-skills:tdd",
)
"""Every skill a prompt template invokes (``tests/test_preflight.py`` keeps them in step)."""

BUILTIN_SKILLS: frozenset[str] = frozenset({"code-review"})


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def check(
    repo_root: str, *, env: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    gh_authenticated: Callable[[], bool] = authenticated,
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
    config_dir = env.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    for skill in REQUIRED_SKILLS:
        if skill not in BUILTIN_SKILLS and not skill_installed(skill, repo_root, config_dir):
            report.warnings.append(
                f"skill `/{skill}` not found in {config_dir}/skills, {repo_root}/.claude/skills "
                "or an enabled plugin; the engine's agents invoke it")
    return report


def skill_installed(skill: str, repo_root: str, config_dir: str) -> bool:
    """Whether ``skill`` (``name`` or ``plugin:name``) is a personal, project or plugin skill."""
    if ":" not in skill:
        return any(os.path.isfile(os.path.join(base, "skills", skill, "SKILL.md"))
                   for base in (config_dir, os.path.join(repo_root, ".claude")))
    plugin, name = skill.split(":", 1)
    installed = _read_json(os.path.join(config_dir, "plugins", "installed_plugins.json"))
    enabled = _read_json(os.path.join(config_dir, "settings.json")).get("enabledPlugins", {})
    for key, entries in installed.get("plugins", {}).items():
        if key.split("@", 1)[0] != plugin or enabled.get(key) is False:
            continue
        for entry in entries:
            if _plugin_has_skill(entry.get("installPath", ""), name):
                return True
    return False


def _plugin_has_skill(install_path: str, name: str) -> bool:
    manifest = _read_json(os.path.join(install_path, ".claude-plugin", "plugin.json"))
    dirs = [os.path.join(install_path, d) for d in manifest.get("skills", [])
            if os.path.basename(os.path.normpath(d)) == name]
    dirs.append(os.path.join(install_path, "skills", name))
    return any(os.path.isfile(os.path.join(d, "SKILL.md")) for d in dirs)


def _read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
