import json
import os
import tempfile
import unittest

from spec_engine import results

GOOD = {name: json.loads(results.example(name)) for name in results.SCHEMAS}


def bad(name, **changes):
    d = json.loads(results.example(name))
    for k, v in changes.items():
        if v is KeyError:
            d.pop(k)
        else:
            d[k] = v
    return d


class ResultsTest(unittest.TestCase):
    def assertInvalid(self, name, data, *fragments):
        value, error = results.SCHEMAS[name](data)
        self.assertIsNone(value)
        self.assertIsInstance(error, str)
        for frag in fragments:
            self.assertIn(frag, error)

    def test_schema_names(self):
        self.assertEqual(set(results.SCHEMAS),
                         {"implement", "review", "gate_fix", "resolve", "spec_review", "e2e",
                          "dedup"})

    def test_examples_pass_their_validator(self):
        for name, data in GOOD.items():
            with self.subTest(name=name):
                self.assertEqual(results.SCHEMAS[name](data), (data, None))

    def test_follow_ups_are_optional_and_checked(self):
        for name in ("review", "spec_review"):
            with self.subTest(name=name):
                good = bad(name, follow_ups=KeyError)
                self.assertEqual(results.SCHEMAS[name](good), (good, None))
                entry = GOOD[name]["follow_ups"][0]
                self.assertInvalid(name, bad(name, follow_ups=[{**entry, "category": "bug"}]),
                                   f"{name}.follow_ups[0].category", "'pre-existing'")
                self.assertInvalid(name, bad(name, follow_ups=[{**entry, "severity": "low"}]),
                                   f"{name}.follow_ups[0].severity", "'medium'")
                no_why = {k: v for k, v in entry.items() if k != "why_separate"}
                self.assertInvalid(name, bad(name, follow_ups=[no_why]),
                                   f"{name}.follow_ups[0].why_separate", "missing")
                self.assertInvalid(name, bad(name, follow_ups=[{**entry, "acceptance": "x"}]),
                                   f"{name}.follow_ups[0].acceptance", "list")

    def test_empty_lists_and_unknown_keys_allowed(self):
        ok = {"fixed": [], "pending": [], "scope_creep": [], "extra": 1}
        self.assertEqual(results.validate_review(ok)[1], None)

    def test_not_an_object(self):
        for name in results.SCHEMAS:
            self.assertInvalid(name, [], f"{name}: expected an object, got list")

    def test_implement(self):
        self.assertInvalid("implement", bad("implement", status="done"), "implement.status",
                           "'implemented'", "'done'")
        self.assertInvalid("implement", bad("implement", summary=KeyError), "implement.summary",
                           "missing")
        self.assertInvalid("implement", bad("implement", denied_actions=["a", 3]),
                           "implement.denied_actions[1]", "string")
        self.assertInvalid("implement", bad("implement", denied_actions="x"),
                           "implement.denied_actions", "list")

    def test_review(self):
        self.assertInvalid("review", bad("review", fixed=[{"kind": "bug", "title": "t",
                                                           "commit": "c"}]),
                           "review.fixed[0].kind", "'spec'")
        self.assertInvalid("review", bad("review", pending=[{"kind": "spec", "title": "t"}]),
                           "review.pending[0].reason", "missing")
        self.assertInvalid("review", bad("review", fixed=["x"]), "review.fixed[0]", "object")
        self.assertInvalid("review", bad("review", scope_creep=KeyError), "review.scope_creep")
        self.assertInvalid("review", bad("review", dismissed=[{"kind": "spec", "title": "t"}]),
                           "review.dismissed[0].reason", "missing")
        self.assertInvalid("review", bad("review", dismissed="x"), "review.dismissed", "list")

    def test_review_dismissed_is_optional_and_defaults_to_empty(self):
        old = bad("review", dismissed=KeyError)
        value, error = results.validate_review(old)
        self.assertIsNone(error)
        self.assertEqual(value.get("dismissed", []), [])

    def test_gate_fix(self):
        self.assertInvalid("gate_fix", {"summary": 3}, "gate_fix.summary", "integer")
        self.assertInvalid("gate_fix", {}, "gate_fix.summary", "missing")

    def test_resolve(self):
        self.assertInvalid("resolve", bad("resolve", verdict="resolved"), "resolve.verdict",
                           "'RESOLVED'")
        self.assertEqual(results.validate_resolve({"verdict": "ESCALATE", "summary": ""})[1], None)

    def test_spec_review(self):
        hard = GOOD["spec_review"]["hard"][0]
        self.assertInvalid("spec_review", bad("spec_review", hard=[{**hard, "line": "42"}]),
                           "spec_review.hard[0].line", "integer or null")
        self.assertInvalid("spec_review", bad("spec_review", hard=[{**hard, "line": True}]),
                           "spec_review.hard[0].line")
        self.assertEqual(results.validate_spec_review(
            bad("spec_review", hard=[{**hard, "line": None}]))[1], None)
        self.assertInvalid("spec_review",
                           bad("spec_review", not_fixed=[{"severity": "high", "title": "t"}]),
                           "spec_review.not_fixed[0].severity", "'medium'")
        self.assertInvalid("spec_review",
                           bad("spec_review", fixed=[{"severity": "low", "title": "t",
                                                      "commit": "c"}]),
                           "spec_review.fixed[0].severity")
        self.assertInvalid("spec_review",
                           bad("spec_review", not_fixed=[{"severity": "low", "title": "t",
                                                          "reason": 1}]),
                           "spec_review.not_fixed[0].reason", "string")
        no_scenario = {k: v for k, v in hard.items() if k != "failure_scenario"}
        self.assertInvalid("spec_review", bad("spec_review", hard=[no_scenario]),
                           "spec_review.hard[0].failure_scenario", "missing")

    def test_e2e(self):
        self.assertInvalid("e2e", bad("e2e", fixed=[{"title": "t"}]), "e2e.fixed[0].commit")
        self.assertInvalid("e2e", bad("e2e", pending=[{"title": "t", "reason": None}]),
                           "e2e.pending[0].reason", "null")
        self.assertInvalid("e2e", bad("e2e", verdict="OK"), "e2e.verdict", "'PARTIAL'")
        self.assertInvalid("e2e", bad("e2e", collateral=KeyError), "e2e.collateral", "missing")
        ac = GOOD["e2e"]["acs"][0]
        self.assertInvalid("e2e", bad("e2e", acs=[{**ac, "ticket": "12"}]),
                           "e2e.acs[0].ticket", "integer")
        self.assertInvalid("e2e", bad("e2e", acs=[{**ac, "derived": "no"}]),
                           "e2e.acs[0].derived", "true or false")
        self.assertInvalid("e2e", bad("e2e", acs=[{**ac, "verdict": "SKIPPED"}]),
                           "e2e.acs[0].verdict")
        collateral = GOOD["e2e"]["collateral"][0]
        self.assertInvalid("e2e", bad("e2e", collateral=[{**collateral, "action": "ignored"}]),
                           "e2e.collateral[0].action")
        self.assertInvalid("e2e", bad("e2e", notes=[1]), "e2e.notes[0]")

    def test_e2e_verdict_must_add_up(self):
        ok, failed, nv = ({"ticket": 1, "ac": "AC1", "criterion": "c", "derived": False,
                           "verdict": v, "evidence": "e"} for v in ("PASS", "FAIL", "NOT VERIFIABLE"))
        for acs, verdict in (([ok], "PASS"), ([ok, nv], "PARTIAL"), ([nv, failed], "FAIL")):
            self.assertIsNone(results.validate_e2e(bad("e2e", acs=acs, verdict=verdict))[1])
            for other in ("PASS", "FAIL", "PARTIAL"):
                if other != verdict:
                    self.assertInvalid("e2e", bad("e2e", acs=acs, verdict=other),
                                       f"add up to {verdict!r}")
        self.assertInvalid("e2e", bad("e2e", acs=[], verdict="PASS"), "e2e.acs", "BLOCKED")
        self.assertInvalid("e2e", bad("e2e", acs=[], verdict="BLOCKED", blocked_by=" "),
                           "e2e.blocked_by")
        self.assertIsNone(results.validate_e2e(
            bad("e2e", acs=[], verdict="BLOCKED", blocked_by="no E2E.md"))[1])


class ReadResultTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, ".herdr-spec", "s7-ticket-1.implement.json")
        os.makedirs(os.path.dirname(self.path))

    def write(self, text):
        with open(self.path, "w") as f:
            f.write(text)

    def test_missing(self):
        value, error = results.read_result(self.path, "implement")
        self.assertIsNone(value)
        self.assertIn(self.path, error)
        self.assertIn("not found", error)

    def test_bad_json(self):
        self.write("{nope")
        value, error = results.read_result(self.path, "implement")
        self.assertIsNone(value)
        self.assertIn(self.path, error)
        self.assertIn("invalid JSON", error)

    def test_schema_error(self):
        self.write(json.dumps({"status": "implemented", "summary": "s"}))
        value, error = results.read_result(self.path, "implement")
        self.assertIsNone(value)
        self.assertIn(self.path, error)
        self.assertIn("implement.denied_actions", error)

    def test_valid(self):
        self.write(results.example("implement"))
        self.assertEqual(results.read_result(self.path, "implement"), (GOOD["implement"], None))


if __name__ == "__main__":
    unittest.main()
