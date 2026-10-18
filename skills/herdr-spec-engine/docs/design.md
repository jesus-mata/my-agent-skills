# herdr-spec-engine — design contract

The build contract for the engine. Vocabulary is defined in `../GLOSSARY.md`; the core decision
in `adr/0001-engine-drives-supervisor-escalates.md`. Every module below is written against this
document — if code and this file disagree, fix one of them in the same change.

## Constraints

- Python **3.11+**, **standard library only**. No `pip install`, no `requirements.txt`.
- Runs from the linked skill folder with no build step: `<SKILL_DIR>/engine <command>`.
- Every external effect goes through a **port** (`spec_engine/ports.py`). The state machine never
  imports `subprocess`, `socket` or `os.system`; adapters do.
- The engine process is the **only writer** of `state.json`. Other commands (`resolve`, `stop`)
  write to inbox files the engine consumes.
- Tests: `python3 -m unittest discover -s skills/herdr-spec-engine/tests -t skills/herdr-spec-engine`,
  no network, no herdr, no Claude, no real `gh`. Real git is allowed in temp dirs.

## Layout

```
skills/herdr-spec-engine/
  SKILL.md                 supervisor playbook
  GLOSSARY.md
  docs/adr/  docs/design.md
  engine                   executable launcher (python3), puts its dir on sys.path, calls spec_engine.cli:main
  spec_engine/
    __init__.py
    model.py               dataclasses + enums (Plan, Run, Stage, Outcome, Escalation, ...)
    ports.py               typing.Protocol for Herdr, Git, GitHub, Shell, Clock
    store.py               state dir, atomic state.json, events.jsonl, inboxes, pid lock
    results.py             result-file schemas + validation
    prompts.py             template loading/rendering (string.Template, strict)
    prompts/*.md           prompt templates
    plan.py                build + validate plan, gate discovery
    transitions.py         (stage, outcome) -> next; escalation kinds and their allowed actions
    stages.py              stage handlers: enter() and poll()
    merge_queue.py         integrate sub-machine
    scheduler.py           the engine loop: readiness, concurrency, inbox, spec phases, completion
    spec_phases.py         spec review, fix-run creation, e2e, final report
    cli.py                 argparse: plan, run, watch, resolve, status, stop, abort
    adapters/
      __init__.py
      herdr_socket.py      Herdr over the unix socket (NDJSON)
      git_cli.py           Git via `git`
      gh_cli.py            GitHub via `gh`
      system.py            Shell (subprocess) and Clock (time)
  tests/
    __init__.py
    fakes.py               in-memory FakeHerdr, FakeGitHub, FakeShell, FakeClock (+ helpers)
    test_*.py
```

## State directory

`<git-common-dir>/herdr-spec/<N>/` (`git rev-parse --git-common-dir`, made absolute):

| File | Writer | Content |
| --- | --- | --- |
| `plan.json` | `engine plan` | the validated Plan |
| `state.json` | engine loop | the whole RunState, rewritten atomically (tmp + `os.replace`) after **every** transition |
| `events.jsonl` | engine loop | append-only `{"ts","run","type",...}` log, human/debug only — never read back for logic |
| `resolutions.jsonl` | `engine resolve` | append-only `{"escalation_id","action","note","ts"}`; engine consumes each tick, records consumed ids in state |
| `stop` | `engine stop` | presence = engine should persist and exit at next tick; engine deletes it on exit |
| `engine.pid` | engine loop | pid of the running engine; `run` refuses if the pid is alive |
| `out/` | engine | archived copies of every accepted result file, `<run_id>.<stage>.<attempt>.json` |
| `report.md` | engine | final report |

`store.Store(state_dir, now=time.time)` wraps this directory: `paths` (the files above),
`state_dir_for(common_dir, spec)`, `load_plan/save_plan`, `load_state/save_state` (None when
absent), `append_event(run, type, **data)`, `append_resolution(escalation_id, action, note)`,
`read_resolutions()`, `request_stop/stop_requested/clear_stop`,
`write_pid/read_pid/clear_pid/engine_alive`, `archive_result(run_id, stage, attempt, data)`,
`write_report(text)`.

