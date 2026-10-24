---
name: herdr-implement-spec
description: "Implement every ticket of a spec/PRD by orchestrating parallel Claude instances in herdr worktrees, wave by wave, merging each into a spec branch, then code-review and E2E-test the whole spec. Use when the user hands you a spec or PRD (or its GitHub issue) and wants its linked issues or slices implemented, not just a single ticket. Use only when the user explicitly asks for it instead of herdr-spec-engine."
---

Implements the spec given, or the spec GitHub issue provided, by orchestrating Claude agents with herdr: implement every ticket wave by wave, then review and E2E-test the spec branch.

Requires: the `herdr` CLI, an authenticated `gh`, Claude Code, and the `/implement-ticket`, `/e2e`, `/code-review`, `/mattpocock-skills:code-review` and `/mattpocock-skills:tdd` skills available to the sub-agents.

- The spec issue is just the spec; the related issues or slices are the work to be implemented.
- `<N>` is the spec issue number. `<SKILL_DIR>` is this skill's base directory.
- Pass every new Claude instance minimal context, so it knows what is being done and that it is a sub Claude instance.
- Start every Claude agent with `-- --permission-mode auto --model opus`. Never `--dangerously-skip-permissions`: the auto-mode classifier refuses to launch it.
- Prompt herdr agents only with `<SKILL_DIR>/prompt-agent.sh <agent> "<prompt>"`, never plain `herdr agent prompt`: it runs a long `/command` prompt as a command instead of pasted text, and confirms the turn started. It returns in seconds, without waiting for the turn.
- Wait on herdr agents only with `<SKILL_DIR>/wait-agents.sh <agent>...`, run with the Bash tool's `run_in_background` flag so you are woken when it exits. Never wait on agents one by one. Its output has a `== <agent> (pane <id>) -> <state>` block per agent with that agent's last turn, then a `summary:` line; exit 0 all finished, 3 some blocked, 1 some timed out or gone. Read more of a pane with `herdr agent read <agent> --lines 200`.

# Setup

- `git checkout main && git pull`, then create the branch for the whole spec (the "spec branch").
- Read the spec issue and list its related issues, their order and dependencies, to build the implementation graph. Make sure they belong to the spec. Ignore closed tickets; only work on issues labeled `ready-for-agent`.
- Group the graph into **waves**: a wave is the set of open tickets whose blockers are all closed or merged into the spec branch. A wave runs in parallel; the next starts only when the whole wave is merged.

# Implementation

Per wave: steps 1–3 for every ticket (fan out), steps 4–5 once for the wave, then steps 6–8.

1. Assign the ticket to the current GitHub user.
2. Create its worktree, based on the spec branch:
   - `herdr worktree create --cwd "$PWD" --branch "ticket-<ID>" --base "<SPEC_BRANCH>" --label "ticket-<ID>" --no-focus --json` → PANE_ID is `result.root_pane.pane_id`, WORKSPACE_ID is `result.workspace.workspace_id`. If the branch exists, use `herdr worktree open --branch "ticket-<ID>"`.
   - `herdr agent start ticket-<ID> --kind claude --pane <PANE_ID> --timeout 60000 -- --permission-mode auto --model opus`
3. `<SKILL_DIR>/prompt-agent.sh ticket-<ID> "use /implement-ticket <ID> ..."`. In one or two sentences add: it is a sub Claude instance, the spec issue, its branch and what the spec branch already contains, the sibling tickets running in parallel, keep changes scoped to its own components/tests, commit on its branch and do not push, merge, switch branches or deploy. If siblings touch the same shared file (index, router, registry, config), tell each exactly where its piece goes.
4. `<SKILL_DIR>/wait-agents.sh ticket-<ID_1> ticket-<ID_2> ...`
   - `done`/`idle`: read its summary in the output, check the branch has commits (`git log --oneline <SPEC_BRANCH>..ticket-<ID>`) and a clean tree.
   - `blocked`: read the pane; answer routine decisions with `prompt-agent.sh`, otherwise hand off to a human. Wait on it again.
   - `timeout`/`gone`: read the pane; re-prompt it once if it stalled, otherwise hand off to a human.
   - An acceptance criterion blocked by a classifier-denied outward action (deploy, publish, send, external write): don't retry it; comment on the ticket, leave it open, continue with tickets that don't depend on it.
5. Review each ticket in its own agent. `<SKILL_DIR>/prompt-agent.sh ticket-<ID> "/mattpocock-skills:code-review <SPEC_BRANCH> ..."`. Add: the spec is ticket #<ID> (`gh issue view <ID>`), part of spec #<N>. Fix every Spec finding that is missing or wrong and every hard Standards violation; fix smells only when cheap and inside the ticket; only report scope creep. Each fix test-first with `/mattpocock-skills:tdd`, one commit each on its branch, no push/merge/branch switch. End the turn with exactly:

   ```
   ## Review ticket #<ID>
   Fixed: - [spec|standards] <title> (<commit>)
   Pending: - [spec|standards] <title> — <reason>
   Scope creep: - <title>
   ```

   Then `<SKILL_DIR>/wait-agents.sh ticket-<ID_1> ticket-<ID_2> ...` and handle states as in step 4. Check each agent's block in the output has the report; if not (it may have scrolled out of the read), prompt once more for it.
