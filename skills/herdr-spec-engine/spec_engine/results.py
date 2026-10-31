"""Result files: the schema-checked JSON an agent writes to end its turn.

Validators take the parsed JSON and return ``(value, None)`` or ``(None, error)``. Unknown keys
are allowed; every list may be empty. Optional lists (e.g. ``review.dismissed``) may be missing;
readers treat a missing one as ``[]``.
"""
from __future__ import annotations

import json
from typing import Any, Callable

Validator = Callable[[Any], "tuple[dict | None, str | None]"]


class _Invalid(Exception):
    pass


def _obj(v: Any, where: str) -> dict:
    if not isinstance(v, dict):
        raise _Invalid(f"{where}: expected an object, got {_kind(v)}")
    return v


def _field(d: dict, key: str, where: str) -> Any:
    if key not in d:
        raise _Invalid(f"{where}.{key}: missing required field")
    return d[key]


def _str(d: dict, key: str, where: str) -> str:
    v = _field(d, key, where)
    if not isinstance(v, str):
        raise _Invalid(f"{where}.{key}: expected a string, got {_kind(v)}")
    return v


def _enum(d: dict, key: str, where: str, allowed: tuple[str, ...]) -> str:
    v = _field(d, key, where)
    if v not in allowed:
        choices = ", ".join(repr(a) for a in allowed)
        raise _Invalid(f"{where}.{key}: expected one of {choices}, got {v!r}")
    return v


def _int_or_null(d: dict, key: str, where: str) -> int | None:
    v = _field(d, key, where)
    if v is not None and (isinstance(v, bool) or not isinstance(v, int)):
        raise _Invalid(f"{where}.{key}: expected an integer or null, got {_kind(v)}")
    return v


def _int(d: dict, key: str, where: str) -> int:
    v = _field(d, key, where)
    if isinstance(v, bool) or not isinstance(v, int):
        raise _Invalid(f"{where}.{key}: expected an integer, got {_kind(v)}")
    return v


def _bool(d: dict, key: str, where: str) -> bool:
    v = _field(d, key, where)
    if not isinstance(v, bool):
        raise _Invalid(f"{where}.{key}: expected true or false, got {_kind(v)}")
    return v


def _list(d: dict, key: str, where: str) -> list:
    v = _field(d, key, where)
    if not isinstance(v, list):
        raise _Invalid(f"{where}.{key}: expected a list, got {_kind(v)}")
    return v


def _str_list(d: dict, key: str, where: str) -> list[str]:
    items = _list(d, key, where)
    for i, item in enumerate(items):
        if not isinstance(item, str):
            raise _Invalid(f"{where}.{key}[{i}]: expected a string, got {_kind(item)}")
    return items


def _obj_list(d: dict, key: str, where: str, check: Callable[[dict, str], None]) -> list[dict]:
    items = _list(d, key, where)
    for i, item in enumerate(items):
        path = f"{where}.{key}[{i}]"
        check(_obj(item, path), path)
    return items


def _opt_obj_list(d: dict, key: str, where: str,
                  check: Callable[[dict, str], None]) -> list[dict]:
    """Like ``_obj_list``, but the key may be missing (older results omit it; read it as ``[]``)."""
    return _obj_list(d, key, where, check) if key in d else []


def _kind(v: Any) -> str:
    if v is None:
        return "null"
    return {bool: "boolean", int: "integer", float: "number", str: "string", list: "list",
            dict: "object"}.get(type(v), type(v).__name__)


def _validator(name: str, check: Callable[[dict, str], None]) -> Validator:
    def validate(data: Any) -> tuple[dict | None, str | None]:
        try:
            check(_obj(data, name), name)
        except _Invalid as e:
            return None, str(e)
        return data, None

    validate.__name__ = f"validate_{name}"
    validate.__doc__ = f"Validate a `{name}` result."
    return validate


def _implement(d: dict, w: str) -> None:
    _enum(d, "status", w, ("implemented", "outward-denied", "develop-failed"))
    _str(d, "summary", w)
    _str_list(d, "denied_actions", w)


FOLLOW_UP_CATEGORIES = ("pre-existing", "out-of-scope", "needs-decision", "too-large", "tech-debt",
                        "deferred")
FOLLOW_UP_SEVERITIES = ("blocker", "high", "medium")


