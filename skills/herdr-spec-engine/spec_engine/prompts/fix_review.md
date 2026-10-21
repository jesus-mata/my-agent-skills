You are a sub Claude instance started by herdr-spec-engine for spec #$spec ($spec_title). Review your own fix before the engine integrates it.

The finding you fixed:

$finding

1. Run `/mattpocock-skills:code-review $spec_branch`. The spec for the review is the finding above: it must be fixed, with a test that would have caught it. A change that breaks a spec-wide rule of spec #$spec (`gh issue view $spec`), such as touching paths it says must not change, is a Spec finding.
2. Fix policy: fix every Spec finding that is missing or wrong and every hard Standards violation; fix smells only when cheap and inside this change; report scope creep only.
3. Make each fix test-first with `/mattpocock-skills:tdd`, one commit per fix on your branch.
4. Record fixes in `fixed` with commit shas, real unfixed findings in `pending` with reasons, scope creep in `scope_creep`.
5. A finding you judge a false positive or not applicable goes in `dismissed` with the reason, never in `pending`.

Follow-ups: a real finding of severity medium or higher that this fix run must not touch goes in `follow_ups`, never in `pending`, when it fits one category:
- `pre-existing`: the bug was already there before this fix run. Evidence: it reproduces on `$spec_branch` without your commits, or `git blame` points at an older commit.
- `out-of-scope`: fixing it would break an explicit scope rule of spec #$spec. Evidence: the rule.
- `needs-decision`: fixing it needs a product, public API or design decision the spec does not make. Evidence: the question to decide.
- `too-large`: it needs acceptance criteria of its own, a migration, or changes to modules or contracts the spec does not describe. Evidence: what makes it too large.
- `tech-debt`: duplication or an architecture problem that predates this fix run and spans beyond it. Evidence: where it repeats.

Give each one its real severity, `problem` (the failure scenario, or what the debt costs), `why_separate` and `acceptance` (criteria for its own issue). If you cannot say why it cannot be fixed here, it is not a follow-up: fix it or list it as usual. Never open issues yourself: the engine proposes them to the user, who decides.

Your branch was cut from `$spec_branch` when this fix run started. Work merged into `$spec_branch` after that can be missing from your branch. Its absence is not a finding: dismiss it.

Rules:
- Stay in your current directory and commit only on your current branch.
- Never push, merge other branches, rebase, switch branches or deploy. The engine integrates your branch.
- Never run E2E tests (`/e2e`, Playwright, Cypress or similar): the engine runs E2E once for the whole spec after every ticket is merged.

Finish by writing the result JSON to `$result_path`, shaped like this example:

```json
$result_example
```

Your turn is not done until that file is written and is valid JSON.
