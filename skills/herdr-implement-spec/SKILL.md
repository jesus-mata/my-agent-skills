---
name: herdr-implement-spec
description: "Implement every ticket of a spec/PRD by orchestrating parallel Claude instances in herdr worktrees, wave by wave, merging each into a spec branch, then code-review and E2E-test the whole spec. Use when the user hands you a spec or PRD (or its GitHub issue) and wants its linked issues or slices implemented, not just a single ticket."
---

Implements the spec given, or the spec GitHub issue provided, by orchestrating Claude agents with herdr: implement every ticket wave by wave, then review and E2E-test the spec branch.

Requires: the `herdr` CLI, an authenticated `gh`, Claude Code, and the `/implement-ticket`, `/e2e`, `/code-review` and `/mattpocock-skills:tdd` skills available to the sub-agents.

- The spec issue is just the spec; the related issues or slices are the work to be implemented.
- `<N>` is the spec issue number. `<SKILL_DIR>` is this skill's base directory.
- Pass every new Claude instance minimal context, so it knows what is being done and that it is a sub Claude instance.
- Start every Claude agent with `-- --permission-mode auto --model opus`. Never `--dangerously-skip-permissions`: the auto-mode classifier refuses to launch it.
- Wait on herdr agents only with `<SKILL_DIR>/wait-agents.sh <agent>...`, run with the Bash tool's `run_in_background` flag so you are woken when it exits. Never wait on agents one by one.

# Setup

- `git checkout main && git pull`, then create the branch for the whole spec (the "spec branch").
- Read the spec issue and list its related issues, their order and dependencies, to build the implementation graph. Make sure they belong to the spec. Ignore closed tickets; only work on issues labeled `ready-for-agent`.
- Group the graph into **waves**: a wave is the set of open tickets whose blockers are all closed or merged into the spec branch. A wave runs in parallel; the next starts only when the whole wave is merged.

# Implementation

Per wave: steps 1–3 for every ticket (fan out), step 4 once, then steps 5–7.

1. Assign the ticket to the current GitHub user.
2. Create its worktree, based on the spec branch:
   - `herdr worktree create --cwd "$PWD" --branch "ticket-<ID>" --base "<SPEC_BRANCH>" --label "ticket-<ID>" --no-focus --json` → PANE_ID is `result.root_pane.pane_id`, WORKSPACE_ID is `result.workspace.workspace_id`. If the branch exists, use `herdr worktree open --branch "ticket-<ID>"`.
   - `herdr agent start ticket-<ID> --kind claude --pane <PANE_ID> --timeout 60000 -- --permission-mode auto --model opus`
3. `herdr agent prompt ticket-<ID> "use /implement-ticket <ID> ..."` — no `--wait`, it serializes the wave. In one or two sentences add: it is a sub Claude instance, the spec issue, its branch and what the spec branch already contains, the sibling tickets running in parallel, keep changes scoped to its own components/tests, commit on its branch and do not push, merge, switch branches or deploy. If siblings touch the same shared file (index, router, registry, config), tell each exactly where its piece goes.
4. `<SKILL_DIR>/wait-agents.sh ticket-<ID_1> ticket-<ID_2> ...`
   - `done`/`idle`: read the summary (`herdr agent read ticket-<ID>`), check the branch has commits (`git log --oneline <SPEC_BRANCH>..ticket-<ID>`) and a clean tree.
   - `blocked`: read the pane; answer routine decisions with `herdr agent prompt`, otherwise hand off to a human. Wait on it again.
   - An acceptance criterion blocked by a classifier-denied outward action (deploy, publish, send, external write): don't retry it; comment on the ticket, leave it open, continue with tickets that don't depend on it.
5. Merge each ticket branch, one at a time: `git merge --no-ff ticket-<ID>`.
   - On conflict, spawn a built-in `Agent` subagent with `model: "opus"`: tell it to use `/mattpocock-skills:resolving-merge-conflicts`, give it the spec, both tickets and the order the spec defines, and have it finish with `RESOLVED: <summary>` or `ESCALATE: <reason>`. On `ESCALATE` (big chunks, significant logic changes), hand off to a human and wait.
   - After the wave's last merge, run the repo's install, lint/type check, format check, build and full test suite on the spec branch. Fix formatting yourself; hand anything else back to the responsible ticket's agent.
