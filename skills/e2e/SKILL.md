---
name: e2e
description: Bring up the local stack and end-to-end test a change — web app, HTTP API, CLI, or desktop app — driven by the project's root E2E.md. Use it when you need to verify that something actually works, not just that it compiles or that the unit tests pass.
---

# e2e

Drive the real thing and show evidence. This skill is the **procedure**; every
project-specific fact — services, ports, credentials, seed data, gotchas — lives
in **`E2E.md` at the repo root**. Never hardcode a project fact here.

Argument: `--keep` promotes the test into the versioned suite. Default is
ephemeral (write it, run it, report, delete it).

A caller's rules take precedence over this procedure.

## Procedure

1. **Read `E2E.md`** at the repo root. If it does not exist, follow
   [E2E_TEMPLATE.md](E2E_TEMPLATE.md) first, then come back.
2. **Number the criteria.** Use the caller's acceptance criteria. With none, turn
   the request into numbered, checkable statements about observable behaviour and
   state them before testing. Source them from the request or ticket, never the
   diff.
3. **Preflight the target.** The base URLs and database hosts in `E2E.md` are
   local or a declared test environment, and the accounts are its test users. If
   you cannot show this, the run is `BLOCKED`.
4. **Health-check before starting anything.** Probe every service in the
   _Services_ table and start **only what is down**. The user very likely has a
   dev server running already; killing it or double-binding its port is the
   fastest way to waste a run.
5. **Prove the code under test is current.** Each service running it has this
   checkout as its working directory, and it reloads on change or started after
   the last commit. If one you did not start fails that proof, start your own on a
   free port with the _Port override_ from the _Services_ table, and point whatever
   reaches that service at the new port. With the override empty, find it in the
   repo's scripts and config, and write it into the table once your instance passes
   its health check and this proof. If the service cannot move, the run is
   `BLOCKED`: name the service and the override it needs. Reuse running dependencies
   such as databases.
6. **Pick the surface** from the _How to test_ table, then read its section in
   [SURFACES.md](SURFACES.md).
7. **Write one test per criterion**, starting from the project's helper (see
   _Helper discipline_). Cover the happy path plus each unhappy path the criterion
   states, and nothing beyond them. A criterion that writes data reads the outcome
   back through a different path from the action: a reload, an API read or a
   database query.
8. **Triage each failure.** A bad selector, missing seed, stale service or wrong
   credentials is your test or the environment: fix it and run again. Anything
   else is `FAIL`.
9. **Get a red proof** for every test (see _Red proof_).
10. **Do the final run:** every criterion once, with each test unedited, on the
    final code. First restart the services you started that run the code under
    test, and prove any you reused are still current. Your verdicts come from
    this run.
11. **Report** one verdict per criterion, citing screenshot / trace / output file
    paths.
12. **Teardown**: stop only the services _you_ started, and only if the user asks.
13. **Feed `E2E.md` back**: any gotcha that cost you a failed run gets written into
    its _Gotchas_ section before you close. That is how this file gets good.

## Verdicts

One per criterion:

- `PASS`: green in the final run, red in its red proof, evidence cited.
- `FAIL`: it ran and the behaviour contradicts the criterion. This includes a
  startup failure caused by the change.
- `NOT VERIFIABLE`: it cannot be exercised end to end, it has no red proof, or it
  is a UI criterion with no visual artifact. Say exactly what is missing.

`BLOCKED` applies to the whole run: the target or the environment stopped it. Give
the reason.

## Red proof

A test earns `PASS` only after you have seen it go _red_. Cite what turned red.

- **Bug fix:** run the test on the base commit in a temporary worktree. Bringing
  up a second stack may be too costly; then use the wrong-expected check below.
- **New behaviour:** assert the before state, so the test is red until the action
  happens. With no before state to assert, use the wrong-expected check.
- **Wrong-expected check:** temporarily change the expected value, confirm the
  test goes red for that reason, and restore it. Application code stays untouched.

## Helper discipline

Every project accumulates one flow that every test needs — log in, seed a tenant,
mint a record. That flow belongs in **one helper module**, declared in `E2E.md`,
never copy-pasted into a test.

When your test needs a flow the helper does not cover, **add it to the helper**.
Copying it into the test is how the next agent ends up re-deriving it — and the
waits and retries in there are exactly the knowledge that is expensive to rebuild.

## Craft rules

- **Module resolution is relative to the script's file.** A script written to a
  scratch directory cannot `require` the project's test deps. Write it inside the
  test directory and delete it afterwards.
- **Fail early and loudly on a missing service.** A stack check that throws in two
  seconds is worth far more than a locator timing out at 40.