## Result files (agent → engine handoff)

Agents never get parsed from the terminal. Every agent turn the engine waits on ends with the agent
writing JSON to `<agent_cwd>/.herdr-spec/<run_id>.<stage>.json`. `.herdr-spec/` is added once to
`<git-common-dir>/info/exclude` at `run` start, so it never dirties a tree (shared by all
worktrees). The engine deletes the file before sending a prompt, and after the agent goes
idle/done reads + validates it, archives it to `out/`, then deletes it.

Schemas (`results.py`, hand-written validators returning `(value, None)` or `(None, error_str)`;
unknown keys allowed; every list may be empty):

- **implement** — `{"status": "implemented" | "outward-denied", "summary": str, "denied_actions": [str]}`
- **review** — `{"fixed": [{"kind": "spec"|"standards", "title": str, "commit": str}], "pending": [{"kind": "spec"|"standards", "title": str, "reason": str}], "scope_creep": [str]}`
- **gate_fix** — `{"summary": str}`
- **resolve** — `{"verdict": "RESOLVED" | "ESCALATE", "summary": str}`
- **spec_review** — `{"fixed": [{"severity": "blocker"|"high", "title": str, "commit": str}], "hard": [{"severity": "blocker"|"high", "title": str, "file": str, "line": int|null, "failure_scenario": str}], "not_fixed": [{"severity": "medium"|"low", "title": str}]}`
- **e2e** — `{"passed": [str], "fixed": [{"title": str, "commit": str}], "pending": [{"title": str, "reason": str}]}`

`results.SCHEMAS: dict[str, Validator]` keyed by the names above; `results.example(name) -> str`
gives a JSON example for prompts.

## Plan (`plan.py`, `engine plan <N>`)

```
engine plan <N> [--branch spec-<N>] [--gate CMD]... [--from FILE]
```

1. Read the spec issue: `GitHub.issue(N)`. Tickets = `sub_issues`. With `--from FILE` (fallback for
   specs without sub-issues) tickets and blockers come from the file: `{"tickets": [{"number": int,
   "blocked_by": [int]}]}`; each ticket is still read from GitHub for title/state/labels.
2. For each ticket: `GitHub.issue(t)`. Blockers = its `blocked_by` that are sub-issues of the same
   spec. A `blocked_by` outside the spec: closed → ignored; open → recorded as `external_blockers`.
3. Classify each **open** ticket: `ready-for-agent` only → `agent`; `ready-for-human` only →
   `human`; neither or both → `unrefined`. Closed tickets → `done` (they satisfy blockers).
4. Validate: acyclic (report the cycle); no blocker points at a ticket missing from the plan.
5. Gate: `--gate` values if given, else `discover_gate(repo_root)`: from `package.json` scripts
   (install by lockfile: `pnpm install --frozen-lockfile` / `yarn install --frozen-lockfile` /
   `bun install` / `npm ci`; then scripts present among `lint`, `typecheck`|`type-check`,
   `format:check`, `build`, `test` as `<pm> run <script>`), else `Makefile` targets among
   `lint test build`, else `go.mod` → `go vet ./...`, `go build ./...`, `go test ./...`, else
   `Cargo.toml` → `cargo build`, `cargo test`, else `pyproject.toml` → `python3 -m pytest`.
   Empty gate is allowed but printed as a warning.
6. Write `plan.json`; print the graph (depth = "wave" for display only), each ticket's class,
   external blockers, unrefined tickets, the spec branch and the gate. Exit 0 if runnable, 1 if
   there are unrefined tickets or a cycle (plan still written so the supervisor can show it).

`Plan` = `{spec: int, title, branch, base: "main", gate: [str], tickets: [PlanTicket]}`;
`PlanTicket` = `{number, title, klass: agent|human|unrefined|done, blockers: [int],
external_blockers: [str], labels: [str]}`.

## Runs, stages, outcomes

