#!/usr/bin/env bash
# herdr-report.sh — utilidades compartidas por los scripts de la skill.
# No se ejecuta directamente: se hace `source` desde ellos.
#
# Vive aparte porque el filtro de abajo costó tres correcciones (espacios duros,
# caja de entrada tecleada, recorte del banner) y tener dos copias garantiza que
# se separen.

HERDR_REPORT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# clean_report_  (stdin -> stdout)
# Deja sólo el último turno del agente: desde el prompt realmente enviado hasta
# el final, sin banner de bienvenida, marco de la TUI, caja de entrada ni barra
# de estado. Nunca falla: si no reconoce nada devuelve lo que haya (con `grep`
# esto rompía el pipefail cuando no casaba nada).
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

# La TUI separa con espacios duros (U+00A0), así que "❯ texto" no casa con un
# espacio normal. Normalizamos antes de mirar nada.
lines = [l.replace("\xa0", " ") for l in sys.stdin.read().splitlines()]
while lines and chrome(lines[-1]):
    lines.pop()
# Un "❯ texto" al final es la caja de entrada con algo tecleado sin enviar, no
# un prompt enviado: si lo tomáramos como inicio del turno nos comeríamos la
# respuesta entera.
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
# Quita el eco del prompt que la TUI pinta al principio del turno. Con un prompt
# largo (p.ej. "$(cat plan.md)") ese eco se comía todo el reporte. Si no
# encuentra dónde empieza la respuesta devuelve la entrada tal cual.
drop_prompt_echo_() {
  python3 -c '
import sys

MARKS = ("⏺", "✻", "✽", "⎿", "✢")   # inicio de la respuesta del agente
lines = sys.stdin.read().splitlines()
# No exigimos ver el "❯": con un prompt de fichero el eco es tan largo que ni
# entra en la ventana de lectura. Cortamos desde la primera marca de respuesta.
for i, l in enumerate(lines):
    if l.strip().startswith(MARKS):
        lines = lines[i:]
        break
sys.stdout.write("\n".join(lines))
'
}

# slash_prompt_ <prompt>  (-> $SLASH_PROMPT, $SLASH_PROMPT_FILE)
# Un prompt que empieza por "/cmd" pero es multilínea o largo entra en la TUI
# como "[Pasted text #N]", y un texto pegado nunca se interpreta como slash
# command: el /e2e no se cargaba. Lo partimos: el comando va solo, en una línea
# corta que la TUI sí reconoce, y el resto del prompt a un fichero que el agente
# lee. Cualquier otro prompt se devuelve tal cual.
# Deja el resultado en variables y no en stdout, para que quien lo llama tenga
# la ruta sin perderla en el subshell de un $(...).
#   SLASH_PROMPT       prompt a mandar
#   SLASH_PROMPT_FILE  fichero creado, o vacío si no hizo falta partir
#   SLASH_PROMPT_MAX   longitud máxima de una línea sin partir (300)
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
  # Primera palabra = comando; todo lo demás (incluido el resto de la primera
  # línea) es el cuerpo.
  cmd="${prompt%%[[:space:]]*}"
  body="${prompt#"$cmd"}"
  dir="${TMPDIR:-/tmp}"; dir="${dir%/}/herdr-prompts"
  mkdir -p "$dir"
  # Nadie borra estos ficheros al acabar (el lanzador vuelve antes de que el
  # agente los lea), así que se purgan aquí los de más de un día.
  find "$dir" -type f -mmin +1440 -delete 2>/dev/null || true
  SLASH_PROMPT_FILE=$(mktemp "${dir}/${cmd#/}.XXXXXX")
  printf '%s\n' "$body" > "$SLASH_PROMPT_FILE"
  SLASH_PROMPT="$cmd Your full instructions for this command are in $SLASH_PROMPT_FILE — read that whole file first and follow it."
}

# render_prompt_ <fichero> [CLAVE=valor ...]  (-> stdout)
# Sustituye cada {{CLAVE}} del fichero por su valor. Los prompts viajan a otro
# agente como texto: un "$TICKET_ID" dentro de un `$(cat prompt.md)` llegaba
# literal, sin expandir, y el shell de ese agente no tiene la variable, así que
# la review recibía "TICKET: " vacío. Falla si queda algún {{CLAVE}} sin valor.
render_prompt_() {
  local file="$1"
  shift
  python3 - "$file" "$@" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
for kv in sys.argv[2:]:
    key, value = kv.split("=", 1)
    text = text.replace("{{%s}}" % key, value)
left = sorted(set(re.findall(r"\{\{[A-Z_]+\}\}", text)))
if left:
    sys.exit("render_prompt_: %s tiene placeholders sin valor: %s" % (sys.argv[1], ", ".join(left)))
sys.stdout.write(text)
PY
}

# read_turn_ <pane> <lineas>  (-> stdout)
# Último turno del agente, limpio. Leemos de sobra y recortamos: pedir justo
# <lineas> se comía la respuesta cuando el banner de bienvenida ocupaba media
# foto, y `drop_prompt_echo_` quita el eco de un prompt largo.
read_turn_() {
  herdr pane read "$1" --source recent-unwrapped --lines $(($2 * 4)) 2>/dev/null \
    | clean_report_ | drop_prompt_echo_
}

