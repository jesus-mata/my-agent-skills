---
name: develop-ticket
description: "Develops a ticket or issue on the current branch: reads it, codes it test-first, validates and commits. Use when a ticket's code must be written on an assigned branch, by hand or from an orchestrator. For the full pipeline to an MR, use /implement-ticket."
argument-hint: <issue-number>
---

# Develop ticket

Implement ticket $ARGUMENTS on the current branch. E2E, review, pushing and merging belong to the caller.

## Steps

1. **Read the ticket's body and comments**, by the origin remote: run both `gh issue view <n>` and `gh issue view <n> --comments`, because `--comments` alone can omit the body, or `glab issue view <n> --comments`. Take its acceptance criteria verbatim. If it lists none, derive checkable statements of observable behaviour from its stated goal. With no derivable goal, stop with `RESULT: BLOCKED`: criteria come from the ticket, never from the diff.
2. **Implement** test-first with `/mattpocock-skills:tdd`, following YAGNI and one-liner solutions. Done when every acceptance criterion is met.
3. **Validate.** Done when a full pass of both checks changes no code.
   - Run the repo's formatter in write mode on the files this ticket changed, then its linter and typecheck. Find their commands in `CLAUDE.md`/`AGENTS.md`, then `package.json`/`Makefile`/`justfile`, then the ecosystem's convention. Fix what they report, and note any tool the repo lacks.
   - Run `/run-tests --integrations`. Fix every `FAIL` tier. A `NOT FOUND` tier is fine while another tier is `PASS`. Stop with `RESULT: BLOCKED` on any `BLOCKED` tier, or if no tier is `PASS`.
4. **Commit** with a conventional commit that references the issue, such as `feat: add export (#42)`.

## Report

End with the acceptance criteria, any tools noted as missing, and a last line of `RESULT: PASS`, `RESULT: FAIL` for a failure you could not resolve, or `RESULT: BLOCKED` with the reason.
