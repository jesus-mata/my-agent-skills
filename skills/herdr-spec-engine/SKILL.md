---
name: herdr-spec-engine
description: "Implement every ticket of a spec/PRD with parallel Claude agents in herdr worktrees, driven by a deterministic engine that schedules, reviews, gates and merges each ticket into a spec branch, then code-reviews and E2E-tests the whole spec while you supervise its escalations. Use when the user hands you a spec or PRD (or its GitHub issue) and wants its linked issues or sub-issues implemented, not just a single ticket."
---

You are the **supervisor** of a spec run. The engine owns every transition: it claims tickets, starts and prompts agents, checks their result files, runs the gate, merges into the spec branch, closes tickets, then runs spec review and E2E. You start it, sleep until it escalates, and resolve each escalation from its closed set of actions. Vocabulary: [GLOSSARY.md](GLOSSARY.md). Engine internals, stages and escalation effects: [docs/design.md](docs/design.md).

- `<N>` is the spec issue number. `<SKILL_DIR>` is this skill's base directory.
- Requires: running inside herdr (`herdr` CLI), an authenticated `gh`, `python3` 3.11+, Claude Code, and these skills available to the engine's agents: `/implement-ticket`, `/e2e`, `/code-review`, `/mattpocock-skills:code-review`, `/mattpocock-skills:tdd`, `/mattpocock-skills:resolving-merge-conflicts`.
- Your hands stay off the run: you never move tickets, merge, touch the repo root's working tree (the engine keeps the spec branch checked out there), or prompt engine agents, except to answer a blocked one. Anything the engine does not model reaches you as an escalation.

# 1. Plan

1. `<SKILL_DIR>/engine plan <N>` (flags: `--branch B`, `--base B` (default `main`, or `master` if there is no `main`), `--gate CMD` repeatable, `--from FILE` for specs without sub-issues — keep that file outside the repo, an untracked file in the repo root blocks every merge as `repo-dirty`; see design.md "Plan").
2. Show the user the printed graph, the class of each ticket, external blockers, unrefined tickets, the spec branch and the gate commands. Get their confirmation.
3. Exit 1 means unrefined tickets or a cycle. Have the user fix labels (`ready-for-agent` / `ready-for-human`) or blockers, or pass `--gate` if the discovered gate is wrong, then re-run `plan` until it exits 0 and the user confirms.

# 2. Start the engine

1. From the repo root: `herdr tab create --cwd "$PWD" --label engine-spec-<N> --no-focus` → PANE_ID is `.result.root_pane.pane_id`.
2. `herdr pane run <PANE_ID> "<SKILL_DIR>/engine run <N>"`, adding run flags only when the user asks: `--max-agents N` (default 3), `--model M` (opus), `--stage-timeout D` (2h), `--retry-budget N` (1), `--gate-retry-budget N` (2), `--gate-timeout D` (30m), `--poll D` (10s); durations take `90`, `90s`, `30m`, `2h`. A resumed run keeps its stored settings and overrides only the flags given. `run` exits 1 without starting when `plan.json` is missing or unrunnable, another engine for `<N>` is alive, or the run was aborted; read the pane (`herdr pane read <PANE_ID>`) if `watch` reports `ENGINE NOT RUNNING` right away.

# 3. Supervise

Loop until COMPLETE:

1. Run `<SKILL_DIR>/engine watch <N>` (default `--timeout 4h`) with the Bash tool's `run_in_background` flag, and wait to be woken.
2. On wake, act on its exit:
   - **0 with escalations**: handle every printed `ESCALATION <id>` block (run, kind, stage, summary, details, allowed actions and the exact `resolve` command), then go to 1. Watch never re-prints an escalation whose resolution is queued but not yet consumed, nor a handed-off one.
   - **0 with `COMPLETE`**: the report follows on stdout; go to 4.
   - **0 with `ABORTED`**: the user aborted the run; stop supervising.
   - **3 `ENGINE NOT RUNNING`**: the engine died or was stopped. Unless the user stopped it, re-run step 2.2 in the same pane; `engine run <N>` resumes from saved state. Then go to 1.
   - **1** (watch timeout): go to 1.

