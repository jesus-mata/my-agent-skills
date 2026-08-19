#!/bin/sh
# One-liner install for a fresh machine:
#
#   curl -fsSL https://raw.githubusercontent.com/jesus-mata/my-agent-skills/main/bootstrap.sh | sh
#
# Clones this repo to ~/.agent-skills (or $AGENT_SKILLS_HOME) and links every skill into
# every coding agent it finds. Safe to run twice: an existing clone is pulled, not replaced.
set -eu

REPO=${AGENT_SKILLS_REPO:-https://github.com/jesus-mata/my-agent-skills.git}
DEST=${AGENT_SKILLS_HOME:-$HOME/.agent-skills}

command -v git >/dev/null 2>&1 || { echo "bootstrap: git is required" >&2; exit 1; }

if [ -d "$DEST/.git" ]; then
  echo "bootstrap: clone exists at $DEST — pulling"
  git -C "$DEST" pull --ff-only || echo "bootstrap: pull failed, using the working copy as it is" >&2
elif [ -e "$DEST" ]; then
  echo "bootstrap: $DEST exists but is not a git clone — move it aside or set AGENT_SKILLS_HOME" >&2
  exit 1
else
  echo "bootstrap: cloning $REPO into $DEST"
  git clone "$REPO" "$DEST"
fi

echo "bootstrap: linking skills"
exec "$DEST/bin/agent-skills" install "$@"
