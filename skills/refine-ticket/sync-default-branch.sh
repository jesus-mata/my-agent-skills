#!/usr/bin/env bash
# sync-default-branch.sh [cwd]
#
# Brings the repo's default branch (usually main) up to date before the ticket
# is checked against the code, and prints the ref to read the code from.
#
#   ./sync-default-branch.sh
#   ./sync-default-branch.sh ~/repo
#
# Fetches origin, then:
#   - tracked files clean -> switches to the default branch and pulls --ff-only;
#                            prints READ_FROM=<default>
#   - uncommitted changes -> touches nothing in the working tree;
#                            prints READ_FROM=origin/<default>, to be read with
#                            `git show origin/<default>:<path>` / `git grep ... origin/<default>`
#
# The last line of output is always READ_FROM=<ref> on success. On failure it
# exits non-zero with a "sync-default-branch: ..." message and no READ_FROM line.
#
set -euo pipefail

die() { echo "sync-default-branch: $*" >&2; exit 1; }

CWD="${1:-$PWD}"
TOP=$(git -C "$CWD" rev-parse --show-toplevel 2>/dev/null) \
  || die "$CWD is not inside a git repo"

git -C "$TOP" remote get-url origin >/dev/null 2>&1 \
  || die "the repo has no 'origin' remote"
git -C "$TOP" fetch --quiet origin || die "git fetch origin failed"

DEFAULT=$(git -C "$TOP" symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null) \
  || DEFAULT=$(git -C "$TOP" remote show origin | sed -n 's/.*HEAD branch: //p')
DEFAULT="${DEFAULT#origin/}"
[ -n "$DEFAULT" ] || die "could not work out origin's default branch"

# Untracked files neither block a branch switch nor travel with it, so only
# tracked changes count as dirty.
if [ -n "$(git -C "$TOP" status --porcelain --untracked-files=no)" ]; then
  echo "uncommitted changes in $TOP: left the working tree alone; read the code from origin/$DEFAULT"
  echo "READ_FROM=origin/$DEFAULT"
  exit 0
fi

git -C "$TOP" switch --quiet "$DEFAULT" || die "could not switch to '$DEFAULT'"
git -C "$TOP" pull --quiet --ff-only \
  || die "git pull --ff-only on '$DEFAULT' failed (local '$DEFAULT' has diverged from origin?)"

echo "on $DEFAULT at $(git -C "$TOP" rev-parse --short HEAD), up to date with origin/$DEFAULT"
echo "READ_FROM=$DEFAULT"
