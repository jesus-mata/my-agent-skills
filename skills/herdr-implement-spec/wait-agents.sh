#!/usr/bin/env bash
# Wait until every named herdr agent has finished its turn (done, idle or blocked).
# Usage: wait-agents.sh [--timeout SECONDS] <agent-name>...
# Exit 0 when all agents stopped, 1 on timeout (prints the pending agents).
set -u

timeout=3600
if [ "${1:-}" = "--timeout" ]; then timeout=$2; shift 2; fi
[ $# -gt 0 ] || { echo "usage: wait-agents.sh [--timeout SECONDS] <agent-name>..." >&2; exit 2; }

deadline=$((SECONDS + timeout))
sleep 15 # an agent can still report idle right after the prompt is submitted
while [ $SECONDS -lt $deadline ]; do
  pending=""
  for a in "$@"; do
    s=$(herdr agent get "$a" | python3 -c 'import sys,json; print(json.load(sys.stdin)["result"]["agent"]["agent_status"])')
    case "$s" in
      done | idle | blocked) echo "$a: $s" ;;
      *) pending="$pending $a" ;;
    esac
  done
  [ -z "$pending" ] && exit 0
  sleep 30
done
echo "timeout, still pending:$pending"
exit 1
