# full-ticket-impl

Fire-and-forget: one GitHub issue in, one PR and a phone ping out. Merging stays with you.

```
/full-ticket-impl 42
```

## What it does

Your session creates a worktree `../<repo>-42` on branch `ticket/42` from the up to date default
branch, opens a Rex tab `#42` running Claude on Opus, and returns. The agent in that tab:

1. **Develops** with `/develop-ticket`. A comment headed `## Agent Brief` supersedes the issue
   body as the ticket.
2. **Reviews** with `/run-review` over exactly the worktree's commits, with the issue as spec.
3. **Fixes** every Critical and High finding, then re-validates. The review runs once.
4. **Opens a PR** with `Closes #42` and the remaining findings listed.
5. **Pings** you with `/ping-me`: the PR URL, or the stage that failed and why (no PR then).

Unlike `/implement-ticket`, it skips E2E and runs in its own tab, so your session stays free.

## Requirements

- Running inside Rex (`REX_SESSION` set), with `claude` and an authenticated `gh`.
- The skills it uses: `/develop-ticket`, `/run-review`, `/run-tests`, `/ping-me`.
- The tab agent runs with `--permission-mode bypassPermissions`, so it works unattended.
