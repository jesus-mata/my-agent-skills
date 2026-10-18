import argparse
import contextlib
import io
import unittest

from spec_engine import cli


class ParseDurationTest(unittest.TestCase):
    def test_units(self):
        self.assertEqual(cli.parse_duration("90"), 90)
        self.assertEqual(cli.parse_duration("90s"), 90)
        self.assertEqual(cli.parse_duration("30m"), 1800)
        self.assertEqual(cli.parse_duration("2h"), 7200)
        self.assertEqual(cli.parse_duration("1.5h"), 5400)

    def test_invalid(self):
        for text in ("", "h", "2d", "-5", "abc", "1h30m"):
            with self.subTest(text=text), self.assertRaises(argparse.ArgumentTypeError):
                cli.parse_duration(text)


def parse(*argv):
    return cli.build_parser().parse_args(list(argv))


class ParserTest(unittest.TestCase):
    def test_plan(self):
        a = parse("plan", "12", "--branch", "b", "--gate", "make lint", "--gate", "make test",
                  "--from", "t.json")
        self.assertEqual((a.spec, a.branch, a.gate, a.from_file), (12, "b", ["make lint", "make test"], "t.json"))
        self.assertIs(a.handler, cli.cmd_plan)
        a = parse("plan", "12")
        self.assertEqual((a.branch, a.base, a.gate, a.from_file), (None, None, None, None))
        self.assertEqual(parse("plan", "12", "--base", "master").base, "master")

    def test_run(self):
        a = parse("run", "12", "--max-agents", "2", "--model", "sonnet", "--stage-timeout", "1h",
                  "--retry-budget", "0", "--gate-retry-budget", "3", "--gate-timeout", "10m",
                  "--poll", "5")
        self.assertEqual(cli.settings_overrides(a), {
            "max_agents": 2, "model": "sonnet", "stage_timeout": 3600, "retry_budget": 0,
            "gate_retry_budget": 3, "gate_timeout": 600, "poll_seconds": 5})
        self.assertEqual(cli.settings_overrides(parse("run", "12")), {})
        self.assertEqual(cli.settings_overrides(parse("run", "1", "--model", "x")), {"model": "x"})

    def test_watch(self):
        self.assertEqual(parse("watch", "3").timeout, 4 * 3600)
        self.assertEqual(parse("watch", "3", "--timeout", "30m").timeout, 1800)

    def test_resolve(self):
        a = parse("resolve", "3", "e4", "retry", "--note", "try again")
        self.assertEqual((a.spec, a.escalation_id, a.action, a.note), (3, "e4", "retry", "try again"))
        self.assertEqual(parse("resolve", "3", "e4", "retry").note, "")

    def test_status_stop_abort(self):
        self.assertTrue(parse("status", "3", "--json").json)
        self.assertFalse(parse("status", "3").json)
        self.assertIs(parse("stop", "3").handler, cli.cmd_stop)
        self.assertIs(parse("abort", "3").handler, cli.cmd_abort)

    def test_handlers(self):
        for cmd in ("plan", "run", "watch", "resolve", "status", "stop", "abort"):
            self.assertIs(parse(*([cmd, "1"] + (["e1", "x"] if cmd == "resolve" else []))).handler,
                          getattr(cli, f"cmd_{cmd}"))

    def test_rejects_bad_input(self):
        for argv in (["plan"], ["plan", "x"], ["run", "1", "--poll", "soon"], ["frobnicate", "1"],
                     ["resolve", "1", "e1"], []):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    parse(*argv)


if __name__ == "__main__":
    unittest.main()
