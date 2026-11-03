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
   `NOT VERIFIABLE` criteria, and every commit after the reviewed one, because those are not
   reviewed.

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
templates linked into `~/.config/herdr-core/templates`, the skills those templates run, `jq`, and
an authenticated `gh` or `glab`. `bin/agent-skills install` or `update` links every template,
and the `templates/lib` they start through, once `~/.config/herdr-core` exists, so run one of
those after pulling. `bin/agent-skills status` shows any template that is missing.

## Choosing models

Every stage runs Opus at `medium` effort unless you say otherwise. Set any stage with
`<model>[:<effort>]`:

```
/hc-implement-ticket 42 --orchestrator sonnet --dev sonnet:high --review opus --e2e haiku:low
```

Models can be aliases or full IDs. Without an effort, Opus gets `medium`, Sonnet gets `high`, and
any other model gets Claude's own default. Fix rounds run in `dev-42`, so they use the dev model.
Before creating anything, the launcher rejects a bad effort and sends each distinct model one short
Claude request, so a typo stops the launch.

The choices are stored as labels on `ticket-42`. Each template starts Claude through
`templates/lib/hc-claude`, which reads its terminal's `model` and `effort` labels, refuses an
unknown effort, and records what it requested, so the same labels work on any Claude template:

```
hc run --bg --label model=sonnet --label effort=low reviewer "review src/x.rs"
```

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

The run ends with the same report as `/implement-ticket`, plus the worktree, terminal names and
each stage's requested model and effort, on a last line of `RESULT: PASS`, `FAIL` or `BLOCKED`.

## Pings

If [`ping-me`](../ping-me/README.md) is set up, `ticket-42` sends a push when the run ends, when a
follow-up that ran a stage ends, and when cleanup stops at a failed check. `ok` means every stage
passed or was skipped and the MR is open. Read the report before merging, because a skipped E2E and
open Medium or Low findings still count as `ok`. `attention` means something is waiting on you,
such as `NOT VERIFIABLE` criteria or a secret to rotate. `fail` means the run failed or is blocked.

Pings hold the repo folder name, the ticket number, the outcome, the stage and the MR URL, which
shows the org and repo, so read the report for the details. They never change the result: if one
fails, the report says so on a `Ping: failed` line, and without `ping-me` that line appears on
every run.

The orchestrator sends the pings itself, so if `ticket-42` crashes or hits a rate limit, no ping
arrives.
