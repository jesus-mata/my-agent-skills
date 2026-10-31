# implement-ticket

Takes one ticket from code to an open MR. Merging stays with you.

## What it does

The stages run in this order, and the first one that can't be resolved ends the run:

1. **Branch:** stays on the current worktree or feature branch, otherwise creates a worktree from
   the up to date default branch.
2. **Develop:** runs `/develop-ticket` and continues only on `RESULT: PASS`.
3. **E2E:** runs `/e2e` in a new sub-agent against every acceptance criterion, then fixes what
   fails. It is skipped when the change has no visible behaviour on a web, API, CLI or desktop
   surface, or the repo has no `E2E.md`.
4. **Spec review:** runs `/mattpocock-skills:code-review`.
5. **Code review:** runs `/run-review`.
6. **Fix:** fixes every Spec gap, hard Standards violation, Critical and High, then validates, and
   re-runs `/e2e` if the fixes changed code, unless it was skipped.
7. **Open the MR:** pushes the branch and opens a PR/MR with `Closes #<n>` and any criteria E2E
   could not verify.

E2E runs before the reviews because the reviews run only once, so this is the order in which the
E2E fixes still get reviewed, and the E2E re-run in step 6 covers the review fixes.

Every E2E run is a new sub-agent, so the tester has no memory of writing the code and its output
stays out of the main context. It only tests and reports, editing nothing beyond `E2E.md`, its
helper and its own ephemeral spec. The main agent fixes and commits. Each run gets the criteria
from `/develop-ticket` and the previous failures, covers every criterion, and must show that the
service under test runs this worktree's current code. It stops the services it started, and first
confirms the target is not production.

## How to use it

```
/implement-ticket 42
```

Only you can start it: the model never invokes it on its own. Inside a Herdr session, use
`/work-ticket` instead.

It needs an authenticated `gh` or `glab`, `/mattpocock-skills:code-review`, and Claude Code's
built-in `/code-review`, which `/run-review` calls.

The run ends with a report of each stage, any open findings and what needs you, and a last line
of `RESULT: PASS`, `FAIL` or `BLOCKED`. `PASS` means every stage passed or was skipped and the MR
exists. `/e2e` gets at most 3 re-runs per ticket; after that the run ends `BLOCKED` with no MR.

An E2E run also ends the ticket `BLOCKED`, with no MR, when the environment stops it or the target
can't be shown to be safe. That includes a stale service under test that can't start on another
port. To unblock it, stop your dev server or add the service's port override to `E2E.md`. A startup
failure caused by the ticket's own code is a `FAIL`, which gets fixed.

A criterion that can't be exercised end to end is `NOT VERIFIABLE`. It doesn't stop the MR or the
`PASS`, but it is listed in the MR body and on the report's `Needs human` line, so verify it
yourself before merging.
