---
name: merge-pr
description: Squash-merges a GitHub pull request once its checks pass, resolving only trivial conflicts (with a Sonnet subagent) and escalating anything that touches logic or scope, then deletes the remote branch, updates the main checkout and removes the PR's local branch and worktree — herdr or plain git. Use when the user types /merge-pr with a PR number, URL or branch, or none for the current branch's PR.
disable-model-invocation: true
---

# Merge PR

When in doubt, **escalate**: stop, leave the PR open, and tell the user what you found and what they
need to decide. Never use `--admin`, skip a failing check, or force-push.

```
Merge progress:
- [ ] 1. Preflight
- [ ] 2. Wait for checks
- [ ] 3. Resolve conflicts (trivial only), then back to 2
- [ ] 4. Squash-merge
- [ ] 5. Clean up
- [ ] 6. Report
```

## 1. Preflight

No argument → the current branch's PR.

```bash
gh pr view <pr> --json number,state,isDraft,baseRefName,headRefName,headRefOid,mergeable,reviewDecision
```

`MERGED` → go to 5. `CLOSED`, draft, or `CHANGES_REQUESTED` → escalate. `mergeable` `UNKNOWN` →
re-query in a few seconds.

## 2. Wait for checks

`gh pr checks <pr> --watch --fail-fast`. "no checks reported" counts as passing. A failure →
escalate with the check name and link; don't fix code.

## 3. Resolve conflicts

Only if `mergeable` is `CONFLICTING`. Work in the PR branch's worktree (`git worktree list`) if it is
clean and matches `origin/<branch>`, else escalate. With no worktree, make a throwaway one with
`git worktree add <scratch>/merge-pr-<N> <branch>` (never `-b`/`-B`), after checking any local
`<branch>` matches `origin/<branch>`. Then `git fetch origin && git merge origin/<base>` — merge, not rebase, so no force-push.

**Trivial**: independent additions to the same list, imports or config; lines moved or reformatted
on one side; lockfiles and generated files (regenerate them). **Anything else** — same logic changed
on both sides, delete vs. edit, changes beyond the ticket's scope, many hunks, or doubt —
`git merge --abort` and escalate.

Hand the trivial hunks to an `Agent` with `model: "sonnet"`: worktree path, files, the hunks and why
each is trivial, "keep both sides' intent, don't commit, stop if a hunk isn't trivial". Then verify:
`git diff --check` is clean and `git diff origin/<base>...HEAD` is still exactly the PR's change. Run
the project's fast test if it has one. Commit, `git push`, back to 2.

## 4. Squash-merge

Re-read `headRefOid`, then:

```bash
gh pr merge <pr> --squash --match-head-commit <headRefOid>
```

No `--delete-branch`: it breaks on branches checked out in a worktree; step 5 handles it. Poll
`gh pr view <pr> --json state,mergeCommit` until `MERGED` (merge queues and auto-merge leave it
`OPEN` for a while). Refused or dropped from the queue → escalate with gh's message.

## 5. Clean up

From anywhere in the repo, run exactly:

```bash
<SKILL_DIR>/cleanup-merged-branch.sh <headRefName> <headRefOid>
```

`<SKILL_DIR>` is this file's directory. It deletes the remote branch, updates the main checkout,
removes the worktree (herdr or git) and the local branch. It never deletes uncommitted or unmerged
work. The last line says what happened:

- `CLEANUP=done`
- `CLEANUP=kept reason=<r>` → report what was kept and why; don't delete it yourself.
- `CLEANUP=deferred log=<file>` → you are inside the herdr workspace being removed; it closes in
  ~15s. Send the report now as your final message, with no tool calls after it.

Non-zero exit → merged, but cleanup failed; report its message. If your cwd was the removed
worktree, `cd` to the main checkout.

## 6. Report

The PR and its squash commit; conflicts resolved, if any; what cleanup removed or kept. For an
escalation: where it stopped, why, and what the user must decide.
