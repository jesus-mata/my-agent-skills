import json
import os
import shutil
import socket
import tempfile
import threading
import time
import unittest

from spec_engine.adapters.herdr_socket import SocketHerdr, default_socket_path
from spec_engine.ports import HerdrError, Worktree


class FakeHerdrServer:
    """A unix-socket NDJSON server. ``handlers[method](params)`` returns the reply: a dict
    (sent with the request id), or a list of dicts (sent in order) and floats (sleeps). The
    connection is then held open until the client closes it."""

    def __init__(self) -> None:
        # Short path: macOS caps unix socket paths at ~104 bytes.
        self.dir = tempfile.mkdtemp(dir="/tmp", prefix="hse")
        self.path = os.path.join(self.dir, "h.sock")
        self.handlers: dict = {}
        self.requests: list[dict] = []
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(self.path)
        self._sock.listen(16)
        self._stop = False
        threading.Thread(target=self._serve, daemon=True).start()

    def close(self) -> None:
        self._stop = True
        self._sock.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def methods(self) -> list[str]:
        return [r["method"] for r in self.requests]

    def last(self, method: str) -> dict:
        return [r for r in self.requests if r["method"] == method][-1]

    def _serve(self) -> None:
        while not self._stop:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn: socket.socket) -> None:
        with conn:
            reader = conn.makefile("rb")
            line = reader.readline()
            if not line:
                return
            req = json.loads(line)
            self.requests.append(req)
            handler = self.handlers.get(req["method"])
            reply = handler(req["params"]) if handler else {
                "error": {"code": "unknown_method", "message": req["method"]}}
            items = reply if isinstance(reply, list) else [reply]
            try:
                for item in items:
                    if isinstance(item, (int, float)):
                        time.sleep(item)
                        continue
                    msg = item if "event" in item else {"id": req["id"], **item}
                    conn.sendall((json.dumps(msg) + "\n").encode())
                reader.read()  # hold until the client hangs up
            except OSError:
                pass


def ok(result_type: str, **fields) -> dict:
    return {"result": {"type": result_type, **fields}}


def err(code: str, message: str = "boom") -> dict:
    return {"error": {"code": code, "message": message}}


def agent_info(pane_id: str, status: str = "idle", name: str | None = None) -> dict:
    return {"terminal_id": "t", "agent_status": status, "workspace_id": pane_id.split(":")[0],
            "tab_id": pane_id.split(":")[0] + ":t1", "pane_id": pane_id, "focused": False,
            "revision": 1, "name": name, "agent": "claude"}


WORKTREE_RESULT = ok(
    "worktree_created",
    workspace={"workspace_id": "w7", "label": "ticket-3"},
    tab={"tab_id": "w7:t1"},
    root_pane={"pane_id": "w7:p1", "workspace_id": "w7"},
    worktree={"path": "/repo/.worktrees/ticket-3", "branch": "ticket-3", "label": "ticket-3"},
)


