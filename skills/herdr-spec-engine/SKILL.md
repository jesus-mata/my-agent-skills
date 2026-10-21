---
name: herdr-spec-engine
description: "Implements every ticket of a spec, PRD or epic with parallel Claude agents in herdr worktrees, driven by a deterministic engine that schedules, reviews, gates and merges each ticket into a spec branch, then code-reviews and E2E-tests the whole spec; Claude only supervises its escalations. Use when the user hands over a spec or PRD (or its GitHub issue) and wants all its tickets or sub-issues implemented, not a single ticket. Default choice over herdr-implement-spec."
---

You are the **supervisor** of a spec run. The engine owns every transition: it claims tickets, starts and prompts agents, checks their result files, runs the gate, merges into the spec branch, closes tickets, then runs spec review and E2E. You start it, sleep until it escalates, and resolve each escalation from its closed set of actions. Vocabulary: [GLOSSARY.md](GLOSSARY.md). What each escalation action does: [docs/design.md](docs/design.md) "Escalations"; how the plan and its gate are built: "Plan".

- `<N>` is the spec issue number. `<SKILL_DIR>` is this skill's base directory.
- `plan` and `run` check their own requirements (tools, `gh` auth, herdr, Python 3.11+): on exit 2, relay each printed error to the user. A `warning: skill … not found` does not stop the run; tell the user, since the agents that invoke that skill will fail without it.
- Your hands stay off the run: you never move tickets, merge, touch the repo root's working tree (the engine keeps the spec branch checked out there), or prompt engine agents, except to answer a blocked one. Anything the engine does not model reaches you as an escalation.

# 1. Plan

1. `<SKILL_DIR>/engine plan <N>`. Flags:
   - `--branch B` (default `spec-<N>`), `--base B` (default `main`, else `master`).
   - `--gate CMD`, repeatable. Without it the gate comes from a `## Gate` section of the spec body, else is discovered from the repo's build files (design.md "Plan").
   - `--from FILE` for specs without sub-issues. Keep FILE outside the repo: an untracked file in the repo root blocks every merge as `repo-dirty`.
2. Show the user the printed graph, the class of each ticket, external blockers, unrefined tickets, the spec branch and the gate commands with their source, and any gate warning (e.g. the `unittest discover` exit-5 one: suggest the printed guard to the user). Get their confirmation.
3. Exit 1 means unrefined tickets or a cycle. Have the user fix labels (`ready-for-agent` / `ready-for-human`) or blockers, or pass `--gate` (or add a `## Gate` section to the spec body) if the gate is wrong or empty, then re-run `plan` until it exits 0 and the user confirms.

# 2. Start the engine

1. From the repo root: `herdr tab create --cwd "$PWD" --label engine-spec-<N> --no-focus` → PANE_ID is `.result.root_pane.pane_id`.
2. `herdr pane run <PANE_ID> "<SKILL_DIR>/engine run <N>"`. Add run flags (agents, model, timeouts, retry budgets) only when the user asks; `engine run --help` lists them with their defaults. A resumed run keeps its stored settings and overrides only the flags given. `run` exits without starting on a failed preflight (2), or (1) when `plan.json` is missing or unrunnable, another engine for `<N>` is alive, or the run was aborted; read the pane (`herdr pane read <PANE_ID>`) if `watch` reports `ENGINE NOT RUNNING` right away.

# 3. Supervise

Loop until COMPLETE:

1. Run `<SKILL_DIR>/engine watch <N>` (default `--timeout 4h`) with the Bash tool's `run_in_background` flag, and wait to be woken.
2. On wake, act on its exit:
   - **0 with escalations**: handle every printed `ESCALATION <id>` block (run, kind, stage, summary, details, allowed actions and the exact `resolve` command), then go to 1. Watch never re-prints an escalation whose resolution is queued but not yet consumed, nor a handed-off one.
   - **0 with `COMPLETE`**: the report follows on stdout; go to 4.
   - **0 with `ABORTED`**: the user aborted the run; stop supervising.
   - **3 `ENGINE NOT RUNNING`**: the engine died or was stopped. Unless the user stopped it, re-run step 2.2 in the same pane; `engine run <N>` resumes from saved state. Then go to 1.
   - **1** (watch timeout): go to 1.

Resolve with `<SKILL_DIR>/engine resolve <N> <id> <action> [--note TEXT]`, using only an action the escalation lists (exit 0 = queued; exit 2 = unknown id or action not allowed, and it prints the allowed ones). The engine applies it on its next tick. Read an agent's screen with `herdr agent read <agent> --source recent --lines 120`; engine agents, their branches and tabs are named after their run: `s<N>-ticket-<n>`, `s<N>-fix-<k>`, `s<N>-review`, `s<N>-e2e` (the last run, `s<N>-follow-ups`, has no agent), merge resolvers `s<N>-resolve-<run>` (e.g. `s7-resolve-ticket-12`). `<SKILL_DIR>/engine status <N>` (`--json` for the raw state) shows every run, the merge queue and all unresolved escalations.

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
| `follow-ups` | After E2E: the reviews found work that belongs in separate issues (details list `f1, f2, …` with category, severity, problem and why separate; ones already open on GitHub are marked and never re-created). Show the user the list and ask which to create. Never create them without the user's answer. | `create-all` / `create-selected --note "f1 f3"` / `discard`; `hand-to-human` while waiting |

`skip-ticket` drops a ticket and everything it blocks; issue it only when the user chooses it. A handed-off escalation disappears from `watch`; track it yourself and resolve it when the user reports back (`engine status <N>` lists it).

# 4. Finish

On `COMPLETE`, relay `report.md` (printed by `watch`) to the user: tickets done, left open and skipped with reasons, pending review findings and dismissed ones (judged false positives by the reviewer; they never keep a ticket open), spec review fixed / still-pending hard / not fixed findings, fix runs, E2E passed / fixed / pending, follow-ups created / already open / discarded (with issue links), and any open or handed-off escalations. The spec branch is local and nothing was pushed; push or open a PR only when the user asks. The spec review and E2E tabs stay open for inspection.

# Stopping

- `<SKILL_DIR>/engine stop <N>`: the engine saves state and exits at its next tick (Ctrl-C in its pane does the same); agents and worktrees stay. `engine run <N>` resumes later.
- `<SKILL_DIR>/engine abort <N>`: only when the user asks. Stops the engine (waits up to 60 s; exit 1 if it does not stop), interrupts its agents, closes resolver panes and removes the worktrees of unfinished runs (branches are kept). Nothing on GitHub is reverted. An aborted run cannot be resumed.
