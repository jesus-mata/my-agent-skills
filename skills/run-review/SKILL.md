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
   - **Diff:** a `<start>` and `<end>`. For a commit range, its two ends. For a PR target, the base and head SHAs from `gh pr view` or `glab mr view`, by the origin remote, both fetched without checking out; if you cannot fetch them, Standards and Spec are blocked. A path or an empty target has no range to review, so Standards and Spec report `skipped (not a commit range or PR)` and only `/code-review` runs in step 2.
   - **Spec:** `--spec` if given, otherwise every issue the PR body closes. Read an issue's body and comments, by the origin remote: run both `gh issue view <n>` and `gh issue view <n> --comments`, because `--comments` alone can omit the body, or `glab issue view <n> --comments`. Spec is blocked if one of these specs cannot be read, or if `--spec` comes with a path or an empty target.
2. **Start every review not blocked**; both already run in sub-agents.
   - Invoke `/code-review high <target>`, with the target as its only argument besides the level. It runs in the background and its findings arrive in a later notification.
   - Invoke `/mattpocock-skills:code-review` with `<start>` as the fixed point, and these instructions:

     ```
     Review `<end>`, whatever HEAD is: use `git diff <start>...<end>` and `git log <start>..<end>`, and read files with `git show <end>:<path>`. Run git from the current directory, as `git <command>`, and name any denied command in your report. Put this in both sub-agent briefs.
     Spec: <the spec, "search for it", or "skip the Spec sub-agent">. If you find no spec, report "no spec available" for the Spec axis and carry on without asking.
     End both sub-agent briefs with: "Do not invoke /code-review or spawn additional agents: perform this review directly."
     ```

     Its report is input to step 3, so these steps continue after its summary line.

   Done when every review started has finished or failed. A review that is unavailable or fails blocks its axes; the other review still runs to the end, and its findings go through steps 3 and 4. A denied command that stopped a sub-agent reading what it needed blocks that axis too.
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

<the layout below, or: blocked: <reason>>

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

<the same layout, or: skipped (not a commit range or PR) | blocked: <reason>>

## Spec

<the same layout, or: no spec available | skipped (not a commit range or PR) | blocked: <reason>>

RESULT: FAIL
```

List only the groups that have findings, and leave out `Worst` when an axis has none. Every axis always appears, so a blocked run still shows the findings of every review that finished.

The last line is `RESULT: BLOCKED` if any axis is blocked, otherwise `RESULT: FAIL` if any axis has a Critical or High finding, otherwise `RESULT: PASS`. A skipped axis and dismissed findings never affect it.
