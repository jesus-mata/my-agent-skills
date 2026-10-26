#!/usr/bin/env bash
# cleanup-merged-branch.sh <branch> <merged-head-sha> [repo-dir]
#
# Runs after a PR has been squash-merged on GitHub. Brings the main checkout
# up to date and removes everything the PR's branch left behind:
#
#   1. fetches origin and deletes the remote branch (already-gone is fine)
#   2. main checkout clean -> switches it to the default branch, pull --ff-only
#      main checkout dirty -> leaves it alone and says so
#   3. removes the branch's worktree, if it has one: through herdr when a herdr
#      workspace is open on it, with `git worktree remove` otherwise
#   4. deletes the local branch
#
#   ./cleanup-merged-branch.sh ticket-42 3f2c1ab...
#   ./cleanup-merged-branch.sh ticket-42 3f2c1ab... ~/repo
#
# <merged-head-sha> is the PR head that was merged (headRefOid). A squash merge
# never makes the branch an ancestor of main, so `branch -d` can't tell merged
# work from unmerged work; comparing against this SHA can. A worktree with
# uncommitted or untracked files, or a local branch with commits the merge
# didn't include, is left in place and reported — nothing unmerged is deleted.
#
# When the herdr workspace to remove is the one running this script, removing
# it would kill the caller mid-run. The worktree and branch removal is then
# handed to a detached process that starts after DEFER_SECONDS.
#
# Every outcome ends with one line, CLEANUP=<status>:
#   CLEANUP=done             everything removed
#   CLEANUP=deferred log=<f> removal scheduled; <f> records how it went
#   CLEANUP=kept reason=<r>  something was deliberately left; <r> says what
# A failure exits non-zero with a "cleanup-merged-branch: ..." message.
#
set -euo pipefail

# Long enough for the caller to print its report before its pane goes away.
DEFER_SECONDS=15

die() { echo "cleanup-merged-branch: $*" >&2; exit 1; }

BRANCH="${1:-}"
MERGED_SHA="${2:-}"
CWD="${3:-$PWD}"
[ -n "$BRANCH" ] && [ -n "$MERGED_SHA" ] \
  || die "usage: cleanup-merged-branch.sh <branch> <merged-head-sha> [repo-dir]"

git -C "$CWD" rev-parse --git-dir >/dev/null 2>&1 || die "$CWD is not inside a git repo"

# The first entry of `worktree list` is always the main working tree, even
# when this runs from inside a linked worktree.
MAIN=$(git -C "$CWD" worktree list --porcelain | sed -n '1s/^worktree //p')
[ -d "$MAIN" ] || die "could not find the main checkout"

git -C "$MAIN" fetch --quiet --prune origin || die "git fetch origin failed"

DEFAULT=$(git -C "$MAIN" symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null) \
  || DEFAULT=$(git -C "$MAIN" remote show origin | sed -n 's/.*HEAD branch: //p')
DEFAULT="${DEFAULT#origin/}"
[ -n "$DEFAULT" ] || die "could not work out origin's default branch"
[ "$BRANCH" != "$DEFAULT" ] || die "refusing to clean up the default branch '$DEFAULT'"

# --- 1. remote branch --------------------------------------------------------
# The repo may delete head branches on merge by itself; --prune above already
# dropped the tracking ref in that case.
if git -C "$MAIN" show-ref --verify --quiet "refs/remotes/origin/$BRANCH"; then
  git -C "$MAIN" push --quiet origin --delete "$BRANCH" \
    || die "could not delete the remote branch origin/$BRANCH"
  echo "deleted origin/$BRANCH"
else
  echo "origin/$BRANCH already gone"
fi

# --- 2. main checkout --------------------------------------------------------
KEPT=""
keep() { KEPT="${KEPT:+$KEPT,}$1"; }

# Untracked files neither block a branch switch nor travel with it.
if [ -n "$(git -C "$MAIN" status --porcelain --untracked-files=no)" ]; then
  echo "main checkout $MAIN has uncommitted changes: left it on $(git -C "$MAIN" branch --show-current)"
  keep main-checkout-dirty
else
  git -C "$MAIN" switch --quiet "$DEFAULT" || die "could not switch $MAIN to '$DEFAULT'"
  git -C "$MAIN" pull --quiet --ff-only \
    || die "git pull --ff-only on '$DEFAULT' failed (local '$DEFAULT' has diverged from origin?)"
  echo "main checkout on $DEFAULT at $(git -C "$MAIN" rev-parse --short HEAD)"
fi