A **Run** is one entity the scheduler advances. Kinds and their stage sequence:

| Kind | Run id | Stages |
| --- | --- | --- |
| `ticket` | `ticket-<n>` | CLAIM → PROVISION → IMPLEMENT → VERIFY → REVIEW → INTEGRATE → CLOSE |
| `human` | `human-<n>` | AWAIT_HUMAN |
| `fix` | `fix-<N>-<k>` | PROVISION → IMPLEMENT → VERIFY → REVIEW → INTEGRATE → CLOSE |
| `spec_review` | `review-spec-<N>` | PROVISION_TAB → SPEC_REVIEW |
| `e2e` | `e2e-spec-<N>` | PROVISION_TAB → E2E |

Run ids double as herdr agent names and branch names (`ticket-<n>`, `fix-<N>-<k>`); all match
herdr's `[a-z][a-z0-9_-]{0,31}`. Resolver agents are `resolve-<run_id>` truncated to 32 chars.

Terminal statuses: `done`, `left_open`, `skipped`, `aborted`. Non-terminal: `pending` (not yet
ready), `active`, `escalated`.

`Run` fields (all JSON-serialisable): `id, kind, ticket: int|None, finding: dict|None, status,
stage, attempts: dict[stage,int], gate_attempts: int, agent: str|None, pane_id, workspace_id,
worktree: str|None (abs path), awaiting: dict|None, stage_started_at: float, escalation: str|None,
review: dict|None (accepted review result), merge_commit: str|None, notes: [str]`.

`awaiting` = `{"type": "agent_turn", "agent": str, "result": schema_name, "path": abs_path,
"prompted_at": float}` or `{"type": "queue"}` or `{"type": "resolver", "agent": str, "path": ...}`
or `{"type": "escalation"}`.

### Model conventions (`model.py`)

- All enums are `str` enums; JSON holds their values. `Stage` and `Outcome` values are the
  lowercase names (`Stage.PROVISION_TAB == "provision_tab"`, `Outcome.RESULT_INVALID ==
  "result_invalid"`); this value is the `<stage>` in result-file and `out/` archive names and the
  key of `Run.attempts`. Outcomes: `OK, RESULT_INVALID, AGENT_BLOCKED, TIMEOUT, AGENT_UNKNOWN,
  AGENT_LOST, VERIFY_FAILED, INTEGRATED`.
- Other enums: `RunKind` (`ticket|human|fix|spec_review|e2e`), `RunStatus`, `Phase`,
  `EngineStatus` (`running|complete|aborted`), `TicketClass` (`agent|human|unrefined|done`),
  `EscalationKind` (the kinds below; defined in `model.py`, re-exported by `transitions.py`),
  `EscalationStatus` (`open|handed_off|resolved`). `STAGES_BY_KIND` holds the stage sequences.
- `Run.new(kind, run_id, ticket=None, finding=None)` → `pending` run at its kind's first stage.
  `run_id_for(kind, spec=, ticket=, k=)` and `resolver_agent_name(run_id)` build names.
- `Settings` = `max_agents=3, model="opus", stage_timeout=7200, retry_budget=1,
  gate_retry_budget=2, gate_timeout=1800, poll_seconds=10, settle_seconds=15,
  unknown_grace=120` (seconds); `Settings.agent_args` gives the agent args.
- Every dataclass has `to_dict()` / `from_dict()` round-tripping through JSON.

### Readiness and concurrency

A `ticket`/`human` run becomes ready when every blocker's run status is `done` (or the blocker was
`done` in the plan). Runs whose blocker is `skipped`/`left_open` never become ready; at completion
they are marked `skipped` with note "blocked by #x". A ready run with `external_blockers` raises
`external-blocker` before CLAIM. A ready `unrefined` ticket (re-read labels first) raises
`unrefined-ticket`. A ready `human` run raises `hitl-ticket`.

At most `max_agents` runs hold an agent at once (stages PROVISION..CLOSE, PROVISION_TAB and
after). Resolver agents do not count. Ready runs start in ascending ticket number.

