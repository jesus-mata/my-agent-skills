---
name: e2e
description: Bring up the local stack and end-to-end test a change — web app, HTTP API, CLI, or desktop app — driven by the project's root E2E.md. Use it when you need to verify that something actually works, not just that it compiles or that the unit tests pass.
disable-model-invocation: true
---

# e2e

Drive the real thing and show evidence. This skill is the **procedure**; every
project-specific fact — services, ports, credentials, seed data, gotchas — lives
in **`E2E.md` at the repo root**. Never hardcode a project fact here.

Argument: `--keep` promotes the test into the versioned suite. Default is
ephemeral (write it, run it, report, delete it).

## Procedure

1. **Read `E2E.md`** at the repo root. If it does not exist, go to _Bootstrap_
   first, then come back.
2. **Health-check before starting anything.** Probe every service in the
   _Services_ table and start **only what is down**. The user very likely has a
   dev server running already; killing it or double-binding its port is the
   fastest way to waste a run.
3. **Pick the surface** from the _How to test_ table — web, api, cli or desktop.
   The table says which tool and where the tests live.
4. **Write the test**, starting from the project's helper (see _Helper
   discipline_). Ephemeral by default.
5. **Report with evidence**: cite screenshot / trace / output file paths. A UI
   change verified without a visual artifact is not verified.
6. **Teardown**: stop only the services _you_ started, and only if the user asks.
7. **Feed `E2E.md` back**: any gotcha that cost you a failed run gets written into
   its _Gotchas_ section before you close. That is how this file gets good.

## Bootstrap — when `E2E.md` is missing

Read `docker-compose*.yml`, `package.json` / `Makefile` / `*.csproj` / `pyproject.toml`,
`README.md`, `CLAUDE.md`, and any `.env.example` to draft the file from the template
below.

Then **validate the draft by actually running it**: bring the stack up from a cold
state following your own instructions, hit every health check, log in with the
credentials you wrote down. Fix whatever was wrong. An `E2E.md` that was never
executed is worse than none — it teaches the next agent a stack that does not exist.

Present the validated draft for review before using it.

## `E2E.md` template

Single file, no sub-documents. Section headings in English; prose in whatever
language the repo's docs use.

```markdown
# E2E

## Services

| Service | Start | Listens on | Depends on |

## Startup order & health checks

Ordered list. Each entry: the command, and **how to know it is ready** — a URL
that returns, a log line, a port that accepts. "Started" is not "ready".

## Entry points

The URLs / binaries that count as the front door, and which one to prefer when
several are equivalent.

## Users & credentials

Test accounts, roles, how to reset them.

## Seed data

What exists after seeding, the command to re-seed, and whether it is idempotent.
Name the concrete identifiers tests will need.

## How to test

| Surface | Type | Tool | Tests live in | Run one |

## Gotchas

The things that cost a failed run. Symptom first, then cause, then fix.

## Teardown

How to stop each service, and what is safe to leave running.
```

## Surfaces

### web — `@playwright/test`

- `globalSetup` does the health check **and** one real login, persisted with
  `storageState`. Per-test logins are slow and they are what makes a suite crawl.
- Fixtures: `authedPage` (loads the storage state) and `flows` (the project's
  helper). Keep a separate, un-authenticated fixture for tests that exercise
  login itself.
- Config: `trace: "retain-on-failure"`, `screenshot: "only-on-failure"`. The trace
  viewer is the reason to use the runner at all.

### api — `hurl`, falling back to `curl`

Prefer `hurl`: declarative `.hurl` files with native asserts and variable capture
across requests (token → next call), which is what an API e2e actually is.

```hurl
POST {{base}}/api/auth/token
{ "user": "{{user}}" }
HTTP 200
[Captures]
token: jsonpath "$.access_token"
```

If `hurl` is not installed, say so once and fall back to `curl` + `jq` with
explicit exit-code checks. Do not silently skip the assertions.

### cli — spawn the real binary

Run the actual command with real arguments. Assert on **exit code, stdout/stderr,
and side effects on disk** — all three, not just the output. Use a temp working
directory so a failed run leaves nothing behind.

### desktop — Electron via Playwright

`_electron.launch({ args: ["."] })` gives you the same `page` API, the same
fixtures and the same trace as the web branch.

Non-Electron native apps (Swift, Qt, WinUI) are **out of scope**: there is no
equivalent driver, and OS-scripting them is too brittle to encode as a procedure.
If `E2E.md` declares one, work it case by case with the OS's own tooling and say
plainly that it is not a supported branch.

## Helper discipline

Every project accumulates one flow that every test needs — log in, seed a tenant,
mint a record. That flow belongs in **one helper module**, declared in `E2E.md`,
never copy-pasted into a test.

When your test needs a flow the helper does not cover, **add it to the helper**.
Copying it into the test is how the next agent ends up re-deriving it — and the
waits and retries in there are exactly the knowledge that is expensive to rebuild.

## Craft rules

- **Dump the DOM before inventing a selector.** One `page.evaluate` that lists the
  real candidates costs one run and saves three blind ones against a selector you
  imagined.
- **Module resolution is relative to the script's file.** A script written to a
  scratch directory cannot `require` the project's test deps. Write it inside the
  test directory and delete it afterwards.
- **Fixed waits beat `networkidle`** under any dev server with an open HMR socket —
  `waitForLoadState("networkidle")` never resolves there, it just times out at 30s.
- **Verify the input took.** Forms with controlled state can silently re-seed from
  their defaults; read the value back and retry before submitting.
- **Fail early and loudly on a missing service.** A stack check that throws in two
  seconds is worth far more than a locator timing out at 40.
