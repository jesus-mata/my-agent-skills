import contextlib
import dataclasses
import io
import json
import os
import tempfile
import unittest

from spec_engine.cli import plan_command
from spec_engine.model import Plan, PlanTicket, TicketClass
from spec_engine.plan import (
    build_plan, choose_gate, depths, discover_gate, format_plan, gate_from_spec,
    has_acceptance_criteria, plan_runnable, plan_warnings, repo_warnings, validate_plan,
)
from spec_engine.store import Store, state_dir_for
from tests.fakes import FakeGit, FakeGitHub, make_issue, ref

AGENT = ("ready-for-agent",)
HUMAN = ("ready-for-human",)


def spec_with(*tickets, spec=100, sub_issues=None):
    """A FakeGitHub holding spec #``spec`` whose sub-issues are ``tickets`` (Issue objects)."""
    subs = sub_issues if sub_issues is not None else [t.number for t in tickets]
    return FakeGitHub([make_issue(spec, "The spec", sub_issues=subs), *tickets])


def build(gh, spec=100, gate=("make test",), from_file=None):
    return build_plan(gh, spec, f"spec-{spec}", list(gate), from_file)


class BuildPlanTest(unittest.TestCase):
    def test_linear_chain(self):
        gh = spec_with(make_issue(1, labels=AGENT), make_issue(2, labels=AGENT, blocked_by=[1]),
                       make_issue(3, labels=AGENT, blocked_by=[2]))
        plan = build(gh)
        self.assertEqual(plan.spec, 100)
        self.assertEqual(plan.title, "The spec")
        self.assertEqual(plan.branch, "spec-100")
        self.assertEqual(plan.base, "main")
        self.assertEqual(plan.gate, ["make test"])
        self.assertEqual([t.number for t in plan.tickets], [1, 2, 3])
        self.assertEqual([t.blockers for t in plan.tickets], [[], [1], [2]])
        self.assertTrue(all(t.klass is TicketClass.AGENT for t in plan.tickets))
        self.assertEqual(depths(plan), {1: 0, 2: 1, 3: 2})
        self.assertEqual(validate_plan(plan), [])
        self.assertTrue(plan_runnable(plan))

    def test_diamond(self):
        gh = spec_with(make_issue(1, labels=AGENT), make_issue(2, labels=AGENT, blocked_by=[1]),
                       make_issue(3, labels=AGENT, blocked_by=[1]),
                       make_issue(4, labels=AGENT, blocked_by=[3, 2]))
        plan = build(gh)
        self.assertEqual(plan.ticket(4).blockers, [2, 3])
        self.assertEqual(depths(plan), {1: 0, 2: 1, 3: 1, 4: 2})
        self.assertTrue(plan_runnable(plan))

    def test_closed_ticket_is_done_and_kept_as_blocker(self):
        gh = spec_with(make_issue(1, state="CLOSED"), make_issue(2, labels=AGENT, blocked_by=[1]))
        plan = build(gh)
        self.assertIs(plan.ticket(1).klass, TicketClass.DONE)
        self.assertEqual(plan.ticket(2).blockers, [1])
        self.assertTrue(plan_runnable(plan))

    def test_cycle_detection_reports_path(self):
        gh = spec_with(make_issue(1, labels=AGENT, blocked_by=[3]),
                       make_issue(2, labels=AGENT, blocked_by=[1]),
                       make_issue(3, labels=AGENT, blocked_by=[2]),
                       make_issue(4, labels=AGENT))
        plan = build(gh)
        problems = validate_plan(plan)
        self.assertEqual(problems, ["blocker cycle: #1 -> #3 -> #2 -> #1"])
        self.assertFalse(plan_runnable(plan))
        self.assertEqual(depths(plan), {4: 0})
        text = format_plan(plan, problems)
        self.assertIn("In a cycle:", text)
        self.assertIn("NOT RUNNABLE", text)

    def test_unrefined_neither_or_both_labels(self):
        gh = spec_with(make_issue(1), make_issue(2, labels=AGENT + HUMAN),
                       make_issue(3, labels=("bug",) + AGENT))
        plan = build(gh)
        self.assertIs(plan.ticket(1).klass, TicketClass.UNREFINED)
        self.assertIs(plan.ticket(2).klass, TicketClass.UNREFINED)
        self.assertIs(plan.ticket(3).klass, TicketClass.AGENT)
        self.assertEqual(plan.ticket(3).labels, ["bug", "ready-for-agent"])
        problems = validate_plan(plan)
        self.assertEqual(len(problems), 1)
        self.assertIn("unrefined tickets", problems[0])
        self.assertIn("#1, #2", problems[0])
        self.assertFalse(plan_runnable(plan))
        text = format_plan(plan, problems)
        self.assertIn("Unrefined tickets", text)
        self.assertIn("#1 Issue 1  labels: (none)", text)

    def test_closed_unlabeled_ticket_is_done_not_unrefined(self):
        plan = build(spec_with(make_issue(1, state="CLOSED")))
        self.assertIs(plan.ticket(1).klass, TicketClass.DONE)
        self.assertTrue(plan_runnable(plan))

    def test_human_ticket(self):
        gh = spec_with(make_issue(1, labels=HUMAN), make_issue(2, labels=AGENT, blocked_by=[1]))
        plan = build(gh)
        self.assertIs(plan.ticket(1).klass, TicketClass.HUMAN)
        self.assertTrue(plan_runnable(plan))
        self.assertIn("#1 [human] Issue 1", format_plan(plan, []))

    def test_external_blockers_open_recorded_closed_ignored(self):
        gh = spec_with(make_issue(1, labels=AGENT, blocked_by=[50, ref(51, state="CLOSED")]))
        plan = build(gh)
        self.assertEqual(plan.ticket(1).blockers, [])
        self.assertEqual(plan.ticket(1).external_blockers, ["o/r#50"])
        self.assertTrue(plan_runnable(plan))
        self.assertIn("external: o/r#50", format_plan(plan, []))

    def test_cross_repo_ref_with_same_number_is_external(self):
        gh = spec_with(make_issue(1, labels=AGENT),
                       make_issue(2, labels=AGENT, blocked_by=[ref(1, repo="other/lib"),
                                                               ref(9, "CLOSED", "other/lib")]))
        plan = build(gh)
        self.assertEqual(plan.ticket(2).blockers, [])
        self.assertEqual(plan.ticket(2).external_blockers, ["other/lib#1"])

    def test_cross_repo_sub_issues_are_not_tickets(self):
        gh = spec_with(make_issue(1, labels=AGENT),
                       sub_issues=[1, ref(7, repo="other/lib")])
        plan = build(gh)
        self.assertEqual([t.number for t in plan.tickets], [1])

    def test_from_file_supplies_tickets_and_blockers(self):
        gh = FakeGitHub([make_issue(100, "No subs"), make_issue(1, labels=AGENT),
                         make_issue(2, labels=AGENT, blocked_by=[1, 60]),
                         make_issue(3, labels=HUMAN)])
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "tickets.json")
            with open(path, "w") as f:
                json.dump({"tickets": [{"number": 2, "blocked_by": [3]}, {"number": 1},
                                       {"number": 3, "blocked_by": []}]}, f)
            plan = build(gh, from_file=path)
        self.assertEqual([t.number for t in plan.tickets], [1, 2, 3])
        # Blockers come from the file; in-spec GitHub blockers are ignored, external ones kept.
        self.assertEqual(plan.ticket(2).blockers, [3])
        self.assertEqual(plan.ticket(2).external_blockers, ["o/r#60"])
        self.assertIs(plan.ticket(3).klass, TicketClass.HUMAN)
        self.assertTrue(plan_runnable(plan))

    def test_from_file_dangling_blocker(self):
        gh = FakeGitHub([make_issue(100), make_issue(1, labels=AGENT)])
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "tickets.json")
            with open(path, "w") as f:
                json.dump({"tickets": [{"number": 1, "blocked_by": [99]}]}, f)
            plan = build(gh, from_file=path)
        self.assertEqual(validate_plan(plan), ["#1 is blocked by #99, which is not in the plan"])
        self.assertEqual(depths(plan), {1: 0})

    def test_from_file_malformed(self):
        gh = FakeGitHub([make_issue(100)])
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "tickets.json")
            with open(path, "w") as f:
                json.dump({"tickets": [{"number": "1"}]}, f)
            with self.assertRaises(ValueError):
                build(gh, from_file=path)


