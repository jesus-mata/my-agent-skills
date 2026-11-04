---
name: spike
description: Runs a time-boxed spike on one technical unknown. It gathers evidence through research, prototypes or a feasibility PoC on a throwaway branch, and writes a report of options and recommendations for /grilling to decide on. Use when a decision is blocked on a question like "can X do Y here", "which architecture or API contract fits", or "is this feasible", or when the user asks for a spike, investigation or proof of concept before committing to a direction.
---

# Spike

A spike is **time-boxed evidence-gathering for a decision someone else makes**. It answers one
question with evidence and recommends a direction. `/grilling` then settles the decisions with
the human, using the report as context, so the grilling spends its time deciding instead of
researching. The spike delivers knowledge, not product: everything it produces lives on a
throwaway branch.

Run a spike in a full session: the main conversation, or a background terminal such as an hc
or herdr agent. The report file is the deliverable, and a subagent started with an Agent tool
is expected to return findings as text instead of writing files. An orchestrator that wants a
spike should start it in a terminal of its own.

Copy this checklist and tick it off:

```
Spike progress:
- [ ] 1. Frame the question, exit criteria and budget
- [ ] 2. Isolate in a worktree on spike/<slug>
- [ ] 3. Gather evidence within budget
- [ ] 4. Write the report
- [ ] 5. Publish the branch (and comment on the issue)
- [ ] 6. Hand off to /grilling
```

## 1. Frame

The input is either a free-text question or an issue reference, which you read with `gh`/`glab`,
comments included. The step is done once you have all four of these:

- **Question**: one sentence ending in a question mark. If the input holds several unknowns,
  pick the one that blocks the decision and list the rest as out of scope.
- **Decision unblocked**: what someone will decide once the question is answered.
- **Exit criteria**: the observable evidence that would count as an answer. For example: "a PoC
  streams a 1 GB file through the real SDK without buffering it all", or "each of the three
  options is costed against our current auth flow".
- **Budget**: S, M or L. Default to M.

| Budget | Research threads | Prototypes / PoCs |
| --- | --- | --- |
| S | up to 2 | none |
| M | up to 3 | 1 |
| L | up to 5 | up to 3 |

A **research thread** is one sub-question investigated against primary sources. If the input
leaves any of the four open, ask the human in one round of at most three questions, each with
your recommended answer. If the input already pins them down, state them and continue. This is
an intake, not a grilling: the open design decisions belong in the report.

## 2. Isolate

Choose a short kebab-case `<slug>` from the question. Fetch, then create a worktree on a new
branch from the latest default branch, next to the repo:

```sh
git fetch origin
git worktree add -b spike/<slug> ../<repo>-spike-<slug> origin/<default-branch>
```

Do all remaining work inside that worktree. That keeps the human's checkout and uncommitted
work exactly as they were. The spike folder is `docs/spikes/<YYYY-MM-DD>-<slug>/` in the
worktree. Use the repo's existing location for spikes or design notes instead if it has one.

## 3. Gather evidence

Pick the **tracks** that can satisfy the exit criteria. A question can use several. Each track
spends budget:

- **Research**: delegate each thread to `/research`
  (`/mattpocock-skills:research`). Tell it to write its notes into the spike folder as
  `research-<topic>.md`. Use it when the answer lives in docs, specs or source code.
- **Prototype**: delegate to `/prototype` (`/mattpocock-skills:prototype`). Use it when the
  question is "does this logic or state model hold up?" or "what should this UI look like?".
  Its rule 6 (fold the validated decision into the real code) is replaced here by the report:
  the decision goes to the grilling.
- **Feasibility PoC**: you own this one. Write the smallest code that runs against the
  *real* dependency, service or codebase and proves or disproves the exit criterion. The
  evidence is the run itself, so record the exact command and its output. Standalone PoCs go in
  `<spike folder>/poc/`. When the PoC has to run inside the real app, edit the app's code in
  place in the worktree.

A prototype or PoC is done once it has proven or disproven its exit criterion with one recorded
run. Bugs it uncovers along the way that don't block that run (a library quirk, a flaky
teardown) go under "Still unknown / risks" with their symptom, not debugged to the root.

Local services a PoC needs (databases, emulators, containers) are named after the spike, for
example `spike-<slug>-pg`, so they never collide with anything else on the machine. Put the
bring-up, run and teardown commands in one script, `poc/run.sh`, so anyone can rerun the PoC
with a single command. Tear the services down before step 4.

Spike code is **throwaway**: no tests, no polish, only enough error handling to run it. Commit
it to `spike/<slug>` as you go. Where subagents are available, run independent research threads
in parallel in the background while you build the PoC. Otherwise work through them in sequence.

Every finding cites its evidence: a source URL, a file path at a commit, or a PoC command with
its output. A claim without evidence goes under "Still unknown" in the report, not under
"Findings".

The step ends on one of three **exits**:

- **Answered**: the exit criteria are met.
- **Inconclusive**: the budget is spent first. This is a valid result. Stop gathering, and
  record what is still unknown and what would settle it.
- **Reframed**: the evidence shows the real question is a different one. If the human is in
  the conversation, ask whether to switch. If not, record the reframing and keep answering the
  original question within budget.

## 4. Write the report

Write `report.md` in the spike folder from [references/report-template.md](references/report-template.md).
It indexes everything else in the folder. The report **recommends**; it does not decide. Every
option the evidence leaves open becomes an entry under "Decisions for grilling", written as a
ready-made grilling question with a recommended answer and the evidence behind it. The step is
done when every finding links to evidence and every open decision appears in that section.

## 5. Publish

Commit the report and push `spike/<slug>` to `origin`. The spike branch is a primary source:
it stays unmerged forever. Decisions reach the default branch only through what the grilling
produces (ADRs, a spec, tickets). If the spike started from an issue, comment on it with the
question, the exit (answered / inconclusive / reframed), the one-line recommendation, and
links to the branch and the report.

## 6. Hand off

Stop here and tell the human:

- the exit, and the recommendation in one or two lines
- the report path in the worktree, plus the command to read it from the branch, which still
  works after the worktree is removed:
  `git show spike/<slug>:docs/spikes/<date>-<slug>/report.md`
- the next command: `/grilling <worktree>/docs/spikes/<date>-<slug>/report.md`
  (`/mattpocock-skills:grilling`)

Leave the worktree in place for the grilling. The human removes it later with
`git worktree remove`, and the branch keeps the report. Starting the grilling is the human's
call, since it needs them present.
