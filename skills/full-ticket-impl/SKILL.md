---
name: full-ticket-impl
description: Launches a GitHub issue to a PR in a fresh worktree, from an Opus agent in its own Rex tab that develops, reviews, fixes, opens the PR and pings you.
argument-hint: <issue-number>
disable-model-invocation: true
---

# Full ticket implementation

Launch ticket $ARGUMENTS into its own worktree and Rex tab, then return. The agent in the tab owns the pipeline through the ping.

## Steps

1. **Preflight.** Stop with the reason if `REX_SESSION` is unset, or if the branch `ticket/<n>` or the directory `../<repo>-<n>` already exists, where `<repo>` is the basename of the repo root.
2. **Worktree.** Run `git fetch origin` and find `<default>` with `git symbolic-ref --short refs/remotes/origin/HEAD`. Run `git worktree add ../<repo>-<n> -b ticket/<n> origin/<default>`, and record `<base>` as `git rev-parse origin/<default>`.
3. **Launch.** Fill the placeholders of [AGENT_BRIEF.md](AGENT_BRIEF.md) and pass the result as one argument:

   ```sh
   rex window new -s "$REX_SESSION" "#<n>" -c <worktree> --focus=false -- \
     claude --model opus --permission-mode bypassPermissions "<brief>"
   ```

   Done when `rex capture` on the new tab shows Claude working on the brief.
4. **Report** the worktree path, the branch and the tab name.
