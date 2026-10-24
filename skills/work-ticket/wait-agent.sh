#!/usr/bin/env bash
# wait-agent.sh <agente|pane> [--timeout-ms MS] [--until-line RE] [--lines N]
#
# Espera a que un agente de herdr termine su turno e imprime su resultado. Se
# lanza con el `run_in_background` del Bash tool: Claude Code despierta a quien
# lo lanzó cuando sale, y el reporte está en su salida. Nada de sondear.
#
#   ./wait-agent.sh review                                  # 1 h, primer turno
#   ./wait-agent.sh ticket-42 --until-line 'TICKET (DONE|FAIL|PARTIAL|BLOCKED) '
#
# Úsalo tras responder a un agente bloqueado o pedirle algo de nuevo; los
# lanzadores (start-ticket.sh, run-phase.sh) ya lo llaman ellos mismos.
#
#   --timeout-ms   tope de la espera (3600000 = 1 h)
#   --until-line   regex (ERE): un turno terminado sin esa línea no cuenta
#   --lines        líneas del turno a imprimir (40)
#
# Salida: 0 terminó · 3 bloqueado esperando input · 1 timeout o agente perdido.
set -euo pipefail

usage() { echo "uso: wait-agent.sh <agente|pane> [--timeout-ms MS] [--until-line RE] [--lines N]" >&2; exit 2; }

TARGET="${1:-}"
[ -n "$TARGET" ] || usage
shift
WATCH_MS=3600000
DONE_RE=""
LINES=40
while [ $# -gt 0 ]; do
  case "$1" in
    --timeout-ms) WATCH_MS="${2:?}"; shift 2 ;;
    --until-line) DONE_RE="${2:?}"; shift 2 ;;
    --lines)      LINES="${2:?}"; shift 2 ;;
    *) usage ;;
  esac
done
case "$WATCH_MS$LINES" in *[!0-9]*) usage ;; esac

. "$(dirname "${BASH_SOURCE[0]}")/herdr-report.sh"

rc=0
wait_agent_ "$TARGET" "$WATCH_MS" "$LINES" "$DONE_RE" || rc=$?
exit "$rc"
