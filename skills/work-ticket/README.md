# work-ticket — scripts

Contenido: [Ficheros](#ficheros) · [start-ticket.sh](#start-ticketsh) ·
[run-phase.sh](#run-phasesh) · [spawn-ticket.sh](#spawn-ticketsh) ·
[split-pane.sh](#split-panesh) · [herdr-report.sh](#herdr-reportsh) ·
[Cosas que costaron sangre](#cosas-que-costaron-sangre)

Scripts para lanzar agentes claude en herdr y recibir sus resultados de
vuelta. Sólo funcionan **dentro de herdr** (`HERDR_ENV=1`).

## Ficheros

| Fichero | Qué hace |
|---|---|
| `start-ticket.sh` | Punto de entrada de la skill: valida, actualiza y lanza el agente del ticket |
| `run-phase.sh` | Lo usa el agente del ticket para lanzar la review o la E2E |
| `spawn-ticket.sh` | Crea un git worktree, arranca claude dentro y le manda un prompt |
| `split-pane.sh` | Divide un pane, arranca claude dentro y le manda un prompt |
| `herdr-report.sh` | Librería compartida: plantillas, filtro del turno y watcher. No se ejecuta sola |
| `*_PROMPT.md`, `TRIAGE_RULES.md` | Prompts de cada fase, con placeholders `{{CLAVE}}` |
| `evals/evals.json` | Escenarios con los que probar la skill de punta a punta |

Flujo: `start-ticket.sh` → agente del ticket (`IMPLEMENT_PROMPT.md`) →
`run-phase.sh review` → `run-phase.sh e2e` → reporte al pane de origen.

`spawn-ticket.sh` y `split-pane.sh` **vuelven enseguida** (~7 s) en cuanto confirman que el prompt
entró: no esperan a que el agente termine. La vigilancia queda en background y,
cuando el agente acaba, herdr lanza una notificación.

Opcionalmente pueden además **mandarle el resultado como prompt al pane desde el
que se lanzó el script**, para que ese agente lo vea sin sondear nada. Va
**desactivado por defecto** — despierta a ese agente y le consume contexto — y se
activa con `TICKET_REPORT=1` / `SPLIT_REPORT=1`. Valen `1`, `true`, `yes`, `on` o
`si`, en cualquier combinación de mayúsculas.

---

## start-ticket.sh

```
start-ticket.sh <ticket> [cwd]
```

`<ticket>` vale `42`, `#42` o la URL del issue. En orden, y se para con un
mensaje en el primer fallo:

1. Comprueba `HERDR_ENV=1`, `herdr`, `git`, `python3` y `gh`/`glab` según el
   remote `origin`.
2. Exige que no haya cambios sin commitear en ficheros trackeados, cambia a la
   rama por defecto de `origin` y hace `pull --ff-only`.
3. Comprueba que el ticket existe.
4. Rellena `IMPLEMENT_PROMPT.md` y llama a `spawn-ticket.sh` con
   `TICKET_REPORT=1`, `TICKET_DONE_RE` y `TICKET_WATCH_MS` (5 h por defecto).

El reporte llega cuando el agente imprime su línea `TICKET <veredicto>`, no en
el primer turno que termina (ver `watch_and_report_`).

## run-phase.sh

```
run-phase.sh <review|e2e> <ticket-id> <pr-num> [pane-id]
```

Rellena `REVIEW_PROMPT.md` o `E2E_PROMPT.md` más `TRIAGE_RULES.md` con el
ticket y el PR, y llama a `split-pane.sh` con `SPLIT_REPORT=1`. El reporte va
siempre a `$HERDR_PANE_ID` (quien lanza la fase), aunque el split salga de otro
pane: `[pane-id]` sólo elige de dónde sale el split. La review se
abre a la derecha (tope 1 h) y la E2E debajo (tope 2 h). Imprime el pane_id.

## spawn-ticket.sh

```
spawn-ticket.sh <id> [prompt] [cwd] [branch]
```

Crea un worktree nativo de herdr (workspace + tab + pane propios) y arranca
claude en modo yolo en su pane raíz. El script **antepone `ticket-`** al id:
pásale `42`, no `ticket-42`, o saldrá `ticket-ticket-42`.

```bash
cd ~/repo
./spawn-ticket.sh 42 "usa /tdd para implementar el issue #42"
./spawn-ticket.sh 42                              # prompt por defecto: "hi"
./spawn-ticket.sh 42 "..." ~/otro-repo feat/issue-42
```

- `cwd` **debe estar dentro del repo** del que sale la rama (por defecto `$PWD`).
- `branch` por defecto es `ticket-<id>`. Si la rama ya existe, reabre su worktree.
- El checkout va a `~/.herdr/worktrees/<repo>/<rama>` (configurable en
  `~/.config/herdr/config.toml`, sección `[worktrees]`).

| Variable | Por defecto | Para qué |
|---|---|---|
| `TICKET_REPORT` | `0` (off) | Activa el reporte al pane que lanzó el script |
| `TICKET_REPORT_TO` | `$HERDR_PANE_ID` | Pane/agente al que mandar el resultado |
| `TICKET_REPORT_LINES` | `40` | Líneas del pane que se incluyen en el reporte |
| `TICKET_WATCH_MS` | `3600000` | Tope de la vigilancia (1 h; `start-ticket.sh` pone 5 h) |
| `TICKET_DONE_RE` | vacío | Regex de la línea de fin real; hasta verla, un turno terminado no cuenta |

Limpieza — **`herdr worktree remove` no borra la rama**, hacen falta los dos pasos:

```bash
herdr worktree remove --workspace <ws>        # sólo si el workspace sigue abierto
git -C <repo> worktree remove <path>          # si ya se cerró
git -C <repo> branch -d <rama>
```

## split-pane.sh

```
split-pane.sh <nombre> <right|down> [prompt] [pane-id]
```

Divide un pane, etiqueta el nuevo y arranca claude dentro. Sin prompt, deja el
agente listo y no vigila nada.

```bash
./split-pane.sh review right                        # claude listo, sin prompt
./split-pane.sh review right "revisa el diff"       # claude + prompt, sólo notifica
SPLIT_REPORT=1 ./split-pane.sh review right "revisa el diff"   # además reporta al padre
./split-pane.sh tests down "corre los tests" w1:pE  # split de un pane concreto
```

- `pane-id` por defecto es `$HERDR_PANE_ID`, el pane donde corre el script.
- Imprime el `pane_id` nuevo en **stdout** y las pistas en stderr, así que se
  encadena: `PANE=$(./split-pane.sh review right)`.

| Variable | Por defecto | Para qué |
|---|---|---|
| `SPLIT_REPORT` | `0` (off) | Activa el reporte al pane que lanzó el script |
| `SPLIT_REPORT_TO` | pane de origen | Pane/agente al que mandar el resultado |
| `SPLIT_REPORT_LINES` | `40` | Líneas del pane que se incluyen en el reporte |
| `SPLIT_WATCH_MS` | `3600000` | Tope de la vigilancia (1 h) |

## herdr-report.sh

Se hace `source`, no se ejecuta. Expone:

- **`render_prompt_ <fichero> [CLAVE=valor ...]`** (→ stdout): sustituye cada
  `{{CLAVE}}` y falla si queda alguno sin valor.
- **`clean_report_`** (stdin → stdout): deja sólo el último turno del agente,
  sin banner, marco de la TUI, caja de entrada ni barra de estado.
- **`drop_prompt_echo_`** (stdin → stdout): quita el eco del prompt que la TUI
  pinta al principio del turno, cortando desde la primera marca de respuesta
  (`⏺ ✻ ✽ ⎿ ✢`). Si no hay ninguna, devuelve la entrada tal cual.
- **`slash_prompt_ <prompt>`**: si el prompt es un `/cmd` largo o multilínea,
  escribe el cuerpo en un fichero y deja en `$SLASH_PROMPT` la línea corta a
  mandar y en `$SLASH_PROMPT_FILE` la ruta (vacía si no hizo falta). Usa
  variables y no stdout para que la ruta no se pierda en un `$(...)`.
- **`watch_and_report_ <agente> <pane> <destino> <prompt> <watch-ms> <líneas> [nota] [reportar] [fichero-prompt] [fin-re]`**:
  espera a que el agente termine y notifica; si `<reportar>` es truthy, además
  manda el resultado al destino, también si se agota el tiempo. Con `[fin-re]`
  sólo da por terminado el turno que contiene una línea que casa con esa regex.
  Borra `[fichero-prompt]` al salir (trap EXIT).
  Pensada para background: `( watch_and_report_ ... ) >/dev/null 2>&1 & disown`.

| Variable | Por defecto | Para qué |
|---|---|---|
| `REPORT_PROMPT_CHARS` | `400` | Caracteres del prompt que sobreviven en la cabecera del reporte |
| `SLASH_PROMPT_MAX` | `300` | Longitud a partir de la cual un `/cmd` de una línea se parte a fichero |

Vive aparte a propósito: tener dos copias de esta lógica garantizaba que se
separasen.

### Pasar un fichero como prompt

Funciona sin más, con sustitución de comandos — `text` no tiene límite en el API
y `ARG_MAX` es ~1 MB:

```bash
TICKET_REPORT=1 ./spawn-ticket.sh 42 "$(cat plan.md)"
```

`$(cat ...)` no expande variables: un `$TICKET_ID` dentro del fichero llega
literal. Para ficheros con valores usa `{{CLAVE}}` y `render_prompt_`.

Si activas el reporte, **no** repite el fichero: la cabecera lleva el prompt
recortado a `REPORT_PROMPT_CHARS` y `drop_prompt_echo_` quita el eco del pane.
De ~45 líneas de relleno a las dos de la respuesta.

Dos avisos:

- Si el prompt **empieza por `/cmd`** y es multilínea o pasa de
  `SLASH_PROMPT_MAX` (300) caracteres, `slash_prompt_` lo parte: manda sólo
  `/cmd <instrucción de leer el fichero>` y el resto lo escribe en
  `$TMPDIR/herdr-prompts/`. Así `"/e2e ... $(cat E2E_PROMPT.md)"` carga el skill.
  El watcher borra ese fichero al salir, termine como termine.
  Si **no** quieres que se lea como comando, antepón una línea:
  `"Implementa este plan:\n\n$(cat plan.md)"`.
- Pasar la **ruta** en vez del contenido (`"lee ~/repo/plan.md e impleméntalo"`)
  sólo vale si el fichero está commiteado: el worktree únicamente tiene ficheros
  trackeados, y el agente no vive en tu checkout.

---

## Cosas que costaron sangre

Detalles poco obvios de herdr y de la TUI de claude. Están comentados en el
código; se resumen aquí para no volver a tropezar.

- **Un agente que espera a otro termina su turno.** El agente del ticket lanza
  la review y acaba su turno hasta que le llega el reporte, así que pasa a
  `done` con el trabajo a medias. Por eso su watcher espera a la línea
  `TICKET <veredicto>` (`TICKET_DONE_RE`) y no al primer `done`.
- **El pane del que sale un split no es a quien hay que reportar.** La E2E se
  abre desde el pane de la review, y `split-pane.sh` le mandaba su reporte a la
  review en vez de al agente del ticket. `run-phase.sh` fija `SPLIT_REPORT_TO`.
- **`$(cat prompt.md)` no expande variables, y el shell del agente no las
  tiene.** La review recibía `TICKET: ` vacío. Los prompts llevan `{{CLAVE}}` y
  se rellenan con `render_prompt_` antes de enviarlos.
- **Al terminar un turno claude aterriza en `done`, no en `idle`.** Un
  `herdr agent wait --until idle` se queda colgado para siempre. Hay que dejar el
  conjunto por defecto (`idle|done|blocked`) y no pasar `--until`.
- **`--cwd` y `--workspace` son mutuamente excluyentes** en `herdr worktree
  create|open`, al contrario que en `herdr tab create`. `--cwd` es quien resuelve
  el repo origen.
- **`--label` de `worktree create` nombra el workspace**, no el pane ni el tab.
  El pane raíz nace sin etiqueta; hay que ponerla con `herdr pane rename`.
- **Un prompt multilínea entra en la TUI como `[Pasted text #N]` y el Enter no
  siempre pasa.** Hay que confirmar el envío y rescatar con `pane send-keys Enter`.
- **Un texto pegado nunca se ejecuta como slash command**, aunque empiece por
  `/`. `"/e2e …$(cat E2E_PROMPT.md)"` llegaba como `[Pasted text #N]` y el skill
  no se cargaba. El comando tiene que ir solo, en una línea corta
  (`slash_prompt_`).
- **Si el pane destino está a mitad de turno, `agent prompt --wait` casa ESE
  turno** y da el envío por bueno sin haberlo mandado: el reporte se pierde en la
  caja de entrada. Por eso se espera a que el destino se libere antes de escribir.
- **El estado cambia un instante antes de que la TUI pinte la respuesta**, así que
  el watcher espera 2 s antes de leer el pane.
- **Hay que ver el turno arrancar antes de esperar su fin**, o el wait casa el
  `idle` anterior al prompt y reporta con el agente aún pensando.
- **La TUI separa con espacios duros (U+00A0)**, así que `"❯ texto"` no casa con un
  espacio normal. Normalizar antes de comparar.
- **El prompt se cuela en el reporte por dos vías**, no una: el campo `Prompt que
  se le dio:` y el eco que la TUI pinta en el pane. Recortar sólo la primera no
  sirve de nada.
- **Con un prompt largo, la línea `❯` no entra en la ventana de lectura del
  pane**, así que no se puede usar como ancla para localizar el inicio del turno.
- **`$HERDR_PANE_ID` ≠ `herdr pane current`**: el segundo devuelve el pane con el
  foco, que no es el pane donde corre el script si lo lanza un agente en
  background.
- **macOS trae bash 3.2**: nada de `${var,,}`, `declare -A` ni `mapfile`. Un
  `${var,,}` da `bad substitution` y mata el watcher en silencio — y `bash -n`
  no lo detecta, porque es error de ejecución y no de sintaxis.
- **La integración de claude debe estar al día** (`herdr integration status`, se
  actualiza con `herdr integration install claude`). Es el hook que reporta el
  estado real del agente; sin él, `agent wait` no dispara cuando debe.
