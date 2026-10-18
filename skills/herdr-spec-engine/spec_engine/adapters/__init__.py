"""Port implementations that talk to herdr, git, gh and the OS."""
from __future__ import annotations

from dataclasses import dataclass

from ..ports import Clock, Git, GitHub, Herdr, Shell
from .gh_cli import CliGitHub
from .git_cli import CliGit
from .herdr_socket import SocketHerdr
from .system import SubprocessShell, SystemClock


@dataclass(frozen=True)
class Ports:
    herdr: Herdr
    git: Git
    github: GitHub
    shell: Shell
    clock: Clock


def real_ports(cwd: str, socket_path: str | None = None) -> Ports:
    """The production adapters; ``gh`` runs in ``cwd`` so it targets that checkout's repo."""
    return Ports(herdr=SocketHerdr(socket_path), git=CliGit(), github=CliGitHub(cwd),
                 shell=SubprocessShell(), clock=SystemClock())
