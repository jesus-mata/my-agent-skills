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
    _enum(d, "status", w, ("implemented", "outward-denied"))
    _str(d, "summary", w)
    _str_list(d, "denied_actions", w)


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

    def not_fixed(e: dict, p: str) -> None:
        _enum(e, "severity", p, ("medium", "low"))
        _str(e, "title", p)
        if "reason" in e:
            _str(e, "reason", p)

    _obj_list(d, "fixed", w, fixed)
    _obj_list(d, "hard", w, hard)
    _obj_list(d, "not_fixed", w, not_fixed)


def _e2e(d: dict, w: str) -> None:
    def fixed(e: dict, p: str) -> None:
        _str(e, "title", p)
        _str(e, "commit", p)

    def pending(e: dict, p: str) -> None:
        _str(e, "title", p)
        _str(e, "reason", p)

    _str_list(d, "passed", w)
    _obj_list(d, "fixed", w, fixed)
    _obj_list(d, "pending", w, pending)


validate_implement = _validator("implement", _implement)
validate_review = _validator("review", _review)
validate_gate_fix = _validator("gate_fix", _gate_fix)
validate_resolve = _validator("resolve", _resolve)
validate_spec_review = _validator("spec_review", _spec_review)
validate_e2e = _validator("e2e", _e2e)

SCHEMAS: dict[str, Validator] = {
    "implement": validate_implement,
    "review": validate_review,
    "gate_fix": validate_gate_fix,
    "resolve": validate_resolve,
    "spec_review": validate_spec_review,
    "e2e": validate_e2e,
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
    },
    "e2e": {
        "passed": ["User can export a report"],
        "fixed": [{"title": "Export button disabled on load", "commit": "abc1234"}],
        "pending": [{"title": "CSV encoding of emoji", "reason": "Needs product decision"}],
    },
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
