# 1. Link from a single clone; no lockfile

Date: 2026-08-18

## Status

Accepted

## Context

The same set of skills has to be available to every coding agent on every machine I use, and
stay current without ceremony. Each agent reads its own directory — `~/.claude/skills`,
`~/.codex/skills`, `~/.cursor/skills`, `~/.gemini/skills`, `~/.config/opencode/skills` — but
they all agree on the same unit: a folder containing `SKILL.md`.

That leaves a choice about what "installing" a skill means, and this machine already has both
answers running side by side. Cloudflare's installer **copied** the same skill folders into all
five agent directories. The vercel-labs `skills` CLI keeps one copy under `~/.agents/skills`,
records provenance in `~/.agents/.skill-lock.json`, and **symlinks** it into `~/.claude/skills`.

Before this decision, my own skills were maintained by hand-copying between `~/.claude/skills`
and this repository — which is exactly how three byte-identical duplicates came to exist with no
way to tell which was authoritative.

## Decision

One clone of this repository is the source of truth on a machine. Installing a skill creates an
absolute symlink from each agent's skills directory into that clone. Skills are never copied.

Consequently:

- **No hub.** Links point straight at the clone, not through `~/.agents/skills`.
- **No lockfile.** A symlink records its own source, so `status`, `uninstall` and `prune` are
  derived by reading the filesystem.
- **`--copy` mode does not exist.**
- **Destructive operations are scoped by resolution, not by name**: `uninstall` removes only
  links that resolve into the clone; a real directory or a link pointing elsewhere is reported
  and left alone unless `--force`, which backs it up first.

## Consequences

Updating content needs no tool at all: `git pull` and every agent on the machine is current.
Editing a skill in one agent's directory edits the canonical copy, so the copy-and-drift loop
that produced the duplicates is structurally impossible.

The costs are real and accepted:

- **The clone's path is load-bearing.** Move or delete it and every agent on that machine gets
  dangling links. `update` prunes them; nothing prevents them.
- **A skill cannot be installed without the clone present** — no offline artifact, no versioned
  tarball, no pinning. Everyone tracks `main`.
- **Windows without Developer Mode is unsupported**, since it cannot create symlinks freely.
  Accepted because only macOS and Linux are in scope.
- **Two conventions now coexist on my machines**: the `skills` CLI's hub with its lockfile, and
  this clone. They do not manage the same skills, but a future reader will see both.

Reversing this means writing a copy mode and a state file to track what was copied where —
cheap in code, but it reintroduces the drift this decision exists to eliminate.
