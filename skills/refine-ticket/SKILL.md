---
name: refine-ticket
description: Rewrites an existing ticket in place so it matches the /to-tickets format, after syncing the default branch and falsifying the ticket's technical claims against the latest code, sharpens its domain language with /domain-modeling, and labels it ready-for-agent once nothing is left open. Use whenever the user wants to update, refine, clean up, reformat or "fix" a ticket or issue, wants the open questions in a ticket resolved, mentions /to-tickets or the ticket template, or just hands over a ticket number and says it needs work — even when they never name the format. Also use when a ticket came out of an autonomous code review and needs to be made implementable.
disable-model-invocation: true
---

# Refine Ticket

A ticket is an instruction for someone who won't have this conversation; they treat every claim in it
as settled fact. Tickets that need refining usually hide three defects under the formatting:

- **Unverified mechanism.** The _symptom_ is usually real; the _explanation_ is a plausible story told
  from reading the code, and often wrong.
- **Open decisions in disguise.** A "Proposed resolution" listing three options is not a resolution.
- **Fuzzy domain language.** A term the glossary defines differently, or a new name for an existing
  concept.

Copy this checklist and tick it off. Phase 4 earns the skill its keep.

```
Refine progress:
- [ ] 1. Sync the default branch (READ_FROM=<ref>)
- [ ] 2. Read the ticket, its comments, its edges, the glossary and ADRs
- [ ] 3. Explore the code on the right branch
- [ ] 4. Falsify every checkable claim
- [ ] 5. Sharpen the domain language (/domain-modeling)
- [ ] 6. Settle the real decisions with the user
- [ ] 7. Rewrite with references/template.md
- [ ] 8. Publish in place, verify, label
- [ ] 9. Report
```

## 1. Sync the default branch

Run `<SKILL_DIR>/sync-default-branch.sh` (`<SKILL_DIR>` is this file's directory). It fetches `origin`
and fast-forwards the default branch when the tree is clean, or leaves a dirty tree alone. Its last
line is `READ_FROM=<ref>`: read all code from that ref (`git show <ref>:<path>`, `git grep <pattern>
<ref>`). If it fails, report its `sync-default-branch:` message and stop.

## 2. Read the ticket and everything it hangs off

`gh issue view <N> --comments` — decisions often live only in comments. Follow its edges: parent and
sibling tickets, the PR it was found in, cited ADRs. Siblings carving up the same area tell you what
scope is already taken.

Read `GLOSSARY.md` (or `CONTEXT.md`; `GLOSSARY-MAP.md` points to per-context glossaries) and
`docs/adr/`. Note every ticket term the glossary defines differently, lacks, or lists under _Avoid_.

## 3. Explore the code — on the right branch

Read from `READ_FROM`, except when the ticket was raised against an open PR: then the code lives on
that PR's branch (`git fetch origin <branch>`, `git show origin/<branch>:<path>`) unless the PR has
merged since. Code missing from `main` means you read the wrong tree, not that the ticket is wrong.

Note nearby patterns, existing tests, and whether the fix would be the first of its kind in the repo —
worth stating in the ticket, since it tells the implementer there is no local precedent.

## 4. Falsify every checkable claim

List the ticket's factual assertions and try to _break_ each one; confirming finds matching code and
stops. Cheap falsifiers:

- **Read the cited code** at `READ_FROM` — it often says something narrower, or has changed.
- **Query the real database** for claims about data.
- **Run a throwaway reproduction** (disposable container + script) for runtime or engine semantics;
  tear it down afterwards.
- **Run the existing test** — a claimed bug that is covered and passing is the answer.

A claim that **survives** goes in its strongest form, with how it was checked. A claim that **breaks**
is replaced in the body and the trailer records the correction against the original report.

The most valuable finding: the symptom is real but **the conditions under which it fires differ** from
the ticket's. That flips what to reproduce and what the regression test asserts. A mechanism that would
fire far more or far less often than reported usually means a missing condition.

A claim you can't check is written as unverified, with what would settle it.

## 5. Sharpen the domain language

No term conflicts and no new concept → use the glossary's terms and move on. Otherwise load
**/domain-modeling** (`/mattpocock-skills:domain-modeling`) for each fuzzy term: propose the canonical
term, probe its boundary with a concrete scenario, cross-check the code. Ask these in phase 6's round.
Update the glossary as that skill describes and leave glossary/ADR edits **uncommitted**.

## 6. Settle the real decisions with the user

A question is a **real decision** only if two answers lead to materially different work and the code
doesn't already imply one. Everything else — naming, test layer, wording — you decide and state.
Include the decisions the format forces: what proves it's done, what's out of scope, whether the
blocking edge is real.

For each real decision, **prose first**: options against each other (what each buys, costs,
forecloses) and a recommendation; then ask, recommendation first. Offer an ADR per /domain-modeling
only for a decision that is hard to reverse, surprising without context, and a real trade-off.

Nothing genuinely open → skip the interview. An answer of "decide later" leaves that decision open.

## 7. Rewrite

Read [references/template.md](references/template.md) first — the template and its traps. The body
names behaviour and concepts, never file paths or code (the template has the one exception). Analysis
(impact, why it matters) goes as subsections of _What to build_; provenance ("found in the review of
#N") goes in a short trailer. Keep what was already right, including a title that still fits — gratuitous
rewrites hide your real changes from the reviewer.

## 8. Publish in place, verify, label

Same ticket, new body; never a new ticket, never touch the parent. Write the body to a file outside the
repo, then:

```bash
gh issue edit <N> --body-file <file>
diff <(gh issue view <N> --json body -q .body) <file>
```

Any diff beyond trailing whitespace: fix the file, publish again, re-diff until clean.

Then the **ready gate**. The ticket is _ready_ when every real decision is settled (by the user or
deducible from the code), every checkable claim was verified or corrected, and every term conflict is
resolved. Being blocked by another ticket does not affect readiness.

- **Ready** → `gh issue edit <N> --add-label ready-for-agent`.
- **Not ready** → no `ready-for-agent` (remove it if present), and the report lists each open item.

Add other labels only with the user's agreement, and only labels that exist on the tracker. If
`ready-for-agent` doesn't exist there, say so instead of creating it.

Not on GitHub or no `gh`: give the user the body file's path and what to do with it, and don't claim it
was published or labelled.

## 9. Report

- claims verified, and how
- claims broken, and what replaced them
- decisions fixed, and which the user settled
- glossary/ADR changes (uncommitted, with paths)
- `READ_FROM` commit
- the ready gate: `ready-for-agent` applied, or the open items keeping it off

## Adapting to the repo

Take language, register and label vocabulary from the repo, not your defaults: match existing tickets
(many keep section headers in English with prose in another language), and use the glossary and ADRs
for domain terms.
