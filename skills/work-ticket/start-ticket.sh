#!/usr/bin/env bash
# start-ticket.sh <ticket> [cwd]
#
# Punto de entrada de la skill. Comprueba el entorno, pone la rama por defecto
# al día, verifica que el ticket existe y lanza el agente del ticket en su
# worktree (rama ticket-<id>) con IMPLEMENT_PROMPT.md ya rellenado.
#
#   ./start-ticket.sh 42
#   ./start-ticket.sh '#42'
#   ./start-ticket.sh https://github.com/org/repo/issues/42 ~/repo
#
# Vuelve en ~10 s. El resultado llega como prompt al pane que lo lanzó cuando el
# agente del ticket imprime su línea `TICKET <veredicto>` — no antes: ese agente
# termina turnos intermedios mientras esperan su review y su E2E.
#
#   TICKET_WATCH_MS   tope de la vigilancia en ms (18000000 = 5 h, ver abajo)
#
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
die() { echo "start-ticket: $*" >&2; exit 1; }

# --- 0. argumentos ----------------------------------------------------------
TICKET_ID="${1:?uso: start-ticket.sh <ticket> [cwd]}"
TICKET_ID="${TICKET_ID##*/}"   # URL del issue -> número
TICKET_ID="${TICKET_ID#\#}"    # "#42" -> "42"
case "$TICKET_ID" in
  ''|*[!0-9]*) die "'$1' no es un número de ticket ni la URL de un issue" ;;
esac
CWD="${2:-$PWD}"

. "$SKILL_DIR/herdr-report.sh"

# --- 1. entorno -------------------------------------------------------------
[ "${HERDR_ENV:-}" = 1 ] || die "no estás dentro de herdr (HERDR_ENV != 1)"
for bin in herdr git python3; do
  command -v "$bin" >/dev/null 2>&1 || die "falta '$bin' en el PATH"
done
TOP=$(git -C "$CWD" rev-parse --show-toplevel 2>/dev/null) \
  || die "$CWD no está dentro de un repo git"
CWD="$TOP"

ORIGIN=$(git -C "$CWD" remote get-url origin 2>/dev/null) \
  || die "el repo no tiene remote 'origin'"
case "$ORIGIN" in
  *github*) FORGE=gh ;;
  *gitlab*) FORGE=glab ;;
  *)        die "origin ($ORIGIN) no es GitHub ni GitLab" ;;
esac
command -v "$FORGE" >/dev/null 2>&1 || die "falta '$FORGE' en el PATH"

# --- 2. rama por defecto al día ---------------------------------------------
# El worktree sale del HEAD de este checkout, así que tiene que estar en la rama
# por defecto y al día. Sólo miramos ficheros trackeados: los untracked no
# viajan al worktree ni estorban al cambiar de rama.
[ -z "$(git -C "$CWD" status --porcelain --untracked-files=no)" ] \
  || die "hay cambios sin commitear en $CWD; guárdalos antes (git stash)"

git -C "$CWD" fetch --quiet origin || die "git fetch origin falló"
DEFAULT=$(git -C "$CWD" symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null) \
  || DEFAULT=$(git -C "$CWD" remote show origin | sed -n 's/.*HEAD branch: //p')
DEFAULT="${DEFAULT#origin/}"
[ -n "$DEFAULT" ] || die "no pude averiguar la rama por defecto de origin"

git -C "$CWD" switch --quiet "$DEFAULT" || die "no pude cambiar a '$DEFAULT'"
git -C "$CWD" pull --quiet --ff-only || die "git pull --ff-only en '$DEFAULT' falló"

# --- 3. el ticket existe ----------------------------------------------------
# Fallar aquí cuesta segundos; fallar dentro del agente cuesta minutos.
if [ "$FORGE" = gh ]; then
  TITLE=$(cd "$CWD" && gh issue view "$TICKET_ID" --json title -q .title 2>&1) \
    || die "gh no encuentra el issue #$TICKET_ID: $TITLE"
else
  TITLE=$(cd "$CWD" && glab issue view "$TICKET_ID" 2>&1 | sed -n 's/^title:[[:space:]]*//p') \
    || die "glab no encuentra el issue #$TICKET_ID"
  [ -n "$TITLE" ] || die "glab no encuentra el issue #$TICKET_ID"
fi
echo "ticket #$TICKET_ID: $TITLE" >&2

# --- 4. lanzar el agente del ticket -----------------------------------------
PROMPT=$(render_prompt_ "$SKILL_DIR/IMPLEMENT_PROMPT.md" \
  TICKET_ID="$TICKET_ID" SKILL_DIR="$SKILL_DIR")

# 5 h = implementar (~1 h) + review (tope 1 h) + E2E (tope 2 h) + margen. Es sólo
# un tope: el reporte llega en cuanto aparece la línea TICKET.
export TICKET_WATCH_MS="${TICKET_WATCH_MS:-18000000}"
export TICKET_REPORT=1
# Debe casar con la primera línea de FINAL OUTPUT en IMPLEMENT_PROMPT.md.
export TICKET_DONE_RE='TICKET (DONE|FAIL|PARTIAL|BLOCKED) '
exec "$SKILL_DIR/spawn-ticket.sh" "$TICKET_ID" "$PROMPT" "$CWD"
