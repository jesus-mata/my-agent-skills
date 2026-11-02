---
name: hc-implement-ticket
description: "Takes a ticket from code to MR with an hc orchestrator: develop, review and E2E each run in their own terminal, which stay open for follow-ups."
argument-hint: <issue-number>
disable-model-invocation: true
allowed-tools: Bash(printenv HC_TERMINAL_ID) Bash(git rev-parse *) Bash(hc get *) Bash(hc run *) Bash(hc read *) Bash(hc keys *) Bash(hc kill *) Bash(hc rm *) Bash(herdr-app ls) Bash(herdr-app do space.new *)
---

# Launch the ticket orchestrator

Start the `ticket-orchestrator` hc template on ticket $ARGUMENTS, then hand over. The orchestrator runs the workflow in [WORKFLOW.md](WORKFLOW.md); this session only launches it.

1. **Check.** Stop and say why unless `$ARGUMENTS` is one issue number and `printenv HC_TERMINAL_ID` prints an address. The main checkout is the parent of `git rev-parse --path-format=absolute --git-common-dir`, and `<repo>` is its folder name.
2. **Check the name.** If `hc get ticket-<n>` finds a terminal, live or finished, stop and show its `cwd` and state. Hc names are unique across repos, so tell the human to run `hc kill ticket-<n>` and `hc rm ticket-<n>`, and to remove any `fix/issue_<n>` branch or worktree before a retry.
3. **Open a space,** only if `herdr-app ls` lists the address from step 1. Run `herdr-app do space.new --name "<repo> #<n>" --folder <main checkout> --tab ticket` and keep its `space`, `tab` and `terminal`.
4. **Start the orchestrator.** Add the labels only if step 3 opened a space:

   ```sh
   hc run --bg --outlive-parent --name ticket-<n> --cwd <main checkout> \
     --label herdr.space=<space> --label herdr.tab=<tab> ticket-orchestrator "<n>"
   ```

   If `first_message.sent` is false, read `hc read ticket-<n>`. Accept a folder trust dialog for the main checkout with `hc keys ticket-<n> down enter`. If the task is not on its screen, `hc kill` and `hc rm` it, then start it once more: the task holds the template's instructions, so a plain send cannot replace it. If it still has not arrived, stop and say what the screen shows.
5. **Remove the placeholder.** Run `hc kill` then `hc rm` on the `terminal` from step 3. It is the space's initial shell. If step 4 failed, this also closes the space.

Done when the task is on `ticket-<n>`'s screen. Name the terminal, and end your turn: its report arrives here as an `hc` message.
