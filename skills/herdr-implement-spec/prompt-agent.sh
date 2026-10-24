#!/usr/bin/env bash
# Send a prompt to a herdr agent and confirm it was submitted.
# Usage: prompt-agent.sh <agent> <prompt>
# Returns once the agent has started working on it (a few seconds); it does
# not wait for the turn. Wait with wait-agents.sh.
#
# Why not plain `herdr agent prompt`:
# - A long or multi-line "/cmd ..." enters the TUI as pasted text and is never
#   run as a slash command; the command goes alone, the rest to a file.
# - A multi-line prompt can stall with the text typed but Enter not taken
#   (agent_prompt_stalled), and Claude reports ready a moment before it accepts
#   Enter: confirm the turn started, press Enter again if not.
set -euo pipefail

[ $# -eq 2 ] || { echo "usage: prompt-agent.sh <agent> <prompt>" >&2; exit 2; }
agent="$1"

# shellcheck source=herdr-lib.sh disable=SC1091
. "$(dirname "${BASH_SOURCE[0]}")/herdr-lib.sh"

slash_prompt_ "$2"
if out=$(herdr agent prompt "$agent" "$SLASH_PROMPT" \
    --wait --until working --until blocked --until idle --until done --timeout 20000 2>&1); then
  exit 0
fi
case "$out" in
  *agent_blocked*)
    echo "prompt-agent: $agent is blocked waiting for input; read its pane and answer that first" >&2
    exit 1 ;;
esac
herdr agent send-keys "$agent" Enter >/dev/null 2>&1 || true
herdr agent wait "$agent" --until working --until blocked --timeout 10000 >/dev/null 2>&1 && exit 0
echo "prompt-agent: $agent did not start working on the prompt: $out" >&2
exit 1
