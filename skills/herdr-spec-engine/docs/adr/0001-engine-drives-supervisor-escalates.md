# 1. A coded engine drives the spec; the Claude session only resolves escalations

Date: 2026-10-17

## Status

Accepted

## Context

`herdr-implement-spec` makes one Claude session the scheduler, the retry policy and the
bookkeeper of a multi-hour run. It works out waves, waits on agents, checks that branches have
commits, parses reports by reading the terminal, merges, and decides what to do on every failure.
That is control flow, and an LLM carries it out unreliably over long runs. It loses track of
state, skips checks, re-waits wrongly, and cannot resume after the session dies.

## Decision

A standalone program, the engine, owns every transition of a spec run. It is a Python 3
stdlib-only CLI shipped inside the skill and talks to herdr over its socket API. The Claude
session becomes the supervisor. It starts the engine, then sleeps until the engine raises an
escalation, and resolves it from a closed set of actions. It never chooses the next step.

Judgment the engine cannot make stays with LLMs, but only at defined points. Implementing,
reviewing and resolving conflicts are done by agents the engine starts. Answering a blocked agent
and deciding escalations is the supervisor's job. Agents hand verdicts back as schema-checked
files, never as terminal output to parse.

## Considered options

- **Keep the LLM orchestrator, add more helper scripts.** Rejected: the LLM is still the clock,
  so the failure modes above remain.
- **An "oracle" engine** (`engine next` returns an action; Claude executes it and reports back).
  Rejected for the same reason: the loop still advances only when the LLM remembers to turn it.

## Consequences

Because the engine schedules, **waves are dropped**. A ticket starts as soon as its blockers are
integrated, capped by a concurrency limit. Waves only existed because a human-shaped orchestrator
needed batches.

Integration goes through a **one-at-a-time merge queue**. Each ticket branch absorbs the spec
branch and passes the gate in its own worktree before the spec branch moves, so the spec branch
is never red and no ticket starts from a broken base.

State is persisted after every transition, so a run survives the engine or the supervisor dying
and resumes in place.

The costs are accepted:

- **Flexibility moves into code.** A situation the stage graph does not model becomes an
  escalation, not an improvisation. Handling it permanently means changing the engine.
- **Prompts are templates in the engine.** They are no longer prose the orchestrator adapts per
  ticket, and per-ticket nuance has to be expressed through placeholders.
- **A second implementation exists** alongside `herdr-implement-spec` until this one has proven
  itself on real specs.
