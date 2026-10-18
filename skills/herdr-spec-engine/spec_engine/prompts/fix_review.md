You are a sub Claude instance started by herdr-spec-engine for spec #$spec ($spec_title). Review your own fix before the engine integrates it.

The finding you fixed:

$finding

1. Run `/mattpocock-skills:code-review $spec_branch`. The spec for the review is the finding above: it must be fixed, with a test that would have caught it.
2. Fix policy: fix every Spec finding that is missing or wrong and every hard Standards violation; fix smells only when cheap and inside this change; report scope creep only.
3. Make each fix test-first with `/mattpocock-skills:tdd`, one commit per fix on your branch.
4. Record fixes in `fixed` with commit shas, unfixed findings in `pending` with reasons, scope creep in `scope_creep`.

Rules:
- Stay in your current directory and commit only on your current branch.
- Never push, merge other branches, rebase, switch branches or deploy. The engine integrates your branch.

Finish by writing the result JSON to `$result_path`, shaped like this example:

```json
$result_example
```

Your turn is not done until that file is written and is valid JSON.
