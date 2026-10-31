# Surfaces

Read only the section for the surface you picked.

## web — explore with `playwright-cli`, verify with `@playwright/test`

Two tools, one engine, two different jobs. Do not swap them.

**1. Explore — `playwright-cli`.** Look at the real page before writing any
selector. Recent Playwright ships it as `playwright cli` (check with `playwright cli
--help`; 1.62 has it), so it uses the runner's version and browser. Use the global
`@playwright/cli` package only when the project has no local Playwright.

- One named session per run (`-s=<name>`), opened with the project's CLI config
  (`--config=…`, declared in `E2E.md`). Reuse the runner's login with
  `state-load <storageState>` instead of logging in by hand.
- `snapshot` (cap it with `--depth`, or snapshot one ref) and `find "<text>"` /
  `find --regex` show the real tree. `generate-locator <ref>` returns the
  Playwright locator to paste into the spec. `console` and `requests` show what
  the page did.
- **Headless sets a bot user-agent.** Pin a real desktop UA in the CLI config.
  Bot detection can change what the server renders (full HTML instead of a
  stream, for example), and then you are exploring a different page.
- **Nothing you see here is a verdict or evidence.** Exploring finds selectors
  and confirms that a flow is reachable. `close` the session when you are done.

**2. Verify — `@playwright/test`.** The spec is the only source of a verdict.

- One `test` per acceptance criterion, asserted with `expect`. The spec can be
  re-run unchanged, including the final run, and it exits non-zero on failure. A
  CLI command history can do neither.
- `globalSetup` does the health check **and** one real login, persisted with
  `storageState`. Per-test logins are slow and they are what makes a suite crawl.
- Fixtures: `authedPage` (loads the storage state) and `flows` (the project's
  helper). Keep a separate, un-authenticated fixture for tests that exercise
  login itself.
- Config: `trace: "retain-on-failure"`, `screenshot: "only-on-failure"`. The trace
  viewer is the reason to use the runner at all. Evidence is the runner's
  screenshot or trace. Take an explicit `page.screenshot()` for every UI AC,
  because on a pass the runner keeps nothing.

**Craft rules:**

- **Never invent a selector.** Every locator in a spec comes from a
  `playwright-cli` snapshot or from `generate-locator`. One look at the real tree
  saves three blind runs against a selector you imagined.
- **Wait on state.** Web-first assertions such as
  `await expect(locator).toBeVisible()` retry on their own, and `expect.poll`
  covers backend state. Use a fixed wait only when there is nothing to observe,
  with a comment saying why. `waitForLoadState("networkidle")` never resolves under
  a dev server with an open HMR socket; it just times out at 30s.
- **Verify the input took.** Forms with controlled state can silently re-seed from
  their defaults; read the value back and retry before submitting.

## api — `hurl`, falling back to `curl`

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

## cli — spawn the real binary

Run the actual command with real arguments. Assert on **exit code, stdout/stderr,
and side effects on disk** — all three, not just the output. Use a temp working
directory so a failed run leaves nothing behind.

## desktop — Electron via Playwright

`_electron.launch({ args: ["."] })` gives you the same `page` API, the same
fixtures, the same trace and the same craft rules as the web branch.

Non-Electron native apps (Swift, Qt, WinUI) are **out of scope**: there is no
equivalent driver, and OS-scripting them is too brittle to encode as a procedure.
If `E2E.md` declares one, work it case by case with the OS's own tooling and say
plainly that it is not a supported branch.
