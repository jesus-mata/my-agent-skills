---
name: refine-ticket
description: Rewrites an existing ticket in place so it matches the /to-tickets format, after syncing the default branch and falsifying the ticket's technical claims against the latest code, and sharpens its domain language with /domain-modeling. Use whenever the user wants to update, refine, clean up, reformat or "fix" a ticket or issue, wants the open questions in a ticket resolved, mentions /to-tickets or the ticket template, or just hands over a ticket number and says it needs work — even when they never name the format. Also use when a ticket came out of an autonomous code review and needs to be made implementable.
disable-model-invocation: true
---

# Refine Ticket

A ticket is an instruction for someone who won't have this conversation. A false claim in a ticket
costs far more than the same claim in chat, because the next reader treats it as settled fact.
Reformatting a ticket without checking what it asserts just gives a wrong instruction better
typography.

Tickets that need refining usually hide three defects under the formatting problem:

- **Unverified mechanism.** Especially from an autonomous reviewer. The _symptom_ is almost always
  real; the _explanation_ is a plausible story told from reading the code, and plausible and true
  diverge more often than they look.
- **Open decisions in disguise.** A "Proposed resolution" listing three options is not a
  resolution. Whoever picks the ticket up either guesses or stalls.
- **Fuzzy domain language.** A ticket that says "account" when the glossary distinguishes Customer
  from User, or invents a name for an existing concept, forces every reader to translate — and some
  will translate wrong.

Copy this checklist and tick it off as you go. Phase 4 is the one that earns the skill its keep.

```
Refine progress:
- [ ] 1. Sync the default branch (READ_FROM=<ref>)
- [ ] 2. Read the ticket, its comments, its edges, the glossary and ADRs
- [ ] 3. Explore the code on the right branch
- [ ] 4. Falsify every checkable claim
- [ ] 5. Sharpen the domain language (/domain-modeling)
- [ ] 6. Separate real decisions from deducible details; ask only the real ones
- [ ] 7. Rewrite with references/template.md
- [ ] 8. Publish in place and verify the published body
- [ ] 9. Report what changed
```

## 1. Sync the default branch

Every claim gets checked against the latest code, never a stale checkout. Run exactly:

```bash
<SKILL_DIR>/sync-default-branch.sh
```

`<SKILL_DIR>` is the directory this `SKILL.md` lives in. The script fetches `origin`, and if the
tracked files are clean it switches to the default branch (usually `main`) and pulls `--ff-only`.
With uncommitted changes it leaves the working tree alone. Either way its last line is
`READ_FROM=<ref>`: read the code from that ref for the rest of the skill (`git show <ref>:<path>`,
`git grep <pattern> <ref>` when it is `origin/<default>`).

If the script fails, report its `sync-default-branch:` message and stop — do not fall back to
whatever happens to be checked out.

## 2. Read the whole ticket and everything it hangs off

Fetch the body _and_ the comments (`gh issue view <N> --comments`) — decisions often live only in
comments. Then follow its edges: parent and sibling tickets, the PR it was found in, the ADRs it
cites. A ticket raised from a review of PR #N is a child of that PR's ticket, and its siblings
usually carve up the same area; reading them stops you from writing overlapping scope.

Read the domain model too: `GLOSSARY.md` (or `CONTEXT.md` in older repos; `GLOSSARY-MAP.md` points
to per-context glossaries) and `docs/adr/`. Note every term in the ticket that the glossary defines
differently, doesn't define, or flags under _Avoid_.

## 3. Explore the code the ticket describes — on the right branch

By default that is `READ_FROM` from phase 1. The exception: if the ticket was raised against an open
PR, **the code it describes is not on the default branch yet.** Read it where it lives
(`git fetch origin <branch>` then `git show origin/<branch>:<path>`). Finding the described code
absent from `main` is not evidence the ticket is wrong; it is evidence you read the wrong tree. Do
check whether the PR has merged since the ticket was written — then `READ_FROM` is right after all.

Note what already exists nearby, because it changes what you can ask for: patterns the codebase
already uses, tests that already cover the area, whether the fix would be the first of its kind in
this repo. That last one is worth stating in the ticket — "this would be the first X in the backend"
tells the implementer they have no local precedent to copy.

## 4. Falsify every checkable claim

List the ticket's factual assertions, then try to break each one. Do not confirm them — confirmation
bias reads a claim, finds code that matches it, and stops.

Checkable claims look like "the database does X under Y", "this guard doesn't cover Z", "this path
is only reachable from W", "no caller handles this case", "this is what the user sees". Each has a
cheap falsifier:

- **Read the cited code** at `READ_FROM` — the claim often paraphrases code that says something
  narrower, or code that has changed since.