class FormatPlanTest(unittest.TestCase):
    def plan(self, gate=("npm test",)):
        return Plan(spec=7, title="Spec", branch="spec-7", gate=list(gate), tickets=[
            PlanTicket(1, "One", TicketClass.DONE),
            PlanTicket(2, "Two", TicketClass.AGENT, blockers=[1]),
            PlanTicket(3, "Three", TicketClass.AGENT),
            PlanTicket(4, "Four", TicketClass.HUMAN, blockers=[2, 3], external_blockers=["o/r#9"]),
        ])

    def test_grouped_by_depth(self):
        text = format_plan(self.plan(), [])
        self.assertIn("Spec #7: Spec", text)
        self.assertIn("Spec branch: spec-7", text)
        w0, w1, w2 = text.index("Wave 0:"), text.index("Wave 1:"), text.index("Wave 2:")
        self.assertLess(w0, text.index("#1 [done] One"))
        self.assertLess(text.index("#3 [agent] Three"), w1)
        self.assertLess(w1, text.index("#2 [agent] Two  blocked by #1"))
        self.assertLess(w2, text.index("#4 [human] Four  blocked by #2, #3  external: o/r#9"))
        self.assertIn("  npm test", text)
        self.assertNotIn("WARNING", text)
        self.assertIn("Plan is runnable.", text)

    def test_empty_gate_warns(self):
        text = format_plan(self.plan(gate=()), [])
        self.assertIn("WARNING: the gate is empty", text)
        self.assertIn("Hint: declare the gate in the spec issue body (a `## Gate` section", text)
        self.assertIn("or pass --gate", text)

    def test_gate_source_shown(self):
        text = format_plan(self.plan(), [], "spec #7 body")
        self.assertIn("Gate (spec #7 body):\n  npm test", text)
        self.assertNotIn("Hint:", text)


    def test_test_runner_gate_notes_that_no_tests_passes(self):
        for cmd in ("python3 -m unittest discover -s tests", "python3 -m pytest"):
            text = format_plan(self.plan(gate=(cmd,)), [])
            self.assertIn("Note: exit 5 (no tests found)", text)
            self.assertNotIn("WARNING", text)
        self.assertNotIn("exit 5", format_plan(self.plan(), []))


