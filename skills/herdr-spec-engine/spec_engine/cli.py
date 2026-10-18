"""Command line: ``engine plan|run|watch|resolve|status|stop|abort``."""
from __future__ import annotations

import argparse
import re
import sys
from typing import Any, Callable, Sequence, TextIO

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


# command handlers (filled in by the scheduler / CLI work) ---------------------------------------

def _not_implemented(name: str) -> int:
    print(f"engine {name}: not implemented", file=sys.stderr)
    return 2


def plan_command(
    github: Any, git: Any, cwd: str, spec: int, branch: str | None, gate: list[str] | None,
    from_file: str | None, out: TextIO,
) -> int:
    """Build, validate, save and print the plan. 0 if runnable, 1 if not, 2 on input errors."""
    import os

    from . import plan as planner
    from .store import Store, state_dir_for

    repo_root = git.repo_root(cwd)
    common_dir = os.path.join(cwd, git.common_dir(cwd))  # absolute stays absolute
    gate_cmds = list(gate) if gate else planner.discover_gate(repo_root)
    try:
        plan = planner.build_plan(github, spec, branch or f"spec-{spec}", gate_cmds, from_file)
    except (OSError, ValueError, LookupError) as e:
        print(f"engine plan: {e}", file=sys.stderr)
        return 2
    problems = planner.validate_plan(plan)
    store = Store(state_dir_for(common_dir, spec))
    store.save_plan(plan)
    out.write(planner.format_plan(plan, problems))
    out.write(f"Plan written to {store.paths.plan}\n")
    return 0 if not problems else 1


def cmd_plan(args: argparse.Namespace) -> int:
    import os

    from .adapters.gh_cli import CliGitHub
    from .adapters.git_cli import CliGit

    cwd = os.getcwd()
    return plan_command(CliGitHub(cwd), CliGit(), cwd, args.spec, args.branch, args.gate,
                        args.from_file, sys.stdout)


def cmd_run(args: argparse.Namespace) -> int:
    return _not_implemented("run")


def cmd_watch(args: argparse.Namespace) -> int:
    return _not_implemented("watch")


def cmd_resolve(args: argparse.Namespace) -> int:
    return _not_implemented("resolve")


def cmd_status(args: argparse.Namespace) -> int:
    return _not_implemented("status")


def cmd_stop(args: argparse.Namespace) -> int:
    return _not_implemented("stop")


def cmd_abort(args: argparse.Namespace) -> int:
    return _not_implemented("abort")


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
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
