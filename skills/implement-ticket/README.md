# implement-ticket

Takes one ticket from code to an open MR. Merging stays with you.

## What it does

The stages run in this order, and the first one that can't be resolved ends the run:

1. **Branch:** stays on the current worktree or feature branch, otherwise creates a worktree from
   the up to date default branch.
2. **Develop:** runs `/develop-ticket` and continues only on `RESULT: PASS`.
3. **E2E:** runs `/e2e` against every acceptance criterion, and fixes what fails. It is skipped when
   the change has no visible behaviour on a web, API, CLI or desktop surface, or the repo has no
   `E2E.md`.
4. **Spec review:** runs `/mattpocock-skills:code-review`.
5. **Code review:** runs `/run-review`.
6. **Fix:** fixes every Spec gap, hard Standards violation, Critical and High, then validates, and
   re-runs `/e2e` unless it was skipped.
7. **Open the MR:** pushes the branch and opens a PR/MR with `Closes #<n>`.

E2E runs before the reviews because the reviews run only once, so this is the order in which the
E2E fixes still get reviewed, and the E2E re-run in step 6 covers the review fixes.

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
