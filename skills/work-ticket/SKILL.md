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

1. From the repo checkout, run:

   ```bash
   ~/.claude/skills/work-ticket/start-ticket.sh <TICKET_ID>
   ```

   `<TICKET_ID>` is the issue number: `42`, `#42` or the issue URL. Do not
   modify the command or call `spawn-ticket.sh` directly. The script
   switches to the default branch, pulls, checks the ticket exists, and
   spawns the ticket agent on branch `ticket-<TICKET_ID>`. It returns in
   ~10 s. If it exits non-zero, report its message to the user and stop.

2. End your turn. The ticket agent runs implement → code review → E2E (see
   IMPLEMENT_PROMPT.md) and stops at the first phase that does not pass.
   Its result arrives as a new message starting with `[herdr]`, possibly
   hours later. Do not poll its pane.

3. When it arrives, find the block starting `TICKET <verdict>`. If the
   message reports state `timeout…` or has no such block, the agent did not
   finish: read more with the `herdr pane read` command the message gives,
   and report what you find. It is not done.

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
