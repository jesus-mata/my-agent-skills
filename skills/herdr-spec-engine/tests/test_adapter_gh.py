import json
import subprocess
import unittest
from unittest import mock

from spec_engine.adapters import gh_cli
from spec_engine.adapters.gh_cli import CliGitHub, GhError, parse_issue, repo_of
from spec_engine.ports import IssueRef

ISSUE_JSON = {
    "number": 12,
    "title": "Spec: payments",
    "state": "OPEN",
    "labels": [{"id": "L1", "name": "spec", "description": "", "color": "fff"},
               {"id": "L2", "name": "afk", "description": "", "color": "000"}],
    "url": "https://github.com/acme/app/issues/12",
    "subIssues": {"nodes": [
        {"id": "I1", "number": 13, "state": "OPEN", "title": "A",
         "url": "https://github.com/acme/app/issues/13"},
        {"id": "I2", "number": 14, "state": "CLOSED", "title": "B",
         "url": "https://github.com/acme/app/issues/14"},
    ], "totalCount": 2},
    "blockedBy": {"nodes": [
        {"id": "I3", "number": 7, "state": "OPEN", "title": "Other repo",
         "url": "https://github.com/acme/lib/issues/7"},
    ], "totalCount": 1},
}


def completed(stdout: str = "", stderr: str = "", code: int = 0):
    return subprocess.CompletedProcess(args=[], returncode=code, stdout=stdout, stderr=stderr)


class CliGitHubTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(gh_cli.subprocess, "run")
        self.run = patcher.start()
        self.addCleanup(patcher.stop)
        self.run.return_value = completed()
        self.gh = CliGitHub("/repo")

    def argv(self) -> list[str]:
        return self.run.call_args.args[0]

    def test_issue_parses_refs_and_cross_repo_blockers(self):
        self.run.return_value = completed(json.dumps(ISSUE_JSON))
        issue = self.gh.issue(12)
        self.assertEqual(self.argv(), ["gh", "issue", "view", "12", "--json",
                                       "number,title,state,labels,url,subIssues,blockedBy"])
        self.assertEqual(self.run.call_args.kwargs["cwd"], "/repo")
        self.assertEqual(issue.number, 12)
        self.assertEqual(issue.title, "Spec: payments")
        self.assertEqual(issue.state, "OPEN")
        self.assertEqual(issue.labels, ("spec", "afk"))
        self.assertEqual(issue.url, "https://github.com/acme/app/issues/12")
        self.assertEqual(issue.sub_issues, (
            IssueRef(13, "OPEN", "https://github.com/acme/app/issues/13", "acme/app"),
            IssueRef(14, "CLOSED", "https://github.com/acme/app/issues/14", "acme/app"),
        ))
        self.assertEqual(issue.blocked_by, (
            IssueRef(7, "OPEN", "https://github.com/acme/lib/issues/7", "acme/lib"),))

    def test_issue_with_empty_connections(self):
        data = {**ISSUE_JSON, "labels": [], "subIssues": {"nodes": [], "totalCount": 0},
                "blockedBy": {"nodes": [], "totalCount": 0}}
        self.run.return_value = completed(json.dumps(data))
        issue = self.gh.issue(12)
        self.assertEqual((issue.labels, issue.sub_issues, issue.blocked_by), ((), (), ()))

    def test_issue_not_found_raises_lookup_error(self):
        self.run.return_value = completed(
            stderr="GraphQL: Could not resolve to an issue or pull request with the number of 99.",
            code=1)
        with self.assertRaises(LookupError):
            self.gh.issue(99)

    def test_other_failures_raise_gh_error(self):
        self.run.return_value = completed(stderr="HTTP 502", code=1)
        with self.assertRaises(GhError):
            self.gh.issue(12)
        with self.assertRaises(GhError):
            self.gh.close(12)

    def test_assign_comment_close(self):
        self.gh.assign_self(5)
        self.assertEqual(self.argv(), ["gh", "issue", "edit", "5", "--add-assignee", "@me"])
        self.gh.comment(5, "multi\nline `body` $HOME")
        self.assertEqual(self.argv(), ["gh", "issue", "comment", "5", "--body-file", "-"])
        self.assertEqual(self.run.call_args.kwargs["input"], "multi\nline `body` $HOME")
        self.gh.close(5)
        self.assertEqual(self.argv(), ["gh", "issue", "close", "5"])

    def test_repo_of(self):
        self.assertEqual(repo_of("https://github.com/acme/lib/issues/7"), "acme/lib")
        self.assertEqual(repo_of("https://ghe.corp.example/team/svc/issues/1"), "team/svc")
        self.assertEqual(repo_of("https://github.com/acme/lib/pull/3"), "acme/lib")
        self.assertEqual(repo_of("not a url"), "")

    def test_parse_issue_accepts_bare_lists(self):
        issue = parse_issue({"number": 1, "title": "t", "state": "closed", "labels": ["x"],
                             "url": "https://github.com/o/r/issues/1",
                             "subIssues": [{"number": 2, "state": "open",
                                            "url": "https://github.com/o/r/issues/2"}],
                             "blockedBy": None})
        self.assertEqual(issue.state, "CLOSED")
        self.assertEqual(issue.labels, ("x",))
        self.assertEqual(issue.sub_issues[0].state, "OPEN")
        self.assertEqual(issue.blocked_by, ())


if __name__ == "__main__":
    unittest.main()
