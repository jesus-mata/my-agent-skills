"""The state directory: plan, atomic state, event log, inboxes, stop flag and pid lock."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Callable

from .model import Plan, RunState


def state_dir_for(common_dir: str, spec: int) -> str:
    """``<git-common-dir>/herdr-spec/<N>`` as an absolute path."""
    return os.path.join(os.path.abspath(common_dir), "herdr-spec", str(spec))


@dataclass(frozen=True)
class StorePaths:
    root: str
    plan: str
    state: str
    events: str
    resolutions: str
    stop: str
    pid: str
    out: str
    report: str


class Store:
    """File-backed persistence for one spec's state directory."""

    def __init__(self, state_dir: str, now: Callable[[], float] = time.time) -> None:
        self.state_dir = os.path.abspath(state_dir)
        self._now = now
        j = lambda name: os.path.join(self.state_dir, name)  # noqa: E731
        self.paths = StorePaths(
            root=self.state_dir, plan=j("plan.json"), state=j("state.json"),
            events=j("events.jsonl"), resolutions=j("resolutions.jsonl"), stop=j("stop"),
            pid=j("engine.pid"), out=j("out"), report=j("report.md"),
        )

    state_dir_for = staticmethod(state_dir_for)

    def ensure(self) -> None:
        os.makedirs(self.paths.out, exist_ok=True)

    # plan / state ---------------------------------------------------------------------------

    def load_plan(self) -> Plan | None:
        data = self._read_json(self.paths.plan)
        return None if data is None else Plan.from_dict(data)

    def save_plan(self, plan: Plan) -> None:
        self._write_json_atomic(self.paths.plan, plan.to_dict())

    def load_state(self) -> RunState | None:
        data = self._read_json(self.paths.state)
        return None if data is None else RunState.from_dict(data)

    def save_state(self, state: RunState) -> None:
        self._write_json_atomic(self.paths.state, state.to_dict())

    # logs and inboxes -----------------------------------------------------------------------

    def append_event(self, run: str | None, type: str, **data: Any) -> None:
        self._append_jsonl(self.paths.events, {"ts": self._now(), "run": run, "type": type, **data})

    def append_resolution(
        self, escalation_id: str, action: str, note: str = "", ts: float | None = None
    ) -> None:
        self._append_jsonl(self.paths.resolutions, {
            "escalation_id": escalation_id, "action": action, "note": note,
            "ts": self._now() if ts is None else ts,
        })

    def read_resolutions(self) -> list[dict]:
        """Every well-formed line of the resolutions inbox, in order (bad lines skipped)."""
        try:
            with open(self.paths.resolutions, encoding="utf-8") as f:
                lines = f.readlines()
        except FileNotFoundError:
            return []
        out = []
        for line in lines:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                out.append(item)
        return out

    # stop flag ------------------------------------------------------------------------------

    def request_stop(self) -> None:
        self.ensure()
        with open(self.paths.stop, "w", encoding="utf-8"):
            pass

    def stop_requested(self) -> bool:
        return os.path.exists(self.paths.stop)

    def clear_stop(self) -> None:
        _unlink(self.paths.stop)

    # pid lock -------------------------------------------------------------------------------

    def write_pid(self, pid: int | None = None) -> None:
        self.ensure()
        with open(self.paths.pid, "w", encoding="utf-8") as f:
            f.write(str(os.getpid() if pid is None else pid))

    def read_pid(self) -> int | None:
        try:
            with open(self.paths.pid, encoding="utf-8") as f:
                return int(f.read().strip())
        except (FileNotFoundError, ValueError):
            return None

    def clear_pid(self) -> None:
        _unlink(self.paths.pid)

    def engine_alive(self) -> bool:
        pid = self.read_pid()
        if pid is None or pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    # outputs --------------------------------------------------------------------------------

    def archive_result(self, run_id: str, stage: str, attempt: int, data: Any) -> str:
        """Copy an accepted result to ``out/<run_id>.<stage>.<attempt>.json``; returns the path."""
        stage = getattr(stage, "value", stage)
        path = os.path.join(self.paths.out, f"{run_id}.{stage}.{attempt}.json")
        self._write_json_atomic(path, data)
        return path

    def write_report(self, text: str) -> str:
        self.ensure()
        tmp = self.paths.report + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, self.paths.report)
        return self.paths.report

    # helpers --------------------------------------------------------------------------------

    def _read_json(self, path: str) -> Any:
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return None

    def _write_json_atomic(self, path: str, data: Any) -> None:
        self.ensure()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)

    def _append_jsonl(self, path: str, item: dict) -> None:
        self.ensure()
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(item, sort_keys=True) + "\n")


def _unlink(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
