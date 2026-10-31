---
name: run-review
description: Runs `/code-review high` and classifies every finding as Critical, High, Medium or Low, ending in a PASS/FAIL/BLOCKED verdict. Use when review findings need a severity or a verdict, by hand or from another skill.
argument-hint: "[PR number | commit range | path]"
---

# Run review

Review a change and report classified findings. Code, tickets and PRs stay untouched: acting on the findings belongs to the caller.

Target: $ARGUMENTS (empty means the current diff)

## Steps

1. **Review.** Invoke `/code-review high <target>`, with the target as its only argument besides the level. It runs in the background and its findings arrive in a later notification; these steps resume when they do. If the skill is unavailable or the review fails, report `RESULT: BLOCKED` with the reason.
2. **Classify every finding.** Read the code at its `file:line` as it stands in the target, and weigh its failure scenario; review findings can be uncertain. For a PR target, fetch the PR's head without checking it out and read with `git show <sha>:<path>` and `git blame <sha>`; if you cannot fetch it, report `RESULT: BLOCKED`. Give it exactly one outcome with a one-line justification, and keep every finding in the report. Done when each one has an outcome.
   - **Not a bug**: the code disproves the failure scenario.
   - **Pre-existing**: `git blame` shows it predates the change, and the change does not make it worse.
   - Otherwise, one severity from the list below.
3. **Report** in the format below, as your final message.

## Severity

- **Critical**: data loss, a security hole, an outage, or a crash on a main path.
- **High**: wrong behaviour on a common path, or a broken requirement.
- **Medium**: a real bug limited to an edge case or with a small blast radius.
- **Low**: a minor issue or cleanup with no user-visible effect.

A borderline finding takes the higher level.

## Report

```
Target: <PR, branch, path or current diff>

Critical
- <file:line> <summary>
  Why: <justification>

High
- ...

Dismissed
- <file:line> <summary> (Not a bug | Pre-existing)
  Why: <justification>

Findings: <n> critical / <n> high / <n> medium / <n> low / <n> dismissed

RESULT: FAIL
```

List only the groups that have findings. A blocked run reports only the target, the reason and the last line.

The last line is `RESULT: BLOCKED` if the review did not run, `RESULT: FAIL` if any finding is Critical or High, otherwise `RESULT: PASS`. Dismissed findings never affect it.
