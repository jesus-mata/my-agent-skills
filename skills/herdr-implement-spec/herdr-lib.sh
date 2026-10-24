#!/usr/bin/env bash
# herdr-lib.sh — helpers shared by wait-agents.sh and prompt-agent.sh.
# Not run directly: `source` it.
#
# Copied from skills/work-ticket/herdr-report.sh, where each quirk below was
# found the hard way. A fix there likely belongs here too.

HERDR_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# clean_report_  (stdin -> stdout)
# Keeps only the agent's last turn: from the last prompt actually sent to the
# end, without the welcome banner, TUI frame, input box or status bar. Never
# fails: if it recognises nothing it returns what it got.
clean_report_() {
  python3 -c '
import sys

BOX = "─━│┃┌┐└┘├┤┬┴┼╭╮╰╯╱╲"
PROMPT = "❯"

def chrome(line):
    s = line.strip()
    if not s or s == PROMPT:
        return True
    if all(c in BOX + " " for c in s):
        return True
    return s.startswith(("Model:", "⏵⏵", "✔ Update installed"))

# The TUI separates with non-breaking spaces (U+00A0), so "❯ text" does not
# match a plain space. Normalise before looking at anything.
lines = [l.replace("\xa0", " ") for l in sys.stdin.read().splitlines()]
while lines and chrome(lines[-1]):
    lines.pop()
# A trailing "❯ text" is the input box with unsent typing, not a sent prompt:
# taking it as the turn start would swallow the whole answer.
while lines and lines[-1].strip().startswith(PROMPT + " "):
    lines.pop()
    while lines and chrome(lines[-1]):
        lines.pop()
sent = [i for i, l in enumerate(lines) if l.strip().startswith(PROMPT + " ")]
if sent:
    lines = lines[sent[-1]:]
sys.stdout.write("\n".join(l for l in lines if not chrome(l)))
'
}

# drop_prompt_echo_  (stdin -> stdout)
# Drops the prompt echo the TUI paints at the start of the turn; a long prompt
# echo swallowed the whole report. Cuts from the first answer mark, since with
# a long prompt the "❯" line does not even fit in the read window.
drop_prompt_echo_() {
  python3 -c '
import sys

MARKS = ("⏺", "✻", "✽", "⎿", "✢")   # start of the agent answer
lines = sys.stdin.read().splitlines()
for i, l in enumerate(lines):
    if l.strip().startswith(MARKS):
        lines = lines[i:]
        break
sys.stdout.write("\n".join(lines))
'
}

# read_turn_ <pane> <lines>  (-> stdout)
# The agent's last turn, cleaned. Reads 4x and trims: reading exactly <lines>
# lost the answer when the welcome banner filled half the screen.
read_turn_() {
  herdr pane read "$1" --source recent-unwrapped --lines $(($2 * 4)) 2>/dev/null \
    | clean_report_ | drop_prompt_echo_
}

# slash_prompt_ <prompt>  (-> $SLASH_PROMPT, $SLASH_PROMPT_FILE)
# A prompt starting with "/cmd" that is multi-line or long enters the TUI as
# "[Pasted text #N]", and pasted text is never run as a slash command: the
# skill never loads. So the command goes alone on a short line and the rest to
# a file the agent reads. Any other prompt is returned as is.
#   SLASH_PROMPT       prompt to send
#   SLASH_PROMPT_FILE  file created, or empty if no split was needed
#   SLASH_PROMPT_MAX   max length of an unsplit single line (300)
slash_prompt_() {
  local prompt="$1" cmd body dir
  SLASH_PROMPT="$prompt"
  SLASH_PROMPT_FILE=""
  case "$prompt" in
    /*) ;;
    *)  return 0 ;;
  esac
  case "$prompt" in
    *"
"*) ;;
    *)  [ "${#prompt}" -gt "${SLASH_PROMPT_MAX:-300}" ] || return 0 ;;
  esac
  cmd="${prompt%%[[:space:]]*}"
  body="${prompt#"$cmd"}"
  dir="${TMPDIR:-/tmp}"; dir="${dir%/}/herdr-prompts"
  mkdir -p "$dir"
  # Nobody deletes these once read (the sender returns first): purge old ones.
  find "$dir" -type f -mmin +1440 -delete 2>/dev/null || true
  SLASH_PROMPT_FILE=$(mktemp "${dir}/${cmd#/}.XXXXXX")
  printf '%s\n' "$body" > "$SLASH_PROMPT_FILE"
  SLASH_PROMPT="$cmd Your full instructions for this command are in $SLASH_PROMPT_FILE — read that whole file first and follow it."
}

# wait_one_ <agent> <deadline-epoch> <lines> [end-re]  (-> stdout, status)
#
# Waits for the agent to finish its turn, block, or hit the deadline, then
# prints a header line and its last turn.
#
# [end-re] is an ERE marking the real end of the work. Without it the first
# finished turn is the result. With it, a turn that ends without that line
# does not count: the agent is waiting on background work of its own (fix
# agents, subagents) and will be woken, so keep waiting.
#
# Returns 0 finished · 3 blocked waiting for input · 1 timeout or agent gone.
wait_one_() {
  local target="$1" deadline="$2" lines="$3" end_re="${4:-}"
  local pane wait_out status full left rc

  pane=$(herdr agent get "$target" 2>/dev/null \
    | python3 -c 'import sys,json;print(json.load(sys.stdin)["result"]["agent"]["pane_id"])' \
      2>/dev/null) || {
    echo "== $target -> gone: no such agent"
    return 1
  }

  status="timeout"
  while :; do
    left=$(( (deadline - $(date +%s)) * 1000 ))
    [ "$left" -gt 0 ] || break

    # No --until: the default set is idle|done|blocked. Do not narrow it —
    # claude lands on `done` after a turn, so `--until idle` hangs forever.
    wait_out=$(herdr agent wait "$target" --timeout "$left" 2>&1) || break

    # The state flips a moment before the TUI paints the answer.
    sleep 2
    status=$(printf '%s' "$wait_out" \
      | python3 -c 'import sys,json;print(json.load(sys.stdin)["result"]["agent"]["agent_status"])' \
      2>/dev/null) || status="?"
    full=$(read_turn_ "$pane" "$lines")

    [ -n "$end_re" ] && [ "$status" != blocked ] || break
    if printf '%s\n' "$full" | grep -Eq "$end_re"; then break; fi

    # Turn ended without the end line: wait until it is woken again.
    status="timeout"
    left=$(( (deadline - $(date +%s)) * 1000 ))
    [ "$left" -gt 0 ] || break
    herdr agent wait "$target" --until working --timeout "$left" >/dev/null 2>&1 || break
  done

  if [ "$status" = timeout ]; then
    full=$(read_turn_ "$pane" "$lines")
    # `agent wait` also fails when the agent disappears (pane closed): do not
    # call that a timeout if the deadline had not passed.
    if [ "$(date +%s)" -lt "$deadline" ]; then
      status="gone: the wait failed before the deadline; pane or agent closed?"
    else
      status="timeout"
    fi
  fi

  case "$status" in
    timeout|gone*) rc=1 ;;
    blocked)       rc=3 ;;
    *)             rc=0 ;;
  esac

  echo "== $target (pane $pane) -> $status"
  printf '%s\n' "$full" | tail -n "$lines"
  echo
  return "$rc"
}
