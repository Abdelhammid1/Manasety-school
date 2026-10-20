"""SAAS-012 — shared machinery for the route-isolation matrix.

A matrix `Entry` says how to attack one endpoint from school A with
school B's ids. `check_blocked()` runs one attack and fails loudly
(never skips) when isolation is missing:

  * status must be 403 or 404,
  * none of B's marker strings may appear in the response body,
  * for writes, B's snapshot must be identical before and after.

URLs are built from `rule.arguments`, so a fetcher that returns the
wrong param names is a test failure, not a silent skip.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

BLOCKED = (403, 404)


def host(bundle: dict) -> str:
    return f"http://{bundle['school'].slug}.manasety.ai"


@dataclass(frozen=True)
class Entry:
    """One endpoint in the isolation matrix.

    ids:      B -> {url_param: id}. Must cover every <param> of the rule.
    methods:  methods to attack with (each is tested separately).
    form:     (A, B) -> form payload for POST (optional).
    roles:    school-A roles to attack as.
    snapshot: B -> comparable state of B's record; read before/after a
              write and must not change. Runs inside an app context.
    mixed:    (A, B) -> {url_param: id} mixing A and B ids (multi-id rules).
    skip:     explicit written reason; empty means the entry runs.
    """
    ids: Callable[[dict], dict[str, int]]
    methods: tuple[str, ...] = ("GET",)
    form: Optional[Callable[[dict, dict], dict]] = None
    roles: tuple[str, ...] = ("admin",)
    snapshot: Optional[Callable[[dict], Any]] = None
    mixed: Optional[Callable[[dict, dict], dict[str, int]]] = None
    skip: str = ""


class HarnessError(AssertionError):
    """The matrix itself is wrong (bad params, unknown endpoint)."""


def rule_for(app, endpoint: str):
    rules = [r for r in app.url_map.iter_rules() if r.endpoint == endpoint]
    if not rules:
        raise HarnessError(f"{endpoint}: no such endpoint in url_map")
    # Prefer the rule with the most arguments (the id-bearing one).
    return max(rules, key=lambda r: len(r.arguments))


def build_url(app, endpoint: str, params: dict[str, Any], base_url: str) -> str:
    from flask import url_for
    rule = rule_for(app, endpoint)
    want, got = set(rule.arguments), set(params)
    if want != got:
        raise HarnessError(
            f"{endpoint}: id fetcher returned params {sorted(got)} but "
            f"{rule.rule} needs {sorted(want)}"
        )
    with app.test_request_context(base_url=base_url):
        return url_for(endpoint, **params)


def _snap(app, entry: Entry, B: dict):
    if entry.snapshot is None:
        return None
    from app.extensions import db
    with app.app_context():
        try:
            return entry.snapshot(B)
        finally:
            db.session.remove()


def check_blocked(app, client, endpoint: str, entry: Entry, method: str,
                  url: str, A: dict, B: dict) -> None:
    """Fire one cross-tenant request and assert it was refused."""
    before = _snap(app, entry, B)
    data = entry.form(A, B) if (entry.form and method != "GET") else None
    resp = client.open(url, method=method, data=data, base_url=host(A))
    body = resp.get_data(as_text=True)
    leaked = [m for m in B["markers"] if m in body]
    after = _snap(app, entry, B)

    problems = []
    if resp.status_code not in BLOCKED:
        problems.append(f"status {resp.status_code} (expected 403/404)")
    if leaked:
        problems.append(f"school B data in body: {leaked}")
    if before != after:
        problems.append(f"school B record changed: {before!r} -> {after!r}")
    assert not problems, (
        f"ISOLATION GAP {method} {endpoint} {url} as A — "
        + "; ".join(problems)
    )


def ticket_for(endpoint: str) -> str:
    """Which SAAS isolation ticket owns an endpoint still pending."""
    bp = endpoint.split(".", 1)[0]
    if bp in ("finance", "hr"):
        return "SAAS-013"
    if bp in ("students", "attendance", "portal"):
        return "SAAS-014"
    if bp == "lms":
        return "SAAS-016" if endpoint in LMS_STUDENT_ENDPOINTS else "SAAS-015"
    if bp == "courses":
        return "SAAS-016"
    if bp == "api":
        return "SAAS-017"
    return "SAAS-018"


LMS_STUDENT_ENDPOINTS = frozenset({
    "lms.assignment_submit", "lms.attempt_autosave", "lms.attempt_flag",
    "lms.attempt_tab_switch", "lms.quiz_result", "lms.quiz_submit",
    "lms.quiz_take",
})
