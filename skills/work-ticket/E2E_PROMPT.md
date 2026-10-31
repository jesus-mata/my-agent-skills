Run start to finish without asking me anything. Nobody is watching this
pane. Where a decision is ambiguous, apply the defaults below and note
the call you made.

GOAL: prove that the code on this branch satisfies every acceptance
criterion of the ticket, by driving the running system — not by reading
the diff and not by running unit tests.

You were launched with the /e2e command, so its skill is already loaded:
follow it. These instructions may reach you as a file named in that
command's arguments. If no e2e instructions were loaded, abort and report
that.

PREFLIGHT — all four, in order. Any failure here is an abort:

1. You are in the ticket worktree, on the PR branch, working tree clean.
   Confirm with `git status -sb`. Never test the default branch.
2. Establish the ticket's ACs per TRIAGE RULES. The review phase runs
   before you, so if the ticket had none it has already derived a set
   and posted it there — reuse that comment verbatim rather than
   deriving your own. A derived AC is tested and reported exactly like a
   written one; say in the report which set you used. No ACs and no
   derivable goal is an abort: report BLOCKED.
3. Read E2E.md at the repo root. IF IT DOES NOT EXIST: stop. Report
   BLOCKED — "no E2E.md, cannot know how to bring this stack up". Do not
   guess ports, commands, credentials or seed data. Do not bootstrap it.
4. Confirm the target is NOT production: the base URL / DB host in
   E2E.md must be local or a declared test environment, and the accounts
   must be the test users from its Users & credentials section. If you
   cannot prove the target is safe, stop and report BLOCKED.

TEST — one scenario per AC, no exceptions:

- Pick the surface from E2E.md's How to test table. UI change → drive it
  with Playwright through the real browser. Backend/API-only → hurl or
  curl. CLI-only → spawn the real binary and assert exit code, output
  and disk side effects.
- Tests are EPHEMERAL: write, run, report, delete. Do not add them to
  the versioned suite and do not commit them.
- Evidence is mandatory. Every AC verdict cites something: a screenshot
  path, a trace path, the HTTP response, the command output. A UI AC
  with no visual artifact is NOT VERIFIABLE (say the artifact is
  missing), never PASS.
- Also run the ticket's unhappy paths if the ACs state any (validation
  errors, permissions, empty states). Do not invent extra scope beyond
  the ACs.

VERDICT per AC — exactly one of:

- PASS — scenario ran green, evidence cited.
- FAIL — scenario ran and the behaviour contradicts the AC.
- NOT VERIFIABLE — cannot be exercised end to end (needs a third-party
  sandbox, manual hardware, etc.). Say precisely what is missing.

Overall result is PASS only if every AC is PASS. One NOT VERIFIABLE
makes the overall result PARTIAL.

ON FAIL — first, decide what actually broke. First match wins:

1. YOUR TEST or the environment (bad selector, missing seed, stale
   service, wrong credentials). Fix the test / re-seed and re-run. This
   is not a finding — do not touch application code for it. If the cause
   was non-obvious, add it to E2E.md's Gotchas section.
2. TICKET (no code change) if any TICKET CRITERION holds. Do not attempt
   the fix, mark that AC FAIL, link the ticket in the report.
3. FIX — everything else, including when the cause sits outside the
   ticket's scope, and including a pre-existing cause: an AC is failing,
   so the PRE-EXISTING rule in TRIAGE RULES sends it here too. Keep the
   fix contained and targeted at that AC.

COLLATERAL — something you see broken while driving the system that no AC
covers. Never go looking for it; never discard it either:

- Caused by this diff and Medium or worse → FIX it, same rules as above.
  A runtime regression the review phase could not see is what this phase
  is for. Counts against the fix cap.
- Pre-existing → no AC is involved by definition, so the PRE-EXISTING
  rule never fixes it: Critical or High is a ticket candidate, Medium or
  Low is reported only.
- Any TICKET CRITERION holds → ticket candidate.
- Caused by this diff and below Medium → report it. No fix, no ticket.

Collateral never changes an AC verdict or the overall verdict.

FIXES:

- One commit per AC fixed, message references the AC ("AC3: ...").
- No refactors and no reformatting. Edits outside the PR's scope are
  allowed only for a fix that passed triage; prefix that commit subject
  `out-of-scope: ...` so a human can tell ticket work from a fix this
  run forced.
- After each fix, re-run that AC's scenario. A fix is not done until
  its scenario is green.
- Max 3 fix attempts per AC, max 8 fixes total. Beyond that, stop
  fixing and report the remainder as FAIL. The ticket cap and the dedup
  pass that must precede any ticket are in TRIAGE RULES.
- After all fixes: re-run the FULL set of AC scenarios from a cold
  stack, not just the ones you touched. Report that final run.
- PUSH the commits to the PR branch. Never push to the default branch,
  never merge, never close the ticket.

TEARDOWN — before FINAL OUTPUT, also after an abort: stop every process
and container you started (servers, test doubles, databases), delete the
test data you created, and restore any untracked config you changed.
Leave untouched whatever was already running before you started. List
in the report anything you could not stop.

ABORT CONDITIONS — stop, revert nothing, report state, do not push:

- Preflight failed (see above).
- The stack does not come up after 2 attempts following E2E.md exactly.
- A fix already in progress turns out to need a product decision you
  cannot make from the ACs alone, and reverting it would leave the
  branch inconsistent. A failure that needs such a decision BEFORE you
  touch it is not an abort — it is the DECISION criterion, so ticket it,
  mark that AC FAIL and carry on with the remaining ACs.
- More than 3 fix attempts on the same AC.
- Any step would touch production or real user data.

REPORTING via gh|glab — one comment on the PR, one on the ticket:

- A table: AC | verdict | evidence | what was done.
- Fixes applied (commit shas), out-of-scope and pre-existing-cause ones
  marked as such; collateral findings and what you did with each;
  tickets created (with links), each naming the TICKET CRITERION that
  sent it there; candidates deduped into an existing ticket (with
  links); gotchas written back into E2E.md.
- Any default you applied under ambiguity, and any abort condition hit.

FINAL OUTPUT — print exactly this block as your last message, so the
agent that launched you can parse it. The first line must match exactly:

    E2E <PASS|FAIL|PARTIAL|BLOCKED> — ticket #{{TICKET_ID}}, PR #{{PR_NUM}}
    ACs: <n> passed / <n> failed / <n> not verifiable
    <one line per AC: "ACn — <PASS|FAIL|NOT VERIFIABLE> — <evidence path or output>">
    Fixes pushed: <shas or none>   Collateral: <n> fixed / <n> reported
    Tickets: <links or none>   Deduped into: <links or none>
    Blocked by: <reason or none>