def _follow_up(e: dict, p: str) -> None:
    _enum(e, "category", p, FOLLOW_UP_CATEGORIES)
    _enum(e, "severity", p, FOLLOW_UP_SEVERITIES)
    _str(e, "title", p)
    _str(e, "file", p)
    _int_or_null(e, "line", p)
    _str(e, "problem", p)
    _str(e, "why_separate", p)
    _str(e, "evidence", p)
    _str_list(e, "acceptance", p)


def _review(d: dict, w: str) -> None:
    kinds = ("spec", "standards")

    def fixed(e: dict, p: str) -> None:
        _enum(e, "kind", p, kinds)
        _str(e, "title", p)
        _str(e, "commit", p)

    def with_reason(e: dict, p: str) -> None:
        _enum(e, "kind", p, kinds)
        _str(e, "title", p)
        _str(e, "reason", p)

    _obj_list(d, "fixed", w, fixed)
    _obj_list(d, "pending", w, with_reason)
    _opt_obj_list(d, "dismissed", w, with_reason)
    _str_list(d, "scope_creep", w)
    _opt_obj_list(d, "follow_ups", w, _follow_up)


def _gate_fix(d: dict, w: str) -> None:
    _str(d, "summary", w)


def _resolve(d: dict, w: str) -> None:
    _enum(d, "verdict", w, ("RESOLVED", "ESCALATE"))
    _str(d, "summary", w)


def _spec_review(d: dict, w: str) -> None:
    severe = ("blocker", "high")

    def fixed(e: dict, p: str) -> None:
        _enum(e, "severity", p, severe)
        _str(e, "title", p)
        _str(e, "commit", p)

    def hard(e: dict, p: str) -> None:
        _enum(e, "severity", p, severe)
        _str(e, "title", p)
        _str(e, "file", p)
        _int_or_null(e, "line", p)
        _str(e, "failure_scenario", p)

    def not_fixed(e: dict, p: str) -> None:  # a medium one not fixed is a `deferred` follow-up
        _enum(e, "severity", p, ("low",))
        _str(e, "title", p)
        if "reason" in e:
            _str(e, "reason", p)

    _obj_list(d, "fixed", w, fixed)
    _obj_list(d, "hard", w, hard)
    _obj_list(d, "not_fixed", w, not_fixed)
    _opt_obj_list(d, "follow_ups", w, _follow_up)


E2E_VERDICTS = ("PASS", "FAIL", "PARTIAL", "BLOCKED")
AC_VERDICTS = ("PASS", "FAIL", "NOT VERIFIABLE")
SEVERITIES = ("blocker", "high", "medium", "low")
COLLATERAL_ACTIONS = ("fixed", "follow-up", "reported")


def e2e_verdict(acs: list[dict]) -> str:
    """The overall verdict the AC verdicts add up to: PASS only if every AC passed, FAIL if any
    failed, else PARTIAL (some could not be verified)."""
    verdicts = {a["verdict"] for a in acs}
    if "FAIL" in verdicts:
        return "FAIL"
    if "NOT VERIFIABLE" in verdicts:
        return "PARTIAL"
    return "PASS"


def ac_verdict(cases: list[dict]) -> str:
    """The AC verdict its cases add up to: FAIL if any case failed, else NOT VERIFIABLE if any
    could not be verified, else PASS."""
    verdicts = {c["verdict"] for c in cases}
    if "FAIL" in verdicts:
        return "FAIL"
    if "NOT VERIFIABLE" in verdicts:
        return "NOT VERIFIABLE"
    return "PASS"


