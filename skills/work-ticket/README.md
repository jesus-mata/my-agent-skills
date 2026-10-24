# work-ticket — scripts

Contenido: [Ficheros](#ficheros) · [start-ticket.sh](#start-ticketsh) ·
[run-phase.sh](#run-phasesh) · [wait-agent.sh](#wait-agentsh) ·
[spawn-ticket.sh](#spawn-ticketsh) ·
[split-pane.sh](#split-panesh) · [herdr-report.sh](#herdr-reportsh) ·
[Cosas que costaron sangre](#cosas-que-costaron-sangre)

Scripts para lanzar agentes claude en herdr y recibir sus resultados de
vuelta. Sólo funcionan **dentro de herdr** (`HERDR_ENV=1`).

## Ficheros

| Fichero | Qué hace |
|---|---|
| `start-ticket.sh` | Punto de entrada de la skill: valida, actualiza y lanza el agente del ticket |
| `run-phase.sh` | Lo usa el agente del ticket para lanzar la review o la E2E y esperarla |
| `wait-agent.sh` | Espera a que un agente termine e imprime su último turno |
| `spawn-ticket.sh` | Crea un git worktree, arranca claude dentro y le manda un prompt |
| `split-pane.sh` | Divide un pane, arranca claude dentro y le manda un prompt |
| `herdr-report.sh` | Librería compartida: plantillas, filtro del turno y espera. No se ejecuta sola |
| `*_PROMPT.md`, `TRIAGE_RULES.md` | Prompts de cada fase, con placeholders `{{CLAVE}}` |
| `evals/evals.json` | Escenarios con los que probar la skill de punta a punta |

Flujo: `start-ticket.sh` → agente del ticket (`IMPLEMENT_PROMPT.md`) →
`run-phase.sh review` → `run-phase.sh e2e` → salida de `start-ticket.sh`.

**Los resultados se recogen, no se entregan.** `start-ticket.sh` y
`run-phase.sh` lanzan el agente y luego **esperan** a que termine
(`wait-agent.sh`), imprimiendo su último turno. Quien los llama los lanza con el
`run_in_background` del Bash tool, termina su turno, y Claude Code le despierta
cuando el script sale, con el reporte en la salida. Es el modelo de
`herdr-implement-spec`.

Antes un watcher en background le *tecleaba* el reporte al pane padre. Eso
obligaba a esperar a que el padre estuviera libre, rescatar el Enter de un
texto pegado, acertar a qué pane reportar… y aun así se perdían reportes.

`spawn-ticket.sh` y `split-pane.sh` sólo lanzan: vuelven en ~7 s, en cuanto
confirman que el prompt entró. Para recoger el resultado, `wait-agent.sh`.

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
4. Rellena `IMPLEMENT_PROMPT.md`, lanza el agente con `spawn-ticket.sh` y
   espera con `wait-agent.sh --until-line 'TICKET (DONE|…) '` (tope
   `TICKET_WATCH_MS`, 5 h por defecto).

La espera acaba cuando el agente imprime su línea `TICKET <veredicto>`, no en
el primer turno que termina (ver `wait_agent_`). Si falla antes de lanzar,
sale con `start-ticket: …` y sin la línea `herdr: agent …`.

## run-phase.sh

```
run-phase.sh <review|e2e> <ticket-id> <pr-num> [pane-id]
```

Rellena `REVIEW_PROMPT.md` o `E2E_PROMPT.md` más `TRIAGE_RULES.md` con el
ticket y el PR, abre la fase con `split-pane.sh` y la espera con
`wait-agent.sh`. `[pane-id]` elige de dónde sale el split. La review se abre a
la derecha (tope 1 h) y la E2E debajo (tope 2 h); `PHASE_WATCH_MS` cambia el
tope.

## wait-agent.sh

```
wait-agent.sh <agente|pane> [--timeout-ms MS] [--until-line RE] [--lines N]
```

Espera a que el agente termine su turno (o se bloquee, o se agote el tope),
lanza una notificación de herdr e imprime:

```
herdr: agent '<nombre>' (pane <id>) -> <done|idle|blocked|timeout: …>

<últimas N líneas del turno>

Leer más:        herdr pane read …
Responderle:     herdr agent prompt <nombre> '<texto>'
Seguir esperando: …/wait-agent.sh <nombre> … # en background
```

Salida `0` terminó, `3` bloqueado esperando input, `1` timeout o agente
perdido. Con `--until-line`, un turno terminado sin esa línea no cuenta y se
sigue esperando. Úsalo, en background, tras responder a un agente bloqueado o
pedirle que repita su reporte.

| Opción | Por defecto | Para qué |
|---|---|---|
| `--timeout-ms` | `3600000` | Tope de la espera (1 h) |
| `--until-line` | vacío | Regex de la línea de fin real |
| `--lines` | `40` | Líneas del turno que se imprimen |

## spawn-ticket.sh

```
spawn-ticket.sh <id> [prompt] [cwd] [branch]
```

Crea un worktree nativo de herdr (workspace + tab + pane propios) y arranca
claude en modo yolo con `--model opus` en su pane raíz. Imprime el nombre del
agente en stdout y las pistas en stderr: `NAME=$(./spawn-ticket.sh 42 "...")`. El script **antepone `ticket-`** al id:
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

Divide un pane, etiqueta el nuevo y arranca claude (yolo, `--model opus`)
dentro. No espera al turno: para eso, `wait-agent.sh <pane_id>`.

```bash
./split-pane.sh review right                        # claude listo, sin prompt
./split-pane.sh review right "revisa el diff"       # claude + prompt
./split-pane.sh tests down "corre los tests" w1:pE  # split de un pane concreto
```

- `pane-id` por defecto es `$HERDR_PANE_ID`, el pane donde corre el script.
- Imprime el `pane_id` nuevo en **stdout** y las pistas en stderr, así que se
  encadena: `PANE=$(./split-pane.sh review right)`.

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
- **`read_turn_ <pane> <líneas>`** (→ stdout): lee el pane y lo pasa por los
  dos filtros de arriba.
- **`wait_agent_ <agente|pane> <watch-ms> <líneas> [fin-re]`** (→ stdout,
  código): espera en primer plano, notifica e imprime el reporte. Es lo que
  hay debajo de `wait-agent.sh`.

| Variable | Por defecto | Para qué |
|---|---|---|
| `SLASH_PROMPT_MAX` | `300` | Longitud a partir de la cual un `/cmd` de una línea se parte a fichero |

Vive aparte a propósito: tener dos copias de esta lógica garantizaba que se
separasen.

### Pasar un fichero como prompt

Funciona sin más, con sustitución de comandos — `text` no tiene límite en el API
y `ARG_MAX` es ~1 MB:

```bash
./spawn-ticket.sh 42 "$(cat plan.md)"
```

`$(cat ...)` no expande variables: un `$TICKET_ID` dentro del fichero llega
literal. Para ficheros con valores usa `{{CLAVE}}` y `render_prompt_`.

`wait-agent.sh` **no** repite el fichero: `drop_prompt_echo_` quita el eco del
pane. De ~45 líneas de relleno a las dos de la respuesta.

Dos avisos:

- Si el prompt **empieza por `/cmd`** y es multilínea o pasa de
  `SLASH_PROMPT_MAX` (300) caracteres, `slash_prompt_` lo parte: manda sólo
  `/cmd <instrucción de leer el fichero>` y el resto lo escribe en
  `$TMPDIR/herdr-prompts/`. Así `"/e2e ... $(cat E2E_PROMPT.md)"` carga el skill.
  Los ficheros de más de un día se purgan en la siguiente llamada.
  Si **no** quieres que se lea como comando, antepón una línea:
  `"Implementa este plan:\n\n$(cat plan.md)"`.
- Pasar la **ruta** en vez del contenido (`"lee ~/repo/plan.md e impleméntalo"`)
  sólo vale si el fichero está commiteado: el worktree únicamente tiene ficheros
  trackeados, y el agente no vive en tu checkout.

---

## Cosas que costaron sangre

Detalles poco obvios de herdr y de la TUI de claude. Están comentados en el
código; se resumen aquí para no volver a tropezar.

- **Teclear el reporte en el pane padre no escala.** Era la causa de la mitad
  de esta lista (Enter que no entra, padre a mitad de turno, reporte al pane
  equivocado). Ahora quien lanza espera con `run_in_background` y lee la
  salida; nadie le escribe.
- **Un agente que espera a otro termina su turno.** El agente del ticket lanza
  la review en background y acaba su turno hasta que sale, así que pasa a
  `done` con el trabajo a medias. Por eso `start-ticket.sh` espera a la línea
  `TICKET <veredicto>` (`--until-line`) y no al primer `done`.
- **Una línea de veredicto ausente no siempre es un fallo**: puede haberse
  salido de la ventana de lectura. El agente del ticket pide una vez que la
  repita antes de dar la fase por BLOCKED.
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
  siempre pasa.** Al lanzar un agente hay que confirmar el envío y rescatar
  con `pane send-keys Enter`.
- **Un texto pegado nunca se ejecuta como slash command**, aunque empiece por
  `/`. `"/e2e …$(cat E2E_PROMPT.md)"` llegaba como `[Pasted text #N]` y el skill
  no se cargaba. El comando tiene que ir solo, en una línea corta
  (`slash_prompt_`).
- **Si el agente está a mitad de turno, `agent prompt --wait` casa ESE
  turno** y da el envío por bueno sin haberlo mandado. Escríbele sólo cuando
  `wait-agent.sh` haya vuelto.
- **El estado cambia un instante antes de que la TUI pinte la respuesta**, así que
  `wait_agent_` espera 2 s antes de leer el pane.
- **Hay que ver el turno arrancar antes de esperar su fin**, o el wait casa el
  `idle` anterior al prompt y reporta con el agente aún pensando.
- **La TUI separa con espacios duros (U+00A0)**, así que `"❯ texto"` no casa con un
  espacio normal. Normalizar antes de comparar.
- **La TUI pinta el eco del prompt en el pane**, y con un prompt largo se come
  el reporte: `drop_prompt_echo_` lo quita.
- **Con un prompt largo, la línea `❯` no entra en la ventana de lectura del
  pane**, así que no se puede usar como ancla para localizar el inicio del turno.
- **`$HERDR_PANE_ID` ≠ `herdr pane current`**: el segundo devuelve el pane con el
  foco, que no es el pane donde corre el script si lo lanza un agente en
  background.
- **macOS trae bash 3.2**: nada de `${var,,}`, `declare -A` ni `mapfile`. Un
  `${var,,}` da `bad substitution` y mata el script en silencio — y `bash -n`
  no lo detecta, porque es error de ejecución y no de sintaxis.
- **La integración de claude debe estar al día** (`herdr integration status`, se
  actualiza con `herdr integration install claude`). Es el hook que reporta el
  estado real del agente; sin él, `agent wait` no dispara cuando debe.
