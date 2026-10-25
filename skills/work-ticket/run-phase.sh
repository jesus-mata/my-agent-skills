#!/usr/bin/env bash
# run-phase.sh <review|e2e> <ticket-id> <pr-num> [pane-id]
#
# Lanza una fase del ticket en un split, con su prompt y las TRIAGE RULES ya
# rellenados, y espera a que termine (wait-agent.sh). Lo usa el agente del
# ticket (ver IMPLEMENT_PROMPT.md), con el `run_in_background` del Bash tool:
# al salir, Claude Code le despierta y el reporte de la fase está en la salida.
#
#   PHASE_WATCH_MS   tope de la espera (review 1 h, e2e 2 h)
#   REVIEW_LEVEL     nivel de esfuerzo de /code-review (high por defecto)
#
#   ./run-phase.sh review 42 117
#   ./run-phase.sh e2e 42 117 w3:p2      # split del pane de la review
#
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
usage() { echo "uso: run-phase.sh <review|e2e> <ticket-id> <pr-num> [pane-id]" >&2; exit 2; }

PHASE="${1:-}"
TICKET_ID="${2:-}"
PR_NUM="${3:-}"
SRC_PANE="${4:-}"

case "$TICKET_ID" in ''|*[!0-9]*) echo "ticket-id inválido: '$TICKET_ID'" >&2; usage ;; esac
case "$PR_NUM"    in ''|*[!0-9]*) echo "pr-num inválido: '$PR_NUM'" >&2; usage ;; esac

. "$SKILL_DIR/herdr-report.sh"

RULES=$(render_prompt_ "$SKILL_DIR/TRIAGE_RULES.md" TICKET_ID="$TICKET_ID" PR_NUM="$PR_NUM")

case "$PHASE" in
  review)
    REVIEW_LEVEL=$(review_level_ "${REVIEW_LEVEL:-}") || exit 2
    BODY=$(render_prompt_ "$SKILL_DIR/REVIEW_PROMPT.md" TICKET_ID="$TICKET_ID" PR_NUM="$PR_NUM" \
      REVIEW_LEVEL="$REVIEW_LEVEL")
    PROMPT="Instructions for an autonomous code review of PR #$PR_NUM. TICKET: #$TICKET_ID.

$BODY

$RULES"
    # /code-review va en un segundo prompt, solo y en una línea: así se ejecuta
    # como slash command con sus argumentos (slash_prompt_ los mandaría al
    # fichero). Corre como fork en background, así que las instrucciones tienen
    # que llegar antes, al agente de la review y no al fork, y su primer turno
    # acaba sin veredicto: esperamos a la línea REVIEW, no al fin de turno.
    FOLLOWUP="/code-review $REVIEW_LEVEL $PR_NUM"
    DONE_RE='REVIEW (PASS|FAIL|BLOCKED) '
    DIRECTION=right
    # Review + fixes + build + tests completos caben en 1 h.
    : "${PHASE_WATCH_MS:=3600000}"
    ;;
  e2e)
    BODY=$(render_prompt_ "$SKILL_DIR/E2E_PROMPT.md" TICKET_ID="$TICKET_ID" PR_NUM="$PR_NUM")
    # Empieza por /e2e para que cargue el skill: slash_prompt_ parte el resto a
    # un fichero, porque un texto pegado nunca se ejecuta como slash command.
    PROMPT="/e2e Perform an autonomous E2E test of PR #$PR_NUM for TICKET: #$TICKET_ID.

$BODY

$RULES"
    DIRECTION=down
    # El stack se levanta en frío al menos dos veces (inicio y pasada final).
    : "${PHASE_WATCH_MS:=7200000}"
    ;;
  *) echo "fase inválida: '$PHASE'" >&2; usage ;;
esac

PANE=$("$SKILL_DIR/split-pane.sh" "$PHASE" "$DIRECTION" "$PROMPT" ${SRC_PANE:+"$SRC_PANE"})

if [ -n "${FOLLOWUP:-}" ]; then
  # El primer turno sólo acusa las instrucciones ("READY"); esperamos a que
  # acabe para que el comando no entre en mitad de él.
  ACK=$(herdr agent wait "$PANE" --timeout 300000 2>&1) \
    || { echo "run-phase: el agente de $PHASE no acusó sus instrucciones (pane $PANE)" >&2; exit 1; }
  case "$ACK" in
    *'"blocked"'*) echo "run-phase: el agente de $PHASE se bloqueó antes de $FOLLOWUP (pane $PANE)" >&2; exit 1 ;;
  esac
  if ! herdr agent prompt "$PANE" "$FOLLOWUP" \
      --wait --until working --until idle --until done --timeout 20000 >/dev/null 2>&1; then
    # agent_prompt_stalled: el texto quedó escrito pero el Enter no entró.
    herdr pane send-keys "$PANE" Enter >/dev/null 2>&1 || true
  fi
fi

exec "$SKILL_DIR/wait-agent.sh" "$PANE" --timeout-ms "$PHASE_WATCH_MS" \
  ${DONE_RE:+--until-line "$DONE_RE"}
