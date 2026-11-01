#!/bin/bash
# Sends a ntfy push when Claude needs attention.
# Reads the hook payload on stdin; config lives in ~/.config/ping-me/ntfy.conf.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

NTFY_SERVER="https://ntfy.sh"
conf="${XDG_CONFIG_HOME:-$HOME/.config}/ping-me/ntfy.conf"
[ -f "$conf" ] && . "$conf"
[ -n "$NTFY_TOPIC" ] || exit 0

state="$HOME/.claude/state/ntfy"
mkdir -p "$state"

input=$(cat)
field() { jq -r "$1 // empty" <<<"$input"; }

event=$(field .hook_event_name)
session=$(field .session_id | tr -cd 'A-Za-z0-9_-')
project=$(basename "$(field .cwd)")
last_file="$state/$session.attention"

send() { # title, message, priority, tags
  jq -n --arg topic "$NTFY_TOPIC" --arg title "$1" --arg message "$2" \
    --argjson priority "$3" --arg tag "$4" \
    '{topic: $topic, title: $title, message: $message[0:300], priority: $priority, tags: [$tag]}' |
    curl -fsS -m 8 -H 'Content-Type: application/json' -d @- "$NTFY_SERVER/" \
      >/dev/null 2>>"$state/errors.log"
}

attention() { # message
  # Notification and PreToolUse can fire for the same prompt.
  local now last
  now=$(date +%s)
  last=$(cat "$last_file" 2>/dev/null || echo 0)
  [ $((now - last)) -ge 5 ] || return 0
  echo "$now" >"$last_file"
  send "$project: necesita tu atención" "$1" 4 bell
}

case "$event" in
  Notification)
    # idle_prompt and agent_completed only mean a turn ended.
    case "$(field .notification_type)" in
      idle_prompt | agent_completed) exit 0 ;;
    esac
    attention "$(field .message)"
    ;;
  PreToolUse)
    case "$(field .tool_name)" in
      AskUserQuestion) attention "$(field '.tool_input.questions[0].question')" ;;
      ExitPlanMode) attention "Plan listo para revisar" ;;
    esac
    ;;
esac
exit 0