def _e2e(d: dict, w: str) -> None:
    def case(e: dict, p: str) -> None:
        _str(e, "case", p)
        _enum(e, "verdict", p, AC_VERDICTS)
        _str(e, "evidence", p)

    def ac(e: dict, p: str) -> None:
        _int(e, "ticket", p)
        _str(e, "ac", p)
        _str(e, "criterion", p)
        _bool(e, "derived", p)
        verdict = _enum(e, "verdict", p, AC_VERDICTS)
        _str(e, "evidence", p)
        cases = _opt_obj_list(e, "cases", p, case)
        if cases and verdict != ac_verdict(cases):
            raise _Invalid(f"{p}.verdict: its cases add up to {ac_verdict(cases)!r}, not "
                           f"{verdict!r} (any FAIL case is FAIL; else any NOT VERIFIABLE is NOT "
                           "VERIFIABLE; else PASS)")

    def fixed(e: dict, p: str) -> None:
        _str(e, "title", p)
        _str(e, "commit", p)

    def pending(e: dict, p: str) -> None:
        _str(e, "title", p)
        _str(e, "reason", p)

    def collateral(e: dict, p: str) -> None:
        _str(e, "title", p)
        _enum(e, "severity", p, SEVERITIES)
        _bool(e, "caused_by_spec", p)
        _enum(e, "action", p, COLLATERAL_ACTIONS)
        _str(e, "detail", p)

    verdict = _enum(d, "verdict", w, E2E_VERDICTS)
    blocked_by = _str(d, "blocked_by", w)
    acs = _obj_list(d, "acs", w, ac)
    _obj_list(d, "fixed", w, fixed)
    _obj_list(d, "pending", w, pending)
    _obj_list(d, "collateral", w, collateral)
    _opt_obj_list(d, "follow_ups", w, _follow_up)
    if "notes" in d:
        _str_list(d, "notes", w)
    if verdict == "BLOCKED":
        if not blocked_by.strip():
            raise _Invalid(f"{w}.blocked_by: a BLOCKED verdict must say what blocked it")
        return
    if not acs:
        raise _Invalid(f"{w}.acs: a {verdict} verdict needs one entry per acceptance criterion "
                       "tested (use BLOCKED with blocked_by when none could be tested)")
    expected = e2e_verdict(acs)
    if verdict != expected:
        raise _Invalid(f"{w}.verdict: the AC verdicts add up to {expected!r}, not {verdict!r} "
                       "(PASS only if every AC is PASS; any FAIL is FAIL; otherwise PARTIAL)")


def _dedup(d: dict, w: str) -> None:
    def match(e: dict, p: str) -> None:
        _str(e, "id", p)
        verdict = _enum(e, "verdict", p, ("COVERED", "NEW"))
        issue = _int_or_null(e, "issue", p)
        _str(e, "reason", p)
        if verdict == "COVERED" and issue is None:
            raise _Invalid(f"{p}.issue: a COVERED follow-up names the open issue covering it")

    _obj_list(d, "matches", w, match)
    groups = _list(d, "duplicates", w)
    for i, group in enumerate(groups):
        path = f"{w}.duplicates[{i}]"
        if not isinstance(group, list) or len(group) < 2 or \
                not all(isinstance(x, str) for x in group):
            raise _Invalid(f"{path}: expected a list of two or more follow-up ids")


validate_implement = _validator("implement", _implement)
validate_review = _validator("review", _review)
validate_gate_fix = _validator("gate_fix", _gate_fix)
validate_resolve = _validator("resolve", _resolve)
validate_spec_review = _validator("spec_review", _spec_review)
validate_e2e = _validator("e2e", _e2e)
validate_dedup = _validator("dedup", _dedup)

SCHEMAS: dict[str, Validator] = {
    "implement": validate_implement,
    "review": validate_review,
    "gate_fix": validate_gate_fix,
    "resolve": validate_resolve,
    "spec_review": validate_spec_review,
    "e2e": validate_e2e,
    "dedup": validate_dedup,
}

