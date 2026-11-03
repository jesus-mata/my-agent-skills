---
name: hc-implement-spec
description: "Implements every ticket of a spec made by /to-spec and /to-tickets with an hc orchestrator: each ticket is developed and reviewed in its own terminal in dependency order, merged into an integration branch, then the whole spec is reviewed, E2E-tested and opened as one PR. Terminals show up named in herdr-app."
argument-hint: "<spec-issue> [--parallel <n>] [--orchestrator|--dev|--review|--e2e <model>[:<effort>]]"
disable-model-invocation: true
allowed-tools: Read Bash(printenv HC_TERMINAL_ID) Bash(git rev-parse *) Bash(hc get *) Bash(hc run *) Bash(hc read *) Bash(hc keys *) Bash(hc kill *) Bash(hc rm *) Bash(claude -p *) Bash(herdr-app ls) Bash(herdr-app do space.new *)
---

# Launch the spec orchestrator

Start the `spec-orchestrator` hc template on the spec in `$ARGUMENTS`, then hand over. The orchestrator runs the workflow in [WORKFLOW.md](WORKFLOW.md); this session only launches it.

1. **Check.** Stop and say why unless `$ARGUMENTS` is one issue number `<N>` plus any flags, and `printenv HC_TERMINAL_ID` prints an address.
   - `--parallel <n>`, with `<n>` from 1 to 6, defaults to 3.
   - Each of `--orchestrator`, `--dev`, `--review` and `--e2e` may appear once, as `<model>[:<effort>]`. `<model>` must match `^[a-zA-Z0-9.\[\]-]+$`, and `<effort>` must be `low`, `medium`, `high`, `xhigh` or `max`.
   - The main checkout is the parent of `git rev-parse --path-format=absolute --git-common-dir`, and `<repo>` is its folder name.
2. **Check the name.** If `hc get spec-<N>` finds a live terminal, stop and show its `cwd` and state. If it finds a finished one, stop and tell the human to run `hc rm spec-<N>` first: hc names are unique across repos.
3. **Fresh or resume.** `Read` `~/.cache/hc-spec/<repo>-<N>/state.md`. If it exists, this is a resume: the task in step 6 is `<N> --resume`, and tell the human so. A not-found error means a fresh run, with the task `<N>`.
4. **Check the models.** For each distinct model in the flags, run `claude -p --model '<model>' --setting-sources "" --tools "" --no-session-persistence "Reply ok"`. Stop and name the model if one exits non-zero: Claude starts with a bad model and only fails on its first request, which would leave the run silent.
5. **Open a space,** only if `herdr-app ls` lists the address from step 1. Run `herdr-app do space.new --name "<repo> spec #<N>" --folder <main checkout> --tab orquestador` and keep its `space`, `tab` and `terminal`.
6. **Start the orchestrator.** Add the `herdr.*` labels only if step 5 opened a space, and a model or effort label only for a value the flags gave:

   ```sh
   hc run --bg --outlive-parent --name spec-<N> --cwd <main checkout> \
     --label herdr.space=<space> --label herdr.tab=<tab> \
     --label spec=<N> --label role=orchestrator --label parallel=<n> \
     --label 'model=<orchestrator model>' --label 'effort=<orchestrator effort>' \
     --label 'model.dev=<model>' --label 'effort.dev=<effort>' \
     --label 'model.review=<model>' --label 'effort.review=<effort>' \
     --label 'model.e2e=<model>' --label 'effort.e2e=<effort>' \
     spec-orchestrator "<task>"
   ```

   If `first_message.sent` is false, read `hc read spec-<N>`. Accept a folder trust dialog for the main checkout with `hc keys spec-<N> down enter`. If the task is not on its screen, `hc kill` and `hc rm` it, then start it once more: the task holds the template's instructions, so a plain send cannot replace it. If it still has not arrived, stop and say what the screen shows.
7. **Remove the placeholder.** Run `hc kill` then `hc rm` on the `terminal` from step 5. It is the space's initial shell. If step 6 failed, this also closes the space.

Done when the task is on `spec-<N>`'s screen. Name the terminal, tell the human they can talk to it in its tab or with `hc send spec-<N> "<message>"`, and end your turn: its report arrives here as an `hc` message.
