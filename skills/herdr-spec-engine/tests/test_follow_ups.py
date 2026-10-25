import unittest

from spec_engine import follow_ups
from spec_engine.model import Plan, Run, RunKind
from spec_engine.ports import OpenIssue
from tests.fakes import FakeGitHub


def finding(title, file="src/a.py", category="pre-existing", severity="high", **kw):
    return {"category": category, "severity": severity, "title": title, "file": file,
            "line": kw.pop("line", 3), "problem": f"{title} breaks", "why_separate": "predates",
            "evidence": "git blame", "acceptance": kw.pop("acceptance", ["It works"]), **kw}


def reviewed(kind, run_id, *found):
    run = Run.new(kind, run_id)
    run.review = {"fixed": [], "follow_ups": list(found)}
    return run


PLAN = Plan(spec=7, title="Spec seven", branch="spec-7")


class CollectTest(unittest.TestCase):
    def test_merges_duplicates_across_reviews_and_marks_open_issues(self):
        runs = [
            reviewed(RunKind.TICKET, "s7-ticket-1", finding("Session never expires"),
                     finding("Locale ignored", category="needs-decision")),
            Run.new(RunKind.E2E, "s7-e2e"),
            reviewed(RunKind.SPEC_REVIEW, "s7-review",
                     finding("Session  never expires!"),  # same file, same normalized title
                     finding("Session never expires", file="src/b.py"),
                     finding("Old cache leak", category="tech-debt")),
            reviewed(RunKind.FIX, "s7-fix-1", finding("Locale ignored",
                                                      category="needs-decision")),
        ]
        entries = follow_ups.collect(runs, [OpenIssue(9, "old cache LEAK", "u9")])
        self.assertEqual([(e["id"], e["title"], e["file"], e["found_by"], e["state"])
                          for e in entries], [
            ("f1", "Session never expires", "src/a.py", ["s7-ticket-1", "s7-review"], "proposed"),
            ("f2", "Locale ignored", "src/a.py", ["s7-ticket-1", "s7-fix-1"], "proposed"),
            ("f3", "Session never expires", "src/b.py", ["s7-review"], "proposed"),
            ("f4", "Old cache leak", "src/a.py", ["s7-review"], "already_open"),
        ])
        self.assertEqual(entries[3]["issue"], {"number": 9, "url": "u9"})
        self.assertEqual([e["id"] for e in follow_ups.proposed(entries)], ["f1", "f2", "f3"])

    def test_runs_without_follow_ups_yield_nothing(self):
        run = Run.new(RunKind.TICKET, "s7-ticket-1")
        run.review = {"fixed": [], "pending": [], "scope_creep": []}
        self.assertEqual(follow_ups.collect([run, Run.new(RunKind.FIX, "s7-fix-1")], []), [])

    def test_details_list_every_entry_and_the_actions(self):
        entries = follow_ups.collect(
            [reviewed(RunKind.SPEC_REVIEW, "s7-review", finding("Leak"), finding("Debt"))],
            [OpenIssue(9, "Debt", "u9")])
        text = follow_ups.details(entries)
        self.assertIn("f1 [high] pre-existing: Leak (src/a.py:3) — found by s7-review", text)
        self.assertIn("    why separate: predates", text)
        self.assertIn("f2 [high] pre-existing: Debt (src/a.py:3) — found by s7-review\n"
                      "    already open as #9: not created again", text)
        self.assertIn("create-all creates f1; create-selected creates only the ids in --note "
                      "(e.g. --note \"f1\"); discard creates none.", text)


class SelectionTest(unittest.TestCase):
    def setUp(self):
        self.entries = follow_ups.collect(
            [reviewed(RunKind.SPEC_REVIEW, "s7-review", finding("A"), finding("B"),
                      finding("C"))], [OpenIssue(9, "C", "u9")])

    def test_ids_in_any_separator_deduplicated(self):
        self.assertEqual(follow_ups.parse_selection("f2, f1 f2", self.entries),
                         (["f2", "f1"], None))

    def test_errors(self):
        for note, error in (("", "needs the follow-up ids"), ("all", "needs the follow-up ids"),
                            ("f1 f7", "unknown follow-up ids: f7"),
                            ("f3", "not proposed for creation: f3")):
            with self.subTest(note=note):
                ids, problem = follow_ups.parse_selection(note, self.entries)
                self.assertEqual(ids, [])
                self.assertIn(error, problem)