class GateFromSpecTest(unittest.TestCase):
    def test_gate_section_fenced_block(self):
        body = ("Intro\n\n## Gate\n\nRun these:\n\n```sh\n# comment\n"
                "python3 -m unittest discover -s tests\n\n$ ruff check .\n```\n\n## Notes\n"
                "```\nnot a gate\n```\n")
        self.assertEqual(gate_from_spec(body),
                         ["python3 -m unittest discover -s tests", "ruff check ."])

    def test_gate_heading_any_level_and_tilde_fence(self):
        self.assertEqual(gate_from_spec("#### Gate commands\n~~~\nmake check\n~~~\n"),
                         ["make check"])

    def test_fence_outside_the_gate_section_is_ignored(self):
        self.assertEqual(gate_from_spec("## Usage\n```\nmake run\n```\n## Gate\nTBD\n"), [])

    def test_gate_line(self):
        body = "Scope: only src/\n\nGate: `pnpm test`\n- **Gate:** `pnpm lint` and `pnpm build`\n"
        self.assertEqual(gate_from_spec(body), ["pnpm test", "pnpm lint", "pnpm build"])

    def test_gate_section_wins_over_gate_line(self):
        self.assertEqual(gate_from_spec("Gate: `a`\n## Gate\n```\nb\n```\n"), ["b"])

    def test_no_gate(self):
        self.assertEqual(gate_from_spec(""), [])
        self.assertEqual(gate_from_spec("The gate is decided later.\n```\nx\n```"), [])


class ChooseGateTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        with open(os.path.join(self.root, "Cargo.toml"), "w"):
            pass

    def test_precedence(self):
        body = "Gate: `make spec`"
        self.assertEqual(choose_gate(["make x"], body, 7, self.root), (["make x"], "--gate"))
        self.assertEqual(choose_gate(None, body, 7, self.root), (["make spec"], "spec #7 body"))
        self.assertEqual(choose_gate([], "", 7, self.root),
                         (["cargo build", "cargo test"], "discovered from repository files"))
        os.remove(os.path.join(self.root, "Cargo.toml"))
        self.assertEqual(choose_gate(None, "", 7, self.root), ([], ""))


class DiscoverGateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    def write(self, name, content=""):
        with open(os.path.join(self.root, name), "w") as f:
            f.write(content if isinstance(content, str) else json.dumps(content))

    def package(self, *scripts):
        self.write("package.json", {"name": "x", "scripts": {s: "true" for s in scripts}})

    def test_nothing(self):
        self.assertEqual(discover_gate(self.root), [])

    def test_pnpm(self):
        self.package("test", "lint", "dev", "type-check", "build", "format:check")
        self.write("pnpm-lock.yaml")
        self.assertEqual(discover_gate(self.root), [
            "pnpm install --frozen-lockfile", "pnpm run lint", "pnpm run type-check",
            "pnpm run format:check", "pnpm run build", "pnpm run test",
        ])

    def test_typecheck_preferred_over_type_check(self):
        self.package("typecheck", "type-check")
        self.write("yarn.lock")
        self.assertEqual(discover_gate(self.root),
                         ["yarn install --frozen-lockfile", "yarn run typecheck"])

    def test_bun(self):
        self.package("test")
        self.write("bun.lockb")
        self.assertEqual(discover_gate(self.root), ["bun install", "bun run test"])

    def test_npm_ci_with_lockfile(self):
        self.package("lint")
        self.write("package-lock.json", "{}")
        self.assertEqual(discover_gate(self.root), ["npm ci", "npm run lint"])

    def test_npm_without_lockfile(self):
        self.package()
        self.assertEqual(discover_gate(self.root), ["npm install"])

    def test_makefile(self):
        self.write("Makefile", "VAR := 1\nbuild: dep\n\tcc\ntest:\n\t./t\n.PHONY: test\n")
        self.assertEqual(discover_gate(self.root), ["make test", "make build"])

    def test_makefile_without_targets_falls_through(self):
        self.write("Makefile", "run:\n\t./run\n")
        self.write("go.mod", "module x\n")
        self.assertEqual(discover_gate(self.root),
                         ["go vet ./...", "go build ./...", "go test ./..."])

    def test_cargo(self):
        self.write("Cargo.toml")
        self.assertEqual(discover_gate(self.root), ["cargo build", "cargo test"])

    def test_pyproject(self):
        self.write("pyproject.toml")
        self.assertEqual(discover_gate(self.root), ["python3 -m pytest"])

    def test_dotnet_solution(self):
        self.write("App.sln")
        self.write("pyproject.toml")
        self.assertEqual(discover_gate(self.root),
                         ["dotnet build App.sln", "dotnet test App.sln --no-build"])

    def test_dotnet_slnx(self):
        self.write("App.slnx")
        self.assertEqual(discover_gate(self.root),
                         ["dotnet build App.slnx", "dotnet test App.slnx --no-build"])

    def test_several_dotnet_solutions_discover_no_gate(self):
        self.write("A.sln")
        self.write("B.sln")
        self.write("go.mod", "module x\n")
        self.assertEqual(discover_gate(self.root), [])
        plan = Plan(spec=7, title="S", branch="spec-7", gate=[])
        with open(os.path.join(self.root, "E2E.md"), "w"):
            pass
        [warning] = plan_warnings(plan, self.root)
        self.assertIn("several .NET solutions at the repository root (A.sln, B.sln)", warning)
        self.assertIn('--gate "dotnet build A.sln"', warning)
        plan.gate = ["make check"]
        self.assertEqual(plan_warnings(plan, self.root), [])

    def test_makefile_wins_over_dotnet(self):
        self.write("Makefile", "test:\n\t./t\n")
        self.write("App.sln")
        self.assertEqual(discover_gate(self.root), ["make test"])

    def test_package_json_wins_over_others(self):
        self.package("test")
        self.write("pyproject.toml")
        self.assertEqual(discover_gate(self.root), ["npm install", "npm run test"])


