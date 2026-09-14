# my-agent-skills

My personal agent skills, plus a small installer that links them into every coding agent on a
machine — Claude Code, Codex, Cursor, Gemini CLI, opencode, and anything else that reads a
`skills/` directory.

Skills are **linked, not copied**. One clone is the source of truth: edit a skill here and every
agent on that machine sees the change immediately. Updating is `git pull`.

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/jesus-mata/my-agent-skills/main/bootstrap.sh | sh
```

Clones to `~/.agent-skills` and links every skill into every agent it finds. Run it again any
time — an existing clone is pulled, never replaced.

Already have a clone? Use it directly:

```sh
git clone https://github.com/jesus-mata/my-agent-skills.git
cd my-agent-skills
bin/agent-skills install
```

The installer links from whichever clone it lives in, so there is never a second copy drifting
behind the one you edit.

## Skills

<!-- skills:start -->

| Skill | What it does |
| --- | --- |
| [`e2e`](skills/e2e/SKILL.md) | Bring up the local stack and end-to-end test a change — web app, HTTP API, CLI, or desktop app — driven by the project's root E2E.md. Use it when you need to verify that something actually works, not just that it compiles or that the unit tests pass. |
| [`herdr-implement-spec`](skills/herdr-implement-spec/SKILL.md) | Implement every ticket of a spec/PRD by orchestrating parallel Claude instances in herdr worktrees, wave by wave, merging each into a spec branch. Use when the user hands you a spec or PRD (or its GitHub issue) and wants its linked issues or slices implemented, not just a single ticket. |
| [`implement-ticket`](skills/implement-ticket/SKILL.md) | Implements the work of a ticket or issue |
| [`refine-ticket`](skills/refine-ticket/SKILL.md) | Rewrite an existing ticket in place so it matches the /to-tickets format, falsifying its technical claims against the real code before trusting any of them. Use whenever the user wants to update, refine, clean up, reformat or "fix" a ticket or issue, wants the open questions in a ticket resolved, mentions /to-tickets or the ticket template, or just hands you a ticket number and says it needs work — even when they never name the format. Also use when a ticket came out of an autonomous code review and needs to be made implementable. |

<!-- skills:end -->

## Commands

```
bin/agent-skills install [skill...]    Link skills into every detected agent
bin/agent-skills update                git pull, relink, prune links to skills that are gone
bin/agent-skills status                What is linked, missing, shadowed or dangling
bin/agent-skills uninstall [skill...]  Remove links pointing into this clone — nothing else
bin/agent-skills adopt <skill>         Move a skill out of an agent into this clone, link it back
bin/agent-skills validate [skill...]   Check frontmatter and references
bin/agent-skills readme                Regenerate the skill table above
```

Flags: `--target claude,codex` (or an absolute path to any other agent's skills directory),
`--all`, `--force`, `--dry-run`.

## Agents

Linked only where the agent is already installed — the tool never creates an agent's home
directory, only its `skills/` folder.

| Agent | Directory |
| --- | --- |
| Claude Code | `~/.claude/skills` |
| Codex | `~/.codex/skills` |
| Cursor | `~/.cursor/skills` |
| Gemini CLI | `~/.gemini/skills` |
| opencode | `~/.config/opencode/skills` |
| anything else | `--target /path/to/skills` |

Agents that read only an `AGENTS.md` (aider, goose) are out of scope: a flat file has no
progressive disclosure, so "installing" a skill there means pasting its whole body into every
prompt.

macOS and Linux. POSIX `sh`, no runtime dependencies beyond `git`.

## How it behaves when things collide

- A **real directory** where a link belongs (an older copy of the same skill) is left alone and
  reported. `--force` moves it to `~/.agent-skills-backups/<timestamp>/` and then links.
- A link pointing **somewhere other than this clone** belongs to another tool; same rule.
- `uninstall` removes only links that resolve into this clone. Nothing else is ever deleted.
- There is no lockfile. A symlink already records where it came from, so `status` reads the
  filesystem and cannot disagree with it.

## Writing a skill

A skill is a directory under `skills/` containing `SKILL.md` with YAML frontmatter:

```md
---
name: my-skill
description: What it does, and when an agent should reach for it.
---

# my-skill
...
```

`bin/agent-skills validate` checks the frontmatter, that relative file references resolve, and
that `/other-skill` references name a skill that actually ships in this repo — a reference to a
skill you have locally but haven't published here will dangle on every other machine.

## License

MIT — see [LICENSE](LICENSE).
