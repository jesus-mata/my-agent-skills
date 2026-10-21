"""Command line: ``engine plan|run|watch|resolve|status|stop|abort``."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Callable, Sequence, TextIO

from .model import Escalation, EscalationStatus, EngineStatus, RunState, RunStatus, Settings
from .store import Store, state_dir_for

_DURATION_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smh]?)\s*$")
_UNITS = {"": 1, "s": 1, "m": 60, "h": 3600}

# `run` flags that map onto Settings fields (dest == Settings field name).
SETTINGS_FLAGS: tuple[str, ...] = (
    "max_agents", "model", "stage_timeout", "retry_budget",
    "gate_retry_budget", "gate_timeout", "poll_seconds",
)


def parse_duration(text: str) -> float:
    """Seconds from ``"90"``, ``"90s"``, ``"30m"`` or ``"2h"``."""
    m = _DURATION_RE.match(str(text))
    if not m:
        raise argparse.ArgumentTypeError(f"invalid duration {text!r} (use e.g. 90, 90s, 30m, 2h)")
    return float(m.group(1)) * _UNITS[m.group(2)]


def settings_overrides(args: argparse.Namespace) -> dict[str, Any]:
    """The Settings fields given explicitly on a `run` command line."""
    return {k: getattr(args, k) for k in SETTINGS_FLAGS if getattr(args, k, None) is not None}


# command handlers -------------------------------------------------------------------------------
#
# Each ``cmd_<name>(args)`` builds the real adapters and delegates to ``<name>_command(...)``,
# which takes ports / a Store and is what the tests drive.

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE_CMD = os.path.join(SKILL_DIR, "engine")


def invoked_engine_cmd(argv0: str | None = None) -> str:
    """The launcher path as the supervisor invoked it (``sys.argv[0]`` made absolute).

    Not resolved through symlinks, so a skill dir symlinked into a checkout prints the path the
    supervisor typed. Falls back to ``ENGINE_CMD`` when not run through the ``engine`` launcher.
    """
    argv0 = sys.argv[0] if argv0 is None else argv0
    if argv0 and os.path.basename(argv0) == "engine":
        return os.path.abspath(argv0)
    return ENGINE_CMD
WATCH_INTERVAL = 5.0
ABORT_WAIT = 60.0


def _err(command: str, message: str) -> None:
    print(f"engine {command}: {message}", file=sys.stderr)


def plan_command(
    github: Any, git: Any, cwd: str, spec: int, branch: str | None, gate: list[str] | None,
    from_file: str | None, out: TextIO, base: str | None = None,
) -> int:
    """Build, validate, save and print the plan. 0 if runnable, 1 if not, 2 on input errors.

    ``base`` (the spec branch's base) defaults to ``main``, or ``master`` when only that exists.
    """
    from . import plan as planner

    repo_root = git.repo_root(cwd)
    common_dir = os.path.join(cwd, git.common_dir(cwd))  # absolute stays absolute
    try:
        spec_issue = github.issue(spec)
        gate_cmds, gate_source = planner.choose_gate(gate, spec_issue.body, spec, repo_root)
        plan = planner.build_plan(github, spec, branch or f"spec-{spec}", gate_cmds, from_file,
                                  spec_issue=spec_issue)
    except (OSError, ValueError, LookupError) as e:
        _err("plan", str(e))
        return 2
    if base is None and not git.branch_exists(repo_root, "main") and \
            git.branch_exists(repo_root, "master"):
        base = "master"
    plan.base = base or "main"
    problems = planner.validate_plan(plan)
    store = Store(state_dir_for(common_dir, spec))
    store.save_plan(plan)
    out.write(planner.format_plan(plan, problems, gate_source))
    out.write(f"Plan written to {store.paths.plan}\n")
    return 0 if not problems else 1


def _store_for(git: Any, cwd: str, spec: int) -> Store:
    return Store(state_dir_for(os.path.join(cwd, git.common_dir(cwd)), spec))


def _cwd_store(spec: int) -> Store:
    from .adapters.git_cli import CliGit

    cwd = os.getcwd()
    return _store_for(CliGit(), cwd, spec)


def _no_state(command: str, store: Store, spec: int) -> int:
    hint = "run `engine run %d`" % spec if os.path.exists(store.paths.plan) else \
        "run `engine plan %d` first" % spec
    _err(command, f"no engine state for spec #{spec} in {store.state_dir} ({hint})")
    return 1


def preflight_ok(command: str, report: Any, err: TextIO) -> bool:
    """Print the preflight report; False when it has errors (the command then exits 2)."""
    for warning in report.warnings:
        err.write(f"engine {command}: warning: {warning}\n")
    for error in report.errors:
        err.write(f"engine {command}: {error}\n")
    return not report.errors


def cmd_plan(args: argparse.Namespace) -> int:
    from . import preflight
    from .adapters.gh_cli import CliGitHub
    from .adapters.git_cli import CliGit

    cwd = os.getcwd()
    if not preflight_ok("plan", preflight.check(CliGit().repo_root(cwd)), sys.stderr):
        return 2
    return plan_command(CliGitHub(cwd), CliGit(), cwd, args.spec, args.branch, args.gate,
                        args.from_file, sys.stdout, base=args.base)


# run ------------------------------------------------------------------------------------------

def run_command(ports: Any, cwd: str, spec: int, overrides: dict[str, Any], out: TextIO) -> int:
    """Run (or resume) the engine in the foreground until complete, stopped or interrupted.

    0 when complete or stopped; 1 when it may not start (no plan, unrunnable plan, another
    engine alive, run already aborted).
    """
    from . import plan as planner
    from .scheduler import Engine
    from .stages import Context

    repo_root = ports.git.repo_root(cwd)
    common_dir = os.path.join(cwd, ports.git.common_dir(cwd))
    store = Store(state_dir_for(common_dir, spec), now=ports.clock.now)
    plan = store.load_plan()
    if plan is None:
        _err("run", f"no plan for spec #{spec} in {store.state_dir}; run `engine plan {spec}`")
        return 1
    problems = planner.validate_plan(plan)
    if problems:
        _err("run", "the plan is not runnable; fix it and re-run `engine plan "
             f"{spec}`:\n" + "\n".join(f"  - {p}" for p in problems))
        return 1
    if store.engine_alive():
        _err("run", f"an engine for spec #{spec} is already running (pid {store.read_pid()})")
        return 1
    previous = store.load_state()
    if previous is not None and previous.status is EngineStatus.ABORTED:
        _err("run", f"the run of spec #{spec} was aborted; remove {store.state_dir} to start over")
        return 1
    if previous is not None and previous.status is EngineStatus.COMPLETE:
        out.write(f"Spec #{spec} is already complete. Report: {store.paths.report}\n")
        return 0
    settings = Settings.from_dict({**(previous.settings.to_dict() if previous else {}),
                                   **overrides})
    ctx = Context(herdr=ports.herdr, git=ports.git, github=ports.github, shell=ports.shell,
                  clock=ports.clock, plan=plan, settings=settings, store=store,
                  repo_root=repo_root, common_dir=common_dir)
    engine = Engine(ctx)
    out.write(f"herdr-spec-engine: {'resuming' if previous else 'starting'} spec #{spec} "
              f"({plan.title}) on branch {plan.branch}; {len(plan.tickets)} tickets, "
              f"max {settings.max_agents} agents, model {settings.model}\n"
              f"state: {store.state_dir}\n")
    out.flush()
    try:
        engine.run_forever()
    except KeyboardInterrupt:
        if ctx.state is not None:
            engine.event(None, "stopped", reason="interrupted")
            engine.persist()
        store.clear_pid()
        out.write(f"Interrupted: state saved. Resume with `engine run {spec}`.\n")
        return 0
    state = ctx.state
    if state is not None and state.status is EngineStatus.COMPLETE:
        out.write(f"COMPLETE. Report: {store.paths.report}\n")
    else:
        out.write(f"Stopped: state saved. Resume with `engine run {spec}`.\n")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from .adapters import real_ports
    from .adapters.git_cli import CliGit

    from . import preflight

    cwd = CliGit().repo_root(os.getcwd())
    if not preflight_ok("run", preflight.check(cwd), sys.stderr):
        return 2
    return run_command(real_ports(cwd), cwd, args.spec, settings_overrides(args), sys.stdout)


# watch ----------------------------------------------------------------------------------------

def pending_resolution_ids(store: Store, state: RunState) -> set[str]:
    """Escalation ids with a resolutions.jsonl line the engine has not consumed yet."""
    consumed = set(state.consumed_resolutions)
    return {str(item.get("escalation_id")) for item in store.read_resolutions()
            if f"{item.get('escalation_id')}@{item.get('ts')}" not in consumed}


def reportable_escalations(store: Store, state: RunState) -> list[Escalation]:
    """Open escalations the supervisor has not answered yet (handed-off ones are skipped)."""
    pending = pending_resolution_ids(store, state)
    escs = [e for e in state.escalations.values()
            if e.status is EscalationStatus.OPEN and e.id not in pending]
    return sorted(escs, key=lambda e: (e.created_at, int(e.id[1:]) if e.id[1:].isdigit() else 0))


def format_escalation(state: RunState, esc: Escalation, engine_cmd: str = ENGINE_CMD) -> str:
    run = state.runs.get(esc.run)
    run_label = esc.run + (f" (#{run.ticket})" if run is not None and run.ticket else "")
    lines = [f"ESCALATION {esc.id}",
             f"  run:     {run_label}",
             f"  kind:    {esc.kind.value}",
             f"  stage:   {esc.stage.value if esc.stage else '-'}",
             f"  summary: {esc.summary}"]
    if esc.details:
        lines.append("  details:")
        lines += [f"    {line}" for line in esc.details.splitlines()]
    lines.append(f"  actions: {', '.join(esc.actions)}")
    lines.append(f"  resolve: {engine_cmd} resolve {state.spec} {esc.id} <action> [--note TEXT]")
    return "\n".join(lines)


def watch_command(
    store: Store, spec: int, timeout: float, out: TextIO, *, now: Callable[[], float],
    sleep: Callable[[float], None], alive: Callable[[], bool] | None = None,
    interval: float = WATCH_INTERVAL, engine_cmd: str = ENGINE_CMD,
) -> int:
    """Poll state.json (read-only) until there is something for the supervisor.

    0: open escalations printed, or COMPLETE + report, or ABORTED. 3: ENGINE NOT RUNNING (pid
    dead on two consecutive polls and not complete). 1: timeout.
    """
    alive = alive or store.engine_alive
    deadline = now() + timeout
    dead_polls = 0
    while True:
        state = store.load_state()
        if state is not None and state.status is EngineStatus.COMPLETE:
            out.write("COMPLETE\n\n")
            try:
                with open(store.paths.report, encoding="utf-8") as f:
                    out.write(f.read())
            except FileNotFoundError:
                out.write(f"(no report at {store.paths.report})\n")
            return 0
        if state is not None and state.status is EngineStatus.ABORTED:
            out.write("ABORTED\n")
            return 0
        escs = reportable_escalations(store, state) if state is not None else []
        if escs:
            out.write(f"{len(escs)} open escalation(s) for spec #{spec}:\n\n")
            out.write("\n\n".join(format_escalation(state, e, engine_cmd) for e in escs))
            out.write("\n")
            return 0
        dead_polls = 0 if alive() else dead_polls + 1
        if dead_polls >= 2:
            out.write(f"ENGINE NOT RUNNING: restart with `{engine_cmd} run {spec}`\n")
            return 3
        if now() >= deadline:
            out.write(f"watch timed out after {timeout:g}s; nothing to do yet\n")
            return 1
        sleep(max(0.0, min(interval, deadline - now())))


def cmd_watch(args: argparse.Namespace) -> int:
    import time

    return watch_command(_cwd_store(args.spec), args.spec, args.timeout, sys.stdout,
                         now=time.time, sleep=time.sleep, engine_cmd=invoked_engine_cmd())


# resolve --------------------------------------------------------------------------------------

def resolve_command(store: Store, spec: int, escalation_id: str, action: str, note: str,
                    out: TextIO) -> int:
    """Validate against state.json and append to resolutions.jsonl. 0 queued; 2 when there is
    no state or the id / action is not valid."""
    state = store.load_state()
    if state is None:
        _no_state("resolve", store, spec)
        return 2
    esc = state.escalations.get(escalation_id)
    if esc is None:
        unresolved = [e.id for e in state.escalations.values()
                      if e.status is not EscalationStatus.RESOLVED]
        _err("resolve", f"unknown escalation {escalation_id!r}; unresolved: "
             f"{', '.join(unresolved) or 'none'}")
        return 2
    if esc.status is EscalationStatus.RESOLVED:
        _err("resolve", f"{esc.id} is already resolved ({esc.resolution})")
        return 2
    if action not in esc.actions:
        _err("resolve", f"{action!r} is not allowed for {esc.id} ({esc.kind.value}); "
             f"allowed actions: {', '.join(esc.actions)}")
        return 2
    store.append_resolution(esc.id, action, note)
    out.write(f"Queued {esc.id} {action}; the engine applies it on its next tick.\n")
    if not store.engine_alive():
        out.write(f"Note: the engine is not running; it applies this when resumed "
                  f"(`engine run {spec}`).\n")
    return 0


def cmd_resolve(args: argparse.Namespace) -> int:
    return resolve_command(_cwd_store(args.spec), args.spec, args.escalation_id, args.action,
                           args.note, sys.stdout)


# status ---------------------------------------------------------------------------------------

def _awaiting_label(run: Any) -> str:
    aw = run.awaiting or {}
    kind = aw.get("type", "-")
    if kind in ("agent_turn", "resolver"):
        return f"{kind}:{aw.get('result', '')} ({aw.get('agent', '')})"
    return kind


def status_command(store: Store, spec: int, as_json: bool, out: TextIO) -> int:
    """Print runs, queue and escalations (or state.json). 0, or 1 when there is no state."""
    state = store.load_state()
    if state is None:
        return _no_state("status", store, spec)
    if as_json:
        out.write(json.dumps(state.to_dict(), indent=2, sort_keys=True) + "\n")
        return 0
    pid = store.read_pid()
    engine = f"engine running (pid {pid})" if store.engine_alive() else "engine not running"
    out.write(f"spec #{state.spec} on {state.branch}: {state.status.value}, phase "
              f"{state.phase.value}, {engine}\n\nRuns:\n")
    rows = [(r.id, r.status.value, r.stage.value, _awaiting_label(r))
            for r in state.runs.values()]
    widths = [max([len(h)] + [len(row[i]) for row in rows])
              for i, h in enumerate(("RUN", "STATUS", "STAGE", "AWAITING"))]
    for row in [("RUN", "STATUS", "STAGE", "AWAITING")] + rows:
        out.write("  " + "  ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip() + "\n")
    out.write(f"\nMerge queue: {', '.join(state.queue) or 'empty'}\n")
    pending = pending_resolution_ids(store, state)
    unresolved = [e for e in state.escalations.values()
                  if e.status is not EscalationStatus.RESOLVED]
    out.write(f"\nEscalations ({len(unresolved)} unresolved, "
              f"{len(state.escalations) - len(unresolved)} resolved):\n")
    for e in unresolved:
        flag = " [resolution queued]" if e.id in pending else ""
        out.write(f"  {e.id} {e.status.value} {e.kind.value} on {e.run}: {e.summary} "
                  f"(actions: {', '.join(e.actions)}){flag}\n")
    if not unresolved:
        out.write("  none\n")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    return status_command(_cwd_store(args.spec), args.spec, args.json, sys.stdout)


# stop / abort ---------------------------------------------------------------------------------

def stop_command(store: Store, spec: int, out: TextIO) -> int:
    """Ask a running engine to persist and exit at its next tick."""
    if not store.engine_alive():
        out.write(f"No engine is running for spec #{spec}.\n")
        return 0
    store.request_stop()
    out.write(f"Stop requested; the engine saves state and exits at its next tick. Resume with "
              f"`engine run {spec}`.\n")
    return 0


def abort_command(store: Store, spec: int, herdr: Any, out: TextIO, *,
                  now: Callable[[], float], sleep: Callable[[float], None],
                  wait: float = ABORT_WAIT) -> int:
    """Stop the engine, interrupt its agents, close resolver panes and remove the worktrees of
    unfinished runs (branches kept); status ``aborted``. Nothing on GitHub is reverted."""
    if store.engine_alive():
        store.request_stop()
        deadline = now() + wait
        while store.engine_alive() and now() < deadline:
            sleep(1.0)
        if store.engine_alive():
            _err("abort", f"the engine (pid {store.read_pid()}) did not stop within {wait:g}s; "
                 "nothing was torn down")
            return 1
    state = store.load_state()
    if state is None:
        return _no_state("abort", store, spec)
    if state.status is EngineStatus.ABORTED:
        out.write(f"Spec #{spec} was already aborted.\n")
        return 0
    problems = []

    def best_effort(what: str, fn: Callable[[], Any]) -> None:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - teardown continues
            problems.append(f"{what}: {exc}")

    for run in state.runs.values():
        if run.terminal:
            continue
        aw = run.awaiting or {}
        if aw.get("type") == "resolver":
            if aw.get("agent"):
                best_effort(f"interrupt {aw['agent']}",
                            lambda: herdr.interrupt_agent(aw["agent"]))
            if aw.get("pane_id"):
                best_effort(f"close resolver pane {aw['pane_id']}",
                            lambda: herdr.close_pane(aw["pane_id"]))
        if run.agent:
            best_effort(f"interrupt {run.agent}", lambda: herdr.interrupt_agent(run.agent))
        if run.workspace_id:
            best_effort(f"remove worktree of {run.id}",
                        lambda: herdr.remove_worktree(run.workspace_id))
            run.workspace_id = None
        run.status = RunStatus.ABORTED
        run.notes.append("aborted")
    state.queue = []
    state.status = EngineStatus.ABORTED
    store.save_state(state)
    store.append_event(None, "aborted", problems=problems)
    store.clear_stop()
    out.write(f"Aborted spec #{spec}: agents interrupted, worktrees of unfinished runs removed "
              f"(branches kept). Nothing on GitHub was reverted.\n")
    for p in problems:
        out.write(f"  warning: {p}\n")
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    return stop_command(_cwd_store(args.spec), args.spec, sys.stdout)


def cmd_abort(args: argparse.Namespace) -> int:
    import time

    from .adapters.herdr_socket import SocketHerdr

    return abort_command(_cwd_store(args.spec), args.spec, SocketHerdr(), sys.stdout,
                         now=time.time, sleep=time.sleep)


# parser -------------------------------------------------------------------------------------------

def _non_negative_int(text: str) -> int:
    try:
        n = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected an integer, got {text!r}") from None
    if n < 0:
        raise argparse.ArgumentTypeError(f"expected a non-negative integer, got {n}")
    return n


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="engine", description="herdr-spec-engine")
    sub = p.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def add(name: str, handler: Callable[[argparse.Namespace], int], help: str):
        sp = sub.add_parser(name, help=help, description=help)
        sp.add_argument("spec", type=int, metavar="N", help="spec issue number")
        sp.set_defaults(handler=handler)
        return sp

    sp = add("plan", cmd_plan, "build and validate the plan for spec N")
    sp.add_argument("--branch", help="spec branch (default spec-<N>)")
    sp.add_argument("--base", help="branch the spec branch starts from and the spec review "
                    "diffs against (default main, or master when there is no main)")
    sp.add_argument("--gate", action="append", default=None, metavar="CMD",
                    help="gate command (repeatable; default: discovered)")
    sp.add_argument("--from", dest="from_file", metavar="FILE",
                    help='tickets file {"tickets": [{"number", "blocked_by"}]}')

    # Defaults are None so a resumed run overrides only flags given explicitly.
    sp = add("run", cmd_run, "run (or resume) the engine for spec N")
    sp.add_argument("--max-agents", dest="max_agents", type=_non_negative_int, help="default 3")
    sp.add_argument("--model", dest="model", help="default opus")
    sp.add_argument("--stage-timeout", dest="stage_timeout", type=parse_duration,
                    help="default 2h")
    sp.add_argument("--retry-budget", dest="retry_budget", type=_non_negative_int, help="default 1")
    sp.add_argument("--gate-retry-budget", dest="gate_retry_budget", type=_non_negative_int,
                    help="default 2")
    sp.add_argument("--gate-timeout", dest="gate_timeout", type=parse_duration,
                    help="default 30m")
    sp.add_argument("--poll", dest="poll_seconds", type=parse_duration, help="default 10")

    sp = add("watch", cmd_watch, "wait for an escalation, completion or engine death")
    sp.add_argument("--timeout", type=parse_duration, default=parse_duration("4h"),
                    help="default 4h")

    sp = add("resolve", cmd_resolve, "resolve an escalation with one of its actions")
    sp.add_argument("escalation_id", metavar="ESCALATION_ID")
    sp.add_argument("action", metavar="ACTION")
    sp.add_argument("--note", default="", metavar="TEXT")

    sp = add("status", cmd_status, "print runs, queue and escalations")
    sp.add_argument("--json", action="store_true", help="print state.json")

    add("stop", cmd_stop, "ask the engine to persist and exit")
    add("abort", cmd_abort, "stop the engine and tear down agents and worktrees")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    from .adapters.gh_cli import GhError
    from .adapters.git_cli import GitError
    from .ports import HerdrError

    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except (GitError, GhError, HerdrError, OSError) as e:
        _err(args.command, str(e))
        return 2


if __name__ == "__main__":
    sys.exit(main())
