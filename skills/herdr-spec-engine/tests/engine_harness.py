"""A scenario harness for driving ``Engine.tick()`` with the in-memory fakes."""
from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
from typing import Callable

from spec_engine.model import Plan, PlanTicket, RunStatus, Settings, TicketClass
from spec_engine.scheduler import Engine
from spec_engine.stages import Context
from spec_engine.store import Store, state_dir_for
from tests.fakes import (
    FakeClock, FakeGit, FakeGitHub, FakeHerdr, FakeShell, find_result_path, make_issue,
)

SPEC = 7
BRANCH = "spec-7"
COMMON_VARS = {"spec", "spec_title", "result_path", "result_example"}
# Template variables from design.md "Prompts" (besides the common ones).
TEMPLATE_VARS = {
    "implement": {"ticket", "ticket_title", "branch", "spec_branch", "integrated", "siblings"},
    "verify_failed": {"ticket", "branch", "spec_branch", "problem"},
    "review": {"ticket", "spec_branch"},
    "result_retry": {"error"},
    "gate_failed": {"command", "exit_code", "output"},
    "resolver": {"run_id", "branch", "spec_branch", "conflicts"},
    "spec_review": {"spec_branch", "base"},
    "fix_implement": {"branch", "spec_branch", "finding"},
    "fix_review": {"spec_branch", "finding"},
    "e2e": {"spec_branch", "tickets", "not_integrated"},
}

IMPLEMENTED = {"status": "implemented", "summary": "done", "denied_actions": []}
REVIEW_CLEAN = {"fixed": [], "pending": [], "scope_creep": []}
GATE_FIXED = {"summary": "fixed the gate"}


def ticket(number: int, blockers=(), klass: str = "agent", external=(), title: str = ""):
    return PlanTicket(number=number, title=title or f"Ticket {number}",
                      klass=TicketClass(klass), blockers=list(blockers),
                      external_blockers=list(external))


LABELS = {"agent": ["ready-for-agent"], "human": ["ready-for-human"], "unrefined": [],
          "done": ["ready-for-agent"]}


class Harness:
    """Fakes + a temp state dir + an Engine whose renderer checks the design's variables."""

    def __init__(self, tickets: list[PlanTicket], *, gate=("make test",),
                 settings: Settings | None = None) -> None:
        self.tmp = tempfile.mkdtemp(prefix="engine-test-")
        self.clock = FakeClock(1000)
        self.root = os.path.join(self.tmp, "repo")
        os.makedirs(self.root)
        self.common_dir = os.path.join(self.root, ".git")
        self.herdr = FakeHerdr(os.path.join(self.tmp, "wt"), clock=self.clock)
        self.git = FakeGit(root=self.root)
        self.github = FakeGitHub([
            make_issue(t.number, title=t.title, labels=LABELS[t.klass.value],
                       state="CLOSED" if t.klass is TicketClass.DONE else "OPEN")
            for t in tickets
        ])
        self.shell = FakeShell()
        self.plan = Plan(spec=SPEC, title="Spec seven", branch=BRANCH, gate=list(gate),
                         tickets=list(tickets))
        self.settings = settings or Settings()
        self.store = Store(state_dir_for(self.common_dir, SPEC), now=self.clock.now)
        self.rendered: list[tuple[str, dict]] = []
        self.engine = self.new_engine()

    def cleanup(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    # engine ---------------------------------------------------------------------------------

    def render(self, name: str, **vars) -> str:
        expected = COMMON_VARS | TEMPLATE_VARS[name]
        if set(vars) != expected:
            raise AssertionError(f"{name}: vars {sorted(vars)} != design {sorted(expected)}")
        self.rendered.append((name, vars))
        return f"[{name}] Write your result JSON to {vars['result_path']} when done."

    def new_engine(self) -> Engine:
        ctx = Context(herdr=self.herdr, git=self.git, github=self.github, shell=self.shell,
                      clock=self.clock, plan=copy.deepcopy(self.plan), settings=self.settings,
                      store=self.store, repo_root=self.root, common_dir=self.common_dir,
                      render=self.render)
        return Engine(ctx)

    def start(self) -> Harness:
        self.engine.startup()
        return self

    def tick(self, n: int = 1, dt: float = 10) -> bool:
        alive = True
        for _ in range(n):
            alive = self.engine.tick()
            self.clock.advance(dt)
        return alive

    def run_until(self, pred: Callable[[], bool], max_ticks: int = 60, dt: float = 10) -> None:
        for _ in range(max_ticks):
            if pred():
                return
            if not self.tick(dt=dt):
                break
        if not pred():
            raise AssertionError(f"condition not reached; runs: {self.summary()}")

    def summary(self) -> dict:
        return {r.id: (r.status.value, r.stage.value) for r in self.state.runs.values()}

    # inspection -----------------------------------------------------------------------------

    @property
    def state(self):
        return self.engine.state

    def run(self, run_id: str):
        return self.state.runs[run_id]

    def status(self, run_id: str) -> RunStatus:
        return self.state.runs[run_id].status

    def templates(self) -> list[str]:
        return [name for name, _ in self.rendered]

    def open_escalations(self):
        return [e for e in self.state.escalations.values() if e.status.value != "resolved"]

    def only_escalation(self):
        open_ = self.open_escalations()
        assert len(open_) == 1, open_
        return open_[0]

    def resolve(self, esc_id: str, action: str, note: str = "") -> None:
        self.store.append_resolution(esc_id, action, note)

    # scripted agents ------------------------------------------------------------------------

    def turn(self, agent: str, result: dict | str | None, *, commits: int = 0,
             status: str = "idle", branch: str | None = None,
             also: Callable[[], None] | None = None) -> None:
        """On the next prompt to ``agent``: add commits, write ``result``, set ``status``."""

        def handler(fake: FakeHerdr, name: str, text: str) -> None:
            if commits:
                self.git.add_commits(branch or name, commits, base=BRANCH)
            if result is not None:
                path = find_result_path(text)
                assert path, text
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(result if isinstance(result, str) else json.dumps(result))
            if also:
                also()
            fake.set_status(name, status)

        self.herdr.on_prompt(agent, handler)

    def script_ticket(self, run_id: str, review: dict | None = None) -> None:
        """A well-behaved agent: implements with a commit, then reviews cleanly."""
        self.turn(run_id, IMPLEMENTED, commits=1)
        self.turn(run_id, review or REVIEW_CLEAN)