class SocketHerdrTest(unittest.TestCase):
    def setUp(self):
        self.server = FakeHerdrServer()
        self.addCleanup(self.server.close)
        self.slept: list[float] = []
        self.herdr = SocketHerdr(self.server.path, timeout=5, sleep=self.slept.append)

    def test_envelope_and_ping(self):
        self.server.handlers["ping"] = lambda p: ok("pong", version="0.9.1", protocol=22)
        self.assertEqual(self.herdr.ping()["version"], "0.9.1")
        self.herdr.ping()
        a, b = self.server.requests
        self.assertEqual(set(a), {"id", "method", "params"})
        self.assertEqual((a["method"], a["params"]), ("ping", {}))
        self.assertIsInstance(a["id"], str)
        self.assertNotEqual(a["id"], b["id"])

    def test_error_response_raises_herdr_error(self):
        self.server.handlers["pane.close"] = lambda p: err("pane_not_found", "pane w9:p9 not found")
        with self.assertRaises(HerdrError) as cm:
            self.herdr.close_pane("w9:p9")
        self.assertEqual(cm.exception.code, "pane_not_found")
        self.assertEqual(cm.exception.message, "pane w9:p9 not found")
        self.assertEqual(self.server.last("pane.close")["params"], {"pane_id": "w9:p9"})

    def test_no_server_raises_connection_failed(self):
        herdr = SocketHerdr(os.path.join(self.server.dir, "nope.sock"))
        with self.assertRaises(HerdrError) as cm:
            herdr.ping()
        self.assertEqual(cm.exception.code, "connection_failed")

    def test_create_and_open_worktree(self):
        self.server.handlers["worktree.create"] = lambda p: WORKTREE_RESULT
        self.server.handlers["worktree.open"] = lambda p: {
            "result": {**WORKTREE_RESULT["result"], "type": "worktree_opened", "already_open": True}}
        wt = self.herdr.create_worktree("/repo", "ticket-3", "spec-7", "ticket-3")
        self.assertEqual(wt, Worktree("w7", "w7:p1", "/repo/.worktrees/ticket-3"))
        self.assertEqual(self.server.last("worktree.create")["params"], {
            "cwd": "/repo", "branch": "ticket-3", "base": "spec-7", "label": "ticket-3",
            "focus": False})
        self.assertEqual(self.herdr.open_worktree("/repo", "ticket-3", "ticket-3"), wt)
        self.assertEqual(self.server.last("worktree.open")["params"], {
            "cwd": "/repo", "branch": "ticket-3", "label": "ticket-3", "focus": False})

    def test_worktree_result_missing_fields(self):
        self.server.handlers["worktree.create"] = lambda p: ok("worktree_created")
        with self.assertRaises(HerdrError) as cm:
            self.herdr.create_worktree("/repo", "b", "main", "b")
        self.assertEqual(cm.exception.code, "invalid_response")

    def test_remove_worktree(self):
        self.server.handlers["worktree.remove"] = lambda p: ok(
            "worktree_removed", workspace_id="w7", path="/x", forced=False)
        self.herdr.remove_worktree("w7")
        self.assertEqual(self.server.last("worktree.remove")["params"], {"workspace_id": "w7"})
        self.herdr.remove_worktree("w7", force=True)
        self.assertEqual(self.server.last("worktree.remove")["params"],
                         {"workspace_id": "w7", "force": True})

    def test_tabs_and_panes(self):
        self.server.handlers["tab.create"] = lambda p: ok(
            "tab_created", tab={"tab_id": "w1:t2"}, root_pane={"pane_id": "w1:p4"})
        self.server.handlers["pane.split"] = lambda p: ok("pane_info", pane={"pane_id": "w1:p5"})
        self.assertEqual(self.herdr.create_tab("/repo", "human-4"), "w1:p4")
        self.assertEqual(self.server.last("tab.create")["params"],
                         {"cwd": "/repo", "label": "human-4", "focus": False})
        self.assertEqual(self.herdr.split_pane("w1:p4", "/repo"), "w1:p5")
        self.assertEqual(self.server.last("pane.split")["params"], {
            "target_pane_id": "w1:p4", "direction": "right", "cwd": "/repo", "focus": False})

    def test_agent_start_prompt_read_interrupt(self):
        self.server.handlers["agent.start"] = lambda p: ok(
            "agent_started", agent=agent_info("w7:p1", name="ticket-3"), argv=["claude"])
        self.server.handlers["agent.prompt"] = lambda p: ok(
            "agent_prompted", agent=agent_info("w7:p1", "working", "ticket-3"))
        self.server.handlers["agent.read"] = lambda p: ok(
            "pane_read", read={"pane_id": "w7:p1", "text": "hello\nworld\n", "truncated": True})
        self.server.handlers["agent.send_keys"] = lambda p: ok("ok")

        self.herdr.start_agent("ticket-3", "w7:p1", ["--model", "opus"])
        self.assertEqual(self.server.last("agent.start")["params"], {
            "name": "ticket-3", "kind": "claude", "pane_id": "w7:p1",
            "args": ["--model", "opus"], "timeout_ms": 60000})
        self.herdr.prompt_agent("ticket-3", "do it")
        self.assertEqual(self.server.last("agent.prompt")["params"],
                         {"target": "ticket-3", "text": "do it"})
        self.assertEqual(self.herdr.read_agent("ticket-3", 40), "hello\nworld\n")
        self.assertEqual(self.server.last("agent.read")["params"], {
            "target": "ticket-3", "source": "recent", "lines": 40, "format": "text",
            "strip_ansi": True})
        self.herdr.interrupt_agent("ticket-3")
        self.assertEqual(self.server.last("agent.send_keys")["params"],
                         {"target": "ticket-3", "keys": ["ctrl+c"]})

    def test_agent_status(self):
        statuses = iter(["blocked", "weird"])
        self.server.handlers["agent.get"] = lambda p: ok(
            "agent_info", agent=agent_info("w7:p1", next(statuses), p["target"]))
        self.assertEqual(self.herdr.agent_status("ticket-3"), "blocked")
        self.assertEqual(self.server.last("agent.get")["params"], {"target": "ticket-3"})
        self.assertEqual(self.herdr.agent_status("ticket-3"), "unknown")

    def test_agent_not_found_is_missing(self):
        self.server.handlers["agent.get"] = lambda p: err(
            "agent_not_found", "agent target ticket-3 not found")
        self.assertEqual(self.herdr.agent_status("ticket-3"), "missing")

    def test_agent_pane(self):
        self.server.handlers["agent.get"] = lambda p: ok(
            "agent_info", agent=agent_info("w7:p1", "idle", p["target"]))
        self.assertEqual(self.herdr.agent_pane("ticket-3"), "w7:p1")
        self.server.handlers["agent.get"] = lambda p: err("agent_not_found", "gone")
        self.assertIsNone(self.herdr.agent_pane("ticket-3"))

    def test_agent_status_other_errors_raise(self):
        self.server.handlers["agent.get"] = lambda p: err("internal", "x")
        with self.assertRaises(HerdrError):
            self.herdr.agent_status("ticket-3")

    def test_prompt_missing_agent_raises(self):
        self.server.handlers["agent.prompt"] = lambda p: err("agent_not_found", "gone")
        with self.assertRaises(HerdrError) as cm:
            self.herdr.prompt_agent("ticket-3", "x")
        self.assertEqual(cm.exception.code, "agent_not_found")

    # wait_for_change -------------------------------------------------------------------------

    def _agents(self, *agents):
        self.server.handlers["agent.list"] = lambda p: ok("agent_list", agents=list(agents))

    def test_wait_returns_on_event(self):
        self._agents(agent_info("w7:p1", "working", "ticket-3"), agent_info("w1:p9", "idle"))
        event = {"event": "pane.agent_status_changed",
                 "data": {"pane_id": "w7:p1", "workspace_id": "w7", "agent_status": "idle"}}
        self.server.handlers["events.subscribe"] = lambda p: [
            ok("subscription_started"), 0.2, event]
        start = time.monotonic()
        self.herdr.wait_for_change(5)
        elapsed = time.monotonic() - start
        self.assertGreaterEqual(elapsed, 0.15)
        self.assertLess(elapsed, 3)
        self.assertEqual(self.slept, [])
        subs = self.server.last("events.subscribe")["params"]["subscriptions"]
        self.assertEqual(subs, [{"type": "pane.agent_status_changed", "pane_id": "w7:p1"},
                                {"type": "pane.closed"}, {"type": "pane.exited"}])

    def test_wait_returns_on_timeout(self):
        self._agents(agent_info("w7:p1", "working", "ticket-3"))
        self.server.handlers["events.subscribe"] = lambda p: [ok("subscription_started")]
        start = time.monotonic()
        self.herdr.wait_for_change(0.4)
        elapsed = time.monotonic() - start
        self.assertGreaterEqual(elapsed, 0.35)
        self.assertLess(elapsed, 3)
        self.assertEqual(self.slept, [])

    def test_wait_returns_on_events_lost(self):
        self._agents(agent_info("w7:p1", "working", "ticket-3"))
        self.server.handlers["events.subscribe"] = lambda p: [
            ok("subscription_started"), err("events_lost", "fell behind")]
        start = time.monotonic()
        self.herdr.wait_for_change(5)
        self.assertLess(time.monotonic() - start, 3)
        self.assertEqual(self.slept, [])

    def test_wait_without_named_agents_sleeps(self):
        self._agents(agent_info("w1:p9", "idle"))
        self.herdr.wait_for_change(2)
        self.assertNotIn("events.subscribe", self.server.methods())
        self.assertEqual(len(self.slept), 1)
        self.assertAlmostEqual(self.slept[0], 2, delta=0.5)

    def test_wait_subscribe_error_falls_back_to_sleep(self):
        self._agents(agent_info("w7:p1", "working", "ticket-3"))
        self.server.handlers["events.subscribe"] = lambda p: err("pane_not_found", "w7:p1")
        self.herdr.wait_for_change(2)
        self.assertEqual(len(self.slept), 1)
        self.assertAlmostEqual(self.slept[0], 2, delta=0.5)

    def test_wait_without_server_sleeps(self):
        herdr = SocketHerdr(os.path.join(self.server.dir, "nope.sock"), sleep=self.slept.append)
        herdr.wait_for_change(1)
        self.assertEqual(len(self.slept), 1)


class SocketPathTest(unittest.TestCase):
    def test_resolution_order(self):
        self.assertEqual(default_socket_path({"HERDR_SOCKET_PATH": "/s.sock",
                                              "HERDR_SESSION": "x"}), "/s.sock")
        self.assertEqual(default_socket_path({"HERDR_SESSION": "x"}),
                         os.path.expanduser("~/.config/herdr/sessions/x/herdr.sock"))
        self.assertEqual(default_socket_path({}), os.path.expanduser("~/.config/herdr/herdr.sock"))


if __name__ == "__main__":
    unittest.main()