class AcceptanceCriteriaTest(unittest.TestCase):
    def test_bodies_with_criteria(self):
        for body in ("## Acceptance criteria\n- exports CSV", "### Acceptance Criteria",
                     "**Acceptance criteria**\n1. x", "Acceptance criteria:\n- x",
                     "## ACs\n- x", "**AC:** exports", "AC: exports", "**ACs**",
                     "## Acceptance Criteria (must pass)", "Do it.\n\n- [ ] exports CSV",
                     "  * [x] done already"):
            self.assertTrue(has_acceptance_criteria(body), body)

    def test_bodies_without_criteria(self):
        for body in ("", "Fix login", "## Goal\nUsers can export.\n- a bullet",
                     "We accept that this is slow.", "ACME integration",
                     "Acceptance of the risk is out of scope", "The account page"):
            self.assertFalse(has_acceptance_criteria(body), body)


class PlanWarningsTest(unittest.TestCase):
    def test_agent_tickets_without_criteria_and_missing_e2e_md(self):
        with tempfile.TemporaryDirectory() as root:
            plan = Plan(spec=7, title="S", branch="spec-7", tickets=[
                PlanTicket(1, "Has ACs", TicketClass.AGENT),
                PlanTicket(2, "Bare", TicketClass.AGENT, has_acceptance=False),
                PlanTicket(3, "Human", TicketClass.HUMAN, has_acceptance=False),
                PlanTicket(4, "Closed", TicketClass.DONE, has_acceptance=False)])
            warnings = plan_warnings(plan, root)
            self.assertEqual(len(warnings), 2)
            self.assertIn("without acceptance criteria", warnings[0])
            self.assertIn("#2 Bare", warnings[0])
            self.assertNotIn("#3", warnings[0])
            self.assertNotIn("#4", warnings[0])
            self.assertIn("no E2E.md", warnings[1])
            with open(os.path.join(root, "E2E.md"), "w"):
                pass
            self.assertEqual(plan_warnings(plan, root), [warnings[0]])
            text = format_plan(plan, [], warnings=warnings)
            self.assertIn("WARNING: tickets without acceptance criteria", text)
            self.assertIn("WARNING: no E2E.md", text)

    def test_has_acceptance_round_trips_and_defaults_true(self):
        t = PlanTicket(2, "Bare", TicketClass.AGENT, has_acceptance=False)
        self.assertFalse(PlanTicket.from_dict(t.to_dict()).has_acceptance)
        legacy = {k: v for k, v in t.to_dict().items() if k != "has_acceptance"}
        self.assertTrue(PlanTicket.from_dict(legacy).has_acceptance)


