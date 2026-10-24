#!/usr/bin/env bash
# herdr-report.sh — utilidades compartidas por spawn-ticket.sh y split-pane.sh.
# No se ejecuta directamente: se hace `source` desde ellos.
#
# Vive aparte porque el filtro de abajo costó tres correcciones (espacios duros,
# caja de entrada tecleada, recorte del banner) y tener dos copias garantiza que
# se separen.

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
    return s.startswith("Model:") or s.startswith("⏵⏵")

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
# Deja el resultado en variables y no en stdout: llamada con $(...) la ruta del
# fichero se quedaría en el subshell y el watcher no podría borrarlo.
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

# watch_and_report_ <agente> <pane> <pane-destino> <prompt> <watch-ms> <lineas> [nota] [reportar] [fichero-prompt] [fin-re]
#
# [fichero-prompt] es el que creó slash_prompt_: se borra al salir, acabe como
# acabe (turno terminado, bloqueado o timeout); el agente lo lee al empezar el
# turno. Va en un trap EXIT, así que la función tiene que correr en su propio
# subshell — que es como se lanza siempre.
#
# [fin-re] es una regex (ERE) que marca el final real del trabajo. Sin ella, el
# primer turno terminado es el resultado. Con ella, un turno que acaba sin esa
# línea no cuenta: el agente está esperando a otro (p.ej. el agente del ticket
# acaba su turno mientras corre su review), así que esperamos a que lo despierten
# y volvemos a mirar. Sin esto el padre recibía "terminó" con la fase 2 a medias.
#
# Bloquea hasta que el agente termina (o se bloquea, o se agota <watch-ms>) y
# avisa con una notificación. Si <reportar> es 1/true/yes/on, además le manda el
# resultado como prompt al pane destino — también al agotarse el tiempo, para
# que el destino no se quede esperando un reporte que nunca llega.
# Pensada para lanzarse en background:
#   ( watch_and_report_ ... ) >/dev/null 2>&1 & disown
watch_and_report_() {
  local name="$1" pane="$2" report_to="$3" prompt="$4"
  local watch_ms="$5" report_lines="$6" note="${7:-}" do_report="${8:-0}"
  local prompt_file="${9:-}" done_re="${10:-}"
  local wait_out status result full prompt_short deadline left

  # La ruta se expande ya: el trap salta con la función terminada, cuando el
  # `local` ya no existe y `set -u` lo daría por unbound.
  [ -z "$prompt_file" ] || trap "rm -f $(printf '%q' "$prompt_file")" EXIT

  # Nada de ${var,,}: macOS trae bash 3.2 y ahí es "bad substitution", que mata
  # el watcher en silencio (y `bash -n` no lo ve, porque es error de ejecución).
  case "$(printf '%s' "$do_report" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|on|si|sí) do_report=1 ;;
    *)                   do_report=0 ;;
  esac

  # El prompt puede ser un fichero entero — p.ej. spawn-ticket.sh X "$(cat plan.md)" —
  # y repetirlo completo inunda al agente que recibe el reporte. Lo recortamos:
  # el resumen sólo necesita recordar qué se pidió, no volver a pedirlo.
  prompt_short=$(printf '%s' "$prompt" | REPORT_PROMPT_CHARS="${REPORT_PROMPT_CHARS:-400}" python3 -c '
import os, sys
limit = int(os.environ["REPORT_PROMPT_CHARS"])
text = sys.stdin.read().strip()
if len(text) > limit:
    head = text[:limit].rsplit(" ", 1)[0]
    text = head + " […+%d caracteres]" % (len(text) - len(head))
# En una sola línea: un prompt multilínea rompía la lectura del resumen.
sys.stdout.write(" ".join(text.split()))
') || prompt_short="$prompt"   # si el recorte falla, mejor el prompt entero que nada

  # Primero esperamos a ver el turno arrancar. Sin esto el wait de abajo casa el
  # `idle` de ANTES del prompt y reporta con el agente aún pensando. Si el turno
  # fue instantáneo no llegaremos a verlo: seguimos igual.
  herdr agent wait "$name" --until working --timeout 30000 >/dev/null 2>&1 || true

  deadline=$(( $(date +%s) + watch_ms / 1000 ))
  status="timeout"
  while :; do
    left=$(( (deadline - $(date +%s)) * 1000 ))
    [ "$left" -gt 0 ] || break

    # Sin --until: el conjunto por defecto es idle|done|blocked. Importante no
    # estrecharlo — al terminar un turno claude aterriza en `done`, no en `idle`,
    # así que un `--until idle` deja el watcher colgado para siempre.
    wait_out=$(herdr agent wait "$name" --timeout "$left" 2>&1) || break

    # El estado cambia un instante antes de que la TUI pinte la respuesta.
    sleep 2
    status=$(printf '%s' "$wait_out" \
      | python3 -c 'import sys,json;print(json.load(sys.stdin)["result"]["agent"]["agent_status"])' \
      2>/dev/null) || status="?"

    # Leemos de sobra y recortamos al último turno: pedir justo $report_lines se
    # comía la respuesta cuando el banner de bienvenida ocupaba media foto.
    # `drop_prompt_echo_` quita el eco del prompt, que con un fichero como prompt
    # se comía el reporte entero; la cabecera ya lleva la versión recortada.
    full=$(herdr pane read "$pane" --source recent-unwrapped \
             --lines $((report_lines * 4)) 2>/dev/null \
           | clean_report_ | drop_prompt_echo_)

    # Sin marca de fin, o bloqueado esperando input: este turno es el resultado.
    [ -n "$done_re" ] && [ "$status" != blocked ] || break
    if printf '%s\n' "$full" | grep -Eq "$done_re"; then break; fi

    # Turno terminado sin la línea final: esperamos a que lo despierten.
    status="timeout"
    left=$(( (deadline - $(date +%s)) * 1000 ))
    [ "$left" -gt 0 ] || break
    herdr agent wait "$name" --until working --timeout "$left" >/dev/null 2>&1 || break
  done

  if [ "$status" = timeout ]; then
    # Al agotarse el tiempo puede que no hayamos leído nada todavía.
    full=$(herdr pane read "$pane" --source recent-unwrapped \
             --lines $((report_lines * 4)) 2>/dev/null \
           | clean_report_ | drop_prompt_echo_)
    # `agent wait` también falla si el agente desaparece (pane cerrado): no lo
    # llamemos timeout si el tope aún no se había agotado.
    if [ "$(date +%s)" -lt "$deadline" ]; then
      status="timeout: el wait falló antes del tope; ¿se cerró el pane o el agente?"
    else
      status="timeout: sin línea final tras $((watch_ms / 60000)) min"
    fi
  fi
  result=$(printf '%s\n' "$full" | tail -n "$report_lines")

  case "$status" in
    timeout*) herdr notification show "$name sin terminar" \
                --body "sigue sin acabar tras $((watch_ms / 60000)) min" --sound request ;;
    blocked) herdr notification show "$name bloqueado" \
               --body "espera input en $pane" --sound request ;;
    *)       if [ "$do_report" = 1 ]; then
               herdr notification show "$name terminó" \
                 --body "resultado enviado a $report_to" --sound done
             else
               herdr notification show "$name terminó" \
                 --body "$pane · turno completado" --sound done
             fi ;;
  esac

  # El reporte al pane padre va desactivado por defecto: despierta a ese agente y
  # le consume contexto, y muchas veces basta con la notificación.
  [ "$do_report" = 1 ] || return 0

  # Si el destino está a mitad de turno, `--wait` casaría ESE turno y daríamos el
  # envío por bueno sin haberlo mandado: el reporte se queda en la caja de
  # entrada y se pierde. Esperamos a que se libere antes de escribirle.
  herdr agent wait "$report_to" --timeout 300000 >/dev/null 2>&1 || true

  # Un reporte multilínea entra en la TUI como "[Pasted text #N]" y el Enter no
  # siempre pasa, así que confirmamos el envío y rescatamos con un Enter suelto.
  if ! herdr agent prompt "$report_to" \
"[herdr] el agente '$name' (pane $pane) terminó en estado '$status'.${note:+
$note}
Prompt que se le dio: $prompt_short

Últimas $report_lines líneas de su pane:
$result

Para leer más: herdr pane read $pane --source recent-unwrapped --lines 200" \
      --wait --until working --until idle --until done --timeout 20000 \
      >/dev/null 2>&1; then
    herdr pane send-keys "$report_to" Enter >/dev/null 2>&1 \
      || herdr notification show "$name: no pude avisar a $report_to" \
           --body "¿ese pane tiene un agente?" --sound request
  fi
}