### Stage handlers (`stages.py`)

Each stage has `enter(ctx, run)` (perform the action, set `awaiting`) and `poll(ctx, run) ->
Outcome | None` (`None` = still waiting). `ctx` bundles ports, plan, settings, store and paths.

Agent-turn polling (shared by IMPLEMENT, REVIEW, gate fix, SPEC_REVIEW, E2E, resolver):
`Herdr.agent_status(agent)`:
- `working` → None (still waiting); if `now - stage_started_at > stage_timeout` → `TIMEOUT`.
- `blocked` → `AGENT_BLOCKED`.
- `idle`/`done` → read result file: valid → `OK` (value stored on run); missing/invalid →
  `RESULT_INVALID` (error kept for the retry prompt). Ignore idle/done during the first
  `settle_seconds` (default 15) after `prompted_at` — an agent can report idle before it starts.
- `unknown` → None until 120 s in that state, then `AGENT_UNKNOWN`.
- `missing` (agent not found) → `AGENT_LOST`.

| Stage | enter | outcomes → next |
| --- | --- | --- |
| CLAIM | `GitHub.assign_self(n)` | OK → PROVISION |
| PROVISION | `Herdr.create_worktree(branch=id, base=spec_branch)` (or `open_worktree` if the branch exists), `Herdr.start_agent(id, pane, agent_args)` | OK → IMPLEMENT |
| IMPLEMENT | prompt `implement` (fix runs: `fix_implement`) | OK+implemented → VERIFY; OK+outward-denied → escalate `outward-action-denied` |
| VERIFY | none (synchronous) | `Git.commits_ahead(spec_branch, id) > 0` and `Git.is_clean(worktree)` → OK → REVIEW; else `VERIFY_FAILED` → prompt `verify_failed`, wait turn (schema `implement`), re-VERIFY |
| REVIEW | prompt `review` (fix runs: `fix_review`) | OK → INTEGRATE (store `review`) |
| INTEGRATE | enqueue in merge queue | see Merge queue; `INTEGRATED` → CLOSE |
| CLOSE | ticket: `GitHub.comment` (merge commit, pending findings), `GitHub.close` unless a pending `spec` finding exists (then comment only, status `done` anyway — dependents unblock on merge); remove worktree; fix: remove worktree | OK → status `done` |
| AWAIT_HUMAN | raise `hitl-ticket` | resolved `done` → status `done` |
| PROVISION_TAB | `Herdr.create_tab(cwd=repo_root, label=id)`, `start_agent` | OK → next |
| SPEC_REVIEW | prompt `spec_review` | OK → `spec_phases.on_spec_review(result)` |
| E2E | prompt `e2e` | OK → status `done`, then report |

Generic outcomes, any agent-turn stage:
- `RESULT_INVALID` → if `attempts[stage] < retry_budget`: prompt `result_retry` (path, error,
  example), attempts += 1, keep waiting; else escalate `budget-exhausted`.
- `AGENT_BLOCKED` → escalate `agent-blocked` (include `Herdr.read_agent(agent, 60)` in details).
- `TIMEOUT` → escalate `stage-timeout`. `AGENT_UNKNOWN` → escalate `agent-unknown`.
- `AGENT_LOST` → re-provision once (open worktree, start agent, re-send the stage prompt, counts as
  an attempt); if attempts exhausted escalate `budget-exhausted`.
- An exception from a port in `enter` → counts as an attempt; retry next tick; exhausted →
  `budget-exhausted` with the exception text.

### Merge queue (`merge_queue.py`)

FIFO of run ids persisted in state. Only the head is processed. For the head run:

1. `base = Git.rev_parse(spec_branch)`. In the worktree: `Git.merge(worktree, spec_branch)`.
   Conflict → start resolver: `Herdr.split_pane(run.pane_id, cwd=worktree)`, start agent
   `resolve-…`, prompt `resolver`, await `resolve` result. `RESOLVED` → check `Git.is_clean` and
   no unmerged paths, continue to 2 (else treat as `ESCALATE`). `ESCALATE` → escalate
   `resolver-escalated`. Close the resolver pane when done.