class RepoWarningsTest(unittest.TestCase):
    def setUp(self):
        self.git = FakeGit(branches={"main": 5, "origin/main": 5})
        self.git.upstreams["main"] = "origin/main"
        self.plan = Plan(spec=7, title="S", branch="spec-7", gate=["true"])

    def test_clean_and_up_to_date(self):
        self.assertEqual(repo_warnings(self.git, "/repo", self.plan), [])
        self.assertEqual(self.git.calls_to("fetch_upstream")[0]["branch"], "main")

    def test_dirty_root_lists_the_changes(self):
        self.git.set_status("/repo", [" M src/a.py", "?? notes.txt"])
        [warning] = repo_warnings(self.git, "/repo", self.plan)
        self.assertIn("uncommitted changes (src/a.py, notes.txt)", warning)
        self.assertIn("repo-dirty", warning)

    def test_dirty_root_caps_the_list(self):
        self.git.set_status("/repo", [f"?? f{i}" for i in range(13)])
        [warning] = repo_warnings(self.git, "/repo", self.plan)
        self.assertIn("f9 and 3 more", warning)
        self.assertNotIn("f10", warning)

    def test_behind_upstream_is_fast_forwarded(self):
        self.git.branches["origin/main"] = 8
        [warning] = repo_warnings(self.git, "/repo", self.plan)
        self.assertIn("local main is 3 commits behind origin/main", warning)
        self.assertIn("fast-forwards it before cutting spec-7", warning)

    def test_behind_and_diverged(self):
        self.git.ahead[("main", "origin/main")] = 1
        self.git.ahead[("origin/main", "main")] = 2
        [warning] = repo_warnings(self.git, "/repo", self.plan)
        self.assertIn("1 commit behind origin/main", warning)
        self.assertIn("2 commits of its own", warning)
        self.assertIn("--ff-only` before cutting spec-7 will fail", warning)

    def test_behind_with_existing_spec_branch(self):
        self.git.branches.update({"origin/main": 6, "spec-7": 5})
        [warning] = repo_warnings(self.git, "/repo", self.plan)
        self.assertIn("spec branch spec-7 already exists", warning)

    def test_no_upstream_or_no_base_is_silent(self):
        del self.git.upstreams["main"]
        self.assertEqual(repo_warnings(self.git, "/repo", self.plan), [])
        self.plan.base = "develop"
        self.assertEqual(repo_warnings(self.git, "/repo", self.plan), [])
        self.assertEqual(len(self.git.calls_to("fetch_upstream")), 1)

    def test_failed_fetch_is_a_warning(self):
        self.git.fetch_error = "git fetch -q origin refs/heads/main failed (128): no network"
        [warning] = repo_warnings(self.git, "/repo", self.plan)
        self.assertIn("could not fetch the upstream of main", warning)
        self.assertIn("no network", warning)


class PlanCommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.git = FakeGit(root=self.root)
        self.store = Store(state_dir_for(os.path.join(self.root, ".git"), 100))

    def run_plan(self, gh, gate=None, branch=None, from_file=None):
        out = io.StringIO()
        code = plan_command(gh, self.git, self.root, 100, branch, gate, from_file, out)
        return code, out.getvalue()

    def test_plan_reads_acceptance_criteria_and_warns(self):
        gh = spec_with(make_issue(1, labels=AGENT), make_issue(2, labels=AGENT))
        gh.add(dataclasses.replace(gh.issues[2], body="## Acceptance criteria\n- [ ] works"))
        code, out = self.run_plan(gh, gate=["make check"])
        self.assertEqual(code, 0)  # a warning never makes the plan unrunnable
        self.assertEqual([t.has_acceptance for t in self.store.load_plan().tickets],
                         [False, True])
        self.assertIn("WARNING: tickets without acceptance criteria", out)
        self.assertIn("#1 Issue 1", out)
        self.assertIn("WARNING: no E2E.md", out)

    def test_dirty_root_and_stale_base_warn_without_blocking(self):
        self.git.set_status(self.root, ["?? spec.json"])
        self.git.branches["origin/main"] = 3
        self.git.upstreams["main"] = "origin/main"
        code, out = self.run_plan(spec_with(make_issue(1, labels=AGENT)), gate=["true"])
        self.assertEqual(code, 0)
        self.assertIn("WARNING: the repository root has uncommitted changes (spec.json)", out)
        self.assertIn("WARNING: local main is 2 commits behind origin/main", out)

    def test_runnable_writes_plan_and_exits_0(self):
        with open(os.path.join(self.root, "Cargo.toml"), "w"):
            pass
        gh = spec_with(make_issue(1, labels=AGENT), make_issue(2, labels=AGENT, blocked_by=[1]))
        code, out = self.run_plan(gh)
        self.assertEqual(code, 0)
        plan = self.store.load_plan()
        self.assertEqual(plan.branch, "spec-100")
        self.assertEqual(plan.gate, ["cargo build", "cargo test"])
        self.assertEqual([t.blockers for t in plan.tickets], [[], [1]])
        self.assertIn("Plan is runnable.", out)
        self.assertIn(self.store.paths.plan, out)

    def test_gate_from_spec_body_beats_repo_discovery(self):
        with open(os.path.join(self.root, "Cargo.toml"), "w"):
            pass
        gh = spec_with(make_issue(1, labels=AGENT))
        gh.add(dataclasses.replace(gh.issues[100], body="## Gate\n```\nmake smoke\n```\n"))
        code, out = self.run_plan(gh)
        self.assertEqual(code, 0)
        self.assertEqual(self.store.load_plan().gate, ["make smoke"])
        self.assertIn("Gate (spec #100 body):\n  make smoke", out)
        self.assertEqual(len(gh.calls_to("issue")), 2)  # the spec is read once

    def test_explicit_gate_beats_spec_body(self):
        gh = spec_with(make_issue(1, labels=AGENT))
        gh.add(dataclasses.replace(gh.issues[100], body="Gate: `make smoke`"))
        code, out = self.run_plan(gh, gate=["make check"])
        self.assertEqual(self.store.load_plan().gate, ["make check"])
        self.assertIn("Gate (--gate):", out)

    def test_explicit_gate_and_branch(self):
        gh = spec_with(make_issue(1, labels=AGENT))
        code, out = self.run_plan(gh, gate=["make check"], branch="feat")
        self.assertEqual(code, 0)
        plan = self.store.load_plan()
        self.assertEqual((plan.branch, plan.gate), ("feat", ["make check"]))
        self.assertNotIn("WARNING: the gate", out)

    def test_base_defaults_to_master_when_there_is_no_main(self):
        self.git = FakeGit(root=self.root, branches={"master": 1}, head="master")
        code, out = self.run_plan(spec_with(make_issue(1, labels=AGENT)), gate=["true"])
        self.assertEqual(code, 0)
        self.assertEqual(self.store.load_plan().base, "master")
        self.assertIn("(base master)", out)

    def test_explicit_base(self):
        out = io.StringIO()
        code = plan_command(spec_with(make_issue(1, labels=AGENT)), self.git, self.root, 100,
                            None, ["true"], None, out, base="develop")
        self.assertEqual(code, 0)
        self.assertEqual(self.store.load_plan().base, "develop")

    def test_unrunnable_still_writes_plan_and_exits_1(self):
        gh = spec_with(make_issue(1))
        code, out = self.run_plan(gh)
        self.assertEqual(code, 1)
        self.assertIsNotNone(self.store.load_plan())
        self.assertIn("NOT RUNNABLE", out)
        self.assertIn("WARNING: the gate is empty", out)

    def test_cycle_exits_1(self):
        gh = spec_with(make_issue(1, labels=AGENT, blocked_by=[2]),
                       make_issue(2, labels=AGENT, blocked_by=[1]))
        code, out = self.run_plan(gh, gate=["true"])
        self.assertEqual(code, 1)
        self.assertIn("blocker cycle: #1 -> #2 -> #1", out)

    def test_missing_from_file_exits_2(self):
        gh = spec_with(make_issue(1, labels=AGENT))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code, _ = self.run_plan(gh, gate=["true"],
                                    from_file=os.path.join(self.root, "nope.json"))
        self.assertEqual(code, 2)
        self.assertIn("nope.json", err.getvalue())
        self.assertIsNone(self.store.load_plan())


if __name__ == "__main__":
    unittest.main()