_EXAMPLES: dict[str, dict] = {
    "implement": {"status": "implemented", "summary": "Added the export endpoint with tests.",
                  "denied_actions": []},
    "review": {
        "fixed": [{"kind": "spec", "title": "Missing empty-state message", "commit": "abc1234"}],
        "pending": [{"kind": "standards", "title": "Long function in parser.py",
                     "reason": "Needs a wider refactor"}],
        "dismissed": [{"kind": "spec", "title": "Helper from ticket #3 missing",
                       "reason": "Not a finding: #3 merged into the spec branch after this "
                                 "branch was cut"}],
        "scope_creep": ["Renamed unrelated helper"],
        "follow_ups": [{
            "category": "pre-existing", "severity": "high",
            "title": "Session cookie never expires", "file": "src/auth/session.py", "line": 88,
            "problem": "A stolen cookie stays valid forever.",
            "why_separate": "The bug predates this spec and the fix touches auth, which the spec "
                            "does not cover.",
            "evidence": "git blame: line 88 last changed in a1b2c3d, two years before this spec.",
            "acceptance": ["Session cookies expire after the configured TTL"]}],
    },
    "gate_fix": {"summary": "Fixed the failing lint rule in api.py."},
    "resolve": {"verdict": "RESOLVED", "summary": "Kept both import blocks; tests pass."},
    "spec_review": {
        "fixed": [{"severity": "high", "title": "Off-by-one in pagination", "commit": "abc1234"}],
        "hard": [{"severity": "blocker", "title": "Race on concurrent save", "file": "src/save.py",
                  "line": 42, "failure_scenario": "Two saves at once lose the first write."}],
        "not_fixed": [{"severity": "low", "title": "Inconsistent log wording"},
                      {"severity": "low", "title": "CI does not run the new tests",
                       "reason": "Out of scope: the spec allows no changes outside src/"}],
        "follow_ups": [{
            "category": "needs-decision", "severity": "medium",
            "title": "Export ignores the user's locale", "file": "src/export.py", "line": None,
            "problem": "Dates in exported CSVs are always US-formatted.",
            "why_separate": "Which locale wins (account or browser) is a product decision the "
                            "spec does not make.",
            "evidence": "Decide: format exports by account locale or by browser locale?",
            "acceptance": ["Exported dates follow the chosen locale"]}],
    },
    "e2e": {
        "verdict": "FAIL",
        "blocked_by": "",
        "acs": [
            {"ticket": 12, "ac": "AC1", "criterion": "A user can export the report as CSV",
             "derived": False, "verdict": "PASS",
             "evidence": "e2e/screenshots/export-ac1.png"},
            {"ticket": 12, "ac": "AC2",
             "criterion": "An empty report cannot be exported and says why",
             "derived": False, "verdict": "FAIL",
             "evidence": "empty report: export stays enabled (e2e/screenshots/export-ac2-empty.png)",
             "cases": [
                 {"case": "empty report: export disabled", "verdict": "FAIL",
                  "evidence": "e2e/screenshots/export-ac2-empty.png"},
                 {"case": "empty report: reason shown", "verdict": "PASS",
                  "evidence": "e2e/screenshots/export-ac2-reason.png"}]},
            {"ticket": 13, "ac": "AC1", "criterion": "The export email reaches the user",
             "derived": True, "verdict": "NOT VERIFIABLE",
             "evidence": "needs the mail provider's sandbox, which E2E.md does not declare"},
        ],
        "fixed": [{"title": "AC1 #12: export button disabled on load", "commit": "abc1234"}],
        "pending": [{"title": "#12 AC2 export of an empty report",
                     "reason": "needs a decision on what an empty export means"},
                    {"title": "#13 AC1 export email", "reason": "no mail sandbox"}],
        "collateral": [{"title": "Console warning on the reports page", "severity": "low",
                        "caused_by_spec": True, "action": "reported",
                        "detail": "React key warning in ReportList"}],
        "follow_ups": [],
        "notes": ["Used the admin test user: E2E.md lists no plain user"],
    },
}


_EXAMPLES["dedup"] = {
    "matches": [
        {"id": "f1", "verdict": "COVERED", "issue": 31,
         "reason": "#31 'Sessions never expire' is the same bug in src/auth/session.py"},
        {"id": "f2", "verdict": "NEW", "issue": None,
         "reason": "searched 'locale', 'export date format', src/export.py: nothing open"},
        {"id": "f3", "verdict": "NEW", "issue": None, "reason": "may overlap #40 (date utils)"},
    ],
    "duplicates": [["f2", "f4"]],
}


def example(name: str) -> str:
    """A JSON example for result ``name`` that passes its own validator."""
    return json.dumps(_EXAMPLES[name])


def validate(name: str, data: Any) -> tuple[dict | None, str | None]:
    return SCHEMAS[name](data)


def read_result(path: str, name: str) -> tuple[dict | None, str | None]:
    """Read and validate the result file at ``path`` against schema ``name``."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return None, f"{path}: result file not found"
    except OSError as e:
        return None, f"{path}: cannot read result file: {e}"
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return None, f"{path}: invalid JSON: {e}"
    value, error = SCHEMAS[name](data)
    if error:
        return None, f"{path}: {error}"
    return value, None
