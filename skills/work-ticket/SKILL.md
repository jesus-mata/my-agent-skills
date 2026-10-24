---
name: work-ticket
description: Runs one ticket end to end from inside Herdr. Spawns a Claude agent in its own git worktree that implements the ticket and opens a PR/MR, then code-reviews it and E2E-tests it against the ticket's acceptance criteria, and reports the verdict back. Use when the user, in a Herdr session, wants to work on, implement or ship a single GitHub or GitLab ticket or issue, or validate an implementation against its acceptance criteria. Not for a whole spec or PRD (use herdr-spec-engine) nor outside Herdr (use implement-ticket).
---

# Work a ticket in a Herdr worktree

Requirements. `start-ticket.sh` checks the first three and stops with a
message if one fails:

- Inside Herdr (`HERDR_ENV=1`), with its claude integration up to date
  (`herdr integration status`).
- `git`, `python3`, and `gh` (GitHub) or `glab` (GitLab), authenticated.
- No uncommitted changes to tracked files in the repo checkout.
- The skills the spawned agents load: `/implement-ticket`, `/code-review`,
  `/e2e`, `/to-tickets`.
- `E2E.md` at the repo root, or the E2E phase ends BLOCKED.

## Steps

1. From the repo checkout, run with the Bash tool's `run_in_background`
   flag:

   ```bash
   ~/.claude/skills/work-ticket/start-ticket.sh <TICKET_ID>
   ```

   `<TICKET_ID>` is the issue number: `42`, `#42` or the issue URL. Do not
   modify the command or call `spawn-ticket.sh` directly. The script
   switches to the default branch, pulls, checks the ticket exists, spawns
   the ticket agent on branch `ticket-<TICKET_ID>`, then waits for it.

2. End your turn. The ticket agent runs implement → code review → E2E (see
   IMPLEMENT_PROMPT.md) and stops at the first phase that does not pass.
   You are woken when the script exits, possibly hours later. Do not poll
   its pane.

3. Read the script's output:
   - No line starting `herdr: agent` → it failed before launching. Report
     its `start-ticket:` message to the user and stop.
   - `-> blocked` → the ticket agent is waiting for input. Read its pane.
     A routine question the ticket answers → reply with the `herdr agent
     prompt` command the output prints, run the printed `wait-agent.sh`
     command in the background and end your turn again. Otherwise relay
     the question to the user.
   - `-> timeout…`, or no block starting `TICKET <verdict>` → the agent did
     not finish: read more with the `herdr pane read` command the output
     gives, and report what you find. It is not done.
   - A `TICKET <verdict>` block → if it names a PR/MR, check it before
     trusting it: the PR/MR exists and has commits (`gh pr view <url> --json state,commits`
     or `glab mr view <url>`). If not, the ticket is not done, whatever the
     block says.

4. Post one comment on the PR/MR with the TICKET block (`gh pr comment` or
   `glab mr note`, by the origin remote). Review and E2E already posted
   their own details, so do not repeat them. Then report to the user in
   this shape:

   ```
   Ticket #<id>: <DONE|FAIL|PARTIAL|BLOCKED>
   PR: <url>
   Implemented: <2-3 lines>
   E2E per AC:
   - AC1 — <PASS|FAIL|NOT VERIFIABLE> — <evidence>
   Tickets created: <links or none>
   ```

   Any verdict other than DONE: say explicitly that the ticket is not done,
   and why.

## If something hangs or misbehaves

See README.md, section "Cosas que costaron sangre". It also has the
worktree cleanup commands.