class CreateTest(unittest.TestCase):
    def test_creates_the_chosen_ones_and_discards_the_rest(self):
        entries = follow_ups.collect([reviewed(
            RunKind.SPEC_REVIEW, "s7-review", finding("A"),
            finding("B", category="needs-decision"), finding("C"))], [])
        gh = FakeGitHub()
        follow_ups.create(gh, PLAN, entries, ["f2", "f1"])
        self.assertEqual([(c["title"], c["labels"]) for c in gh.created],
                         [("A", []), ("B", ["ready-for-human"])])
        self.assertEqual([e["state"] for e in entries], ["created", "created", "discarded"])
        self.assertEqual(entries[0]["issue"]["number"], gh.created[0]["number"])

    def test_a_retry_after_a_failure_never_creates_twice(self):
        entries = follow_ups.collect(
            [reviewed(RunKind.SPEC_REVIEW, "s7-review", finding("A"), finding("B"))], [])
        gh = FakeGitHub()
        original = gh.create_issue
        calls = []

        def flaky(title, body, labels):
            calls.append(title)
            if title == "B" and calls.count("B") == 1:
                raise RuntimeError("HTTP 502")
            return original(title, body, labels)

        gh.create_issue = flaky
        with self.assertRaises(RuntimeError):
            follow_ups.create(gh, PLAN, entries, None)
        self.assertEqual([e["state"] for e in entries], ["created", "proposed"])
        follow_ups.create(gh, PLAN, entries, None)
        self.assertEqual([c["title"] for c in gh.created], ["A", "B"])

    def test_issue_body(self):
        entry = follow_ups.collect([reviewed(RunKind.TICKET, "s7-ticket-1", finding(
            "Leak", category="out-of-scope", line=None, acceptance=["No leak", "A test"]))],
            [])[0]
        body = follow_ups.issue_body(entry, PLAN)
        for expected in (
            "Follow-up from spec #7 (Spec seven), found by herdr-spec-engine (s7-ticket-1).",
            "**Category:** out-of-scope (fixing it would break a scope rule of the spec)",
            "**Severity:** high", "**Where:** `src/a.py`",
            "## Problem\n\nLeak breaks", "## Why a separate issue\n\npredates",
            "## Evidence\n\ngit blame", "## Acceptance criteria\n\n- [ ] No leak\n- [ ] A test",
        ):
            self.assertIn(expected, body)

    def test_deferred_medium_finding_is_created_without_labels(self):
        entries = follow_ups.collect([reviewed(RunKind.SPEC_REVIEW, "s7-review", finding(
            "Slow list", category="deferred", severity="medium"))], [])
        gh = FakeGitHub()
        follow_ups.create(gh, PLAN, entries, None)
        [created] = gh.created
        self.assertEqual(created["labels"], [])
        self.assertIn("**Category:** deferred (a medium finding the review chose not to fix in "
                      "this spec)", created["body"])
        self.assertIn("**Severity:** medium", created["body"])


if __name__ == "__main__":
    unittest.main()


class ApplyDedupTest(unittest.TestCase):
    def entries(self):
        return [{"id": "f1", "title": "A", "found_by": ["s7-ticket-1"], "state": "proposed",
                 "issue": None},
                {"id": "f2", "title": "B", "found_by": ["s7-review"], "state": "already_open",
                 "issue": {"number": 5, "url": "u5"}},
                {"id": "f3", "title": "C", "found_by": ["s7-review"], "state": "proposed",
                 "issue": None}]

    def test_unknown_and_not_proposed_ids_are_ignored(self):
        from spec_engine.ports import OpenIssue
        entries = self.entries()
        seen = []

        def open_issue(n):
            seen.append(n)
            return OpenIssue(n, "t", f"u{n}")

        notes = follow_ups.apply_dedup(entries, {"matches": [
            {"id": "f9", "verdict": "COVERED", "issue": 7, "reason": ""},
            {"id": "f2", "verdict": "COVERED", "issue": 8, "reason": ""},
            {"id": "f3", "verdict": "NEW", "issue": None, "reason": ""}],
            "duplicates": [["f2", "f3"], ["f9", "f1"]]}, open_issue)
        self.assertEqual((notes, seen), ([], []))
        self.assertEqual([(e["id"], e["state"]) for e in entries],
                         [("f1", "proposed"), ("f2", "already_open"), ("f3", "proposed")])

    def test_duplicates_keep_the_first_and_merge_found_by(self):
        entries = self.entries()
        entries[1]["state"] = "proposed"
        follow_ups.apply_dedup(entries, {"matches": [], "duplicates": [["f3", "f1", "f2"]]},
                               lambda n: None)
        self.assertEqual([e["id"] for e in entries], ["f3"])
        self.assertEqual(entries[0]["found_by"], ["s7-review", "s7-ticket-1"])
        self.assertEqual(entries[0]["also"], ["f1 A", "f2 B"])