2. Gate: each command via `Shell.run(cmd, cwd=worktree, timeout=gate_timeout)`, stop at first
   failure. Failure → if `gate_attempts < gate_retry_budget`: prompt ticket agent `gate_failed`
   (command, exit code, last 150 lines), await `gate_fix`, gate_attempts += 1, go to 1. Else
   escalate `budget-exhausted`.
3. If `Git.rev_parse(spec_branch) != base` → go to 1. Else in the repo root (spec branch checked
   out): `Git.merge(repo_root, id, no_ff=True, message="Merge #<n>: <title>")` (fix runs:
   `"Merge fix-<N>-<k>: <title>"`). Record `merge_commit`, pop the queue → `INTEGRATED`.

The repo root must have the spec branch checked out and be clean (ignoring `.herdr-spec/`);
otherwise raise `budget-exhausted`-style escalation kind `repo-dirty` (actions `retry`).

## Escalations (`transitions.py`)

`Escalation` = `{id: "e<seq>", run, kind, stage, created_at, summary, details, actions: [str],
status: open|handed_off|resolved, resolution: str|None, note}`. While a run's escalation is not
`resolved`, the run's status is `escalated` and it is not polled. Other runs continue.

| Kind | Actions | Effect |
| --- | --- | --- |
| `agent-blocked` | `answered`, `hand-to-human` | answered → resume polling the same turn (reset `stage_started_at`) |
| `agent-unknown` | `answered`, `retry`, `hand-to-human` | retry → re-send stage prompt |
| `stage-timeout` | `retry`, `skip-ticket`, `hand-to-human` | retry → reset timer, keep waiting |
| `budget-exhausted` | `retry`, `skip-ticket`, `hand-to-human` | retry → reset that stage's attempts, re-enter the stage |
| `resolver-escalated` | `resolved-manually`, `hand-to-human` | resolved-manually → merge-queue step 2 |
| `outward-action-denied` | `leave-open`, `retry` | leave-open → comment on ticket, status `left_open`, remove worktree |
| `hitl-ticket` | `done` | engine re-reads issue; closed → `done`; open → stays escalated (details updated) |
| `unrefined-ticket` | `relabeled`, `skip-ticket` | relabeled → re-read labels, reclassify |
| `external-blocker` | `cleared`, `skip-ticket` | cleared → re-read blockers; all closed → proceed |
| `repo-dirty` | `retry` | retry → re-check |

`hand-to-human` sets status `handed_off`: the escalation stays unresolved, `watch` stops reporting
it, and the supervisor resolves it later with one of the other actions. `skip-ticket` → status
`skipped`, remove worktree if any, interrupt agent. Any action not in the list → `resolve` exits 2.

## Scheduler (`scheduler.py`)

`Engine(ctx).run_forever()`:

```
startup: ping herdr; verify repo root on spec branch (create from base if missing: checkout base,
         pull --ff-only, checkout -b); ensure exclude entry; load or init state; write pid
loop:    consume resolutions inbox -> apply
         for each non-terminal, non-escalated run: advance (enter / poll / transition) — persist after each transition
         process merge-queue head
         start ready runs up to max_agents
         if all ticket/human/fix runs terminal and spec phases not started -> spec_phases.start
         if spec phase complete -> write report, state.status = complete, exit 0
         if stop file -> persist, remove pid, exit 0
         Herdr.wait_for_change(timeout=poll_seconds)   # returns early on agent status events
```

State top level: `{version: 1, spec, branch, status: running|complete|aborted, settings,
runs: {id: Run}, queue: [id], escalations: {id: Escalation}, consumed_resolutions: [id...],
seq: int, fix_seq: int, phase: tickets|spec_review|fixes|e2e|complete, started_at, updated_at}`.

Resume: `engine run <N>` with existing state reconciles every active run: agent missing →
`AGENT_LOST` path; otherwise continue polling. Never re-sends a prompt to a live agent that is
`working`.

