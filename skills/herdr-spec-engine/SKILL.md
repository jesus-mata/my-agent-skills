---
name: herdr-spec-engine
description: "Implement every ticket of a spec/PRD with parallel Claude agents in herdr worktrees, driven by a deterministic engine that schedules, reviews, gates and merges each ticket into a spec branch, then code-reviews and E2E-tests the whole spec while you supervise its escalations. Use when the user hands you a spec or PRD (or its GitHub issue) and wants its linked issues or sub-issues implemented, not just a single ticket."
---

You are the **supervisor** of a spec run. The engine owns every transition: it claims tickets, starts and prompts agents, checks their result files, runs the gate, merges into the spec branch, closes tickets, then runs spec review and E2E. You start it, sleep until it escalates, and resolve each escalation from its closed set of actions. Vocabulary: [GLOSSARY.md](GLOSSARY.md). Engine internals, stages and escalation effects: [docs/design.md](docs/design.md).

- `<N>` is the spec issue number. `<SKILL_DIR>` is this skill's base directory.
- Requires: running inside herdr (`herdr` CLI), an authenticated `gh`, `python3` 3.11+, Claude Code, and these skills available to the engine's agents: `/implement-ticket`, `/e2e`, `/code-review`, `/mattpocock-skills:code-review`, `/mattpocock-skills:tdd`, `/mattpocock-skills:resolving-merge-conflicts`.
- Your hands stay off the run: you never move tickets, merge, touch the repo root's working tree (the engine keeps the spec branch checked out there), or prompt engine agents, except to answer a blocked one. Anything the engine does not model reaches you as an escalation.

# 1. Plan

1. `<SKILL_DIR>/engine plan <N>` (flags: `--branch B`, `--gate CMD` repeatable, `--from FILE` for specs without sub-issues; see design.md "Plan").
2. Show the user the printed graph, the class of each ticket, external blockers, unrefined tickets, the spec branch and the gate commands. Get their confirmation.
3. Exit 1 means unrefined tickets or a cycle. Have the user fix labels (`ready-for-agent` / `ready-for-human`) or blockers, or pass `--gate` if the discovered gate is wrong, then re-run `plan` until it exits 0 and the user confirms.

# 2. Start the engine

1. `herdr tab create --cwd "$PWD" --label engine-spec-<N>` → PANE_ID is `.result.root_pane.pane_id`.
2. `herdr pane run <PANE_ID> "<SKILL_DIR>/engine run <N>"`, adding run flags only when the user asks (`--max-agents`, `--model`, `--stage-timeout`, ...; see design.md "CLI").

# 3. Supervise

Loop until COMPLETE:

1. Run `<SKILL_DIR>/engine watch <N>` with the Bash tool's `run_in_background` flag, and wait to be woken.
2. On wake, act on its exit:
   - **0 with escalations**: handle every printed escalation (table below), then go to 1. Watch may re-print an escalation you just resolved until the engine consumes it on its next tick; check `engine status <N>` and watch again.
   - **0 with `COMPLETE`**: go to 4.
   - **3 `ENGINE NOT RUNNING`**: the engine died. Re-run step 2.2 in the same pane; `engine run <N>` resumes from saved state. Then go to 1.
   - **1** (watch timeout): go to 1.

Resolve with `<SKILL_DIR>/engine resolve <N> <id> <action> [--note TEXT]`, using only an action the escalation lists. Read an agent's screen with `herdr agent read <agent> --source recent --lines 120`.

| Kind | What you do | Action |
| --- | --- | --- |
| `agent-blocked` | Read the agent. A routine in-scope decision: answer it with `herdr agent prompt <agent> "<answer>"` (a selection dialog: `herdr agent send-keys`). Anything outward, destructive or a product decision: tell the user. | `answered`; else `hand-to-human` |
| `agent-unknown` | Read the agent. Waiting on input: answer as above. Sitting idle at its prompt without having started: re-send. Otherwise tell the user. | `answered` / `retry` / `hand-to-human` |
| `stage-timeout` | Read the agent. Still making progress: give it more time. Stuck or looping: tell the user. | `retry`; else `hand-to-human` |
| `budget-exhausted` | Read the details (result error, gate output, exception). Transient cause (herdr hiccup, flaky test, network): retry once. Otherwise tell the user. | `retry`; else `hand-to-human` |
| `resolver-escalated` | Tell the user the conflict and the worktree path. Once they have committed the merge there and the tree is clean: | `hand-to-human`, later `resolved-manually` |
| `outward-action-denied` | Tell the user the denied actions. Default to leaving the ticket open; retry only once the user did the action or granted permission. | `leave-open` / `retry` |
| `hitl-ticket` | Tell the user the ticket is theirs. Once they say it is done and closed: | `hand-to-human`, later `done` |
| `unrefined-ticket` | Ask the user to label the ticket, or whether to skip it. | `relabeled` / `skip-ticket` |
| `external-blocker` | Tell the user which outside issue blocks it. Once closed, or if the user says skip: | `cleared` / `skip-ticket` |
| `repo-dirty` | Show the user `git status` of the repo root; it must be on the spec branch and clean. Leave their changes for them to commit or stash, then: | `retry` |

`skip-ticket` drops a ticket and everything it blocks; issue it only when the user chooses it. A handed-off escalation disappears from `watch`; track it yourself and resolve it when the user reports back (`engine status <N>` lists it).

# 4. Finish

On `COMPLETE`, relay `report.md` (printed by `watch`) to the user: tickets done, left open and skipped with reasons, spec review and E2E results, and any handed-off escalations. The spec branch is local and nothing was pushed; push or open a PR only when the user asks. The spec review and E2E tabs stay open for inspection.

# Stopping

- `<SKILL_DIR>/engine stop <N>`: the engine saves state and exits at its next tick; agents and worktrees stay. `engine run <N>` resumes later.
- `<SKILL_DIR>/engine abort <N>`: only when the user asks. Stops the engine, interrupts its agents and removes the worktrees of unfinished runs (branches are kept). Nothing on GitHub is reverted.
