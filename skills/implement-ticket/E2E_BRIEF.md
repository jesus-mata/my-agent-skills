Invoke the /e2e skill on this worktree, without --keep, against these acceptance criteria of ticket #<n>. They are the full list:
<criteria from /develop-ticket's report>

If the skill is unavailable, the run is BLOCKED.

Your tests must reproduce these failures from the previous run:
<the previous report's Failures block, or none>

First confirm the target is not production: the base URLs and database hosts in E2E.md are local or a declared test environment, and the accounts are its test users. If you cannot show the target is safe, the run is BLOCKED.

You test and report; the caller fixes and commits. You may edit E2E.md and its helper module, and write your ephemeral spec in the test directory, deleting it before you report. Evidence goes outside the repo or in a gitignored path. When a test fails through your own mistake, such as a bad selector or missing seed, correct it and run again.

Test this worktree's current code. A service running the code under test must be proven current: its working directory is this worktree, and it reloads on change or started after the last commit. If one you did not start fails that proof, start your own on another port E2E.md documents; with none documented, the run is BLOCKED. Reuse running dependencies such as databases. Before you report, stop every service you started. Services you did not start stay running.

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

An AC is FAIL when the code is wrong, including a startup failure caused by this change, and NOT VERIFIABLE when it cannot be exercised end to end. The last line is RESULT: BLOCKED, with the reason, if the target or the environment stopped the run. Otherwise it is RESULT: FAIL if any AC is FAIL, otherwise RESULT: PASS.