# wait_agent_ <agente|pane> <watch-ms> <lineas> [fin-re]  (-> stdout, código)
#
# Espera en primer plano a que el agente termine (o se bloquee, o se agote
# <watch-ms>), avisa con una notificación e imprime su último turno. Quien lo
# llama lo lanza en background (Bash `run_in_background`) y Claude Code le
# despierta al salir: el resultado se recoge, no se le teclea a nadie. Antes un
# watcher le escribía el reporte en la caja de entrada al pane padre, y eso
# fallaba de mil maneras (padre a mitad de turno, Enter que no entraba, reporte
# al pane equivocado).
#
# [fin-re] es una regex (ERE) que marca el final real del trabajo. Sin ella, el
# primer turno terminado es el resultado. Con ella, un turno que acaba sin esa
# línea no cuenta: el agente está esperando a otro (p.ej. el agente del ticket
# acaba su turno mientras corre su review), así que esperamos a que lo despierten
# y volvemos a mirar.
#
# Códigos: 0 terminó · 3 bloqueado esperando input · 1 timeout o agente perdido.
wait_agent_() {
  local target="$1" watch_ms="$2" report_lines="$3" done_re="${4:-}"
  local info name pane wait_out status full deadline left rc

  info=$(herdr agent get "$target" 2>/dev/null | python3 -c '
import sys, json
a = json.load(sys.stdin)["result"]["agent"]
print(a.get("name") or "", a["pane_id"])' 2>/dev/null) || {
    echo "herdr: no encuentro el agente '$target'"
    return 1
  }
  name="${info% *}"; pane="${info##* }"
  [ -n "$name" ] || name="$target"

  # Primero esperamos a ver el turno arrancar. Sin esto el wait de abajo casa el
  # `idle` de ANTES del prompt y devuelve con el agente aún pensando. Si el turno
  # fue instantáneo no llegaremos a verlo: seguimos igual.
  herdr agent wait "$target" --until working --timeout 30000 >/dev/null 2>&1 || true

  deadline=$(( $(date +%s) + watch_ms / 1000 ))
  status="timeout"
  while :; do
    left=$(( (deadline - $(date +%s)) * 1000 ))
    [ "$left" -gt 0 ] || break

    # Sin --until: el conjunto por defecto es idle|done|blocked. Importante no
    # estrecharlo — al terminar un turno claude aterriza en `done`, no en `idle`,
    # así que un `--until idle` se queda colgado para siempre.
    wait_out=$(herdr agent wait "$target" --timeout "$left" 2>&1) || break

    # El estado cambia un instante antes de que la TUI pinte la respuesta.
    sleep 2
    status=$(printf '%s' "$wait_out" \
      | python3 -c 'import sys,json;print(json.load(sys.stdin)["result"]["agent"]["agent_status"])' \
      2>/dev/null) || status="?"
    full=$(read_turn_ "$pane" "$report_lines")

    # Sin marca de fin, o bloqueado esperando input: este turno es el resultado.
    [ -n "$done_re" ] && [ "$status" != blocked ] || break
    if printf '%s\n' "$full" | grep -Eq "$done_re"; then break; fi

    # Turno terminado sin la línea final: esperamos a que lo despierten.
    status="timeout"
    left=$(( (deadline - $(date +%s)) * 1000 ))
    [ "$left" -gt 0 ] || break
    herdr agent wait "$target" --until working --timeout "$left" >/dev/null 2>&1 || break
  done

  if [ "$status" = timeout ]; then
    full=$(read_turn_ "$pane" "$report_lines")
    # `agent wait` también falla si el agente desaparece (pane cerrado): no lo
    # llamemos timeout si el tope aún no se había agotado.
    if [ "$(date +%s)" -lt "$deadline" ]; then
      status="timeout: el wait falló antes del tope; ¿se cerró el pane o el agente?"
    else
      status="timeout: sin terminar tras $((watch_ms / 60000)) min"
    fi
  fi

  case "$status" in
    timeout*) rc=1
              herdr notification show "$name sin terminar" --body "$status" --sound request ;;
    blocked)  rc=3
              herdr notification show "$name bloqueado" --body "espera input en $pane" --sound request ;;
    *)        rc=0
              herdr notification show "$name terminó" --body "$pane · turno completado" --sound done ;;
  esac >/dev/null 2>&1

  # La primera línea es fija para que quien lo lee sepa qué pasó sin adivinar.
  echo "herdr: agent '$name' (pane $pane) -> $status"
  echo
  printf '%s\n' "$full" | tail -n "$report_lines"
  echo
  echo "Leer más:        herdr pane read $pane --source recent-unwrapped --lines 200"
  echo "Responderle:     herdr agent prompt $name '<texto>'"
  printf 'Seguir esperando: %s/wait-agent.sh %s --timeout-ms %s' \
    "$HERDR_REPORT_DIR" "$name" "$watch_ms"
  [ -z "$done_re" ] || printf ' --until-line %q' "$done_re"
  echo "   # en background"
  return "$rc"
}
