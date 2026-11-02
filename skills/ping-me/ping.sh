#!/bin/bash
# Usage: ping.sh <ok|fail|attention> "<summary>"
# Publishes to the topic in ~/.config/ping-me/ntfy.conf, titled with the current project.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
set -euo pipefail

NTFY_SERVER="https://ntfy.sh"
NTFY_TOPIC=""
conf="${XDG_CONFIG_HOME:-$HOME/.config}/ping-me/ntfy.conf"
[ -f "$conf" ] && . "$conf"
[ -n "$NTFY_TOPIC" ] || { echo "NTFY_TOPIC is not set in $conf" >&2; exit 1; }

status=${1:-}
summary=${2:-}
usage='usage: ping.sh <ok|fail|attention> "<summary>"'
priority=3
case "$status" in
  ok) state="listo"; tag="white_check_mark" ;;
  fail) state="falló"; tag="x" ;;
  attention) state="necesita tu atención"; tag="bell"; priority=4 ;;
  *) echo "$usage" >&2; exit 2 ;;
esac
[ -n "$summary" ] || { echo "$usage" >&2; exit 2; }

jq -n --arg topic "$NTFY_TOPIC" --arg title "$(basename "$PWD"): $state" \
  --arg message "$summary" --argjson priority "$priority" --arg tag "$tag" \
  '{topic: $topic, title: $title, message: $message[0:300], priority: $priority, tags: [$tag]}' |
  curl -fsS -m 8 -H 'Content-Type: application/json' -d @- "$NTFY_SERVER/" >/dev/null
