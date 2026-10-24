TRIAGE RULES — what counts as an acceptance criterion, how to handle a
pre-existing finding, when to open a ticket instead of fixing, and how.
These apply to the code review phase and the E2E phase alike.

ACCEPTANCE CRITERIA — "AC" everywhere below means the ticket's acceptance
criteria, written or derived. Establish them before anything else:

1. Read the ticket — `gh issue view {{TICKET_ID}} --comments` or `glab
   issue view {{TICKET_ID}} --comments`, by the origin remote. Take explicit ACs verbatim and
   number them AC1..ACn.
2. No explicit ACs, but the ticket states a goal, objective or problem to
   solve → derive the criteria from it. Each must be one checkable
   statement about observable behaviour, not a restatement of the goal.
   Number them the same way and mark the set DERIVED.
3. A derived set binds exactly like a written one: it drives the triage,
   an unfixed break of it fails the phase, and a pre-existing bug
   blocking it gets fixed.
4. Post a derived set as a comment on the ticket, marked derived, so
   later phases and a human work from the same list. If the ticket
   already carries such a comment from an earlier phase, use it verbatim
   and do not derive your own.
5. No ACs and no derivable goal — bare title, empty body, a one-liner
   like "fix login" → stop and report BLOCKED: "ticket states no
   acceptance criteria and no derivable goal". Never reconstruct them
   from the diff or the PR description; that validates the code against
   itself.

PRE-EXISTING — the finding was there before this diff, and this diff did
not make it worse. Route it by whether it breaks one of the ticket's ACs:

- Breaks an AC → FIX it. An AC that cannot pass is this ticket's problem
  no matter who caused it. Unless a TICKET CRITERION holds, in which case
  ticket it, do not attempt the fix, and the AC stays failed.
- Does not break an AC → never fix it, however cheap it looks. Critical
  or High → ticket candidate. Medium or Low → document only, no ticket.
- Unclear whether it breaks an AC → treat it as NOT breaking. A weak AC
  link is not licence to edit code this PR never touched.

A fix whose cause was pre-existing says so in its commit body.

TICKET CRITERIA — ticket it, do not fix, if ANY holds:

- SHARED — the fix touches shared logic, business rules or architecture:
  anything other code depends on for its behaviour.
- DECISION — the fix needs a product or design decision you cannot make
  from the ticket and its ACs alone.
- TOO LARGE — the fix is too large to land safely with nobody watching.
  Size is a hint, not a trigger: past ~200 lines or ~8 files it is almost
  always this; below that, size alone is never a reason to ticket.

Unclear whether a fix is contained or cross-cutting → treat it as
cross-cutting, so ticket.

Ticket contents, via /to-tickets: problem summary, impact analysis,
proposed resolution, and why it was not fixed this session.

NEVER CREATE ONE BLIND. Collect every ticket candidate first, then run ONE
dedup pass over the whole list before creating anything.

Delegate that pass to a subagent via your Agent tool: read-only, one spawn
for the whole list, not one per candidate. Give it each candidate's title,
one-line summary, and the files or symbols involved. It searches OPEN
issues only, on the tracker the origin remote points at (`gh issue list
--state open --search ...` or `glab issue list --state opened --search
...`), several ways — by symptom, by file or symbol, by component — not
one keyword guess. It returns per candidate COVERED by #N (same issue, or
the fix falls inside that ticket's scope) or NEW, and flags candidates
that duplicate each other. It creates, comments and edits nothing.

- NEW → create it.
- COVERED by #N → no new ticket. Comment on #N: what this PR surfaced,
  the finding detail, a link to the PR, and that it recurred. Report it
  as "deduped → #N".
- Candidates duplicating each other → one ticket covering both.
- Uncertain or partial overlap → treat as NEW, and name the relation in
  the body ("may overlap #N"). A duplicate beats a lost finding.

CAP: 3 tickets. Deduped candidates do not count against it. Beyond the
cap, document the remainder and say the cap was hit — hitting it means
you are over-ticketing, so re-check those candidates for a contained fix
first.
