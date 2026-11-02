---
name: hc-implement-ticket
description: "Takes a ticket from code to MR with an hc orchestrator: develop, review and E2E each run in their own terminal, which stay open for follow-ups."
argument-hint: "<issue-number> [--orchestrator|--dev|--review|--e2e <model>[:<effort>]]"
disable-model-invocation: true
allowed-tools: Bash(printenv HC_TERMINAL_ID) Bash(git rev-parse *) Bash(hc get *) Bash(hc run *) Bash(hc read *) Bash(hc keys *) Bash(hc kill *) Bash(hc rm *) Bash(claude -p *) Bash(herdr-app ls) Bash(herdr-app do space.new *)
---

# Launch the ticket orchestrator

Start the `ticket-orchestrator` hc template on the ticket in `$ARGUMENTS`, then hand over. The orchestrator runs the workflow in [WORKFLOW.md](WORKFLOW.md); this session only launches it.

1. **Check.** Stop and say why unless `$ARGUMENTS` is one issue number `<n>` plus any stage flags, and `printenv HC_TERMINAL_ID` prints an address. Each of `--orchestrator`, `--dev`, `--review` and `--e2e` may appear once, in any order after `<n>`, as `<model>[:<effort>]`. `<model>` must match `^[a-zA-Z0-9.\[\]-]+$`, and `<effort>` must be `low`, `medium`, `high`, `xhigh` or `max`. The main checkout is the parent of `git rev-parse --path-format=absolute --git-common-dir`, and `<repo>` is its folder name.
2. **Check the name.** If `hc get ticket-<n>` finds a terminal, live or finished, stop and show its `cwd` and state. Hc names are unique across repos, so tell the human to run `hc kill ticket-<n>` and `hc rm ticket-<n>`, and to remove any `fix/issue_<n>` branch or worktree before a retry.
3. **Check the models.** For each distinct model in the flags, run `claude -p --model '<model>' --setting-sources "" --tools "" --no-session-persistence "Reply ok"`. Stop and name the model if one exits non-zero: Claude starts with a bad model and only fails on its first request, which would leave the run silent.
4. **Open a space,** only if `herdr-app ls` lists the address from step 1. Run `herdr-app do space.new --name "<repo> #<n>" --folder <main checkout> --tab ticket` and keep its `space`, `tab` and `terminal`.
5. **Start the orchestrator.** Add the `herdr.*` labels only if step 4 opened a space, and a model or effort label only for a value the flags gave:

   ```sh
   hc run --bg --outlive-parent --name ticket-<n> --cwd <main checkout> \
     --label herdr.space=<space> --label herdr.tab=<tab> \
     --label 'model=<orchestrator model>' --label 'effort=<orchestrator effort>' \
     --label 'model.dev=<model>' --label 'effort.dev=<effort>' \
     --label 'model.review=<model>' --label 'effort.review=<effort>' \
     --label 'model.e2e=<model>' --label 'effort.e2e=<effort>' \
     ticket-orchestrator "<n>"
   ```

   If `first_message.sent` is false, read `hc read ticket-<n>`. Accept a folder trust dialog for the main checkout with `hc keys ticket-<n> down enter`. If the task is not on its screen, `hc kill` and `hc rm` it, then start it once more: the task holds the template's instructions, so a plain send cannot replace it. If it still has not arrived, stop and say what the screen shows.
6. **Remove the placeholder.** Run `hc kill` then `hc rm` on the `terminal` from step 4. It is the space's initial shell. If step 5 failed, this also closes the space.

Done when the task is on `ticket-<n>`'s screen. Name the terminal, and end your turn: its report arrives here as an `hc` message.
