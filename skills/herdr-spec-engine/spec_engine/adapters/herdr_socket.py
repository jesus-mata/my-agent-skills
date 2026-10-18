"""Herdr over its unix socket: newline-delimited JSON, one connection per request.

Method names, params and result shapes follow ``herdr api schema --json`` (protocol 22).
"""
from __future__ import annotations

import itertools
import json
import os
import socket
import time
from typing import Any, Callable

from ..ports import AgentStatus, HerdrError, Worktree

DEFAULT_TIMEOUT = 30.0
AGENT_START_TIMEOUT_MS = 60_000
AGENT_STATUSES = frozenset({"idle", "working", "blocked", "done", "unknown"})
AGENT_NOT_FOUND = "agent_not_found"


def default_socket_path(env: dict[str, str] | None = None) -> str:
    """``HERDR_SOCKET_PATH``, else ``HERDR_SESSION``'s socket, else the default session socket."""
    env = os.environ if env is None else env
    if env.get("HERDR_SOCKET_PATH"):
        return env["HERDR_SOCKET_PATH"]
    base = os.path.expanduser("~/.config/herdr")
    if env.get("HERDR_SESSION"):
        return os.path.join(base, "sessions", env["HERDR_SESSION"], "herdr.sock")
    return os.path.join(base, "herdr.sock")


