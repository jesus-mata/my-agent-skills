"""Preflight: tools, gh auth, herdr socket and the skills the prompts invoke."""
import io
import json
import os
import re
import tempfile
import unittest

from spec_engine import cli, preflight

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "spec_engine", "prompts")
SKILL_RE = re.compile(r"`/([a-z][a-z0-9-]*(?::[a-z0-9-]+)?)")


def write(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class PreflightTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.config = os.path.join(tmp.name, "claude")
        self.repo = os.path.join(tmp.name, "repo")
        self.socket = os.path.join(tmp.name, "herdr.sock")
        write(self.socket)
        self.env = {"CLAUDE_CONFIG_DIR": self.config, "HERDR_SOCKET_PATH": self.socket}

    def install_all_skills(self):
        for name in ("implement-ticket", "e2e"):
            write(os.path.join(self.config, "skills", name, "SKILL.md"))
        plugin = os.path.join(self.config, "plugins", "cache", "mattpocock-skills", "1.0")
        write(os.path.join(plugin, ".claude-plugin", "plugin.json"),
              json.dumps({"skills": ["./skills/engineering/tdd"]}))
        write(os.path.join(plugin, "skills", "engineering", "tdd", "SKILL.md"))
        write(os.path.join(plugin, "skills", "code-review", "SKILL.md"))
        write(os.path.join(self.config, "plugins", "installed_plugins.json"), json.dumps(
            {"plugins": {"mattpocock-skills@official": [{"installPath": plugin}]}}))

    def check(self, which=lambda tool: f"/bin/{tool}", authenticated=True):
        return preflight.check(self.repo, env=self.env, which=which,
                               gh_authenticated=lambda: authenticated)

    def test_all_present_is_clean(self):
        self.install_all_skills()
        report = self.check()
        self.assertEqual(report.errors, [])
        self.assertEqual(report.warnings, [])

    def test_missing_tool_is_an_error(self):
        self.install_all_skills()
        report = self.check(which=lambda tool: None if tool == "herdr" else f"/bin/{tool}")
        self.assertEqual(report.errors, ["`herdr` not found on PATH"])

    def test_unauthenticated_gh_is_an_error(self):
        self.install_all_skills()
        report = self.check(authenticated=False)
        self.assertEqual(report.errors, ["`gh` is not authenticated; run `gh auth login`"])

    def test_auth_not_checked_without_gh(self):
        self.install_all_skills()
        report = self.check(which=lambda tool: None if tool == "gh" else f"/bin/{tool}",
                            authenticated=False)
        self.assertEqual(report.errors, ["`gh` not found on PATH"])

    def test_missing_herdr_socket_is_an_error(self):
        self.install_all_skills()
        os.remove(self.socket)
        report = self.check()
        self.assertEqual(len(report.errors), 1)
        self.assertIn("no herdr socket", report.errors[0])

    def test_missing_skills_are_warnings(self):
        report = self.check()
        self.assertEqual(report.errors, [])
        missing = [re.search(r"`/([^`]+)`", w).group(1) for w in report.warnings]
        self.assertEqual(missing, [s for s in preflight.REQUIRED_SKILLS
                                   if s not in preflight.BUILTIN_SKILLS])

    def test_project_skill_found(self):
        write(os.path.join(self.repo, ".claude", "skills", "e2e", "SKILL.md"))
        self.assertTrue(preflight.skill_installed("e2e", self.repo, self.config))

    def test_disabled_plugin_skill_not_found(self):
        self.install_all_skills()
        write(os.path.join(self.config, "settings.json"),
              json.dumps({"enabledPlugins": {"mattpocock-skills@official": False}}))
        self.assertFalse(preflight.skill_installed("mattpocock-skills:tdd", self.repo,
                                                   self.config))

    def test_required_skills_match_the_prompts(self):
        used = set()
        for name in os.listdir(PROMPTS_DIR):
            with open(os.path.join(PROMPTS_DIR, name), encoding="utf-8") as f:
                used |= set(SKILL_RE.findall(f.read()))
        self.assertEqual(used, set(preflight.REQUIRED_SKILLS))


class PreflightOkTest(unittest.TestCase):
    def test_prints_warnings_and_errors(self):
        err = io.StringIO()
        report = preflight.Report(errors=["`gh` not found on PATH"], warnings=["skill x"])
        self.assertFalse(cli.preflight_ok("plan", report, err))
        self.assertEqual(err.getvalue(), "engine plan: warning: skill x\n"
                                         "engine plan: `gh` not found on PATH\n")

    def test_warnings_alone_pass(self):
        err = io.StringIO()
        self.assertTrue(cli.preflight_ok("run", preflight.Report(warnings=["skill x"]), err))


if __name__ == "__main__":
    unittest.main()
