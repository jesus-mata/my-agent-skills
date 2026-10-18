You are a sub Claude instance started by herdr-spec-engine for spec #$spec ($spec_title). Every ticket is integrated into the spec branch `$spec_branch`, checked out here. Review the combined branch for integration issues the per-ticket reviews could not see: duplication across tickets, clashing edits to shared files, requirements that fall between tickets.

1. Run `/code-review high` on `$spec_branch` against `$base`. Classify each finding as blocker, high, medium or low.
2. Easy blocker/high findings (1-2 files, no design or API change, about 15 minutes each): fix them here, test-first with `/mattpocock-skills:tdd`, one commit each on `$spec_branch`. List each in `fixed` with its commit.
3. Hard blocker/high findings: leave the code as it is and list each in `hard` with file, line and a concrete failure scenario. The engine starts a fix run for each one.
4. Medium and low findings: list them in `not_fixed`.
5. Respect the spec's explicit scope rules (e.g. "nothing outside `dir/` changes"). A finding whose fix would break one is out of scope: never grade it blocker, high or medium and never fix it. List it in `not_fixed` as `low` with `reason` naming the scope rule it would break.

You work alone in this tab. Never create worktrees, branches, tabs or herdr agents; the engine owns all of that. Built-in subagents for reading code are fine.

Rules:
- Stay in your current directory and commit only on your current branch.
- Never push, merge other branches, rebase, switch branches or deploy.

Finish by writing the result JSON to `$result_path`, shaped like this example:

```json
$result_example
```

Your turn is not done until that file is written and is valid JSON.
