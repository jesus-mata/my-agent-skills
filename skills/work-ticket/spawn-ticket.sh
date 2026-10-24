#!/usr/bin/env bash
# spawn-ticket.sh <id> [prompt] [cwd] [branch]
#
# Crea un git worktree nativo de herdr (workspace + tab + pane propios),
# arranca claude en yolo mode dentro de su pane raíz y le manda el prompt inicial.
# Para trabajar un ticket usa start-ticket.sh, que llama a éste ya preparado.
#
# El script antepone "ticket-": pásale sólo el id, o saldrá "ticket-ticket-42".
#
#   ./spawn-ticket.sh 42 "arregla el issue #42"     # workspace y rama ticket-42
#   ./spawn-ticket.sh 42                            # prompt por defecto: "hi"
#   ./spawn-ticket.sh 42 "..." ~/repo feat/issue-42
#
# Vuelve en cuanto confirma que el prompt entró (~7s); no espera al turno.
# Imprime el nombre del agente en stdout (las pistas van a stderr), así que se
# encadena con wait-agent.sh:  NAME=$(./spawn-ticket.sh 42 "...")
#
set -euo pipefail

TAB_LABEL="ticket-${1:?uso: spawn-ticket.sh <id> [prompt] [cwd] [branch]}"
PROMPT="${2:-hi}"
CWD="${3:-$PWD}"
BRANCH="${4:-$TAB_LABEL}"

jq_() { python3 -c "import sys,json;print(json.load(sys.stdin)$1)"; }

. "$(dirname "${BASH_SOURCE[0]}")/herdr-report.sh"

# --- 1. nombre de agente único (herdr falla con agent_name_taken) -----------
NAME="$TAB_LABEL"
i=2
while herdr agent get "$NAME" >/dev/null 2>&1; do
  NAME="${TAB_LABEL}-${i}"
  i=$((i + 1))
done

# --- 2. worktree nuevo, sin robarte el foco ---------------------------------
# `worktree create` abre un workspace propio con su tab y su pane raíz, y deja
# el checkout en ~/.herdr/worktrees/<repo>/<rama>.
# Ojo: --cwd y --workspace son mutuamente excluyentes; --cwd es quien resuelve
# el repo origen, así que sólo pasamos ése.
# Si la rama ya existe, create falla: reabrimos el worktree existente.
if ! OUT=$(herdr worktree create --cwd "$CWD" \
    --branch "$BRANCH" --label "$TAB_LABEL" --no-focus --json 2>&1); then
  CREATE_ERR="$OUT"
  if ! OUT=$(herdr worktree open --cwd "$CWD" \
      --branch "$BRANCH" --label "$TAB_LABEL" --no-focus --json 2>&1); then
    echo "no se pudo crear ni abrir el worktree de '$BRANCH' en $CWD" >&2
    echo "  create: $CREATE_ERR" >&2
    echo "  open:   $OUT" >&2
    exit 1
  fi
fi

PANE=$(printf '%s' "$OUT" | jq_ '["result"]["root_pane"]["pane_id"]')
WT_PATH=$(printf '%s' "$OUT" | jq_ '["result"]["worktree"]["path"]')
WT_WS=$(printf '%s' "$OUT" | jq_ '["result"]["workspace"]["workspace_id"]')

# --- 2b. etiqueta del pane --------------------------------------------------
# `--label` de worktree create nombra el workspace, no el pane: el pane raíz
# nace sin etiqueta. Usamos $NAME (no $TAB_LABEL) para que coincida con el
# nombre del agente cuando hubo colisión y hubo que sufijar.
# Es cosmético: si falla, no tiramos el spawn entero.
herdr pane rename "$PANE" "$NAME" >/dev/null 2>&1 \
  || echo "aviso: no se pudo etiquetar el pane $PANE" >&2

# --- 3. claude en yolo mode, esperando a que la TUI esté lista --------------
# El pane recién creado tarda un instante en llegar a su prompt de shell
# (agent_pane_busy si arrancas demasiado pronto), así que reintenta.
# El modelo va fijado: un ticket no debe correr con el que toque por defecto.
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if herdr agent start "$NAME" --kind claude --pane "$PANE" --timeout 60000 \
      -- --dangerously-skip-permissions --model opus >/dev/null 2>&1; then
    STARTED=1
    break
  fi
  sleep 1
done
[ "${STARTED:-}" = 1 ] || { echo "no se pudo arrancar claude en $PANE" >&2; exit 1; }

# La TUI de claude reporta "ready" un instante antes de aceptar Enter.
sleep 2

# --- 4. prompt inicial: sólo confirmamos que entró --------------------------
# Esperamos al primer cambio de estado, no a que acabe el turno. Así el Enter
# de rescate se dispara únicamente por un fallo de envío real (antes también
# saltaba por timeout, metiendo un Enter en un claude que estaba trabajando).
# Un "/cmd" largo llegaría como texto pegado y no como comando: ver slash_prompt_.
slash_prompt_ "$PROMPT"
if ! herdr agent prompt "$NAME" "$SLASH_PROMPT" \
    --wait --until working --until idle --until done --timeout 20000 >/dev/null 2>&1; then
  # agent_prompt_stalled: el texto quedó escrito pero el Enter no entró.
  herdr pane send-keys "$PANE" Enter >/dev/null 2>&1 || true
fi

echo "$NAME"
{
  echo "  workspace='$TAB_LABEL' agente='$NAME' pane=$PANE (etiquetado '$NAME')"
  echo "  worktree:    $WT_PATH (rama '$BRANCH', workspace $WT_WS)"
  echo "  esperar:     $HERDR_REPORT_DIR/wait-agent.sh $NAME    # en background"
  echo "  ver salida:  herdr pane read $PANE --source recent-unwrapped --lines 60"
  echo "  seguir:      herdr agent prompt $NAME 'siguiente instrucción'"
  echo "  ir al tab:   herdr agent focus $NAME"
  echo "  limpiar:     herdr worktree remove --workspace $WT_WS && git -C $CWD branch -d $BRANCH"
} >&2
