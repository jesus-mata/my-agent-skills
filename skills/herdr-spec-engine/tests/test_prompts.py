import os
import re
import unittest
from string import Template

from spec_engine import prompts, results

COMMON = ("spec", "spec_title", "result_path", "result_example")

# design.md "Prompts": template -> its variables besides COMMON, and the result schema it asks for
DOCUMENTED = {
    "implement": (("ticket", "ticket_title", "branch", "spec_branch", "integrated", "siblings"),
                  "implement"),
    "verify_failed": (("ticket", "branch", "spec_branch", "problem"), "implement"),
    "review": (("ticket", "spec_branch"), "review"),
    "result_retry": (("error",), "review"),
    "gate_failed": (("command", "exit_code", "output"), "gate_fix"),
    "resolver": (("run_id", "branch", "spec_branch", "conflicts"), "resolve"),
    "spec_review": (("spec_branch", "base"), "spec_review"),
    "fix_implement": (("branch", "spec_branch", "finding"), "implement"),
    "fix_review": (("spec_branch", "finding"), "review"),
    "e2e": (("spec_branch", "tickets", "not_integrated"), "e2e"),
    "dedup": (("candidates",), "dedup"),
}

RESULT_PATH = "/repo/wt/s7-ticket-12/.herdr-spec/s7-ticket-12.implement.json"
STRAY = re.compile(r"\$(\{|[A-Za-z_])")


def variables(name):
    extra, schema = DOCUMENTED[name]
    v = {
        "spec": 7,
        "spec_title": "Reporting exports",
        "result_path": RESULT_PATH,
        "result_example": results.example(schema),
    }
    for key in extra:
        v[key] = f"<{key}-value>"
    return v


def used_identifiers(name):
    with open(prompts.template_path(name), encoding="utf-8") as f:
        text = f.read()
    names = set()
    for m in Template.pattern.finditer(text):
        ident = m.group("named") or m.group("braced")
        if ident:
            names.add(ident)
        elif m.group("invalid") is not None:
            raise AssertionError(f"{name}: invalid $ placeholder at offset {m.start()}")
    return names


class TemplateSetTest(unittest.TestCase):
    def test_documented_table_covers_every_template(self):
        self.assertEqual(set(DOCUMENTED), set(prompts.TEMPLATE_NAMES))

    def test_every_template_file_exists(self):
        for name in prompts.TEMPLATE_NAMES:
            self.assertTrue(os.path.isfile(prompts.template_path(name)), name)


class RenderTest(unittest.TestCase):
    def test_renders_with_documented_variables(self):
        for name in prompts.TEMPLATE_NAMES:
            with self.subTest(name):
                prompts.render(name, **variables(name))

    def test_uses_exactly_the_documented_variables(self):
        for name in prompts.TEMPLATE_NAMES:
            with self.subTest(name):
                self.assertEqual(used_identifiers(name), set(COMMON) | set(DOCUMENTED[name][0]))

    def test_contains_result_path_and_example(self):
        for name in prompts.TEMPLATE_NAMES:
            with self.subTest(name):
                v = variables(name)
                text = prompts.render(name, **v)
                self.assertIn(RESULT_PATH, text)
                self.assertIn(v["result_example"], text)

    def test_no_stray_placeholders(self):
        for name in prompts.TEMPLATE_NAMES:
            with self.subTest(name):
                text = prompts.render(name, **variables(name))
                self.assertIsNone(STRAY.search(text), STRAY.search(text))

    def test_states_sub_instance_and_guardrails(self):
        for name in prompts.TEMPLATE_NAMES:
            with self.subTest(name):
                text = prompts.render(name, **variables(name))
                self.assertIn("sub Claude instance started by herdr-spec-engine for spec #7", text)
                self.assertIn("Reporting exports", text)
                self.assertIn("Never push", text)
                self.assertIn("not done until", text)

    def test_every_variable_appears_in_output(self):
        for name in prompts.TEMPLATE_NAMES:
            with self.subTest(name):
                v = variables(name)
                text = prompts.render(name, **v)
                for key in DOCUMENTED[name][0]:
                    self.assertIn(v[key], text, key)

    def test_missing_variable_raises(self):
        v = variables("implement")
        del v["ticket"]
        with self.assertRaises(KeyError):
            prompts.render("implement", **v)


class ContentTest(unittest.TestCase):
    def render(self, name, **overrides):
        v = variables(name)
        v.update(overrides)
        return prompts.render(name, **v)

    def test_result_retry_includes_error(self):
        err = "review.fixed[0].commit: missing required field"
        self.assertIn(err, self.render("result_retry", error=err))

    def test_gate_failed_includes_command_code_and_output(self):
        text = self.render("gate_failed", command="pnpm run test", exit_code=2,
                           output="FAIL src/export.test.ts\n  expected 3, got 4")
        self.assertIn("pnpm run test", text)
        self.assertIn("exit code 2", text)
        self.assertIn("expected 3, got 4", text)

    def test_skill_invocations_carried_over(self):
        expected = {
            "implement": ["/develop-ticket <ticket-value>", "outward-denied", "denied_actions"],
            "review": ["/mattpocock-skills:code-review <spec_branch-value>",
                       "/mattpocock-skills:tdd", "scope_creep", "`dismissed`",
                       "never in `pending`", "is not a finding", "`follow_ups`"],
            "fix_review": ["/mattpocock-skills:code-review <spec_branch-value>",
                           "/mattpocock-skills:tdd", "`dismissed`", "is not a finding",
                           "`follow_ups`"],
            "resolver": ["hunk by hunk", "keeping both intents", "ESCALATE", "RESOLVED"],
            "spec_review": ["/code-review high", "against `<base-value>`",
                            "/mattpocock-skills:tdd", "Never create worktrees",
                            "scope rule", "`out-of-scope`", "Never open issues yourself"],
            "fix_implement": ["/mattpocock-skills:tdd", "outward-denied", "denied_actions"],
            "e2e": ["/e2e", "E2E.md", "not production", "Never create worktrees",
                    "/mattpocock-skills:tdd", "cold stack", "NOT VERIFIABLE", "TEARDOWN"],
        }
        for name, needles in expected.items():
            text = self.render(name)
            for needle in needles:
                with self.subTest(name=name, needle=needle):
                    self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()


class SplitCommandTest(unittest.TestCase):
    def test_leading_command_is_split_from_the_rest(self):
        self.assertEqual(prompts.split_command("/e2e You are a sub Claude.\n\n1. Read it."),
                         ("/e2e", "You are a sub Claude.\n\n1. Read it."))
        self.assertEqual(prompts.split_command("/mattpocock-skills:tdd\nfix it"),
                         ("/mattpocock-skills:tdd", "fix it"))

    def test_text_without_a_leading_command_is_not_split(self):
        for text in ("Run `/e2e` now", " /e2e indented", "/ not a command", "path /e2e"):
            self.assertIsNone(prompts.split_command(text), text)

    def test_command_line_is_one_line(self):
        line = prompts.command_line("/e2e", "/repo/.herdr-spec/s7-e2e.e2e.prompt.md")
        self.assertNotIn("\n", line)
        self.assertTrue(line.startswith("/e2e Your full instructions"))
        self.assertIn("/repo/.herdr-spec/s7-e2e.e2e.prompt.md", line)

    def test_only_the_e2e_template_starts_with_a_command(self):
        starts = {name: prompts.split_command(open(prompts.template_path(name)).read())
                  for name in prompts.TEMPLATE_NAMES}
        self.assertEqual({n for n, s in starts.items() if s}, {"e2e"})
        self.assertEqual(starts["e2e"][0], "/e2e")
