# hc-implement-spec

Implements every ticket of a spec made by `/to-spec` and `/to-tickets`, in the order of their
blocking graph, on one integration branch, then reviews and E2E-tests the whole spec and opens one
PR. Each ticket runs in its own `hc` terminal, and inside Herdr every terminal gets its own named
tab. Merging the PR stays with you.

## What it does

`/hc-implement-spec 7` starts the `spec-orchestrator` template as `spec-7`. It:

1. **Plans.** A sub-agent reads the spec and its tickets and writes the graph, each ticket's kind
   (agent or HITL), the gate commands and every acceptance criterion to `~/.cache/hc-spec/<repo>-7/`.
   A cycle stops the run. A ticket that is neither `ready-for-agent` nor HITL, or has an open
   blocker outside the spec, waits for you while the rest goes on.
2. **Creates `spec/7`** in `../worktree/<repo>-spec_7` from the up to date default branch. Your main
   checkout is never touched.
3. **Runs the frontier,** up to `--parallel` tickets at once (3 by default). Ticket 12 gets branch
   `spec/7-t12` in `../worktree/<repo>-spec_7-t12`, from the current tip of `spec/7`, and one
   terminal, `s7-dev-12`, from the `spec-coder` template. It runs `/develop-ticket`, then
   `/run-review --fresh-classify`, then fix rounds, up to 3 reviews. The reviews and their
   classification run in fresh sub-agents, so the author never judges its own findings.
4. **Merges** each finished ticket through a Sonnet sub-agent, one at a time. It merges `spec/7`
   into the ticket's branch, resolves trivial conflicts, runs the cheap gate (format, lint,
   typecheck or build, fast unit tests), then merges the ticket into `spec/7` with `--no-ff`. A
   conflict that touches logic goes back to `s7-dev-12`, which resolves it and runs `/run-tests`, up
   to 3 rounds. A large one comes to you. A merged ticket's terminal closes, and the next frontier
   starts.
5. **Reviews the spec** in `s7-review`, which also re-checks the findings the tickets dismissed, and
   fixes what it finds.
6. **E2E-tests the spec** in `s7-e2e-1`, against the spec's criteria plus every ticket's, each
   tagged with its ticket. Failures go to `s7-review`; each re-run is a new terminal, up to 3.
7. **Pushes `spec/7` and opens the PR,** closing the spec and every merged ticket.

A HITL ticket gets a plain Claude session, `s7-hitl-14` in its own worktree, and a ping. Work there,
commit, and tell the orchestrator `#14 done`; it merges your work like any other ticket.

Children and the orchestrator exchange only one-line `hc send` messages that name a report file.
The orchestrator's memory is `~/.cache/hc-spec/<repo>-7/state.md`, written after every change, so a
compacted or crashed orchestrator loses nothing.

## How to use it

Run it from any `hc` terminal in the repo:

```
/hc-implement-spec 7
/hc-implement-spec 7 --parallel 2 --dev sonnet:high --review opus --e2e haiku:low
```

Only you can start it. It needs the `spec-orchestrator`, `spec-coder` and `e2e-tester` templates
linked into `~/.config/herdr-core/templates`, the skills those templates run, `jq`, and an
authenticated `gh` or `glab`. The tickets must live in the issue tracker, because `/develop-ticket`
reads them from there. `bin/agent-skills install` or `update` links every template, and
`templates/lib` beside them, once `~/.config/herdr-core` exists, so run one of those after
pulling. `bin/agent-skills status` shows any template that is missing.

Models work as in [`hc-implement-ticket`](../hc-implement-ticket/README.md#choosing-models).
Integration rounds and spec fixes run in the dev and review terminals, so they use those models.
Merge sub-agents always run Sonnet.

## Inside Herdr

The spec gets a space, `<repo> spec #7`, with one tab per terminal: `orquestador`,
`dev #12 <short title>`, `hitl #14`, `review spec` and `e2e 1`. Every terminal also carries the
labels `spec=7`, `role=<orchestrator|dev|hitl|review|e2e>` and `ticket=<n>`. Merge sub-agents have
no tab. Outside Herdr the terminals run hidden, so use `hc attach s7-dev-12`.

## Talking to it

Write in the `orquestador` tab, or from anywhere with `hc send spec-7 "<message>"`. It reads you
between waits, so a reply can take up to nine minutes. Each escalation lists the replies that fit:

| Reply | Effect |
| --- | --- |
| `#14 done` | a HITL ticket, or a failed one you fixed in its worktree, is ready to merge |
| `retry #12` | run the failed ticket's last step again |
| `skip #12` | drop the ticket and everything it blocks |
| `unblocked #12` | an outside blocker is closed |
| `retry review`, `retry e2e` | run that spec stage again |
| `open pr` | open the PR despite an open escalation |
| `cleanup` | remove worktrees, branches and terminals after the PR merged |

If `spec-7` dies, run `hc rm spec-7` and `/hc-implement-spec 7` again: it finds the state and
resumes.

## Finishing

Merge the PR with `/merge-pr <url>` from your own session; it squash-merges and removes `spec/7`
and its worktree. Then tell `spec-7` `cleanup`: it confirms the PR merged, removes every ticket
worktree and branch, without forcing a dirty one, and closes the children. Close `spec-7` yourself.

## Pings

If [`ping-me`](../ping-me/README.md) is set up, `spec-7` sends a push when the plan is ready, when a
ticket merges, when a HITL ticket waits for you, on every escalation, when the run ends and when
cleanup stops. The orchestrator sends them itself, so if it crashes or hits a rate limit, no ping
arrives.