class SocketHerdr:
    """The Herdr port. Transport failures raise ``HerdrError("connection_failed", ...)``."""

    def __init__(self, socket_path: str | None = None, timeout: float = DEFAULT_TIMEOUT,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.socket_path = socket_path or default_socket_path()
        self.timeout = timeout
        self._sleep = sleep
        self._ids = itertools.count(1)

    # transport -------------------------------------------------------------------------------

    def _connect(self, timeout: float) -> socket.socket:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.connect(self.socket_path)
        except OSError as e:
            sock.close()
            raise HerdrError("connection_failed", f"{self.socket_path}: {e}") from e
        return sock

    def _envelope(self, method: str, params: dict[str, Any]) -> tuple[str, bytes]:
        req_id = f"spec-engine-{os.getpid()}-{next(self._ids)}"
        line = json.dumps({"id": req_id, "method": method, "params": params}) + "\n"
        return req_id, line.encode("utf-8")

    @staticmethod
    def _read_line(reader: Any) -> dict:
        raw = reader.readline()
        if not raw:
            raise HerdrError("connection_failed", "connection closed without a response")
        try:
            msg = json.loads(raw)
        except ValueError as e:
            raise HerdrError("invalid_response", f"not JSON: {raw[:200]!r}") from e
        if not isinstance(msg, dict):
            raise HerdrError("invalid_response", f"not an object: {raw[:200]!r}")
        return msg

    @staticmethod
    def _result(msg: dict) -> dict:
        err = msg.get("error")
        if err is not None:
            if isinstance(err, dict):
                raise HerdrError(str(err.get("code", "error")), str(err.get("message", "")))
            raise HerdrError("error", str(err))
        result = msg.get("result")
        return result if isinstance(result, dict) else {}

    def request(self, method: str, params: dict[str, Any] | None = None,
                timeout: float | None = None) -> dict:
        """Send one request on a fresh connection and return its ``result`` object."""
        _, line = self._envelope(method, params or {})
        sock = self._connect(self.timeout if timeout is None else timeout)
        try:
            sock.sendall(line)
            with sock.makefile("rb") as reader:
                msg = self._read_line(reader)
        except OSError as e:  # includes socket.timeout
            raise HerdrError("connection_failed", f"{method}: {e}") from e
        finally:
            sock.close()
        return self._result(msg)

    # Herdr protocol --------------------------------------------------------------------------

    def ping(self) -> dict:
        return self.request("ping", {})

    @staticmethod
    def _worktree(result: dict) -> Worktree:
        try:
            return Worktree(
                workspace_id=result["workspace"]["workspace_id"],
                pane_id=result["root_pane"]["pane_id"],
                path=result["worktree"]["path"],
            )
        except (KeyError, TypeError) as e:
            raise HerdrError("invalid_response", f"worktree result missing {e}") from e

    def create_worktree(self, cwd: str, branch: str, base: str, label: str) -> Worktree:
        return self._worktree(self.request("worktree.create", {
            "cwd": os.path.abspath(cwd), "branch": branch, "base": base, "label": label,
            "focus": False,
        }, timeout=120.0))

    def open_worktree(self, cwd: str, branch: str, label: str) -> Worktree:
        return self._worktree(self.request("worktree.open", {
            "cwd": os.path.abspath(cwd), "branch": branch, "label": label, "focus": False,
        }, timeout=120.0))

    def remove_worktree(self, workspace_id: str) -> None:
        self.request("worktree.remove", {"workspace_id": workspace_id}, timeout=120.0)

    def create_tab(self, cwd: str, label: str) -> str:
        result = self.request("tab.create", {
            "cwd": os.path.abspath(cwd), "label": label, "focus": False,
        })
        return _get(result, "root_pane", "pane_id")

    def split_pane(self, pane_id: str, cwd: str) -> str:
        result = self.request("pane.split", {
            "target_pane_id": pane_id, "direction": "right", "cwd": os.path.abspath(cwd),
            "focus": False,
        })
        return _get(result, "pane", "pane_id")

    def close_pane(self, pane_id: str) -> None:
        self.request("pane.close", {"pane_id": pane_id})

    def start_agent(self, name: str, pane_id: str, args: list[str]) -> None:
        self.request("agent.start", {
            "name": name, "kind": "claude", "pane_id": pane_id, "args": list(args),
            "timeout_ms": AGENT_START_TIMEOUT_MS,
        }, timeout=AGENT_START_TIMEOUT_MS / 1000 + 30)

    def prompt_agent(self, name: str, text: str) -> None:
        self.request("agent.prompt", {"target": name, "text": text})

    def agent_status(self, name: str) -> AgentStatus:
        try:
            result = self.request("agent.get", {"target": name})
        except HerdrError as e:
            if e.code == AGENT_NOT_FOUND:
                return "missing"
            raise
        status = (result.get("agent") or {}).get("agent_status")
        return status if status in AGENT_STATUSES else "unknown"  # type: ignore[return-value]

    def read_agent(self, name: str, lines: int) -> str:
        result = self.request("agent.read", {
            "target": name, "source": "recent", "lines": int(lines), "format": "text",
            "strip_ansi": True,
        })
        read = result.get("read")
        if isinstance(read, dict):
            return str(read.get("text", ""))
        return str(result.get("text", ""))

    def interrupt_agent(self, name: str) -> None:
        self.request("agent.send_keys", {"target": name, "keys": ["ctrl+c"]})

    def wait_for_change(self, timeout: float) -> None:
        """Block until a named agent's status changes, a pane closes/exits, or ``timeout``.

        Subscribes to ``pane.agent_status_changed`` for the panes of named agents (the schema
        requires a ``pane_id`` per entry) plus ``pane.closed`` / ``pane.exited``. With no named
        agents, or on any error, it just sleeps out the remaining time.
        """
        deadline = time.monotonic() + max(0.0, timeout)
        remaining = lambda: max(0.0, deadline - time.monotonic())  # noqa: E731
        try:
            agents = self.request("agent.list", {}, timeout=min(self.timeout, timeout or 1)
                                  ).get("agents") or []
            panes = sorted({a["pane_id"] for a in agents
                            if isinstance(a, dict) and a.get("name") and a.get("pane_id")})
            if not panes:
                self._sleep(remaining())
                return
            subs: list[dict[str, Any]] = [
                {"type": "pane.agent_status_changed", "pane_id": p} for p in panes
            ]
            subs += [{"type": "pane.closed"}, {"type": "pane.exited"}]
            self._subscribe_until_event(subs, remaining)
        except (HerdrError, OSError, ValueError, KeyError, TypeError):
            self._sleep(remaining())

    def _subscribe_until_event(self, subs: list[dict[str, Any]],
                               remaining: Callable[[], float]) -> None:
        left = remaining()
        if left <= 0:
            return
        _, line = self._envelope("events.subscribe", {"subscriptions": subs})
        sock = self._connect(left)
        try:
            sock.sendall(line)
            with sock.makefile("rb") as reader:
                self._result(self._read_line(reader))  # ack (subscription_started) or error
                left = remaining()
                if left <= 0:
                    return
                sock.settimeout(left)
                try:
                    # The first pushed line ends the wait: an event, or an error such as
                    # ``events_lost`` (state changed in ways we missed — re-poll either way).
                    self._read_line(reader)
                except (socket.timeout, TimeoutError):
                    return
        finally:
            sock.close()


def _get(result: dict, *keys: str) -> str:
    cur: Any = result
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            raise HerdrError("invalid_response", f"result missing {'.'.join(keys)}")
        cur = cur[k]
    return str(cur)
