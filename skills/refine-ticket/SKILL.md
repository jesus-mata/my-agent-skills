---
name: refine-ticket
description: Rewrite an existing ticket in place so it matches the /to-tickets format, falsifying its technical claims against the real code before trusting any of them. Use whenever the user wants to update, refine, clean up, reformat or "fix" a ticket or issue, wants the open questions in a ticket resolved, mentions /to-tickets or the ticket template, or just hands you a ticket number and says it needs work — even when they never name the format. Also use when a ticket came out of an autonomous code review and needs to be made implementable.
disable-model-invocation: true
---

# Refine Ticket

A ticket is an instruction aimed at someone who won't have this conversation. That is the whole
reason this skill is more than a reformatter: a false claim inside a ticket costs far more than the
same claim in chat, because the next person reads it as settled fact and builds on it. Prettifying a
ticket without checking what it asserts just gives a wrong instruction better typography.

Tickets that need refining usually arrive with two defects, and both are invisible under the
formatting problem:

- **Unverified mechanism.** Especially in tickets written by an autonomous reviewer. The _symptom_ is
  almost always real — someone saw the 500, the wrong total, the empty list. The _explanation_ is a
  plausible story told from reading the code. Plausible and true diverge more often than they look.
- **Open decisions wearing a disguise.** A "Proposed resolution" listing three options is not a
  resolution. Whoever picks the ticket up either guesses, or stalls.

Work the phases in order. Phase 3 is the one that earns the skill its keep.

## 1. Read the whole ticket and everything it hangs off

Fetch the body _and_ the comments — decisions often live only in comments. Then follow its edges:
parent and sibling tickets, the PR it was found in, the ADRs it cites, the glossary. A ticket raised
from a review of PR #N is a child of that PR's ticket, and its siblings usually carve up the same
area; reading them stops you from writing overlapping scope.

## 2. Explore the code the ticket describes — on the right branch

If the ticket was raised against an open PR, **the code it describes is not on the default branch.**
Read it where it lives (`git show <branch>:<path>`, or fetch the branch first). Reading `main` and
finding the described code absent is not evidence the ticket is wrong; it is evidence you read the
wrong tree.

Note what already exists nearby, because it changes what you can ask for: patterns the codebase
already uses, tests that already cover the area, whether the fix would be the first of its kind in
this repo. That last one is worth stating in the ticket — "this would be the first X in the backend"
tells the implementer they have no local precedent to copy.

## 3. Falsify every checkable claim

List the ticket's factual assertions, then try to break each one. Do not confirm them — try to make
them fail. Confirmation bias reads a claim, finds the code that matches it, and stops.

What counts as checkable: "the database does X under Y", "this guard doesn't cover Z", "this path is
only reachable from W", "no caller handles this case", "this is what the user sees". Each has a cheap
falsifier:

- **Read the cited code** — the claim often paraphrases code that says something narrower.
- **Query the real database** through whatever access the project has, for claims about data.
- **Write a throwaway reproduction** for claims about runtime or engine semantics. A disposable
  container and a script are minutes of work, and they settle in one run what an hour of reasoning
  leaves at "probably". Tear the container down afterwards.
- **Run the test that already exists** — sometimes the claimed bug is already covered and passing,
  which is itself the answer.

**When a claim survives**, say so in the ticket in its strongest form, and mention how it was
checked when the check is reproducible — that is what stops the next reader from re-litigating it.

**When a claim breaks**, do not quietly drop it. The corrected mechanism goes in the body, and a line
at the end records that it was corrected against the original report. Someone will remember the old
explanation; leave them a reason to update rather than a contradiction.

The most valuable outcome of this phase is the one that looks like a small correction and isn't: the
symptom is real, the mechanism is wrong, and **the conditions under which it actually fires are
different from the ones the ticket describes**. That flips what the implementer should reproduce and
what the regression test should assert. Watch specifically for a mechanism that would fire far more
often than the reported frequency, or far less — the mismatch usually means a missing condition.

If a claim can't be checked with what you have, write it as unverified rather than as fact, and say
what would settle it.

## 4. Separate the real decisions from the deducible details

After phases 2 and 3 most "open questions" collapse. What's left is a real decision only if two
answers lead to materially different work and the codebase doesn't already imply one. Everything
else — naming, which test layer, whether to keep an existing message — you decide and state.

For the real decisions: **prose first, questions second.** Lay out the options against each other in
running text — what each buys, what it costs, what it forecloses — and give a recommendation.
Multiple-choice up front makes the user pick between labels before they have the trade-offs. Once the
comparison is on the table, ask, and put your recommendation first.

Include the decisions the ticket itself doesn't raise but the format forces: what proves the work is
done, what's deliberately out of scope, whether the blocking edge is real.

If nothing genuinely open is left, don't manufacture an interview. Rewrite and publish.

## 5. Rewrite

Use the template and the section-by-section guidance in `references/template.md`. Read it before
writing — the traps are specific and most rewrites hit at least one.

Two things to carry across from the original ticket, since the template has no slot labelled for
them: the **analysis** (impact, blast radius, why it matters) belongs inside _What to build_ as
subsections, and the **provenance** ("found in the review of #N") belongs in a short trailer.

Preserve what was already right. A title that still describes the problem exactly stays as it is.
Rewriting for the sake of visible change destroys the reviewer's ability to see what you changed.

## 6. Publish in place

Same ticket, new body — never a new ticket, and never touch the parent. On GitHub that is
`gh issue edit <N> --body-file <file>` plus any label the user agreed to; write the body to a file
first so a shell-quoting accident can't mangle it.

If the tracker isn't GitHub or the CLI isn't available, write the finished body to a file, tell the
user exactly where it is and what to do with it, and don't pretend it was published.

Then report what actually changed — not "updated the ticket", but which claims were verified, which
broke and what replaced them, and which decisions are now fixed. That report is how the user checks
your work without rereading the whole ticket.

## Adapting to the repo

Nothing in this skill hardcodes a language, a label vocabulary, or a tracker. Take those from the
repo you're in:

- **Language and register** of the body: match the existing tickets, not your default. Many repos
  keep section headers in English while the prose is in another language — follow what's there.
- **Domain vocabulary**: use the project glossary (`CONTEXT.md`, `AGENTS.md`, `CLAUDE.md`) and the
  ADRs. A ticket that invents a new name for an existing concept forces every reader to translate.
- **Labels**: only ones that exist on the tracker, and only with the user's agreement — a label like
  `ready-for-agent` is a claim that the ticket is safe to hand to an autonomous agent, which is only
  true once phases 3 and 4 came out clean.
