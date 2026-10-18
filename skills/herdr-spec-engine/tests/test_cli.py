"""The CLI commands through their testable functions, with fakes and temp state dirs."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

from spec_engine import cli
from spec_engine.adapters import Ports
from spec_engine.model import (
    EngineStatus, Escalation, EscalationKind, EscalationStatus, Run, RunKind, RunState,
    RunStatus, Settings, Stage,
)
from spec_engine.transitions import ACTIONS
from tests.engine_harness import IMPLEMENTED, REVIEW_CLEAN, SPEC, Harness, ticket
from tests.fakes import FakeClock

SPEC_REVIEW_CLEAN = {"fixed": [], "hard": [], "not_fixed": []}
E2E_OK = {"passed": ["flow works"], "fixed": [], "pending": []}
ENGINE = "/skills/herdr-spec-engine/engine"


def esc(id_, kind=EscalationKind.AGENT_BLOCKED, run="s7-ticket-1", status=EscalationStatus.OPEN,
        created_at=1.0, details="screen line 1\nscreen line 2"):
    return Escalation(id=id_, run=run, kind=kind, stage=Stage.IMPLEMENT, created_at=created_at,
                      summary=f"{run} needs help", details=details, actions=list(ACTIONS[kind]),
                      status=status)


class CliTestBase(unittest.TestCase):
    def setUp(self):
        self.h = Harness([ticket(1, title="Alpha")])
        self.addCleanup(self.h.cleanup)
        self.store = self.h.store
        self.out = io.StringIO()
        self.err = io.StringIO()
        self.clock = FakeClock(1000)

    def save_state(self, *escalations, runs=None, status=EngineStatus.RUNNING, consumed=()):
        state = RunState(spec=SPEC, branch="spec-7", status=status)
        for run in runs or [Run.new(RunKind.TICKET, "s7-ticket-1", ticket=1)]:
            state.runs[run.id] = run
        for e in escalations:
            state.escalations[e.id] = e
        state.consumed_resolutions = list(consumed)
        self.store.save_state(state)
        return state

    def call(self, fn, *args, **kw):
        with contextlib.redirect_stderr(self.err):
            return fn(*args, **kw)


# run ------------------------------------------------------------------------------------------

class RunCommandTest(CliTestBase):
    def ports(self):
        h = self.h
        return Ports(herdr=h.herdr, git=h.git, github=h.github, shell=h.shell, clock=h.clock)

    def run_cmd(self, overrides=None):
        return self.call(cli.run_command, self.ports(), self.h.root, SPEC, overrides or {},
                         self.out)

    def test_refuses_without_plan(self):
        self.assertEqual(self.run_cmd(), 1)
        self.assertIn("engine plan 7", self.err.getvalue())
        self.assertIsNone(self.store.load_state())

    def test_refuses_unrunnable_plan(self):
        plan = self.h.plan
        plan.tickets.append(ticket(2, klass="unrefined"))
        self.store.save_plan(plan)
        self.assertEqual(self.run_cmd(), 1)
        self.assertIn("unrefined tickets", self.err.getvalue())
        self.assertEqual(self.h.herdr.calls_to("ping"), [])

    def test_refuses_when_another_engine_is_alive(self):
        self.store.save_plan(self.h.plan)
        self.store.write_pid(os.getpid())
        self.assertEqual(self.run_cmd(), 1)
        self.assertIn("already running", self.err.getvalue())
        self.assertEqual(self.h.herdr.calls_to("ping"), [])

    def test_refuses_aborted_run_and_reports_complete_run(self):
        self.store.save_plan(self.h.plan)
        self.save_state(status=EngineStatus.ABORTED)
        self.assertEqual(self.run_cmd(), 1)
        self.assertIn("aborted", self.err.getvalue())
        self.save_state(status=EngineStatus.COMPLETE)
        self.assertEqual(self.run_cmd(), 0)
        self.assertIn("already complete", self.out.getvalue())

    def test_runs_to_completion_with_explicit_settings(self):
        h = self.h
        self.store.save_plan(h.plan)
        h.script_ticket("s7-ticket-1")
        h.turn("s7-review", SPEC_REVIEW_CLEAN)
        h.turn("s7-e2e", E2E_OK)
        self.assertEqual(self.run_cmd({"max_agents": 2, "model": "sonnet"}), 0)
        out = self.out.getvalue()
        self.assertIn("starting spec #7 (Spec seven) on branch spec-7", out)
        self.assertIn("max 2 agents, model sonnet", out)
        self.assertIn(f"COMPLETE. Report: {self.store.paths.report}", out)
        state = self.store.load_state()
        self.assertEqual(state.status, EngineStatus.COMPLETE)
        self.assertEqual((state.settings.max_agents, state.settings.model), (2, "sonnet"))
        self.assertEqual(h.herdr.agent_args["s7-ticket-1"][-1], "sonnet")
        self.assertIsNone(self.store.read_pid())
        self.assertTrue(os.path.isabs(self.store.state_dir))

    def test_ctrl_c_persists_and_resume_overrides_only_explicit_flags(self):
        h = self.h
        self.store.save_plan(h.plan)
        h.herdr.wait_for_change = lambda timeout: (_ for _ in ()).throw(KeyboardInterrupt)
        self.assertEqual(self.run_cmd({"model": "sonnet", "max_agents": 2}), 0)
        self.assertIn("Interrupted: state saved", self.out.getvalue())
        self.assertIsNone(self.store.read_pid())
        state = self.store.load_state()
        self.assertEqual(state.status, EngineStatus.RUNNING)
        self.assertEqual(state.runs["s7-ticket-1"].status, RunStatus.ACTIVE)

        self.out = io.StringIO()
        self.assertEqual(self.run_cmd({"retry_budget": 3}), 0)
        self.assertIn("resuming spec #7", self.out.getvalue())
        settings = self.store.load_state().settings
        self.assertEqual((settings.model, settings.max_agents, settings.retry_budget),
                         ("sonnet", 2, 3))
        self.assertEqual(settings.stage_timeout, Settings().stage_timeout)

    def test_stop_file_ends_the_run(self):
        h = self.h
        self.store.save_plan(h.plan)
        h.herdr.wait_for_change = lambda timeout: self.store.request_stop()
        self.assertEqual(self.run_cmd(), 0)
        self.assertIn("Stopped: state saved", self.out.getvalue())
        self.assertFalse(self.store.stop_requested())


# watch ----------------------------------------------------------------------------------------

class WatchCommandTest(CliTestBase):
    def watch(self, timeout=60, alive=True):
        return self.call(cli.watch_command, self.store, SPEC, timeout, self.out,
                         now=self.clock.now, sleep=self.clock.sleep, alive=lambda: alive,
                         engine_cmd=ENGINE)

    def test_prints_open_escalations_with_actions_and_resolve_command(self):
        self.save_state(esc("e2", created_at=2), esc("e1", EscalationKind.STAGE_TIMEOUT))
        self.assertEqual(self.watch(), 0)
        out = self.out.getvalue()
        self.assertIn("2 open escalation(s)", out)
        self.assertLess(out.index("ESCALATION e1"), out.index("ESCALATION e2"))
        self.assertIn("  run:     s7-ticket-1 (#1)", out)
        self.assertIn("  kind:    stage-timeout", out)
        self.assertIn("  stage:   implement", out)
        self.assertIn("  summary: s7-ticket-1 needs help", out)
        self.assertIn("  details:\n    screen line 1\n    screen line 2", out)
        self.assertIn("  actions: retry, skip-ticket, hand-to-human", out)
        self.assertIn(f"  resolve: {ENGINE} resolve 7 e1 <action> [--note TEXT]", out)

    def test_skips_escalations_with_a_queued_resolution_and_handed_off_ones(self):
        self.save_state(esc("e1"), esc("e2", status=EscalationStatus.HANDED_OFF),
                        esc("e3", status=EscalationStatus.RESOLVED))
        self.store.append_resolution("e1", "answered", ts=5.0)
        self.assertEqual(self.watch(timeout=12), 1)
        self.assertIn("timed out", self.out.getvalue())
        self.assertNotIn("ESCALATION", self.out.getvalue())
        self.assertEqual(self.clock.now(), 1012)

    def test_reports_again_once_the_resolution_is_consumed_and_it_reopened(self):
        self.save_state(esc("e1", EscalationKind.HITL_TICKET), consumed=["e1@5.0"])
        self.store.append_resolution("e1", "done", ts=5.0)
        self.assertEqual(self.watch(), 0)
        self.assertIn("ESCALATION e1", self.out.getvalue())

    def test_complete_prints_report(self):
        self.save_state(status=EngineStatus.COMPLETE)
        self.store.write_report("# Spec #7\n\nall good\n")
        self.assertEqual(self.watch(alive=False), 0)
        self.assertEqual(self.out.getvalue(), "COMPLETE\n\n# Spec #7\n\nall good\n")

    def test_dead_engine_exits_3_after_two_polls(self):
        self.save_state()
        self.assertEqual(self.watch(alive=False), 3)
        self.assertIn("ENGINE NOT RUNNING", self.out.getvalue())
        self.assertIn(f"{ENGINE} run 7", self.out.getvalue())
        self.assertEqual(self.clock.now(), 1005)

    def test_no_state_and_no_engine_exits_3(self):
        self.assertEqual(self.watch(alive=False), 3)

    def test_escalation_wins_over_a_dead_engine(self):
        self.save_state(esc("e1"))
        self.assertEqual(self.watch(alive=False), 0)

    def test_aborted(self):
        self.save_state(status=EngineStatus.ABORTED)
        self.assertEqual(self.watch(alive=False), 0)
        self.assertEqual(self.out.getvalue(), "ABORTED\n")

    def test_waits_until_an_escalation_appears(self):
        self.save_state()
        polls = []

        def sleep(seconds):
            polls.append(seconds)
            self.clock.advance(seconds)
            if len(polls) == 3:
                self.save_state(esc("e1"))

        code = self.call(cli.watch_command, self.store, SPEC, 3600, self.out,
                         now=self.clock.now, sleep=sleep, alive=lambda: True)
        self.assertEqual(code, 0)
        self.assertEqual(polls, [5.0, 5.0, 5.0])
        self.assertIn("ESCALATION e1", self.out.getvalue())


# resolve --------------------------------------------------------------------------------------

class InvokedEngineCmdTest(unittest.TestCase):
    def test_keeps_the_symlinked_path_the_supervisor_typed(self):
        with tempfile.TemporaryDirectory() as tmp:
            real = os.path.join(tmp, "checkout", "herdr-spec-engine")
            os.makedirs(real)
            open(os.path.join(real, "engine"), "w").close()
            link = os.path.join(tmp, "skills", "herdr-spec-engine")
            os.makedirs(os.path.dirname(link))
            os.symlink(real, link)
            typed = os.path.join(link, "engine")
            self.assertEqual(cli.invoked_engine_cmd(typed), typed)
            self.assertNotEqual(cli.invoked_engine_cmd(typed), os.path.realpath(typed))

    def test_relative_path_is_made_absolute(self):
        self.assertEqual(cli.invoked_engine_cmd("skill/engine"),
                         os.path.join(os.getcwd(), "skill", "engine"))

    def test_falls_back_when_not_run_through_the_launcher(self):
        self.assertEqual(cli.invoked_engine_cmd("/x/spec_engine/cli.py"), cli.ENGINE_CMD)
        self.assertEqual(cli.invoked_engine_cmd(""), cli.ENGINE_CMD)

    def test_cmd_watch_passes_the_invoked_path(self):
        args = cli.build_parser().parse_args(["watch", "7"])
        typed = "/home/u/.claude/skills/x/engine"
        with mock.patch.object(cli.sys, "argv", [typed, "watch", "7"]), \
                mock.patch.object(cli, "_cwd_store", return_value=None), \
                mock.patch.object(cli, "watch_command", return_value=0) as watch:
            self.assertEqual(cli.cmd_watch(args), 0)
        self.assertEqual(watch.call_args.kwargs["engine_cmd"], typed)


class ResolveCommandTest(CliTestBase):
    def resolve(self, esc_id, action, note=""):
        return self.call(cli.resolve_command, self.store, SPEC, esc_id, action, note, self.out)

    def test_valid_action_is_appended(self):
        self.save_state(esc("e1"))
        self.assertEqual(self.resolve("e1", "answered", "told it to use v2"), 0)
        [line] = self.store.read_resolutions()
        self.assertEqual((line["escalation_id"], line["action"], line["note"]),
                         ("e1", "answered", "told it to use v2"))
        self.assertIn("Queued e1 answered", self.out.getvalue())

    def test_disallowed_action_exits_2_listing_allowed_actions(self):
        self.save_state(esc("e1"))
        self.assertEqual(self.resolve("e1", "retry"), 2)
        self.assertIn("allowed actions: answered, hand-to-human", self.err.getvalue())
        self.assertEqual(self.store.read_resolutions(), [])

    def test_unknown_or_resolved_escalation_exits_2(self):
        self.save_state(esc("e1", status=EscalationStatus.RESOLVED), esc("e2"))
        self.assertEqual(self.resolve("e9", "answered"), 2)
        self.assertIn("unresolved: e2", self.err.getvalue())
        self.assertEqual(self.resolve("e1", "answered"), 2)
        self.assertIn("already resolved", self.err.getvalue())

    def test_handed_off_escalation_can_still_be_resolved(self):
        self.save_state(esc("e1", EscalationKind.HITL_TICKET, status=EscalationStatus.HANDED_OFF))
        self.assertEqual(self.resolve("e1", "done"), 0)

    def test_no_state_exits_2(self):
        self.assertEqual(self.resolve("e1", "retry"), 2)
        self.assertIn("no engine state", self.err.getvalue())


# status ---------------------------------------------------------------------------------------

class StatusCommandTest(CliTestBase):
    def test_text(self):
        run = Run.new(RunKind.TICKET, "s7-ticket-1", ticket=1)
        run.status, run.stage = RunStatus.ACTIVE, Stage.INTEGRATE
        run.awaiting = {"type": "queue"}
        state = self.save_state(esc("e1"), esc("e2", status=EscalationStatus.RESOLVED),
                                runs=[run])
        state.queue = ["s7-ticket-1"]
        self.store.save_state(state)
        self.store.append_resolution("e1", "answered", ts=3.0)
        self.assertEqual(self.call(cli.status_command, self.store, SPEC, False, self.out), 0)
        out = self.out.getvalue()
        self.assertIn("spec #7 on spec-7: running, phase tickets, engine not running", out)
        self.assertRegex(out, r"s7-ticket-1\s+active\s+integrate\s+queue")
        self.assertIn("Merge queue: s7-ticket-1", out)
        self.assertIn("Escalations (1 unresolved, 1 resolved)", out)
        self.assertIn("e1 open agent-blocked on s7-ticket-1", out)
        self.assertIn("[resolution queued]", out)

    def test_json(self):
        self.save_state(esc("e1"))
        self.assertEqual(self.call(cli.status_command, self.store, SPEC, True, self.out), 0)
        data = json.loads(self.out.getvalue())
        self.assertEqual(data["escalations"]["e1"]["kind"], "agent-blocked")

    def test_no_state_is_a_clean_error(self):
        self.assertEqual(self.call(cli.status_command, self.store, SPEC, False, self.out), 1)
        self.assertIn("engine plan 7", self.err.getvalue())
        self.store.save_plan(self.h.plan)
        self.assertEqual(self.call(cli.status_command, self.store, SPEC, False, self.out), 1)
        self.assertIn("engine run 7", self.err.getvalue())


# stop / abort ---------------------------------------------------------------------------------

class StopAbortTest(CliTestBase):
    def test_stop_requests_a_live_engine_to_exit(self):
        self.store.write_pid(os.getpid())
        self.assertEqual(cli.stop_command(self.store, SPEC, self.out), 0)
        self.assertTrue(self.store.stop_requested())

    def test_stop_without_engine_is_a_no_op(self):
        self.assertEqual(cli.stop_command(self.store, SPEC, self.out), 0)
        self.assertFalse(self.store.stop_requested())
        self.assertIn("No engine is running", self.out.getvalue())

    def abort(self, sleep=None, wait=60):
        return self.call(cli.abort_command, self.store, SPEC, self.h.herdr, self.out,
                         now=self.clock.now, sleep=sleep or self.clock.sleep, wait=wait)

    def runs_for_abort(self):
        herdr = self.h.herdr
        active = Run.new(RunKind.TICKET, "s7-ticket-1", ticket=1)
        wt = herdr.create_worktree(self.h.root, "s7-ticket-1", "spec-7", "s7-ticket-1")
        herdr.start_agent("s7-ticket-1", wt.pane_id, [])
        resolver_pane = herdr.split_pane(wt.pane_id, wt.path)
        herdr.start_agent("s7-resolve-ticket-1", resolver_pane, [])
        active.status, active.stage, active.agent = RunStatus.ACTIVE, Stage.INTEGRATE, "s7-ticket-1"
        active.workspace_id, active.pane_id, active.worktree = wt.workspace_id, wt.pane_id, wt.path
        active.awaiting = {"type": "resolver", "agent": "s7-resolve-ticket-1",
                           "pane_id": resolver_pane}
        done = Run.new(RunKind.TICKET, "s7-ticket-2", ticket=2)
        done.status, done.workspace_id = RunStatus.DONE, "w-done"
        pending = Run.new(RunKind.TICKET, "s7-ticket-3", ticket=3)
        return [active, done, pending], wt, resolver_pane

    def test_abort_tears_down_unfinished_runs(self):
        runs, wt, resolver_pane = self.runs_for_abort()
        state = self.save_state(esc("e1", status=EscalationStatus.HANDED_OFF), runs=runs)
        state.queue = ["s7-ticket-1"]
        self.store.save_state(state)
        self.assertEqual(self.abort(), 0)
        herdr = self.h.herdr
        self.assertEqual(herdr.interrupted, ["s7-resolve-ticket-1", "s7-ticket-1"])
        self.assertEqual(herdr.closed_panes, [resolver_pane])
        self.assertEqual(herdr.removed_worktrees, [wt.workspace_id])  # never the done run's
        self.assertEqual(self.h.github.calls, [])  # nothing on GitHub
        self.assertEqual(self.h.git.calls_to("checkout"), [])  # branches kept
        state = self.store.load_state()
        self.assertEqual(state.status, EngineStatus.ABORTED)
        self.assertEqual(state.queue, [])
        self.assertEqual({r.id: r.status for r in state.runs.values()},
                         {"s7-ticket-1": RunStatus.ABORTED, "s7-ticket-2": RunStatus.DONE,
                          "s7-ticket-3": RunStatus.ABORTED})
        self.assertIn("Nothing on GitHub was reverted", self.out.getvalue())

    def test_abort_continues_past_herdr_errors(self):
        runs, _, _ = self.runs_for_abort()
        self.save_state(runs=runs)
        self.h.herdr.fail_next("remove_worktree", RuntimeError("herdr down"))
        self.assertEqual(self.abort(), 0)
        self.assertIn("warning: remove worktree of s7-ticket-1: herdr down", self.out.getvalue())
        self.assertEqual(self.store.load_state().status, EngineStatus.ABORTED)

    def test_abort_stops_a_live_engine_first(self):
        self.save_state()
        self.store.write_pid(os.getpid())

        def sleep(seconds):
            self.assertTrue(self.store.stop_requested())
            self.store.clear_pid()  # the engine exits
            self.store.clear_stop()

        self.assertEqual(self.abort(sleep=sleep), 0)
        self.assertEqual(self.store.load_state().status, EngineStatus.ABORTED)

    def test_abort_gives_up_when_the_engine_does_not_stop(self):
        self.save_state()
        self.store.write_pid(os.getpid())
        self.assertEqual(self.abort(wait=60), 1)
        self.assertIn("did not stop within 60s", self.err.getvalue())
        self.assertEqual(self.clock.now(), 1060)
        self.assertEqual(self.store.load_state().status, EngineStatus.RUNNING)
        self.assertEqual(self.h.herdr.interrupted, [])

    def test_abort_without_state(self):
        self.assertEqual(self.abort(), 1)


if __name__ == "__main__":
    unittest.main()
