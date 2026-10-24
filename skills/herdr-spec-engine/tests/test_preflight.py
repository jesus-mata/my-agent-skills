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
HEALTHY_INTEGRATION = ("pi: not installed (/h/.pi/x.ts)\n"
                       "claude: installed (v11) (/h/.claude/hooks/herdr-agent-state.sh)\n"
                       "codex: not installed (/h/.codex/x.sh)\n")
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

    def check(self, which=lambda tool: f"/bin/{tool}", authenticated=True,
              integration=HEALTHY_INTEGRATION):
        return preflight.check(self.repo, env=self.env, which=which,
                               gh_authenticated=lambda: authenticated,
                               integration_status=lambda: integration)

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

    def test_outdated_claude_integration_is_an_error(self):
        self.install_all_skills()
        report = self.check(integration="pi: not installed (/x)\n"
                                        "claude: outdated (v7 < v11) (/h/hook.sh)\n")
        self.assertEqual(len(report.errors), 1)
        self.assertIn("claude integration is outdated (v7 < v11)", report.errors[0])
        self.assertIn("herdr integration install claude", report.errors[0])

    def test_missing_claude_integration_is_an_error(self):
        self.install_all_skills()
        report = self.check(integration="claude: not installed (/h/hook.sh)\n")
        self.assertIn("claude integration is not installed", report.errors[0])

    def test_unreadable_integration_status_is_a_warning(self):
        self.install_all_skills()
        for status in (None, "pi: not installed (/x)\n"):
            report = self.check(integration=status)
            self.assertEqual(report.errors, [])
            self.assertEqual(len(report.warnings), 1)
            self.assertIn("herdr integration status", report.warnings[0])

    def test_integration_not_checked_without_herdr(self):
        self.install_all_skills()
        report = self.check(which=lambda tool: None if tool == "herdr" else f"/bin/{tool}",
                            integration=None)
        self.assertEqual(report.warnings, [])

    def test_skill_asked_for_in_text_must_allow_model_invocation(self):
        self.install_all_skills()
        write(os.path.join(self.config, "skills", "implement-ticket", "SKILL.md"),
              "---\nname: implement-ticket\ndisable-model-invocation: true\n---\nbody\n")
        write(os.path.join(self.config, "skills", "e2e", "SKILL.md"),
              "---\nname: e2e\ndisable-model-invocation: true\n---\nbody\n")
        report = self.check()
        self.assertEqual(report.errors, [])
        self.assertEqual(len(report.warnings), 1)  # e2e is sent as a command: allowed
        self.assertIn("`/implement-ticket` sets disable-model-invocation", report.warnings[0])

    def test_command_skills_are_the_templates_leading_commands(self):
        leading = set()
        for name in os.listdir(PROMPTS_DIR):
            with open(os.path.join(PROMPTS_DIR, name), encoding="utf-8") as f:
                m = re.match(r"/([a-z][a-z0-9:-]*)", f.read())
            if m:
                leading.add(m.group(1))
        self.assertEqual(leading, set(preflight.COMMAND_SKILLS))

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