## Spec phases (`spec_phases.py`)

- When ticket runs are all terminal: create the `spec_review` run.
- `on_spec_review(result)`: one `fix` run per `hard` finding (`finding` = the entry), phase
  `fixes`. Fix runs go through the same scheduler and merge queue.
- When all fix runs are terminal (or there were none): create the `e2e` run, phase `e2e`.
- E2E OK → phase `complete`; write `report.md`: tickets done / left open / skipped (with reasons
  and pending `spec` findings), spec review fixed / pending / not fixed, fix runs, e2e passed /
  fixed / pending, open or handed-off escalations, and "spec branch is local; nothing pushed".
- Spec review and e2e tabs are never closed by the engine.

## Prompts (`prompts.py`, `prompts/*.md`)

`render(name, **vars) -> str` with `string.Template.substitute` (missing var → KeyError, a bug).
Every template states: you are a sub Claude instance started by herdr-spec-engine for spec #$spec;
work only in your cwd; commit on your branch; never push, merge, rebase onto other branches, switch
branches or deploy; end your turn by writing the result JSON to `$result_path` (example:
`$result_example`).

| Template | Variables (besides `spec`, `spec_title`, `result_path`, `result_example`) |
| --- | --- |
| `implement` | `ticket`, `ticket_title`, `branch`, `spec_branch`, `integrated` (list of merged tickets), `siblings` (tickets running now) |
| `verify_failed` | `ticket`, `branch`, `spec_branch`, `problem` |
| `review` | `ticket`, `spec_branch` |
| `result_retry` | `error` |
| `gate_failed` | `command`, `exit_code`, `output` |
| `resolver` | `run_id`, `branch`, `spec_branch`, `conflicts` (git status of unmerged paths) |
| `spec_review` | `spec_branch`, `base` |
| `fix_implement` | `branch`, `spec_branch`, `finding` (formatted title/file/line/failure scenario) |
| `fix_review` | `spec_branch`, `finding` |
| `e2e` | `spec_branch` |

Content follows the old skill: implement uses `/implement-ticket <n>`; review uses
`/mattpocock-skills:code-review <spec_branch>` with the fix policy (fix every missing/wrong spec
finding and hard standards violation, test-first with `/mattpocock-skills:tdd`, one commit each,
only report scope creep); resolver uses `/mattpocock-skills:resolving-merge-conflicts`, finishes
the merge commit, ESCALATE for big chunks or significant logic changes; spec review runs
`/code-review high` against `$base`, fixes easy blocker/high findings inline test-first (1–2 files,
no design/API change), lists the rest as `hard`, **never creates worktrees or agents**; e2e runs
`/e2e`, fixes issues test-first with built-in subagents, max 2 fix rounds.

## Ports (`ports.py`)

