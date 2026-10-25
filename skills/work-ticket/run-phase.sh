#!/usr/bin/env bash
# run-phase.sh <review|e2e> <ticket-id> <pr-num> [pane-id]
#
# Lanza una fase del ticket en un split, con su prompt y las TRIAGE RULES ya
# rellenados, y espera a que termine (wait-agent.sh). Lo usa el agente del
# ticket (ver IMPLEMENT_PROMPT.md), con el `run_in_background` del Bash tool:
# al salir, Claude Code le despierta y el reporte de la fase está en la salida.
#
#   PHASE_WATCH_MS   tope de la espera (review 1 h, e2e 2 h)
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
    BODY=$(render_prompt_ "$SKILL_DIR/REVIEW_PROMPT.md" TICKET_ID="$TICKET_ID" PR_NUM="$PR_NUM")
    # Empieza por el slash command para que cargue el skill (ver la fase e2e).
    PROMPT="/mattpocock-skills:code-review Perform an autonomous code review of PR #$PR_NUM. TICKET: #$TICKET_ID.

$BODY

$RULES"
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
exec "$SKILL_DIR/wait-agent.sh" "$PANE" --timeout-ms "$PHASE_WATCH_MS"
