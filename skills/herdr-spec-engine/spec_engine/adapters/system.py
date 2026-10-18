"""Shell commands (subprocess) and wall-clock time."""
from __future__ import annotations

import os
import signal
import subprocess
import time

from ..ports import ShellResult

TIMEOUT_CODE = 124


class SubprocessShell:
    """The Shell port: ``cmd`` runs through the shell with stdout and stderr merged."""

    def run(self, cmd: str, cwd: str, timeout: float) -> ShellResult:
        # Own process group, so a timeout kills the whole tree (not just the shell, whose
        # children would otherwise keep the output pipe open).
        proc = subprocess.Popen(
            cmd, shell=True, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True,
        )
        try:
            out, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
            out, _ = proc.communicate()
            note = f"\n[herdr-spec-engine] command timed out after {timeout:g}s: {cmd}\n"
            return ShellResult(code=TIMEOUT_CODE, output=_decode(out) + note)
        return ShellResult(code=proc.returncode, output=_decode(out))


def _decode(data: bytes | str | None) -> str:
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return data


class SystemClock:
    """The Clock port."""

    def now(self) -> float:
        return time.time()

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)
