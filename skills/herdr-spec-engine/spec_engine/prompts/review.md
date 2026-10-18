You are a sub Claude instance started by herdr-spec-engine for spec #$spec ($spec_title). Review your own work on ticket #$ticket (`gh issue view $ticket`) before the engine integrates it.

1. Run `/mattpocock-skills:code-review $spec_branch`. The spec for the review is ticket #$ticket, part of spec #$spec.
2. Fix policy:
   - Fix every Spec finding that is missing or wrong.
   - Fix every hard Standards violation.
   - Fix smells only when cheap and inside this ticket.
   - Scope creep: report it only, leave the code as it is.
3. Make each fix test-first with `/mattpocock-skills:tdd` (failing test, then fix), one commit per fix on your branch.
4. Record each fix in `fixed` with its commit sha, each finding you did not fix in `pending` with the reason, and scope creep in `scope_creep`.

Rules:
- Stay in your current directory and commit only on your current branch.
- Never push, merge other branches, rebase, switch branches or deploy. The engine integrates your branch.

Finish by writing the result JSON to `$result_path`, shaped like this example:

```json
$result_example
```

Your turn is not done until that file is written and is valid JSON.
