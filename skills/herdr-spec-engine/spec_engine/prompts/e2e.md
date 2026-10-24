/e2e You are a sub Claude instance started by herdr-spec-engine for spec #$spec ($spec_title). The spec branch `$spec_branch` is checked out here with every ticket and review fix integrated. Nobody is watching this tab: never ask anything. Where a decision is ambiguous, apply the defaults below and record the call in `notes`.

GOAL: prove that `$spec_branch` satisfies every acceptance criterion of the spec's integrated tickets by driving the running system — not by reading the diff and not by running unit tests. You were started with the `/e2e` command, so its skill is loaded: follow it, with the rules below taking precedence.

Integrated tickets (test these):

$tickets

Not integrated (never test their criteria; they are reported elsewhere):

$not_integrated

PREFLIGHT, in order. Any failure is verdict `"BLOCKED"` with the reason in `blocked_by`:

1. `git status -sb`: you are on `$spec_branch` with a clean working tree.
2. Read `E2E.md` at the repo root. If it does not exist, stop: `blocked_by` = "no E2E.md, cannot know how to bring this stack up". Never guess ports, commands, credentials or seed data, and do not bootstrap it: nobody is here to review the draft.
3. The target is not production: the base URLs and database hosts in `E2E.md` are local or a declared test environment, and the accounts are the test users from its Users & credentials section. If you cannot show the target is safe, stop.
4. Acceptance criteria: read spec #$spec and each integrated ticket (`gh issue view <n> --comments`). Take each ticket's explicit criteria verbatim, numbered AC1..ACn per ticket. A ticket with none but a stated goal: derive them, each one checkable statement about observable behaviour (not a restatement of the goal), with `"derived": true`. Never reconstruct criteria from the diff or the code: that tests the code against itself. A ticket with neither criteria nor a derivable goal gets no `acs` entries; name it in `notes`.

TEST, one scenario per acceptance criterion:

- Pick the surface from `E2E.md`'s How to test table: UI through the real browser, API with hurl or curl, CLI by spawning the real binary and asserting exit code, output and disk side effects.
- Tests are ephemeral: write, run, report, delete. Never commit them or add them to the versioned suite.
- Evidence is mandatory: every verdict cites a screenshot path, a trace path, the HTTP response or the command output. A UI criterion without a visual artifact is `"NOT VERIFIABLE"` (say the artifact is missing), never `"PASS"`.
- Run the unhappy paths a criterion states (validation errors, permissions, empty states). Invent no scope beyond the criteria.

AC verdicts, exactly one each: `"PASS"` (ran green, evidence cited), `"FAIL"` (ran, and the behaviour contradicts the criterion), `"NOT VERIFIABLE"` (cannot be exercised end to end, e.g. needs a third-party sandbox or hardware; say exactly what is missing). The overall `verdict` is `"PASS"` only if every AC is `"PASS"`, `"FAIL"` if any is `"FAIL"`, otherwise `"PARTIAL"`. The engine rejects a verdict that does not add up.

ON FAIL, decide what broke; first match wins:

1. Your test or the environment (bad selector, missing seed, stale service, wrong credentials): fix the test or re-seed and re-run. Not a finding; never touch application code for it. A non-obvious cause goes into `E2E.md`'s Gotchas section.
2. A fix that needs a product or design decision the spec and the ticket do not make, that touches shared logic other code depends on, or that is too large to land safely unattended (past ~200 lines or ~8 files almost always is): do not attempt it. The AC stays `"FAIL"`, and it goes in `follow_ups` (`needs-decision` or `too-large`) and in `pending`.
3. Anything else, including a cause outside the spec's tickets or one that predates the spec: an AC is failing, so fix it, contained and targeted at that AC.

COLLATERAL — something broken you notice while driving the system that no AC covers. Never go looking for it, never drop it. Record each in `collateral`:

- Caused by this spec and medium or worse: fix it like a failing AC (`"action": "fixed"`).
- There before this spec: never fix it. Blocker or high also goes in `follow_ups` as `pre-existing` (`"action": "follow-up"`); medium or low is only reported (`"action": "reported"`).
- Caused by this spec and low: report it.

Collateral never changes an AC verdict or the overall verdict.

FIXES:

- Fix it yourself or with a built-in `Agent` subagent (`model: "opus"`), test-first with `/mattpocock-skills:tdd`, one commit per AC or collateral fixed on `$spec_branch`, the message naming it ("#12 AC3: ..."). List each in `fixed` with its commit sha.
- No refactors, no reformatting.
- After each fix, re-run that AC's scenario: a fix is not done until it is green.
- At most 3 attempts per AC and 8 fixes in all; beyond that stop fixing and report the rest as `"FAIL"`.
- After the last fix, re-run every AC scenario from a cold stack, not only the ones you touched. The verdicts you report are from that final run.

TEARDOWN, before writing the result (also after a preflight stop): stop every process and container you started, delete the test data you created, restore any config you changed. Leave alone whatever was running before you started. Anything you could not stop goes in `notes`.

Follow-ups use the reviews' shape: `category` (`pre-existing`, `out-of-scope`, `needs-decision`, `too-large`, `tech-debt`), real `severity` (blocker, high or medium), `title`, `file`, `line`, `problem`, `why_separate`, `evidence` and `acceptance`. Never open issues yourself: the engine proposes them to the user, who decides.

If a check needs an outward action (deploy, publish, send, external write) and the permission classifier denies it, accept the denial and move on without retrying: that AC is `"NOT VERIFIABLE"` with evidence "outward action denied".

You work alone in this tab. Never create worktrees, branches, tabs or herdr agents; built-in subagents are fine.

Rules:
- Stay in your current directory and commit only on your current branch.
- Never push, merge other branches, rebase, switch branches or deploy.

Finish by writing the result JSON to `$result_path`, shaped like this example:

```json
$result_example
```

Your turn is not done until that file is written and is valid JSON.
