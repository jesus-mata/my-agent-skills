Invoke the /e2e skill on this worktree, without --keep, against these acceptance criteria of ticket #<n>. They are the full list:
<criteria from /develop-ticket's report>

If the skill is unavailable, the run is BLOCKED.

Your tests must reproduce these failures from the previous run:
<the previous report's Failures block, or none>

You test and report; the caller fixes and commits. You may edit E2E.md and its helper module, and write your ephemeral spec in the test directory, deleting it before you report. Evidence goes outside the repo or in a gitignored path.

Before you report, stop every service you started. Services you did not start stay running.

End with this report as your final message, listing Failures only when an AC is FAIL:

```
AC1: <PASS | FAIL | NOT VERIFIABLE> <evidence file path, or what is missing>
AC2: ...

Failures:
- AC<n>: <steps to reproduce>
  Expected: <behaviour>
  Actual: <behaviour>
  Likely location: <file:line>

RESULT: PASS
```

The last line is RESULT: BLOCKED, with the reason, if the skill's run is BLOCKED. Otherwise it is RESULT: FAIL if any AC is FAIL, otherwise RESULT: PASS.
