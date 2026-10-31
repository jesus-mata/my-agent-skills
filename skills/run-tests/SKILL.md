---
name: run-tests
description: Runs the project's existing test suites on the current branch or worktree and reports a verdict per tier. Use to run the tests or check for regressions, by hand or from another skill. Not for writing tests or proving acceptance criteria (use /e2e).
argument-hint: "[--integrations] [--e2e]"
context: fork
---

# Run tests

Run complete suites against the working tree exactly as it stands, uncommitted changes included, and report. Source and tests stay untouched: fixing belongs to the caller.

Arguments: $ARGUMENTS

Tiers: **unit** always, **integration** with `--integrations`, **e2e** with `--e2e`.

## Steps

1. **Find each tier's command**, stopping at the first source that names it: `CLAUDE.md`/`AGENTS.md`, `E2E.md` (e2e only), `package.json`/`Makefile`/`justfile`, then the ecosystem's convention. A tier with no command is `NOT FOUND`.
2. **Prepare.** If dependencies are missing, as in a fresh worktree, install them from the lockfile (`npm ci`, `uv sync --frozen`). If a tier needs a service that is down, start it only by a method the repo documents. A service that stays down makes its tier `BLOCKED`.
3. **Run each tier once, in order, unfiltered.** Every requested tier runs, even after an earlier one fails. Each tier gets a verdict:
   - `PASS`: exit code 0 with at least one test run.
   - `FAIL`: the code failed the suite: tests failed, it would not compile or collect, or a check such as a coverage threshold failed.
   - `BLOCKED`: the environment stopped the suite (service down, install failed, tool missing).
   - `NOT FOUND`: no command, or the runner found no tests and reported no error.
4. **Stop the services you started.**
5. **Report** in the format below, as your final message. Done when every requested tier has a verdict and every failing test is listed.

## Report

```
Branch: <branch> @ <short-sha> (<clean | uncommitted changes>)

unit: PASS, 212 passed, 0 failed
integration: FAIL, 40 passed, 2 failed
e2e: NOT FOUND

Failures:
- integration: <test name> (<file:line>)
  <error, up to 5 lines>

RESULT: FAIL
```

The last line is `RESULT: FAIL` if any tier is `FAIL`, otherwise `RESULT: BLOCKED` if any tier is `BLOCKED` or `NOT FOUND`, otherwise `RESULT: PASS`. List only the requested tiers.
