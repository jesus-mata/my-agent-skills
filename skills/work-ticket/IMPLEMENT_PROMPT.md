Work ticket #{{TICKET_ID}}. Run the three phases in order; stop at the
first phase that does not pass and go straight to FINAL OUTPUT. Nobody is
watching this pane: do not ask questions.

Phase launcher — opens the phase in a split pane with its prompt already
filled in, and prints the new pane id:

  {{SKILL_DIR}}/run-phase.sh <review|e2e> {{TICKET_ID}} <PR_NUM> [pane-id]

Write <PR_NUM> as the literal number: shell variables do not survive
between your commands. When the phase agent finishes, its result reaches
you as a new message starting with "[herdr]". After launching a phase, END
YOUR TURN and wait for that message — do not poll, sleep or read its pane.

1. IMPLEMENT
   Run the /implement-ticket skill for #{{TICKET_ID}}.
   Then get PR_NUM by the origin remote: `gh pr view --json number -q
   .number` (GitHub) or `glab mr view -F json | jq .iid` (GitLab).
   Phase result: PASS if a PR/MR exists for this branch and the branch has
   commits ahead of the default branch; otherwise FAIL.

2. REVIEW
   `{{SKILL_DIR}}/run-phase.sh review {{TICKET_ID}} <PR_NUM>`
   Note the pane id it prints. The report ends with a line
   `REVIEW <PASS|FAIL|BLOCKED> — ...`; that verdict is the phase result.
   No such line (the agent stopped early or the watch timed out) → BLOCKED.

3. E2E
   `{{SKILL_DIR}}/run-phase.sh e2e {{TICKET_ID}} <PR_NUM> <review pane id>`
   The report ends with a line `E2E <PASS|FAIL|PARTIAL|BLOCKED> — ...`;
   that verdict is the phase result. No such line → BLOCKED.

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
