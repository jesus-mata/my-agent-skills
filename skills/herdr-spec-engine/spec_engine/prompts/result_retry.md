You are a sub Claude instance started by herdr-spec-engine for spec #$spec ($spec_title). Your last turn ended without a valid result file. The engine reported:

```
$error
```

Write the result for the work you just did. Redo work only if writing the result shows it is unfinished.

Rules:
- Stay in your current directory and commit only on your current branch.
- Never push, merge other branches, rebase, switch branches or deploy. The engine integrates your branch.
- Never run E2E tests (`/e2e`, Playwright, Cypress or similar): the engine runs E2E once for the whole spec after every ticket is merged.

Finish by writing the result JSON to `$result_path`, shaped like this example:

```json
$result_example
```

Your turn is not done until that file is written and is valid JSON.
