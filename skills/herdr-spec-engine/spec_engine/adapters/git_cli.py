"""Git via plain ``git -C <cwd> ...`` subprocesses."""
from __future__ import annotations

import os
import subprocess

from ..ports import MergeResult

GIT_ENV = {"GIT_TERMINAL_PROMPT": "0", "GIT_MERGE_AUTOEDIT": "no"}


class GitError(RuntimeError):
    """A git command exited non-zero."""

    def __init__(self, args: list[str], code: int, output: str) -> None:
        super().__init__(f"git {' '.join(args)} failed ({code}): {output.strip()}")
        self.args_ = args
        self.code = code
        self.output = output


class CliGit:
    """The Git port."""

    def __init__(self, timeout: float = 300.0) -> None:
        self.timeout = timeout

    def _run(self, cwd: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        proc = subprocess.run(
            ["git", "-C", cwd, *args], capture_output=True, text=True, timeout=self.timeout,
            env={**os.environ, **GIT_ENV}, stdin=subprocess.DEVNULL,
        )
        if check and proc.returncode != 0:
            raise GitError(list(args), proc.returncode, proc.stdout + proc.stderr)
        return proc

    def _out(self, cwd: str, *args: str) -> str:
        return self._run(cwd, *args).stdout.strip()

    # Git protocol ----------------------------------------------------------------------------

    def common_dir(self, cwd: str) -> str:
        out = self._out(cwd, "rev-parse", "--git-common-dir")
        return os.path.normpath(os.path.join(os.path.abspath(cwd), out))

    def repo_root(self, cwd: str) -> str:
        return self._out(cwd, "rev-parse", "--show-toplevel")

    def current_branch(self, cwd: str) -> str:
        """The checked-out branch, or ``"HEAD"`` when detached."""
        return self._out(cwd, "branch", "--show-current") or "HEAD"

    def branch_exists(self, cwd: str, branch: str) -> bool:
        proc = self._run(cwd, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}",
                         check=False)
        return proc.returncode == 0

    def checkout(self, cwd: str, branch: str, create_from: str | None = None) -> None:
        if create_from is not None:
            self._run(cwd, "checkout", "-q", "-b", branch, create_from)
        else:
            self._run(cwd, "checkout", "-q", branch)

    def pull_ff_only(self, cwd: str) -> None:
        self._run(cwd, "pull", "--ff-only", "-q")

    def rev_parse(self, cwd: str, ref: str) -> str:
        return self._out(cwd, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}")

    def commits_ahead(self, cwd: str, base: str, branch: str) -> int:
        return int(self._out(cwd, "rev-list", "--count", f"{base}..{branch}"))

    def is_clean(self, cwd: str) -> bool:
        """No staged, unstaged or untracked changes; ignored/excluded files don't count."""
        return self._run(cwd, "status", "--porcelain", "-z").stdout == ""

    def unmerged_paths(self, cwd: str) -> list[str]:
        out = self._run(cwd, "diff", "--name-only", "--diff-filter=U", "-z").stdout
        return sorted({p for p in out.split("\0") if p})

    def merge(self, cwd: str, ref: str, no_ff: bool = False,
              message: str | None = None) -> MergeResult:
        args = ["merge", "--no-edit"]
        if no_ff:
            args.append("--no-ff")
        if message is not None:
            args += ["-m", message]
        args.append(ref)
        proc = self._run(cwd, *args, check=False)
        output = proc.stdout + proc.stderr
        if proc.returncode == 0:
            return MergeResult(ok=True, conflict=False, commit=self.rev_parse(cwd, "HEAD"),
                               output=output)
        return MergeResult(ok=False, conflict=bool(self.unmerged_paths(cwd)), commit=None,
                           output=output)

    def merge_abort(self, cwd: str) -> None:
        self._run(cwd, "merge", "--abort")
