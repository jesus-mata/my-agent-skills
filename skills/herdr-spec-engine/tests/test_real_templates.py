"""End-to-end scenarios rendered with the REAL prompt templates (not the harness stub).

Any mismatch between the variables a stage passes and what its template expects (a missing
variable, a list or dict that was not formatted into text) fails here.
"""
import os
import re
import unittest

from spec_engine import prompts
from spec_engine.model import EngineStatus, Phase, RunStatus, Settings
from spec_engine.ports import MergeResult, ShellResult
from tests.engine_harness import BRANCH, GATE_FIXED, IMPLEMENTED, REVIEW_CLEAN, Harness, ticket

HARD = {"severity": "blocker", "title": "Race on save", "file": "src/save.py", "line": 3,
        "failure_scenario": "two saves at once lose the first write"}
E2E_OK = {"passed": ["export flow works"], "fixed": [{"title": "button label", "commit": "e2e1"}],
          "pending": [{"title": "emoji in CSV", "reason": "needs a product decision"}]}
CONFLICT = MergeResult(ok=False, conflict=True, commit=None, output="CONFLICT (content)")
REPR = re.compile(r"\{'|\['|<[a-zA-Z_.]+ object at")


class RealTemplateHarness(Harness):
    """The harness, but prompts come from ``prompts.render`` and every value must be text."""

    def render(self, name: str, **vars) -> str:
        for key, value in vars.items():
            if not isinstance(value, (str, int)) or isinstance(value, bool):
                raise AssertionError(f"{name}: ${key} is {type(value).__name__}, not text")
        text = prompts.render(name, **vars)  # a missing variable raises KeyError
        self.rendered.append((name, vars))
        self.texts.append((name, text))
        return text

    def text_of(self, name: str, index: int = 0) -> str:
        return [t for n, t in self.texts if n == name][index]


