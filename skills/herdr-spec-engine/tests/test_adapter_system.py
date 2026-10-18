import os
import tempfile
import time
import unittest

from spec_engine.adapters import Ports, real_ports
from spec_engine.adapters.system import SubprocessShell, SystemClock


class SubprocessShellTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.shell = SubprocessShell()

    def test_merged_output_exit_code_and_cwd(self):
        r = self.shell.run("pwd; echo out; echo err >&2; exit 3", self.tmp.name, 10)
        self.assertEqual(r.code, 3)
        lines = r.output.splitlines()
        self.assertEqual(os.path.realpath(lines[0]), os.path.realpath(self.tmp.name))
        self.assertIn("out", lines)
        self.assertIn("err", lines)

    def test_timeout_kills_tree_and_returns_124(self):
        start = time.monotonic()
        r = self.shell.run("echo started; sleep 30 & sleep 30", self.tmp.name, 0.5)
        self.assertLess(time.monotonic() - start, 10)
        self.assertEqual(r.code, 124)
        self.assertIn("started", r.output)
        self.assertIn("timed out", r.output)


class SystemClockTest(unittest.TestCase):
    def test_now_and_sleep(self):
        clock = SystemClock()
        self.assertAlmostEqual(clock.now(), time.time(), delta=1)
        start = time.monotonic()
        clock.sleep(0.05)
        clock.sleep(-1)
        self.assertGreaterEqual(time.monotonic() - start, 0.04)


class RealPortsTest(unittest.TestCase):
    def test_factory_builds_all_adapters_without_side_effects(self):
        ports = real_ports("/repo", socket_path="/tmp/none.sock")
        self.assertIsInstance(ports, Ports)
        self.assertEqual(ports.herdr.socket_path, "/tmp/none.sock")
        self.assertEqual(ports.github.cwd, "/repo")


if __name__ == "__main__":
    unittest.main()
