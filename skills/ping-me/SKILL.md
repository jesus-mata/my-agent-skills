---
name: ping-me
description: Sends the user a ntfy push once their request is finished. Use when the user tells you to "ping me", alone or as part of a task (e.g. "fix the test and ping me"). Not for "ping me" inside quoted text, code or logs, or in questions about this skill.
---

Do everything else the user asked first; the ping is the last action of the request. If "ping me" is the whole prompt, send it now.

Send it with:

```bash
~/.claude/skills/ping-me/ping.sh <ok|fail> "<summary>"
```

- `ok` when the request is done; `fail` when it failed or is blocked.
- `<summary>` is one or two sentences in the user's language: what was done and how it ended. Write for a phone screen, and leave out secrets, credentials and customer data, since the topic is readable by anyone who knows its name.

The ping is done when `ping.sh` exits 0. On a non-zero exit, tell the user the ping did not arrive and show the error.