- **Query the real database** through whatever access the project has, for claims about data.
- **Write a throwaway reproduction** for claims about runtime or engine semantics. A disposable
  container and a script settle in one run what an hour of reasoning leaves at "probably". Tear the
  container down afterwards.
- **Run the test that already exists** — a claimed bug that is covered and passing is itself the
  answer.

**When a claim survives**, state it in its strongest form and say how it was checked when the check
is reproducible, so the next reader doesn't re-litigate it.

**When a claim breaks**, do not quietly drop it. The corrected mechanism goes in the body, and the
trailer records that it was corrected against the original report. Someone will remember the old
explanation; give them a reason to update rather than a contradiction.

The most valuable outcome looks like a small correction and isn't: the symptom is real, the
mechanism is wrong, and **the conditions under which it actually fires differ from the ones the
ticket describes**. That flips what the implementer should reproduce and what the regression test
should assert. Watch for a mechanism that would fire far more often than the reported frequency, or
far less — the mismatch usually means a missing condition.

If a claim can't be checked with what you have, write it as unverified and say what would settle it.

## 5. Sharpen the domain language

If phase 2 found no term conflicts and the ticket introduces no new concept, use the glossary's
terms as they are and move on.

Otherwise load **/domain-modeling** (`/mattpocock-skills:domain-modeling`) and follow it for every
term the ticket gets wrong or leaves fuzzy: challenge it against the glossary, propose the canonical
term, probe the boundary with a concrete scenario, and cross-check the code at `READ_FROM`. Resolve
these with the user in the same round as phase 6's questions, not in a separate interview. When a
term is resolved, update the glossary as that skill describes, and use the canonical term in the
ticket.

Leave glossary and ADR edits uncommitted in the working tree and list them in the report — the user
decides whether they land with this ticket, in their own commit, or not at all.

## 6. Separate the real decisions from the deducible details

After phases 3–5 most "open questions" collapse. A question is a real decision only if two answers
lead to materially different work and the codebase doesn't already imply one. Everything else —
naming, which test layer, whether to keep an existing message — you decide and state.

For the real decisions: **prose first, questions second.** Lay out the options against each other —
what each buys, what it costs, what it forecloses — and give a recommendation. Then ask, with your
recommendation first. Multiple-choice up front makes the user pick between labels before they have
the trade-offs.

Include the decisions the format forces even when the ticket doesn't raise them: what proves the work
is done, what's deliberately out of scope, whether the blocking edge is real.

When a decision is hard to reverse, surprising without context, and the result of a real trade-off,
offer an ADR per /domain-modeling. Missing any of the three, skip it.

If nothing genuinely open is left, don't manufacture an interview. Rewrite and publish.

## 7. Rewrite

Read [references/template.md](references/template.md) before writing — it holds the template and the
section-by-section traps, and most rewrites hit at least one.

Two things carry across from the original ticket without a labelled slot: the **analysis** (impact,
blast radius, why it matters) goes inside _What to build_ as subsections, and the **provenance**
("found in the review of #N") goes in a short trailer.

Preserve what was already right. A title that still describes the problem exactly stays as it is.
Rewriting for the sake of visible change destroys the reviewer's ability to see what you changed.

## 8. Publish in place and verify

Same ticket, new body — never a new ticket, and never touch the parent. Write the body to a file
outside the repo first, so a shell-quoting accident can't mangle it, then on GitHub:

```bash
gh issue edit <N> --body-file <file>
diff <(gh issue view <N> --json body -q .body) <file>
```

Add only labels the user agreed to. Any diff beyond trailing whitespace means the publish mangled
the body: fix the file, publish again, and re-run the diff until it is clean.

If the tracker isn't GitHub or `gh` isn't available, tell the user exactly where the finished body
file is and what to do with it, and don't claim it was published.

## 9. Report what changed

Not "updated the ticket", but:

- which claims were verified, and how
- which claims broke, and what replaced them
- which decisions are now fixed, and which the user settled
- which glossary terms or ADRs changed (uncommitted, with paths)
- the commit the code was checked at (`READ_FROM`)

That report is how the user checks your work without rereading the whole ticket.

## Adapting to the repo

Nothing in this skill hardcodes a language, a label vocabulary, or a tracker. Take those from the
repo:

- **Language and register** of the body: match the existing tickets, not your default. Many repos
  keep section headers in English while the prose is in another language — follow what's there.
- **Domain vocabulary**: the glossary and ADRs, sharpened in phase 5.
- **Labels**: only ones that exist on the tracker, and only with the user's agreement — a label like
  `ready-for-agent` claims the ticket is safe to hand to an autonomous agent, which is only true once
  phases 4–6 came out clean.
