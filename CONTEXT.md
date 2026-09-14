# my-agent-skills

A personal collection of agent skills, plus the installer that makes them available to every
coding agent on a machine. This glossary fixes the words used to talk about installation, so
"install" never has to mean two things at once.

## Language

**Skill**:
A folder containing a `SKILL.md` with YAML frontmatter, and optionally supporting files. The
unit of everything here — authored, validated, linked and shared one folder at a time.
_Avoid_: Command, plugin, prompt

**Clone**:
The working copy of this repository on a machine. It is the single source of truth for skill
content; every linked skill on that machine resolves back into it.
_Avoid_: Install directory, source

**Target**:
An agent's user-global skills directory that the installer can link into — `~/.claude/skills`,
`~/.codex/skills`, `~/.cursor/skills`, `~/.gemini/skills`, `~/.config/opencode/skills`. A target
is _detected_ (its parent directory exists) or absent.
_Avoid_: Agent, destination, provider

**Link**:
To create a symlink inside a target pointing at a skill in the clone. The act of making one
skill visible to one agent on one machine.
_Avoid_: Install (ambiguous), copy, sync

**Publish**:
To make the repository available to another person or another machine — pushing to GitHub and
handing over the bootstrap one-liner. Distinct from Link, which is purely local.
_Avoid_: Install (ambiguous), share, distribute

**Shadow**:
A real directory sitting in a target where a link belongs — an older copy of a skill installed
by some other means. Shadows hide the clone's version and must be resolved explicitly.
_Avoid_: Conflict, duplicate

**Adopt**:
To move a skill that exists only as a real directory in a target into the clone, then link it
back — turning what would become a shadow into a link.
_Avoid_: Import, migrate

**Prune**:
To remove links in targets that resolve into the clone but no longer name a skill that exists
there — the residue of a skill deleted or renamed upstream.
_Avoid_: Clean, gc
