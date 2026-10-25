Run start to finish without asking me anything. Where a decision is
ambiguous, apply the defaults below and note the call you made.

You get two messages. This one holds your instructions: do not start the
review yet, do not invoke any skill. Reply only `READY` and end your turn.
The next message is `/code-review {{REVIEW_LEVEL}} {{PR_NUM}}`. It runs the
review in the background, and you are woken when its findings arrive.
Everything below acts on those findings. If the command fails or the skill
isn't available, abort and report BLOCKED.

ACs: establish the ticket's acceptance criteria first, per TRIAGE RULES.
You are the first phase, so if the ticket has none you derive them and
post them on the ticket for the phases that follow.

SEVERITY: Critical / High / Medium / Low, one line of justification each.
Map each finding to the AC it breaks, or "none".

CAUSATION: for every finding, did THIS diff cause it — introduce, regress
or newly expose it? Decide from evidence, not vibes: the PR diff,
`git blame` / `git log -L` on those lines. This answer drives the triage.

TRIAGE — first match wins:

1. PRE-EXISTING — there before this diff, and this diff did not make it
   worse. Route it by the PRE-EXISTING rule in TRIAGE RULES: it is fixed
   only when it breaks an AC, ticketed or documented otherwise.

2. TICKET (no code change) if any TICKET CRITERION holds, regardless of
   severity.

3. FIX if Medium or above AND this diff caused it. This holds even when
   the fix is outside the ticket's scope and breaks no AC — a Medium+
   bug, regression or defect that this diff caused gets fixed here, not
   deferred. A contained blast radius is enough; it does not have to be
   in the ticket's scope to be worth fixing now. This is the expected
   outcome for most findings: turning a contained, diff-caused Medium+
   finding into a ticket is the exception, and you must justify it
   against a named TICKET CRITERION.

4. DOCUMENT only if Low. Do not touch the code. Exception: a Low finding
   that reveals a real structural problem is a TICKET — no code change.

CONFLICT — a finding that breaks an AC and did not end up fixed, whatever
rule sent it there: do not attempt the fix, end the phase FAIL. Applies to
pre-existing findings too — a missed AC is missed no matter who broke it.

TICKETS: rules 1, 2 and 4 produce ticket candidates, not tickets. Finish
triage first, then follow TRIAGE RULES to dedup and create them.

DEFAULTS when unsure:

- Severity borderline → the higher one.
- Unclear whether an AC breaks → treat as breaking, EXCEPT for a
  pre-existing finding, where unclear means not breaking.
- Unclear whether this diff caused it → check `git blame` before
  guessing. Still unclear → pre-existing, routed by rule 1.
- Unclear whether an out-of-scope fix is worth it, and it is contained
  and diff-caused → fix it.
- Cap at 20 fixes; beyond that, document the remainder and say the cap
  was hit. The ticket cap is in TRIAGE RULES.

FIXES:

- One commit per finding, message references the finding ID.
- A fix outside the ticket's scope gets its commit subject prefixed
  `out-of-scope: <finding ID> ...`, so a human can tell ticket work from
  a fix this diff forced.
- No reformatting and no refactors. Edits outside the PR's diff are
  allowed ONLY for a fix that passed rule 3, and must stay minimal and
  targeted at that finding.
- After each fix, re-read the file to confirm the change landed.
- After all fixes: run the repo's build, then its test suite. Discover
  both from CLAUDE.md / AGENTS.md, package.json scripts, Makefile or the
  CI config — first hit wins. If you cannot find either one, report which
  and skip it. Never invent a command.

ABORT CONDITIONS — stop, revert nothing, report state, do not push:

- The ticket has no ACs and no derivable goal (see TRIAGE RULES).
- Build or tests fail and the cause isn't obvious from your own change.
- A fix already in progress turns out to need a product decision you
  can't make from the ACs alone, and reverting it would leave the branch
  inconsistent. A finding that needs such a decision BEFORE you touch it
  is not an abort — it is the DECISION criterion, so ticket it and carry
  on.
- More than 3 fixes fail verification.

PUSH the commits to the PR/MR branch once build and tests are green.
Never push to the default branch, never merge, never close the ticket. If
an abort condition hit, leave the commits local and say so.

REPORTING via gh (GitHub) or glab (GitLab) — pick by the origin remote:

- Line-anchored comment on each fixed finding: what changed and why, and
  for an out-of-scope fix, what in this diff caused it.
- One summary comment, with links throughout: in-scope fixes;
  out-of-scope fixes as their own block, so the PR's growth beyond the
  ticket is explicit; tickets created, each naming the TICKET CRITERION
  that sent it there; candidates deduped into an existing ticket;
  documented-only findings with rationale, pre-existing ones marked as
  such; and any defaults you applied under ambiguity.

FINAL OUTPUT — print exactly this block as your last message, so the
agent that launched you can parse it. The first line must match exactly:

    REVIEW <PASS|FAIL|BLOCKED> — ticket #{{TICKET_ID}}, PR #{{PR_NUM}}
    Findings: <n> critical / <n> high / <n> medium / <n> low
    Fixed: <n> in-scope, <n> out-of-scope
    Ticketed: <n>   Deduped: <n>   Documented: <n>
    Build: <result>   Tests: <result>   Pushed: <shas or none>
    Tickets: <one per line: "<link> — <TICKET CRITERION>", or none>
    Deduped into: <links or none>
    Blocked by: <abort condition or none>

FAIL when a finding hit the CONFLICT rule. BLOCKED when an abort
condition stopped the run. Otherwise PASS.
