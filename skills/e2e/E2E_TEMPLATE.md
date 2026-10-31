# Bootstrap `E2E.md`

Read `docker-compose*.yml`, `package.json` / `Makefile` / `*.csproj` / `pyproject.toml`,
`README.md`, `CLAUDE.md`, and any `.env.example` to draft the file from the template
below.

Then **validate the draft by actually running it**: bring the stack up from a cold
state following your own instructions, hit every health check, log in with the
credentials you wrote down. Fix whatever was wrong. An `E2E.md` that was never
executed is worse than none — it teaches the next agent a stack that does not exist.

Present the validated draft for review before using it.

## Template

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

For a web surface, also give the `playwright-cli` command, its config file
(real desktop UA, the same TLS settings as the runner) and the `storageState`
path to load.

## Gotchas

The things that cost a failed run. Symptom first, then cause, then fix.

## Teardown

How to stop each service, and what is safe to leave running.
```