```python
AgentStatus = Literal["idle", "working", "blocked", "done", "unknown", "missing"]

@dataclass(frozen=True) class Worktree:  workspace_id: str; pane_id: str; path: str
@dataclass(frozen=True) class IssueRef:  number: int; state: str; url: str; repo: str   # repo "owner/name"
@dataclass(frozen=True) class Issue:     number: int; title: str; state: str  # "OPEN"|"CLOSED"
                                         labels: tuple[str, ...]; url: str
                                         sub_issues: tuple[IssueRef, ...]; blocked_by: tuple[IssueRef, ...]
@dataclass(frozen=True) class MergeResult: ok: bool; conflict: bool; commit: str | None; output: str
@dataclass(frozen=True) class ShellResult: code: int; output: str   # stdout+stderr merged

class Herdr(Protocol):
    def ping(self) -> dict: ...
    def create_worktree(self, cwd: str, branch: str, base: str, label: str) -> Worktree: ...
    def open_worktree(self, cwd: str, branch: str, label: str) -> Worktree: ...
    def remove_worktree(self, workspace_id: str) -> None: ...
    def create_tab(self, cwd: str, label: str) -> str: ...            # returns root pane id
    def split_pane(self, pane_id: str, cwd: str) -> str: ...          # returns new pane id
    def close_pane(self, pane_id: str) -> None: ...
    def start_agent(self, name: str, pane_id: str, args: list[str]) -> None: ...   # kind claude
    def prompt_agent(self, name: str, text: str) -> None: ...
    def agent_status(self, name: str) -> AgentStatus: ...
    def read_agent(self, name: str, lines: int) -> str: ...
    def interrupt_agent(self, name: str) -> None: ...                 # ctrl+c
    def wait_for_change(self, timeout: float) -> None: ...            # may return early

class Git(Protocol):
    def common_dir(self, cwd: str) -> str: ...
    def repo_root(self, cwd: str) -> str: ...
    def current_branch(self, cwd: str) -> str: ...
    def branch_exists(self, cwd: str, branch: str) -> bool: ...
    def checkout(self, cwd: str, branch: str, create_from: str | None = None) -> None: ...
    def pull_ff_only(self, cwd: str) -> None: ...
    def rev_parse(self, cwd: str, ref: str) -> str: ...
    def commits_ahead(self, cwd: str, base: str, branch: str) -> int: ...
    def is_clean(self, cwd: str) -> bool: ...                          # respects excludes
    def unmerged_paths(self, cwd: str) -> list[str]: ...
    def merge(self, cwd: str, ref: str, no_ff: bool = False, message: str | None = None) -> MergeResult: ...
    def merge_abort(self, cwd: str) -> None: ...

class GitHub(Protocol):
    def issue(self, number: int) -> Issue: ...
    def assign_self(self, number: int) -> None: ...
    def comment(self, number: int, body: str) -> None: ...
    def close(self, number: int) -> None: ...

class Shell(Protocol):
    def run(self, cmd: str, cwd: str, timeout: float) -> ShellResult: ...

class Clock(Protocol):
    def now(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...
```

Adapter notes (verified against `herdr api schema --json`, herdr 0.9.1 / protocol 22):
- **herdr_socket**: socket path = `HERDR_SOCKET_PATH`, else `~/.config/herdr/sessions/$HERDR_SESSION/herdr.sock`
  if `HERDR_SESSION` is set, else `~/.config/herdr/herdr.sock`. One connection per request: send
  `{"id","method","params"}\n`, read one line; `error {code, message}` → raise
  `HerdrError(code, message)`; transport failures (no socket, closed connection, timeout) → raise
  `HerdrError("connection_failed", …)`. Methods (raw `cwd` values must be absolute):
  `ping`; `worktree.create {cwd, branch, base, label, focus: false}` and `worktree.open {cwd,
  branch, label, focus: false}` → `result.workspace.workspace_id`, `result.root_pane.pane_id`,
  `result.worktree.path` (always present, no git fallback needed); `worktree.remove
  {workspace_id}`; `tab.create {cwd, label, focus: false}` → `result.root_pane.pane_id`;
  `pane.split {target_pane_id, direction: "right", cwd, focus: false}` → `result.pane.pane_id`;
  `pane.close {pane_id}`; `agent.start {name, kind: "claude", pane_id, args, timeout_ms: 60000}`
  (timeout_ms must be in (3000, 300000]); `agent.prompt {target, text}`; `agent.get {target}` →
  `result.agent.agent_status` (error code `agent_not_found` → `missing`; any status outside the
  enum → `unknown`); `agent.read {target, source: "recent", lines, format: "text", strip_ansi:
  true}` → `result.read.text`; `agent.send_keys {target, keys: ["ctrl+c"]}`. `agent.prompt`,
  `agent.read` and `agent.send_keys` on a missing agent raise `HerdrError("agent_not_found")`.
  `wait_for_change`: `agent.list`, take the `pane_id`s of agents with a `name` (the schema
  requires a `pane_id` on every `pane.agent_status_changed` entry — there is no unfiltered form),
  open a connection, `events.subscribe {subscriptions: [{type: "pane.agent_status_changed",
  pane_id}…, {type: "pane.closed"}, {type: "pane.exited"}]}`, read the ack, return at the first
  pushed line (an event, or an `events_lost` error) or at timeout. No named agents, or any error
  before the ack (e.g. a pane vanished, which rejects the whole request) → sleep out the timeout.
