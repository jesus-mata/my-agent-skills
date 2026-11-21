Take issue #<n> from code to an open PR on this branch, `ticket/<n>`. At the first stage that ends BLOCKED or FAIL, skip to step 5 with no PR.

1. **Develop.** Run `/develop-ticket <n>`. Continue only on `RESULT: PASS`.
2. **Review.** Run `/run-review <base>..HEAD --spec <n> --fresh-classify`. `RESULT: BLOCKED` ends the run.
3. **Fix** every Critical and High finding, then repeat `/develop-ticket`'s Validate and Commit steps. Done when none remain and validation is green; the review does not re-run.
4. **PR.** Push the branch and open a ready-for-review PR against `<default>` with `gh`. Its body carries `Closes #<n>`, a summary of the change, and the remaining Medium and Low findings under _Open findings_.
5. **Ping** with `/ping-me`: `ok` with the PR URL, or `fail` with the stage and reason.