Resolve with `<SKILL_DIR>/engine resolve <N> <id> <action> [--note TEXT]`, using only an action the escalation lists (exit 0 = queued; exit 2 = unknown id or action not allowed, and it prints the allowed ones). The engine applies it on its next tick. Read an agent's screen with `herdr agent read <agent> --source recent --lines 120`; engine agents, their branches and tabs are named after their run: `s<N>-ticket-<n>`, `s<N>-fix-<k>`, `s<N>-review`, `s<N>-e2e`, merge resolvers `s<N>-resolve-<run>` (e.g. `s7-resolve-ticket-12`). `<SKILL_DIR>/engine status <N>` (`--json` for the raw state) shows every run, the merge queue and all unresolved escalations.

Every kind also allows `hand-to-human`: use it whenever you are waiting on the user, so `watch` stops reporting the escalation; resolve it later with another action when the user reports back.

| Kind | What you do | Action |
| --- | --- | --- |
| `agent-blocked` | Read the agent. A routine in-scope decision: answer it with `herdr agent prompt <agent> "<answer>"` (a selection dialog: `herdr agent send-keys`). Anything outward, destructive or a product decision: tell the user. | `answered`; else `hand-to-human` |
| `agent-unknown` | Read the agent. Waiting on input: answer as above. Sitting idle at its prompt without having started: re-send. Otherwise tell the user. | `answered` / `retry` / `hand-to-human` |
| `stage-timeout` | Read the agent. Still making progress: give it more time. Stuck or looping: tell the user. | `retry`; else `hand-to-human`; `skip-ticket` only if the user chooses it |
| `budget-exhausted` | Read the details (result error, gate output, exception). Transient cause (herdr hiccup, flaky test, network): retry once. Otherwise tell the user. | `retry`; else `hand-to-human`; `skip-ticket` only if the user chooses it |
| `resolver-escalated` | The conflicted merge of the spec branch is left in progress in the run's worktree (path in details). Tell the user the conflict and the path; they finish the merge there (if none is in progress: `git merge <spec-branch>` first), commit it and leave the tree clean. The engine refuses `resolved-manually` (escalation stays open, reason in details) until that holds, then resumes at the gate. | `hand-to-human`, later `resolved-manually` |
| `outward-action-denied` | Tell the user the denied actions. Default to leaving the ticket open; retry only once the user did the action or granted permission. | `leave-open` / `hand-to-human`, later `retry` |
| `hitl-ticket` | Tell the user the ticket is theirs. Once they say it is done and closed (the engine re-checks; still open → the escalation reopens): | `hand-to-human`, later `done` |
| `unrefined-ticket` | Ask the user to label the ticket, or whether to skip it. | `hand-to-human`, later `relabeled` / `skip-ticket` |
| `external-blocker` | Tell the user which outside issue blocks it. Once closed, or if the user says skip: | `hand-to-human`, later `cleared` / `skip-ticket` |
| `repo-dirty` | Show the user `git status` of the repo root; it must be on the spec branch and clean. Leave their changes for them to commit or stash, then: | `hand-to-human`, later `retry` |

`skip-ticket` drops a ticket and everything it blocks; issue it only when the user chooses it. A handed-off escalation disappears from `watch`; track it yourself and resolve it when the user reports back (`engine status <N>` lists it).

# 4. Finish

On `COMPLETE`, relay `report.md` (printed by `watch`) to the user: tickets done, left open and skipped with reasons, pending review findings and dismissed ones (judged false positives by the reviewer; they never keep a ticket open), spec review fixed / still-pending hard / not fixed findings (offer to open follow-up issues for the not-fixed ones worth keeping), fix runs, E2E passed / fixed / pending, and any open or handed-off escalations. The spec branch is local and nothing was pushed; push or open a PR only when the user asks. The spec review and E2E tabs stay open for inspection.

# Stopping

- `<SKILL_DIR>/engine stop <N>`: the engine saves state and exits at its next tick (Ctrl-C in its pane does the same); agents and worktrees stay. `engine run <N>` resumes later.
- `<SKILL_DIR>/engine abort <N>`: only when the user asks. Stops the engine (waits up to 60 s; exit 1 if it does not stop), interrupts its agents, closes resolver panes and removes the worktrees of unfinished runs (branches are kept). Nothing on GitHub is reverted. An aborted run cannot be resumed.