- **gh_cli**: `gh issue view <n> --json number,title,state,labels,url,subIssues,blockedBy`, run in
  the repo root. `labels` is a list of `{name, …}`; `subIssues` / `blockedBy` are connections
  `{"nodes": [{id, number, state, title, url}], "totalCount": n}`; the repo of a ref is parsed from
  its `url` (`https://<host>/<owner>/<name>/issues/<n>`). A "could not resolve"/"not found" failure
  raises `LookupError` (like `FakeGitHub`), other failures `GhError` (a `RuntimeError`).
  `gh issue edit <n> --add-assignee @me`; `gh issue comment <n> --body-file -` (body on stdin);
  `gh issue close <n>`.
- **git_cli**: plain `git -C <cwd> …`, failures raise `GitError` (a `RuntimeError`).
  `common_dir` = `rev-parse --git-common-dir` made absolute against `cwd`; `is_clean` =
  `git status --porcelain` empty (honours `.gitignore` and `info/exclude`); `unmerged_paths` =
  `diff --name-only --diff-filter=U`; `merge` = `merge --no-edit [--no-ff] [-m msg] <ref>` →
  `ok` with `commit` = new `HEAD`, or not ok with `conflict` = any unmerged paths;
  `current_branch` is `"HEAD"` when detached.
- **system**: `SubprocessShell.run` = `shell=True` in its own process group, stdout+stderr merged;
  on timeout the whole group is killed and it returns code 124 with the partial output plus a
  `command timed out` note. `SystemClock` = `time.time` / `time.sleep`.
- **factory**: `adapters.real_ports(cwd, socket_path=None) -> Ports(herdr, git, github, shell,
  clock)`; `gh` runs in `cwd`.

## CLI (`cli.py`)

```
engine plan <N> [--branch B] [--gate CMD]... [--from FILE]
engine run <N> [--max-agents 3] [--model opus] [--stage-timeout 2h] [--retry-budget 1]
               [--gate-retry-budget 2] [--gate-timeout 30m] [--poll 10]
engine watch <N> [--timeout 4h]
engine resolve <N> <escalation-id> <action> [--note TEXT]
engine status <N> [--json]
engine stop <N>
engine abort <N>
```

- Durations accept `90`, `90s`, `30m`, `2h` (`cli.parse_duration`, also `--poll`).
- Each subcommand is handled by `cmd_<name>(args) -> int` (exit code). `run` flags default to
  `None` (dest = the `Settings` field name, `--poll` → `poll_seconds`) so
  `cli.settings_overrides(args)` returns only the flags given explicitly.
- `run` needs `plan.json`, refuses if the plan has unrefined tickets or a cycle (exit 1), refuses if
  another engine is alive (exit 1). First `run` stores settings; a resumed `run` overrides only the
  flags given explicitly. Agent args = `["--permission-mode", "auto", "--model", <model>]`.
- `watch` reads `state.json` every 5 s (read-only). Exit 0 printing each **open** escalation (id,
  run, kind, summary, details, allowed actions) as soon as one exists; exit 0 printing
  `COMPLETE` + `report.md` when status is complete; exit 3 printing `ENGINE NOT RUNNING` if the
  pid is dead and state is not complete; exit 1 on timeout.
- `resolve` validates the escalation id and action against `state.json`, appends to
  `resolutions.jsonl`, exit 0; unknown id/action → exit 2.
- `status` prints runs (id, status, stage, awaiting), queue, escalations.
- `stop` creates the `stop` file. `abort`: if engine alive, request stop and wait up to 60 s for it
  to exit; then for each run holding an agent: interrupt, close resolver panes, remove worktrees
  of runs not `done` (branches kept); state.status = aborted. Nothing on GitHub is reverted.
