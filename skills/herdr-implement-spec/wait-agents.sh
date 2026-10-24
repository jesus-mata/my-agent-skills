#!/usr/bin/env bash
# Wait until every named herdr agent has finished its turn (done, idle or
# blocked), then print each one's last turn.
# Usage: wait-agents.sh [--timeout SECONDS] [--until-line RE] [--lines N] <agent>...
#   --timeout     shared deadline for all agents (3600)
#   --until-line  ERE: a finished turn without a matching line does not count,
#                 for agents that end turns while their own background work runs
#   --lines       lines of each agent's last turn to print (40)
# Exit 0 when all finished, 3 if any is blocked waiting for input, 1 if any
# timed out or is gone (1 wins over 3).
set -u

usage() { echo "usage: wait-agents.sh [--timeout SECONDS] [--until-line RE] [--lines N] <agent>..." >&2; exit 2; }

timeout=3600
end_re=""
lines=40
while [ $# -gt 0 ]; do
  case "$1" in
    --timeout)    timeout="${2:?}"; shift 2 ;;
    --until-line) end_re="${2:?}"; shift 2 ;;
    --lines)      lines="${2:?}"; shift 2 ;;
    --*)          usage ;;
    *)            break ;;
  esac
done
[ $# -gt 0 ] || usage

# shellcheck source=herdr-lib.sh disable=SC1091
. "$(dirname "${BASH_SOURCE[0]}")/herdr-lib.sh"

deadline=$(( $(date +%s) + timeout ))

# See each turn start before waiting for its end, or the wait matches the
# `idle`/`done` from before the prompt. One shared 30 s budget, not 30 s per
# agent: an agent that already finished would otherwise cost the full 30 s.
start_by=$(( $(date +%s) + 30 ))
for a in "$@"; do
  left=$(( (start_by - $(date +%s)) * 1000 ))
  [ "$left" -gt 0 ] || break
  herdr agent wait "$a" --until working --until blocked --timeout "$left" >/dev/null 2>&1 || true
done

# One after another is fine: the total is still the slowest agent, and an
# agent that is already blocked or done returns at once.
rc=0
summary=""
for a in "$@"; do
  r=0
  wait_one_ "$a" "$deadline" "$lines" "$end_re" || r=$?
  case "$r" in
    1) rc=1; summary="$summary $a:timeout/gone" ;;
    3) [ "$rc" = 1 ] || rc=3; summary="$summary $a:blocked" ;;
    *) summary="$summary $a:done" ;;
  esac
done
echo "summary:$summary"
exit "$rc"
