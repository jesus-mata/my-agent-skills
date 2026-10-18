import json
import os
import tempfile
import unittest

from spec_engine.model import Plan, Run, RunKind, RunState
from spec_engine.store import Store, state_dir_for


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, "herdr-spec", "7"), now=lambda: 42.0)

    def test_state_dir_for(self):
        self.assertEqual(state_dir_for("/r/.git", 7), "/r/.git/herdr-spec/7")
        self.assertEqual(Store.state_dir_for("/r/.git", 7), "/r/.git/herdr-spec/7")

    def test_paths(self):
        p = self.store.paths
        for name, attr in [("plan.json", p.plan), ("state.json", p.state),
                           ("events.jsonl", p.events), ("resolutions.jsonl", p.resolutions),
                           ("stop", p.stop), ("engine.pid", p.pid), ("out", p.out),
                           ("report.md", p.report)]:
            self.assertEqual(attr, os.path.join(self.store.state_dir, name))

    def test_plan_and_state_round_trip(self):
        self.assertIsNone(self.store.load_plan())
        self.assertIsNone(self.store.load_state())
        plan = Plan(spec=7, title="T", branch="spec-7")
        self.store.save_plan(plan)
        self.assertEqual(self.store.load_plan(), plan)
        state = RunState(spec=7, branch="spec-7",
                         runs={"s7-ticket-1": Run.new(RunKind.TICKET, "s7-ticket-1", ticket=1)})
        self.store.save_state(state)
        self.assertEqual(self.store.load_state(), state)
        leftovers = [f for f in os.listdir(self.store.state_dir) if f.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_events_and_resolutions(self):
        self.store.append_event("s7-ticket-1", "transition", to="review")
        with open(self.store.paths.events) as f:
            self.assertEqual(json.loads(f.readline()),
                             {"ts": 42.0, "run": "s7-ticket-1", "type": "transition", "to": "review"})
        self.assertEqual(self.store.read_resolutions(), [])
        self.store.append_resolution("e1", "retry", note="go")
        with open(self.store.paths.resolutions, "a") as f:
            f.write("garbage\n")
        self.store.append_resolution("e2", "done")
        res = self.store.read_resolutions()
        self.assertEqual([r["escalation_id"] for r in res], ["e1", "e2"])
        self.assertEqual(res[0], {"escalation_id": "e1", "action": "retry", "note": "go",
                                  "ts": 42.0})

    def test_stop_flag(self):
        self.assertFalse(self.store.stop_requested())
        self.store.request_stop()
        self.assertTrue(self.store.stop_requested())
        self.store.clear_stop()
        self.store.clear_stop()
        self.assertFalse(self.store.stop_requested())

    def test_pid(self):
        self.assertIsNone(self.store.read_pid())
        self.assertFalse(self.store.engine_alive())
        self.store.write_pid()
        self.assertEqual(self.store.read_pid(), os.getpid())
        self.assertTrue(self.store.engine_alive())
        self.store.write_pid(2 ** 22 + 12345)  # almost certainly not a live pid
        self.assertFalse(self.store.engine_alive())
        self.store.clear_pid()
        self.assertIsNone(self.store.read_pid())

    def test_archive_and_report(self):
        path = self.store.archive_result("s7-ticket-1", "review", 0, {"a": 1})
        self.assertEqual(path, os.path.join(self.store.paths.out, "s7-ticket-1.review.0.json"))
        with open(path) as f:
            self.assertEqual(json.load(f), {"a": 1})
        self.store.write_report("# Report\n")
        with open(self.store.paths.report) as f:
            self.assertEqual(f.read(), "# Report\n")


if __name__ == "__main__":
    unittest.main()