# --- 3. is there anything local the merge didn't include? -------------------
LOCAL_SHA=""
if git -C "$MAIN" show-ref --verify --quiet "refs/heads/$BRANCH"; then
  LOCAL_SHA=$(git -C "$MAIN" rev-parse "refs/heads/$BRANCH")
  if [ "$LOCAL_SHA" != "$MERGED_SHA" ] \
     && ! git -C "$MAIN" merge-base --is-ancestor "$LOCAL_SHA" "$MERGED_SHA" 2>/dev/null; then
    echo "local $BRANCH ($(git -C "$MAIN" rev-parse --short "$LOCAL_SHA")) has commits the merge didn't include: kept the branch and its worktree"
    echo "CLEANUP=kept reason=unmerged-commits${KEPT:+,$KEPT}"
    exit 0
  fi
fi

WT=$(git -C "$MAIN" worktree list --porcelain | awk -v ref="refs/heads/$BRANCH" '
  /^worktree / { path = substr($0, 10) }
  $0 == "branch " ref { print path; exit }')

if [ "$WT" = "$MAIN" ]; then
  # No linked worktree: the branch is checked out in the main checkout, which
  # step 2 could not switch away from.
  echo "$BRANCH is still checked out in $MAIN: kept the local branch"
  echo "CLEANUP=kept reason=${KEPT:-branch-checked-out}"
  exit 0
fi

if [ -n "$WT" ] && [ -n "$(git -C "$WT" status --porcelain)" ]; then
  echo "worktree $WT has uncommitted or untracked files: kept it and the local branch"
  git -C "$WT" status --short | head -20
  echo "CLEANUP=kept reason=worktree-dirty${KEPT:+,$KEPT}"
  exit 0
fi

# --- 4. herdr workspace, if one is open on the worktree ---------------------
WS=""
SELF_WS=""
if [ -n "$WT" ] && command -v herdr >/dev/null 2>&1 && command -v python3 >/dev/null 2>&1; then
  WS=$(herdr worktree list --cwd "$MAIN" 2>/dev/null | python3 -c '
import json, os, sys
wt = os.path.realpath(sys.argv[1])
try:
    for w in json.load(sys.stdin)["result"]["worktrees"]:
        if os.path.realpath(w["path"]) == wt and w.get("open_workspace_id"):
            print(w["open_workspace_id"]); break
except Exception:
    pass
' "$WT" || true)
  if [ -n "$WS" ] && [ -n "${HERDR_PANE_ID:-}" ]; then
    SELF_WS=$(herdr pane get "$HERDR_PANE_ID" 2>/dev/null | python3 -c '
import json, sys
try:
    print(json.load(sys.stdin)["result"]["pane"]["workspace_id"])
except Exception:
    pass
' || true)
  fi
fi

remove_cmds() {
  if [ -n "$WS" ]; then
    echo "herdr worktree remove --workspace '$WS'"
  elif [ -n "$WT" ]; then
    echo "git -C '$MAIN' worktree remove '$WT'"
  fi
  # herdr may leave the git worktree registered; drop any stale entry.
  echo "git -C '$MAIN' worktree prune"
  # -D because a squash merge leaves the branch unmerged in git's eyes; step 3
  # already proved the merge included everything on it.
  [ -z "$LOCAL_SHA" ] || echo "git -C '$MAIN' branch -D '$BRANCH'"
}

case "$(cd "$CWD" && pwd -P)/" in
  "$(cd "${WT:-/nonexistent}" 2>/dev/null && pwd -P)/"*) INSIDE=1 ;;
  *) INSIDE=0 ;;
esac

if [ -n "$WS" ] && { [ "$WS" = "$SELF_WS" ] || [ "$INSIDE" = 1 ]; }; then
  LOG="$(git -C "$MAIN" rev-parse --absolute-git-dir)/merge-pr-cleanup-$BRANCH.log"
  {
    echo "sleep $DEFER_SECONDS"
    remove_cmds
  } > "$LOG.sh"
  nohup sh -c "cd '$MAIN' && sh -ex '$LOG.sh'" > "$LOG" 2>&1 < /dev/null &
  echo "this process runs inside herdr workspace $WS: its removal starts in ${DEFER_SECONDS}s, detached"
  remove_cmds | sed 's/^/  will run: /'
  echo "CLEANUP=deferred log=$LOG${KEPT:+ kept=$KEPT}"
  exit 0
fi

if [ -n "$WS" ]; then
  herdr worktree remove --workspace "$WS" >/dev/null || die "herdr worktree remove --workspace $WS failed"
  echo "removed herdr workspace $WS and its worktree $WT"
elif [ -n "$WT" ]; then
  git -C "$MAIN" worktree remove "$WT" || die "git worktree remove $WT failed"
  echo "removed worktree $WT"
fi
git -C "$MAIN" worktree prune

if [ -n "$LOCAL_SHA" ]; then
  git -C "$MAIN" branch --quiet -D "$BRANCH" || die "could not delete local branch $BRANCH"
  echo "deleted local branch $BRANCH"
fi

if [ -n "$KEPT" ]; then
  echo "CLEANUP=kept reason=$KEPT"
else
  echo "CLEANUP=done"
fi
