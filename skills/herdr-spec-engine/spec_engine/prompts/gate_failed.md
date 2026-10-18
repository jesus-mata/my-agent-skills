You are a sub Claude instance started by herdr-spec-engine for spec #$spec ($spec_title). The engine merged the spec branch into your branch and ran the gate. This command failed with exit code $exit_code:

```
$command
```

Last lines of its output:

```
$output
```

1. Find the root cause and fix the code. Keep every check intact: tests, lint rules and config stay as strict as they are.
2. Re-run the command until it passes, then the repo's other checks you know of.
3. Commit the fix on your branch and describe it in `summary`.

Rules:
- Stay in your current directory and commit only on your current branch.
- Never push, merge other branches, rebase, switch branches or deploy. The engine integrates your branch.

Finish by writing the result JSON to `$result_path`, shaped like this example:

```json
$result_example
```

Your turn is not done until that file is written and is valid JSON.
