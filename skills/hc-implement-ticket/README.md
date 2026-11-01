# hc-implement-ticket

Takes one ticket from code to an open MR, like `/implement-ticket`, but each stage runs in its own
`hc` terminal that stays open for follow-ups or review, and E2E runs last. Merging stays with you.

## What it does

`/hc-implement-ticket 42` starts the `ticket-orchestrator` template as `ticket-42`. The orchestrator
has no file-edit tools and a narrow command allowlist, so children write the code. The allowlist is
a guardrail, not a security boundary, because `hc run` can start any program. It:

1. Creates branch `fix/issue_42` in `../worktree/<repo>-issue_42`, from the up to date default
   branch. If the folder or the branch, local or remote, already exists, the run ends `BLOCKED`
   before creating anything.
2. Runs `dev-42` from the `coder` template.
3. Runs `review-42` from the `reviewer` template, once.
4. Sends every finding back to `dev-42`, which must fix each Critical and High and fixes a Medium or
   Low when it is simple.
5. Runs `e2e-42-1` from the `e2e-tester` template, which reports `SKIPPED` when there is nothing to
   test end to end.
6. Pushes the branch and opens the PR/MR, listing unfixed Medium and Low findings, any
   `NOT VERIFIABLE` criteria, and any E2E fixes, because those are not reviewed.

E2E runs last so a `PASS` always covers the code that gets pushed, usually in one run. E2E failures
go to `dev-42` too, and each re-run is a new terminal, up to 3 per ticket. Children
report one line with a path to their full report, in `~/.cache/hc-coder`, `~/.cache/hc-reviews` and
`~/.cache/hc-e2e`. Reports move between terminals by path, so long or awkward text stays in files.

## How to use it

Run it from any `hc` terminal in the repo:

```
/hc-implement-ticket 42
```

Only you can start it. It needs the `coder`, `e2e-tester`, `reviewer` and `ticket-orchestrator`
templates linked into `~/.config/herdr-core/templates`, the skills those templates run, and an
authenticated `gh` or `glab`.

Inside Herdr, the ticket gets its own space, `<repo> #42`, with the terminals as panes of one tab.
Each E2E re-run gets its own tab. Elsewhere the terminals run hidden, so use `hc attach dev-42`.

The orchestrator stays open after the report. Ask it for follow-ups, because only it can push, or
talk to any child directly. A follow-up reaches the MR only after E2E passes or is skipped.
`hc kill ticket-42` ends all of them and closes the space. The worktree stays until you remove it.

After merging, tell `ticket-42` the MR is merged. It confirms the merge and that the MR holds every
local commit, then removes the worktree, the child terminals and the local branch. It keeps
everything if the MR isn't merged or the worktree has uncommitted work. It leaves the remote branch
alone, and you close `ticket-42` yourself.

Terminal names hold only the issue number, so the same number can't run in two repos at once. To
retry a ticket, or to reuse a number, run `hc kill ticket-42` and `hc rm ticket-42`, and remove any
`fix/issue_42` branch and worktree. The launcher stops and says so if it finds one.

The run ends with the same report as `/implement-ticket`, plus the worktree and terminal names, on
a last line of `RESULT: PASS`, `FAIL` or `BLOCKED`.
