---
name: run-review
description: Runs `/code-review high` and `/mattpocock-skills:code-review`, then classifies every finding per axis (Bugs, Standards, Spec) as Critical, High, Medium or Low, ending in a PASS/FAIL/BLOCKED verdict. Use when review findings need a severity or a verdict, by hand or from another skill.
argument-hint: "[PR number | commit range | path] [--spec <issue | path>]"
---

# Run review

Review a change on three axes and report classified findings. **Bugs** comes from `/code-review`; **Standards** and **Spec** come from `/mattpocock-skills:code-review`. Code, tickets and PRs stay untouched: acting on the findings belongs to the caller.

Arguments: $ARGUMENTS (the target, empty meaning the current diff, plus an optional `--spec`)

## Steps

1. **Prepare the Standards and Spec inputs.**
   - **Diff:** for a commit range, the range as given. For a PR target, take the base and head SHAs from `gh pr view` or `glab mr view`, by the origin remote, fetch both without checking out, and use `<base sha>...<head sha>`; if you cannot fetch them, report `RESULT: BLOCKED`. A path or an empty target has no range to review, so Standards and Spec report `skipped (not a commit range or PR)` and only `/code-review` runs in step 2.
   - **Spec:** `--spec` if given, otherwise an issue the PR body closes. Read an issue's body and comments, by the origin remote: run both `gh issue view <n>` and `gh issue view <n> --comments`, or `glab issue view <n> --comments`. If a `--spec` cannot be read, or the target is a path or empty, report `RESULT: BLOCKED`.
2. **Start both reviews**, which already run in sub-agents.
   - Invoke `/code-review high <target>`, with the target as its only argument besides the level. It runs in the background and its findings arrive in a later notification.
   - Invoke `/mattpocock-skills:code-review` with the fixed point, which is the start of the diff, and these instructions:

     ```
     Review `<diff>`, whatever HEAD is: use `git diff <diff>` and `git log <diff>`, and read files at its end with `git show <end>:<path>`. Put this in both sub-agent briefs.
     Spec: <the spec, or "search for it">. If you find no spec, report "no spec available" for the Spec axis and carry on without asking.
     End both sub-agent briefs with: "Do not invoke /code-review or spawn additional agents: perform this review directly."
     ```

     Its report is input to step 3, so these steps continue after its summary line.

   Done when both reports are in. If either skill is unavailable or its review fails, report `RESULT: BLOCKED`, naming the review.
3. **Classify every finding**, each under the axis that reported it. Read the code at its `file:line` as it stands in the target, and weigh its failure scenario or cited rule or spec line; review findings can be uncertain. For a PR target, read with `git show <sha>:<path>` and `git blame <sha>`. Give it exactly one outcome with a one-line justification, and keep every finding in the report. Done when each one has an outcome.
   - **Not an issue**: the code disproves the finding, or the cited rule or spec line does not say what it claims.
   - **Pre-existing**, for Bugs and Standards: `git blame` shows it predates the change, and the change does not make it worse. On the Spec axis, a requirement the change leaves unmet is a finding, however old the code around it.
   - Otherwise, one severity from the list below.
4. **Report** in the format below, as your final message.

## Severity

- **Critical**: data loss, a security hole, an outage, or a crash on a main path.
- **High**: wrong behaviour on a common path, a missing, partial or broken requirement, or a hard Standards violation.
- **Medium**: a real bug limited to an edge case or with a small blast radius, or scope creep.
- **Low**: a minor issue or cleanup with no user-visible effect, or a Standards judgement call such as a code smell.

A borderline finding takes the higher level.

## Report

The axes stay separate, so a pass on one cannot mask a failure on another: findings are never merged or ranked across axes. An issue found on two axes stays in both, each with a `See also` line.

```
Target: <PR, branch, path or current diff>

## Bugs

Critical
- <file:line, or the spec line for a missing requirement> <summary>
  Why: <justification>
  See also: <axis>, <file:line>

High
- ...

Dismissed
- <file:line> <summary> (Not an issue | Pre-existing)
  Why: <justification>

Findings: <n> critical / <n> high / <n> medium / <n> low / <n> dismissed
Worst: <file:line> <summary>

## Standards

<the same layout, or: skipped (not a commit range or PR)>

## Spec

<the same layout, or: no spec available | skipped (not a commit range or PR)>

RESULT: FAIL
```

List only the groups that have findings, and leave out `Worst` when an axis has none. A blocked run reports only the target, the reason and the last line.

The last line is `RESULT: BLOCKED` if a review that should have run did not, `RESULT: FAIL` if any axis has a Critical or High finding, otherwise `RESULT: PASS`. A skipped axis and dismissed findings never affect it.
