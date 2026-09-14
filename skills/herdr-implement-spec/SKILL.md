---
name: herdr-implement-spec
description: "Implement every ticket of a spec/PRD by orchestrating parallel Claude instances in herdr worktrees, wave by wave, merging each into a spec branch. Use when the user hands you a spec or PRD (or its GitHub issue) and wants its linked issues or slices implemented, not just a single ticket."
---

Implements the spec given, or the spec GitHub issue provided, by orchestrating Claude agents with herdr to implement the spec's issues.
Your goal is to orchestrate the Claude agent panes and implement all tickets to complete the spec.

Requires: the `herdr` CLI, an authenticated `gh`, Claude Code, and the `/implement-ticket` skill available to the sub-agents.

- The spec issue is just the spec; the related issues or slices are the work to be implemented.
- Pass every new Claude instance minimal context, so it knows what is being done and that it is a sub Claude instance.

Follow the workflow below:

# Setup

- `git checkout main && git pull`
- create a new branch used for the whole spec (the "spec branch")
- Read the spec issue and get the list of issues related to the spec to work on and to get its order of implementation and dependencies to build a graph of implementation. Make sure the issues belong to the spec. Ignore closed tickets.
- Only work on issues labeled `ready-for-agent`
- Group the graph into **waves**: a wave is the set of open tickets whose blockers are all closed (or already merged into the spec branch). Every ticket in a wave runs in parallel; the next wave starts only when the whole current wave is merged.

# Implementation

Work wave by wave. For every ticket in the current wave do steps 1–3 (fan out), then step 4 once for the wave (wait), then steps 5–7 per ticket.

1. Assign the ticket to the current GitHub user so it is clear it is being implemented and owned by you.
2. Create a worktree with herdr in this workspace. The name of the worktree is `ticket-<TICKET_ID>`, based on the spec branch so it contains the previous waves.
   - 2a. `herdr worktree create --cwd "$PWD" --branch "ticket-<TICKET_ID>" --base "<SPEC_BRANCH>" --label "ticket-<TICKET_ID>" --no-focus --json` to create the git worktree. Inspect the output and get the PANE_ID from `result.root_pane.pane_id`. If the branch already exists, `herdr worktree create` fails — use `herdr worktree open --branch "ticket-<TICKET_ID>"` instead.
   - 2b. `herdr agent start ticket-<TICKET_ID> --kind claude --pane <PANE_ID> --timeout 60000 -- --permission-mode auto --model opus` to start the claude agent in the pane tab. Do not use `--dangerously-skip-permissions`: the auto-mode classifier refuses to launch it, while `--permission-mode auto` runs unattended with the same guardrails.
3. Fan out: prompt the agent and return immediately — **do not use `--wait` here**, it blocks the shell and serializes the wave.
   - `herdr agent prompt ticket-<TICKET_ID> "use /implement-ticket <TICKET_ID>"`
   - The prompt must include, in one or two sentences: that it is a sub Claude instance, the spec issue, the branch it is on and what the spec branch already contains, which sibling tickets run in parallel, that it must keep changes scoped to its own components/tests, and that it must commit on its branch and not push, merge, switch branches or deploy.
   - If several tickets of the wave touch the same shared file (an index, a router, a registry, a config), tell each agent exactly where its piece goes in that file so the merges are trivial.
4. Wait for the whole wave with one polling loop over all its agents. `WAVE` lists the agent names of the current wave (`ticket-<TICKET_ID>` for each ticket in it). Run the loop with the Bash tool's `run_in_background` flag so you are woken when it exits instead of blocking:

   ```bash
   WAVE="ticket-<TICKET_ID_1> ticket-<TICKET_ID_2> ..."; DEADLINE=$((SECONDS + 3600))
   sleep 15   # an agent can still report idle right after the prompt is submitted
   while [ $SECONDS -lt $DEADLINE ]; do
     pending=""
     for a in $WAVE; do
       s=$(herdr agent get "$a" | python3 -c 'import sys,json; print(json.load(sys.stdin)["result"]["agent"]["agent_status"])')
       case "$s" in done|idle|blocked) echo "$a: $s" ;; *) pending="$pending $a" ;; esac
     done
     [ -z "$pending" ] && exit 0
     sleep 30
   done
   echo "timeout, still pending:$pending"; exit 1
   ```

   - `done` or `idle`: the agent finished its turn. Read its summary with `herdr agent read ticket-<TICKET_ID>` and check the branch has commits (`git log --oneline <SPEC_BRANCH>..ticket-<TICKET_ID>`) and a clean tree.
   - `blocked`: the agent is waiting for input (a permission prompt or a question). Read the pane with `herdr agent read`; answer it with `herdr agent prompt` if it is a routine decision, otherwise hand off to a human. Re-enter the loop for that agent afterwards.
   - If an agent reports an acceptance criterion it could not complete because the classifier denied an outward action (deploy, publish, send, external write), do not retry it yourself: comment on the ticket, leave it open for the human, and keep going with the tickets that do not depend on it.
5. Merge each ticket branch of the wave into the spec branch, one at a time: `git merge --no-ff ticket-<TICKET_ID>`.
   - 5.1. If conflicts, resolve them if possible, otherwise hand off to a human and wait for the conflicts being resolved. Expect trivial conflicts in shared files edited by every ticket of the wave (imports, registrations, entries in a list or config): combine both sides in the order the spec defines.
   - 5.2. After the last merge of the wave, run the project's install, lint/type check, format check, build and full test suite on the spec branch (use whatever scripts the repo defines). Fix formatting yourself; hand anything else back to the responsible ticket's agent with a follow-up prompt.
6. Close the ticket with a comment pointing at its merge commit, and remove its worktree: `herdr worktree remove --workspace <WORKSPACE_ID>` (the id comes from `result.workspace.workspace_id` in step 2a).
7. Compute the next wave from the graph and repeat.

# Important

- If multiple tickets can be implemented in parallel, do it: fan out first, wait once for the whole wave. Never wait on agents one by one.
- If there are conflicts when merging a worktree branch, resolve them yourself if they are trivial. If the changes affect a big chunk of code, change important logic significantly, or are too complex, hand off to a human to resolve them.
- If there are HITL tickets next in the graph order, hand the ticket off to a human and wait for it to be completed. Once the human completes the HITL ticket, resume the work.
- When every ticket is merged, report which tickets are closed, which stay open and why, and that the spec branch is local; push and open a PR only when asked.
