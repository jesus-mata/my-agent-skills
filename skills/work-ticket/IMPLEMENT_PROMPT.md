Work ticket #{{TICKET_ID}}. Run the three phases in order; stop at the
first phase that does not pass and go straight to FINAL OUTPUT. Nobody is
watching this pane: do not ask questions.

Phase launcher — opens the phase in a split pane with its prompt already
filled in, waits for it, and prints its result. Copy these forms exactly,
including the REVIEW_LEVEL prefix on the review:

  REVIEW_LEVEL={{REVIEW_LEVEL}} {{SKILL_DIR}}/run-phase.sh review {{TICKET_ID}} <PR_NUM>
  {{SKILL_DIR}}/run-phase.sh e2e {{TICKET_ID}} <PR_NUM> <review pane id>

Write <PR_NUM> as the literal number: shell variables do not survive
between your commands. Run it with the Bash tool's `run_in_background`
flag, then END YOUR TURN: you are woken when it exits, and the phase's
result is in its output. Do not poll, sleep or read the pane meanwhile.

The output starts with `herdr: agent '<name>' (pane <id>) -> <state>`,
then the agent's last turn, then the exact commands to read more, reply,
and keep waiting. By state:

- `done` / `idle` with the verdict line → that is the phase result.
- `done` / `idle` without it → the line may have scrolled out of the
  read. Ask once: `herdr agent prompt <name> "Print your FINAL OUTPUT
  block again, exactly as specified."`, then run the printed
  `wait-agent.sh` command in the background and end your turn. Still no
  line → the phase is BLOCKED.
- `blocked` → it is waiting for input. Read its pane. A routine question
  the ticket, its ACs or TRIAGE RULES answer → answer with `herdr agent
  prompt <name> "<answer>"`, re-run the printed `wait-agent.sh` command
  in the background, end your turn. Anything else → the phase is BLOCKED;
  quote the question in your summary.
- `timeout…` → the phase is BLOCKED.
- No `herdr: agent` line, only a `run-phase:` error → the phase is
  BLOCKED; quote the error in your summary.

1. IMPLEMENT
   Run the /implement-ticket skill for #{{TICKET_ID}}.
   Then get PR_NUM by the origin remote: `gh pr view --json number -q
   .number` (GitHub) or `glab mr view -F json | jq .iid` (GitLab).
   Phase result: PASS if a PR/MR exists for this branch, the branch has
   commits ahead of the default branch, all of them are pushed and the
   working tree is clean (`git status --porcelain` empty); otherwise FAIL.

2. REVIEW
   `REVIEW_LEVEL={{REVIEW_LEVEL}} {{SKILL_DIR}}/run-phase.sh review {{TICKET_ID}} <PR_NUM>`
   Note the pane id in its first output line. The report ends with a line
   `REVIEW <PASS|FAIL|BLOCKED> — ...`; that verdict is the phase result.

3. E2E
   `{{SKILL_DIR}}/run-phase.sh e2e {{TICKET_ID}} <PR_NUM> <review pane id>`
   The report ends with a line `E2E <PASS|FAIL|PARTIAL|BLOCKED> — ...`;
   that verdict is the phase result.

Never merge, never push to the default branch, never close the ticket.

FINAL OUTPUT — the agent that launched you waits for this block and treats
you as still working until it appears. Print it exactly once, as your last
message, also when you stop early. The first line must match exactly:

    TICKET <DONE|FAIL|PARTIAL|BLOCKED> — ticket #{{TICKET_ID}}, PR <url or none>
    Implement: <PASS|FAIL> — <one line>
    Review: <the REVIEW line verbatim, or "not run">
    E2E: <the E2E line verbatim, or "not run">
    ACs: <one line per AC: "ACn — <E2E verdict> — <evidence>", or "not run">
    Tickets: <links created by review and E2E, or none>
    Summary: <one paragraph covering the three phases>

Overall verdict: DONE only if all three phases PASS. FAIL if any phase
FAILed. BLOCKED if any phase was BLOCKED. PARTIAL if E2E was PARTIAL.
