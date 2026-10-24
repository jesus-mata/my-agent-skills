#!/usr/bin/env bash
# split-pane.sh <pane_name> <right|down> [prompt] [pane-id]
#
# Divide un pane del workspace actual, le pone nombre al pane nuevo y arranca
# claude en yolo mode dentro. Si le pasas un prompt, se lo manda.
#
#   ./split-pane.sh review right                      # claude listo, sin prompt
#   ./split-pane.sh review right "revisa el diff"     # claude + prompt inicial
#   ./split-pane.sh tests down "corre los tests" w1:pE   # split de un pane concreto
#
# El pane nuevo no roba el foco. Imprime su pane_id en stdout (el resto va a
# stderr), así que se puede encadenar:  PANE=$(./split-pane.sh review right)
#
# No espera a que claude termine su turno: sólo confirma que el prompt entró.
# Para recoger el resultado, wait-agent.sh <pane_id> en background.
#
set -euo pipefail

usage() { echo "uso: split-pane.sh <pane_name> <right|down> [prompt] [pane-id]" >&2; exit 2; }

PANE_NAME="${1:-}"
DIRECTION="${2:-}"
PROMPT="${3:-}"
SRC_PANE="${4:-${HERDR_PANE_ID:-}}"

[ -n "$PANE_NAME" ] || usage
case "$DIRECTION" in
  right|down) ;;
  *) echo "dirección inválida: '${DIRECTION}' (usa 'right' o 'down')" >&2; usage ;;
esac

jq_() { python3 -c "import sys,json;print(json.load(sys.stdin)$1)"; }

. "$(dirname "${BASH_SOURCE[0]}")/herdr-report.sh"

# --- 1. pane de origen ------------------------------------------------------
# $HERDR_PANE_ID es el pane donde corre el script; `pane current` devuelve el
# pane con el foco, que no siempre es el mismo (p.ej. un agente en background).
[ -n "$SRC_PANE" ] || SRC_PANE=$(herdr pane current | jq_ '["result"]["pane"]["pane_id"]')

# --- 2. nombre de agente único (herdr falla con agent_name_taken) -----------
NAME="$PANE_NAME"
i=2
while herdr agent get "$NAME" >/dev/null 2>&1; do
  NAME="${PANE_NAME}-${i}"
  i=$((i + 1))
done

# --- 3. split + etiqueta ----------------------------------------------------
NEW_PANE=$(herdr pane split "$SRC_PANE" --direction "$DIRECTION" --no-focus \
  | jq_ '["result"]["pane"]["pane_id"]')

# El pane_id lo asigna herdr; lo que sí se puede fijar es la etiqueta.
herdr pane rename "$NEW_PANE" "$NAME" >/dev/null 2>&1 \
  || echo "aviso: no se pudo etiquetar el pane $NEW_PANE" >&2

# --- 4. claude en yolo mode, esperando a que la TUI esté lista --------------
# El pane recién creado tarda un instante en llegar a su prompt de shell
# (agent_pane_busy si arrancas demasiado pronto), así que reintenta.
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if herdr agent start "$NAME" --kind claude --pane "$NEW_PANE" --timeout 60000 \
      -- --dangerously-skip-permissions --model opus >/dev/null 2>&1; then
    STARTED=1
    break
  fi
  sleep 1
done
[ "${STARTED:-}" = 1 ] || { echo "no se pudo arrancar claude en $NEW_PANE" >&2; exit 1; }

# --- 5. prompt inicial (opcional) -------------------------------------------
if [ -n "$PROMPT" ]; then
  # La TUI de claude reporta "ready" un instante antes de aceptar Enter.
  sleep 2
  # Esperamos al primer cambio de estado, no a que acabe el turno: confirma que
  # el Enter entró sin bloquear el script durante toda la respuesta.
  # Un "/cmd" largo llegaría como texto pegado y no como comando: ver slash_prompt_.
  slash_prompt_ "$PROMPT"
  if ! herdr agent prompt "$NAME" "$SLASH_PROMPT" \
      --wait --until working --until idle --until done --timeout 20000 >/dev/null 2>&1; then
    # agent_prompt_stalled: el texto quedó escrito pero el Enter no entró.
    herdr pane send-keys "$NEW_PANE" Enter >/dev/null 2>&1 || true
  fi
fi

echo "$NEW_PANE"
{
  echo "  pane '$NAME' ($DIRECTION de $SRC_PANE), agente claude"
  [ -z "$PROMPT" ] || echo "  esperar:     $HERDR_REPORT_DIR/wait-agent.sh $NAME    # en background"
  echo "  ver salida:  herdr pane read $NEW_PANE --source recent-unwrapped --lines 60"
  echo "  seguir:      herdr agent prompt $NAME 'siguiente instrucción'"
  echo "  ir al pane:  herdr agent focus $NAME"
  echo "  cerrar:      herdr pane close $NEW_PANE"
} >&2