6. Close the ticket with a comment pointing at its merge commit; `herdr worktree remove --workspace <WORKSPACE_ID>`.
7. Compute the next wave and repeat.

# Review

When every wave is merged:

1. `herdr tab create --cwd "$PWD" --label review-spec-<N>` (prints JSON) → PANE_ID is `result.root_pane.pane_id`.
2. `herdr agent start review-spec-<N> --kind claude --pane <PANE_ID> --timeout 60000 -- --permission-mode auto --model opus`
3. `herdr agent prompt review-spec-<N> "<prompt>"`: sub Claude instance reviewing spec #<N> on `<SPEC_BRANCH>`; follow the **Review agent** section of `<SKILL_DIR>/SKILL.md`.
4. `<SKILL_DIR>/wait-agents.sh --timeout 7200 review-spec-<N>`, then `herdr agent read review-spec-<N>` for its report.

## Review agent

1. Run `/code-review high` on `<SPEC_BRANCH>` against `main`. Classify each finding as blocker/high/medium/low. Only blocker and high get fixed.
2. **Easy fixes** (1–2 files, no design or API change, ~15 min): fix them here with `/mattpocock-skills:tdd` (failing test first), one commit each on the spec branch.
3. **Hard fixes**: one worktree per issue, k = 1, 2, …:
   - `herdr worktree create --cwd "$PWD" --branch "fix-spec-<N>-<k>" --base "<SPEC_BRANCH>" --label "fix-spec-<N>-<k>" --no-focus --json` → PANE_ID and WORKSPACE_ID as in Implementation step 2
   - `herdr agent start fix-spec-<N>-<k> --kind claude --pane <PANE_ID> --timeout 60000 -- --permission-mode auto --model opus`
   - `herdr agent prompt fix-spec-<N>-<k> "<prompt>"`: sub Claude instance, the finding (file, line, failure scenario), spec #<N>; use `/mattpocock-skills:tdd`; commit on its branch, no push/merge/branch switch.
   - `<SKILL_DIR>/wait-agents.sh fix-spec-<N>-1 fix-spec-<N>-2 ...`, then merge each with `git merge --no-ff` (conflicts as in Implementation step 5), run the test suite, `herdr worktree remove --workspace <WORKSPACE_ID>`.
4. End your turn with exactly this report:

   ```
   ## Review spec #<N>
   Fixed: - [<severity>] <title> (<commit>)
   Pending: - [<severity>] <title> — <reason>
   Not fixed (medium/low): - [<severity>] <title>
   ```

# E2E

After review, even if blockers are pending (flag them):

1. `herdr tab create --cwd "$PWD" --label e2e-spec-<N>` → PANE_ID is `result.root_pane.pane_id`; `herdr agent start e2e-spec-<N> --kind claude --pane <PANE_ID> --timeout 60000 -- --permission-mode auto --model opus`
2. `herdr agent prompt e2e-spec-<N> "/e2e <prompt>"`: sub Claude instance on `<SPEC_BRANCH>`; verify end to end that spec #<N> is fully complete and does what it is supposed to do (read the spec and its tickets' acceptance criteria). Fix each issue found with a built-in `Agent` subagent, `model: "opus"`, test-first, one commit each on the spec branch; re-run `/e2e` after fixing, max 2 fix rounds. End the turn with `## E2E spec #<N>` listing `Passed`, `Fixed` and `Pending`.
3. `<SKILL_DIR>/wait-agents.sh --timeout 7200 e2e-spec-<N>`, then `herdr agent read e2e-spec-<N>`.

# Important

- If the next tickets in the graph are HITL, hand them to a human and wait; resume once done.
- Keep the review and e2e tabs open for inspection.
- Final report: tickets closed, tickets left open and why, review and e2e results (fixed and pending), and that the spec branch is local — push and open a PR only when asked.
