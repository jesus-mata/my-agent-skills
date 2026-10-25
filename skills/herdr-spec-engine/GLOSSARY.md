# herdr-spec-engine

Implementing every ticket of a spec with parallel coding agents, where a deterministic engine owns
the control flow and a Claude session only supervises. This glossary is separate from the
installation language in the repository's root `CONTEXT.md`.

## Language

### Work

**Spec**:
The parent issue describing a body of work. It is never implemented itself; its tickets are.
_Avoid_: PRD, epic, parent ticket

**Ticket**:
A sub-issue of a spec, and the unit of work handed to one agent.
_Avoid_: Slice, task, child issue

**HITL ticket**:
An open ticket of a spec labeled `ready-for-human`. A human must do it before its dependents can
start.
_Avoid_: Manual ticket

**Unrefined ticket**:
An open ticket of a spec labeled neither `ready-for-agent` nor `ready-for-human`. Nobody may work
on it until it is labeled.
_Avoid_: Unlabeled ticket, draft

**Blocker**:
A ticket that must be integrated into the spec branch before another ticket may start.
_Avoid_: Dependency, prerequisite

**Plan**:
The validated graph of a spec's tickets and their blockers that a run executes.
_Avoid_: Waves, implementation graph, schedule

**Spec branch**:
The branch every ticket of one spec is integrated into, and the only branch the engine moves.
_Avoid_: Feature branch, integration branch

### Control

**Engine**:
The program that executes a plan, deciding every transition from outcomes alone.
_Avoid_: Orchestrator, workflow, state machine (as a name)

**Supervisor**:
The Claude session that starts the engine and resolves its escalations. It never decides
transitions.
_Avoid_: Orchestrator, main agent, driver

**Ticket run**:
One ticket's journey through the stages, from claiming it to closing it.
_Avoid_: Subworkflow, job, pipeline

**Fix run**:
A ticket run with no ticket of its own, created by the engine for a hard finding from spec review.
_Avoid_: Fix ticket, hotfix

**Follow-up**:
A review or E2E finding, medium or higher, that the reviewed work must not fix and that deserves its own
issue: pre-existing, out of scope, needing a decision, too large, tech debt, or deferred (a
medium finding its review chose not to fix). The engine
proposes follow-ups to the user at the end of a run and creates only the issues the user
confirms.
_Avoid_: Out-of-scope finding, backlog item, TODO

**Stage**:
One named state of a ticket run, such as Implement, Review or Integrate.
_Avoid_: Node, step, phase

**Outcome**:
The result a stage ends with, which alone selects the next stage.
_Avoid_: Result, status, exit code

**Retry budget**:
How many times a stage may be re-attempted before its run escalates.
_Avoid_: Max retries, attempts

**Escalation**:
An outcome the engine cannot resolve, handed to the supervisor with a closed set of allowed
resolutions. Only the escalated run and its dependents wait.
_Avoid_: Error, failure, interrupt

### Integration

**Merge queue**:
The one-at-a-time line through which ticket and fix runs reach the spec branch.
_Avoid_: Merge step

**Gate**:
The repository's checks (install, lint, type check, format, build, tests) that a run must pass
before the spec branch moves.
_Avoid_: CI, checks, verification

**Resolver**:
The agent the engine starts in a run's worktree to settle a merge conflict, ending in `RESOLVED` or
`ESCALATE`.
_Avoid_: Conflict subagent