6. Merge each ticket branch, one at a time: `git merge --no-ff ticket-<ID>`.
   - On conflict, spawn a built-in `Agent` subagent with `model: "opus"`: tell it to resolve each conflicted file hunk by hunk, keeping both intents, give it the spec, both tickets and the order the spec defines, and have it finish with `RESOLVED: <summary>` or `ESCALATE: <reason>`. On `ESCALATE` (big chunks, significant logic changes), hand off to a human and wait.
   - After the wave's last merge, run the repo's install, lint/type check, format check, build and full test suite on the spec branch. Fix formatting yourself; hand anything else back to the responsible ticket's agent.
7. Close the ticket with a comment pointing at its merge commit and listing any pending review findings. If a pending finding is `[spec]` (missing or wrong), comment but leave the ticket open — its dependents still unblock, since they wait on the merge. `herdr worktree remove --workspace <WORKSPACE_ID>`.
8. Compute the next wave and repeat.

# Review

When every wave is merged, review the combined spec branch for integration issues the per-ticket reviews can't see — duplication across tickets, clashing edits to shared files, requirements that fall between tickets:

1. `herdr tab create --cwd "$PWD" --label review-spec-<N>` (prints JSON) → PANE_ID is `result.root_pane.pane_id`.
2. `herdr agent start review-spec-<N> --kind claude --pane <PANE_ID> --timeout 60000 -- --permission-mode auto --model opus`
3. `<SKILL_DIR>/prompt-agent.sh review-spec-<N> "<prompt>"`: sub Claude instance reviewing spec #<N> on `<SPEC_BRANCH>`; follow the **Review agent** section of `<SKILL_DIR>/SKILL.md`.
4. `<SKILL_DIR>/wait-agents.sh --timeout 7200 --until-line '^[^[:alnum:]]*Review spec #<N>[[:space:]]*$' review-spec-<N>` — the review agent ends turns while its fix agents run, so only its report heading counts as finished. Its report is in the output.

## Review agent

1. Run `/code-review high` on `<SPEC_BRANCH>` against `main`. Classify each finding as blocker/high/medium/low. Only blocker and high get fixed.
2. **Easy fixes** (1–2 files, no design or API change, ~15 min): fix them here with `/mattpocock-skills:tdd` (failing test first), one commit each on the spec branch.
3. **Hard fixes**: one worktree per issue, k = 1, 2, …:
   - `herdr worktree create --cwd "$PWD" --branch "fix-spec-<N>-<k>" --base "<SPEC_BRANCH>" --label "fix-spec-<N>-<k>" --no-focus --json` → PANE_ID and WORKSPACE_ID as in Implementation step 2
   - `herdr agent start fix-spec-<N>-<k> --kind claude --pane <PANE_ID> --timeout 60000 -- --permission-mode auto --model opus`
   - `<SKILL_DIR>/prompt-agent.sh fix-spec-<N>-<k> "<prompt>"`: sub Claude instance, the finding (file, line, failure scenario), spec #<N>; use `/mattpocock-skills:tdd`; commit on its branch, no push/merge/branch switch.
   - `<SKILL_DIR>/wait-agents.sh fix-spec-<N>-1 fix-spec-<N>-2 ...`, then merge each with `git merge --no-ff` (conflicts as in Implementation step 6), run the test suite, `herdr worktree remove --workspace <WORKSPACE_ID>`.
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
2. `<SKILL_DIR>/prompt-agent.sh e2e-spec-<N> "/e2e <prompt>"`: sub Claude instance on `<SPEC_BRANCH>`; verify end to end that spec #<N> is fully complete and does what it is supposed to do (read the spec and its tickets' acceptance criteria). Fix each issue found with a built-in `Agent` subagent, `model: "opus"`, test-first, one commit each on the spec branch; re-run `/e2e` after fixing, max 2 fix rounds. End the turn with `## E2E spec #<N>` listing `Passed`, `Fixed` and `Pending`.
3. `<SKILL_DIR>/wait-agents.sh --timeout 7200 --until-line '^[^[:alnum:]]*E2E spec #<N>[[:space:]]*$' e2e-spec-<N>` — it may end turns while its fix subagents run. Its report is in the output.

# Important

- If the next tickets in the graph are HITL, hand them to a human and wait; resume once done.
- Keep the review and e2e tabs open for inspection.
- Final report: tickets closed, tickets left open and why (including pending `[spec]` review findings), review and e2e results (fixed and pending), and that the spec branch is local — push and open a PR only when asked.
