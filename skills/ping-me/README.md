# ping-me

Sends a [ntfy](https://ntfy.sh) push to your phone once Claude finishes what you asked. Say
"fix the test and ping me", or just "ping me" to get one right away.

Works with Claude Code on macOS and Linux, and with ntfy servers that accept unauthenticated
publishing. It needs `bash`, `curl` and `jq`.

## Setup

These steps are written so a person or a Claude session on the new machine can follow them in
order. Steps 1 to 4 install the skill. Step 5 is optional: ask the person before doing it.

### 1. Check the dependencies

```sh
command -v bash curl jq
```

Each one must print a path. Install what is missing with `brew install` on macOS, or the
system's package manager on Linux (for example `sudo apt-get install -y curl jq`).

### 2. Link the skill

The skill must end up at `~/.claude/skills/ping-me`, because `SKILL.md` calls `ping.sh` by that
path. Use `--target claude`: the skill runs only under Claude Code.

```sh
git clone https://github.com/jesus-mata/my-agent-skills.git ~/.agent-skills
~/.agent-skills/bin/agent-skills install ping-me --target claude
```

If the machine already has a clone, run `git pull` there and use its `bin/agent-skills` instead.

If the install reports that `ping-me` is a real directory, an older copy is in the way. Add
`--force`, which backs it up to `~/.agent-skills-backups/` and then links.

### 3. Configure the topic

The topic lives in `~/.claude/ntfy.conf`, outside the repo, so it is never committed. Leave the
file alone if it already exists.

To get every machine's pings in one place, ask the person for the topic they already use and
write it to `NTFY_TOPIC`. Otherwise generate a new one:

```sh
[ -e ~/.claude/ntfy.conf ] || (umask 077; printf 'NTFY_TOPIC=claude-%s\n' "$(openssl rand -hex 12)" > ~/.claude/ntfy.conf)
```

On ntfy.sh anyone who knows a topic's name can read it, so treat the name like a password and
keep it out of repos and shared chats.

To use your own server, add `NTFY_SERVER=https://ntfy.example.com` to the same file.

### 4. Subscribe and test

Subscribe to the topic in the ntfy app, on the server from step 3, then run:

```sh
~/.claude/skills/ping-me/ping.sh ok "Test from $(hostname)"
```

The setup is done when this exits 0 and the push reaches the phone. Sessions that were already
open may need a restart to see the skill.

### 5. Optional: attention hooks

`ntfy-notify.sh` is separate from the skill: it needs no prompt, and pushes on its own whenever
Claude stops to wait for you. It fires when Claude asks a question, when a plan is ready, and on
Claude Code's attention notifications such as a permission prompt. It uses the same
`~/.claude/ntfy.conf`, and skips the notifications that only mean a turn ended.

Merge this into `~/.claude/settings.json`, keeping every hook and setting already there:

```json
{
  "hooks": {
    "Notification": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash \"$HOME/.claude/skills/ping-me/ntfy-notify.sh\"",
            "timeout": 12,
            "async": true
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "AskUserQuestion|ExitPlanMode",
        "hooks": [
          {
            "type": "command",
            "command": "bash \"$HOME/.claude/skills/ping-me/ntfy-notify.sh\"",
            "timeout": 12,
            "async": true
          }
        ]
      }
    ]
  }
}
```

`PreToolUse` is what covers sessions in `bypassPermissions` mode, where permission prompts rarely
appear.

Check the file is still valid JSON, then send a test push:

```sh
jq -e .hooks ~/.claude/settings.json >/dev/null
printf '{"hook_event_name":"PreToolUse","tool_name":"ExitPlanMode","session_id":"setup-test","cwd":"%s"}' "$PWD" |
  bash ~/.claude/skills/ping-me/ntfy-notify.sh
```

The hook always exits 0 so it can never block Claude. It is working when the push reaches the
phone; failed sends land in `~/.claude/state/ntfy/errors.log`. Restart open sessions, or open
`/hooks` once, to load the new hooks.
