# The ticket format, section by section

The template is `/to-tickets`'. It is reproduced here rather than read from the installed plugin,
because plugin paths carry version numbers and break on upgrade.

```markdown
## Parent

A reference to the parent ticket (omit the section entirely if there is none).

## What to build

The end-to-end behaviour this ticket makes work, from the user's perspective — not layer-by-layer
implementation.

## Acceptance criteria

- [ ] Criterion 1
- [ ] Criterion 2

## Blocked by

- A reference to each blocking ticket, or "None — can start immediately".
```

No file paths and no code snippets: both go stale within weeks, and a ticket that cites a path
someone renamed reads as if it were written about a different codebase. The one exception is content
that pins a decision more precisely than prose can — a state machine, a schema, a type shape, or a
result table from a reproduction. Trim it to the decision-rich part.

## What to build

Open with the behaviour, in one paragraph, from outside the system: what someone does, what happens
now, what should happen instead. If the reader stops after that paragraph they should still know
what "done" looks like.

Then the analysis the original ticket carried, as `###` subsections. The two that usually earn their
place:

- **Why it fails, precisely.** The verified mechanism from phase 3 — including the condition that
  makes it fire, which is the part unverified tickets get wrong. If a claim was corrected, this is
  where the corrected version lives.
- **What's deliberately out of scope**, with the reason. Without it the implementer either widens
  the ticket or worries they missed something. "Not necessary for the user to stop seeing X" is a
  complete reason.

Say the *why* behind non-obvious constraints. "The sweep must not take new locks" is an order; "the
sweep must not take new locks, because it runs over every tenant on a timer and blocking there stalls
all of them" is something the implementer can reason with when your instruction meets a case you
didn't foresee.

## Acceptance criteria

Each criterion is a behaviour someone can observe, not an implementation to perform.

- Implementation: `[ ] Use FOR UPDATE when re-reading the row`
- Behaviour: `[ ] The re-read returns the row even when the update changed no values`

The difference matters because the second survives a different-but-correct implementation, and
because it names the exact case that is broken. Criteria phrased as implementation get ticked by
someone who did the edit without ever reproducing the bug.

Aim for criteria that cover, in whatever order fits:

- The behaviour that was broken, in the specific condition that breaks it
- The behaviour that must **not** change — regressions are what reviewers forget to ask for
- The error path, when the ticket touches one: what the user is told when it can't be done
- What proves it — if the mechanism is subtle, say what kind of test settles it and why a weaker one
  doesn't. "A double returning null isn't enough here: what's under test is the engine's semantics,
  not the service's contract."
- The project's own bar for green (the suite, the typecheck) when the change is risky

## Blocked by

A blocking edge means the work genuinely cannot start, not that two tickets are related. An open PR
where the described code lives is a judgement call — often the ticket can be built on that branch,
which makes it unblocked with a note rather than blocked. Ask rather than assume.

## Trailer

Keep the provenance in two or three lines after a rule: where the ticket was found, and — when
phase 3 changed something — that the mechanism was corrected against the original report and how it
was checked. Someone who read the old body needs a reason to re-read it.

---

# Worked example

A ticket claimed a 500 came from a transaction's read view being fixed before another transaction
committed the row, so the re-read couldn't see it.

Reproducing it against the real database showed the explanation was wrong in general: the engine
documents that a transaction which *updates* rows committed by another does see them, and a two-
session repro confirmed the re-read returned the row. The 500 was real, but it needed one more
condition the ticket never mentioned — the update had to change **no values**, so the engine never
re-versioned the row and it stayed outside the read view.

That correction changed the ticket in three ways, and it is the shape to aim for:

1. **The reproduction instructions inverted.** The ticket's motivating scenario — two operators at
   once, typing different addresses — is precisely the case that does *not* fail. The one that does
   is a double submit with an identical body.
2. **The acceptance criteria moved** onto the real condition: "the re-read returns the row also when
   the rewrite changed no values — the only case that fails today."
3. **One proposed option stopped being a guess.** The blocking-read fix was observed working in the
   broken scenario, so the ticket states it as verified rather than proposed.

The two-line result table from the repro went into the body, because it pins the condition in a way
prose kept blurring — the permitted exception to "no snippets".