class RealTemplateScenarioTest(unittest.TestCase):
    def harness(self, tickets, **kw) -> RealTemplateHarness:
        h = RealTemplateHarness.__new__(RealTemplateHarness)
        h.texts = []
        Harness.__init__(h, tickets, **kw)
        self.addCleanup(h.cleanup)
        return h.start()

    def assert_prompt_hygiene(self, h: RealTemplateHarness) -> None:
        for name, text in h.texts:
            with self.subTest(template=name):
                self.assertNotRegex(text, REPR)
                self.assertIn("herdr-spec-engine for spec #7 (Spec seven)", text)
                self.assertIn("```json\n{", text)  # the example is JSON, not a Python dict

    def test_ticket_spec_review_hard_finding_fix_run_e2e_complete(self):
        h = self.harness([ticket(1, title="Export endpoint")])
        h.script_ticket("s7-ticket-1", review={
            "fixed": [], "scope_creep": ["renamed a helper"],
            "pending": [{"kind": "standards", "title": "long function", "reason": "wider refactor"}],
        })
        h.turn("s7-review", {"fixed": [{"severity": "high", "title": "Off by one",
                                            "commit": "abc1234"}],
                                 "hard": [HARD], "not_fixed": [{"severity": "low",
                                                                "title": "log wording"}]})
        h.turn("s7-fix-1", IMPLEMENTED, commits=1)
        h.turn("s7-fix-1", REVIEW_CLEAN)
        h.turn("s7-e2e", E2E_OK)
        h.run_until(lambda: h.state.status is EngineStatus.COMPLETE, max_ticks=80)

        self.assertEqual(h.templates(), ["implement", "review", "spec_review", "fix_implement",
                                         "fix_review", "e2e"])
        for name in ("implement", "review", "fix_implement", "fix_review"):
            self.assertIn("spec-wide rule", h.text_of(name))  # scope rules reach every agent
            self.assertIn("gh issue view 7", h.text_of(name))
        for name in ("review", "fix_review", "spec_review"):
            text = h.text_of(name)
            self.assertIn("goes in `follow_ups`", text)
            self.assertIn("Never open issues yourself", text)
            self.assertIn('"follow_ups": [{"category":', text)  # the example shows the shape
        self.assertIn("it reproduces on `main`", h.text_of("spec_review"))
        self.assert_prompt_hygiene(h)
        implement = h.text_of("implement")
        self.assertIn("ticket #1 (Export endpoint) on branch `s7-ticket-1`", implement)
        self.assertIn("Already integrated into `spec-7`:\n\nnone\n", implement)
        self.assertIn("/implement-ticket 1", implement)
        self.assertIn(f"`{h.run('s7-ticket-1').worktree}/.herdr-spec/s7-ticket-1.implement.json`",
                      implement)
        self.assertIn(f"`{BRANCH}` against `main`", h.text_of("spec_review"))
        for name in ("fix_implement", "fix_review"):
            text = h.text_of(name)
            self.assertIn("Race on save (blocker)\nFile: src/save.py:3\n"
                          "Failure scenario: two saves at once lose the first write", text)
        self.assertIn("branch `s7-fix-1`", h.text_of("fix_implement"))
        # /e2e has disable-model-invocation: it must arrive as a command on one short line,
        # with the rest of the prompt in a file beside the result file.
        sent = h.herdr.prompts["s7-e2e"][0]
        instructions = os.path.join(h.root, ".herdr-spec", "s7-e2e.e2e.prompt.md")
        self.assertEqual(sent, f"/e2e Your full instructions for this command are in "
                               f"{instructions} — read that whole file first and follow it.")
        with open(instructions) as f:
            body = f.read()
        self.assertEqual(body, h.text_of("e2e")[len("/e2e "):])
        self.assertIn(os.path.join(h.root, ".herdr-spec", "s7-e2e.e2e.json"), body)
        for name in ("implement", "review", "spec_review"):
            self.assertFalse(h.herdr.prompts[{"implement": "s7-ticket-1", "review": "s7-ticket-1",
                                              "spec_review": "s7-review"}[name]][0]
                             .startswith("/"), name)

        self.assertEqual(h.state.phase, Phase.COMPLETE)
        self.assertEqual(h.status("s7-fix-1"), RunStatus.DONE)
        with open(h.store.paths.report) as f:
            report = f.read()
        for expected in ("#1 Export endpoint — merged as", "pending [standards] long function",
                         "[high] Off by one (abc1234)", "Hard findings still pending (0)",
                         "[low] log wording", "s7-fix-1 Race on save — merged as",
                         "export flow works", "button label (e2e1)",
                         "emoji in CSV: needs a product decision",
                         "Spec branch `spec-7` is local; nothing was pushed."):
            self.assertIn(expected, report)

    def test_retry_verify_resolver_and_gate_prompts_render(self):
        h = self.harness([ticket(1, title="Alpha"), ticket(2, title="Beta"),
                          ticket(3, blockers=[1], title="Gamma")],
                         settings=Settings(max_agents=2))
        wt1 = os.path.join(h.herdr.worktree_root, "s7-ticket-1")
        wt3 = os.path.join(h.herdr.worktree_root, "s7-ticket-3")
        # s7-ticket-1: invalid result, then a valid one; then a clean review.
        h.turn("s7-ticket-1", "not json", commits=1)
        h.turn("s7-ticket-1", IMPLEMENTED)
        h.turn("s7-ticket-1", REVIEW_CLEAN)
        # s7-ticket-2: forgets to commit (verify_failed), then the gate fails once.
        h.turn("s7-ticket-2", IMPLEMENTED)
        h.turn("s7-ticket-2", IMPLEMENTED, commits=1)
        h.turn("s7-ticket-2", REVIEW_CLEAN)
        h.turn("s7-ticket-2", GATE_FIXED)
        h.shell.results["make test"] = [ShellResult(0, "ok"),
                                        ShellResult(2, "FAILED test_beta\n$HOME is unset"),
                                        ShellResult(0, "ok"), ShellResult(0, "ok")]
        # s7-ticket-3 starts after s7-ticket-1 merged; merging the spec branch conflicts.
        h.script_ticket("s7-ticket-3")
        h.git.script_merge(wt3, BRANCH, CONFLICT)
        h.git.set_unmerged(wt3, ["src/a.py", "src/b.py"])
        h.turn("s7-resolve-ticket-3", {"verdict": "RESOLVED", "summary": "kept both"},
               also=lambda: h.git.set_unmerged(wt3, []))
        h.turn("s7-review", {"fixed": [], "hard": [], "not_fixed": []})
        h.turn("s7-e2e", {"passed": [], "fixed": [], "pending": []})
        h.run_until(lambda: h.state.status is EngineStatus.COMPLETE, max_ticks=120)

        for name in ("implement", "result_retry", "verify_failed", "review", "gate_failed",
                     "resolver", "spec_review", "e2e"):
            self.assertIn(name, h.templates())
        self.assert_prompt_hygiene(h)
        self.assertIn("s7-ticket-1.implement.json: invalid JSON", h.text_of("result_retry"))
        self.assertIn("has no commits ahead of spec-7", h.text_of("verify_failed"))
        gate = h.text_of("gate_failed")
        self.assertIn("exit code 2", gate)
        self.assertIn("```\nmake test\n```", gate)
        self.assertIn("$HOME is unset", gate)  # output is substituted verbatim, never expanded
        resolver = h.text_of("resolver")
        self.assertIn("run `s7-ticket-3` on branch `s7-ticket-3`", resolver)
        self.assertIn("```\nsrc/a.py\nsrc/b.py\n```", resolver)
        self.assertIn("never run `git merge --abort`", resolver)
        implement3 = [t for n, t in h.texts if n == "implement" and "ticket #3" in t][0]
        self.assertIn("Already integrated into `spec-7`:\n\n- #1 Alpha (s7-ticket-1)\n\n", implement3)
        implement2 = [t for n, t in h.texts if n == "implement" and "ticket #2" in t][0]
        self.assertIn("Running in parallel in other worktrees (keep out of their way):\n\n"
                      "- #1 Alpha (s7-ticket-1)\n\n1.", implement2)
        self.assertNotIn(wt1, implement2)
        for n in (1, 2, 3):
            self.assertEqual(h.status(f"s7-ticket-{n}"), RunStatus.DONE)

    def test_fix_run_verify_failed_names_the_finding(self):
        h = self.harness([ticket(1)])
        h.script_ticket("s7-ticket-1")
        h.turn("s7-review", {"fixed": [], "hard": [HARD], "not_fixed": []})
        h.turn("s7-fix-1", IMPLEMENTED)  # forgets to commit
        h.turn("s7-fix-1", IMPLEMENTED, commits=1)
        h.turn("s7-fix-1", REVIEW_CLEAN)
        h.turn("s7-e2e", E2E_OK)
        h.run_until(lambda: h.state.status is EngineStatus.COMPLETE, max_ticks=80)
        self.assert_prompt_hygiene(h)
        self.assertIn('working on the spec review finding "Race on save" on branch `s7-fix-1`',
                      h.text_of("verify_failed"))


if __name__ == "__main__":
    unittest.main()
