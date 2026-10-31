---
name: implement-ticket
description: "Takes a ticket from code to MR: develops it, E2E-tests it, runs spec and code review, fixes what they find, then opens an MR against the default branch."
argument-hint: <issue-number>
disable-model-invocation: true
---

# Implement ticket

Take ticket $ARGUMENTS through every stage in order. At the first stage you cannot resolve, go straight to _Report_. Merging belongs to the human.

## Steps

1. **Branch.** If you are in a worktree or on a feature branch, stay there. Otherwise create a worktree from the up to date default branch. `<base>` is `git merge-base HEAD origin/<default-branch>` after a fetch, so the reviews cover exactly what the MR will contain.
2. **Develop.** Run `/develop-ticket <n>`. Continue only on `RESULT: PASS`.
3. **E2E.** Follow _E2E run_ when the change alters behaviour visible through a web, API, CLI or desktop surface and the repo has an `E2E.md`. Otherwise record `SKIPPED: <reason>`.
4. **Spec review.** Run `/mattpocock-skills:code-review <base>` and collect its findings.
5. **Code review.** Run `/run-review <base>...HEAD` and collect its findings. `RESULT: BLOCKED` ends the run.
6. **Fix** every Spec gap, hard Standards violation, Critical and High. Then repeat `/develop-ticket`'s Validate and Commit steps. If this step changed code and E2E was not `SKIPPED`, follow _E2E run_ again. Done when none of those remain and validation and E2E are green on the final code; the reviews do not re-run.
7. **Open the MR.** Push the branch and open a PR/MR against the default branch with `gh` or `glab`, by the origin remote, with `Closes #<n>` and any `NOT VERIFIABLE` criteria in its body.

## E2E run

Each run is a new `general-purpose` sub-agent in this worktree, so the tester has no memory of writing the code and its noise stays out of this context. Spawn it with [E2E_BRIEF.md](E2E_BRIEF.md) as its prompt, placeholders filled. It may run in the background; these steps resume when its report arrives.

- After every run, commit what it changed in `E2E.md` or its helper.
- On `RESULT: FAIL`, fix what failed, repeat `/develop-ticket`'s Validate and Commit steps, and spawn another run.
- A ticket gets at most 3 re-runs in total, across steps 3 and 6.
- If a run ends `RESULT: BLOCKED`, or a re-run is due with none left, go straight to _Report_ with no MR, and hand it to the human on the `Needs human` line.

Done when a run ends `RESULT: PASS`.

## Report

```
Ticket: #<n>   MR: <url or none>

Develop: <PASS | FAIL | BLOCKED>
E2E: <PASS | FAIL | BLOCKED | SKIPPED: reason | not run>
Spec review: <n> fixed, <n> open
Code review: <n> fixed, <n> open

Open findings:
- <severity or axis> <file:line> <summary>

Needs human: <failing criteria and what was tried, NOT VERIFIABLE criteria, or none>

RESULT: PASS
```

The last line is `RESULT: PASS` if every stage passed or was `SKIPPED` and the MR exists, `RESULT: BLOCKED` if a stage could not run or the E2E cap was hit, otherwise `RESULT: FAIL`.
