"""Hashids in web links: /students/xK9aBc2Q instead of /students/46.

The code hides the global numbering only; school_id filtering stays
the protection (the isolation sweep, test_saas002, covers every
`<hid:…>` route). API, superadmin and platform routes keep raw ids."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from isolation_harness import host

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = ("api", "superadmin", "platform")


@pytest.fixture
def happ(app, monkeypatch):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    return app


def _client(app, login_as, bundle, role="admin"):
    c = app.test_client()
    login_as(c, bundle["users"][role], base_url=host(bundle))
    return c


# ─── the converter ──────────────────────────────────────────────────

def test_url_for_builds_a_code_that_decodes_back(happ):
    from flask import url_for
    from app.services.hashid import MIN_LENGTH, decode
    with happ.test_request_context():
        url = url_for("students.student_detail", student_id=46)
    code = url.rsplit("/", 1)[1]
    assert code != "46" and len(code) >= MIN_LENGTH and code.isalnum()
    with happ.app_context():
        assert decode(code) == 46


def test_url_for_works_outside_a_request(happ, monkeypatch):
    """Emails and jobs build links with only an app context."""
    from flask import url_for
    monkeypatch.setitem(happ.config, "SERVER_NAME", "test-a.example.test")
    with happ.app_context():
        url = url_for("students.student_detail", student_id=7, _external=True)
        assert url.startswith("http://test-a.example.test/students/") and not url.endswith("/7")
        assert url_for("students.student_detail", student_id="12") == url_for(
            "students.student_detail", student_id=12)        # digits as a string too


@pytest.mark.parametrize("bad", ["46", "zzzzzzzz", "AAAAAAAAAAAA", "a1b2c3d4e5", "x" * 40])
def test_a_raw_number_or_a_bad_code_is_a_404(happ, two_schools, login_as, bad):
    c = _client(happ, login_as, two_schools["A"])
    r = c.get(f"/students/{bad}", base_url=host(two_schools["A"]))
    assert r.status_code == 404


def test_a_tampered_code_is_a_404_not_a_500(happ, two_schools, login_as):
    from flask import url_for
    A = two_schools["A"]
    with happ.test_request_context():
        url = url_for("students.student_detail", student_id=A["student"].id)
    tampered = url[:-1] + ("A" if url[-1] != "A" else "B")
    r = _client(happ, login_as, A).get(tampered, base_url=host(A))
    assert r.status_code == 404


def test_the_student_page_opens_by_its_code(happ, two_schools, login_as):
    from flask import url_for
    A = two_schools["A"]
    with happ.test_request_context():
        url = url_for("students.student_detail", student_id=A["student"].id)
    r = _client(happ, login_as, A).get(url, base_url=host(A))
    assert r.status_code == 200
    assert A["student"].permanent_code in r.get_data(as_text=True)    # the code on screen is unchanged


def test_school_b_code_on_school_a_shows_nothing(happ, two_schools, login_as):
    from flask import url_for
    A, B = two_schools["A"], two_schools["B"]
    with happ.test_request_context():
        url = url_for("students.student_detail", student_id=B["student"].id)
    r = _client(happ, login_as, A).get(url, base_url=host(A))
    assert r.status_code in (403, 404)
    assert B["student"].permanent_code not in r.get_data(as_text=True)


@pytest.mark.parametrize("endpoint", ["students.students_list", "teachers.teachers_list",
                                      "finance.invoices_list", "hr.employees_list",
                                      "lms.quizzes_home", "academic.sections_list"])
def test_list_pages_link_by_code(happ, world, login_as, endpoint):
    """No link on the list pages carries a raw id in its path."""
    from flask import url_for
    A = world["A"]
    with happ.test_request_context():
        path = url_for(endpoint)
    r = _client(happ, login_as, A).get(path, base_url=host(A), follow_redirects=True)
    assert r.status_code == 200, (path, r.status_code)
    raw = re.findall(r'(?:href|action|src)="(/(?!static|files|api)[^"?#]*/\d+(?:/[^"?#]*)?)"',
                     r.get_data(as_text=True))
    assert not raw, raw


def test_invoice_print_back_link(happ, world, login_as):
    from flask import url_for
    A = world["A"]
    with happ.test_request_context():
        detail = url_for("finance.invoice_detail", invoice_id=A["invoice"])
        printing = url_for("finance.invoice_print", invoice_id=A["invoice"])
    r = _client(happ, login_as, A).get(printing, base_url=host(A))
    assert r.status_code == 200
    assert f'href="{detail}"' in r.get_data(as_text=True)


# ─── the salt ───────────────────────────────────────────────────────

def test_production_refuses_to_boot_without_a_salt():
    from app.config import _resolve_hashids_salt
    key = "k" * 40
    for env in ({}, {"HASHIDS_SALT": "short"}, {"HASHIDS_SALT": key}):
        with pytest.raises(RuntimeError, match="HASHIDS_SALT") as e:
            _resolve_hashids_salt(key, environ=env, app_env="production")
        assert key not in str(e.value)                          # the value is never printed
    ok = "s" * 40
    assert _resolve_hashids_salt(key, environ={"HASHIDS_SALT": ok}, app_env="production") == ok


# ─── by the code ────────────────────────────────────────────────────

def test_no_int_id_route_outside_api_and_platform():
    bad = []
    for f in (ROOT / "app" / "blueprints").rglob("*.py"):
        if f.relative_to(ROOT / "app" / "blueprints").parts[0] in EXCLUDED:
            continue
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if "<int:" in line:
                bad.append(f"{f.relative_to(ROOT)}:{n}")
    assert not bad, bad


def test_no_hand_built_id_path_in_templates():
    """`/x/{{ y.id }}` or `/x/${id}` in a path: build it with url_for
    (or `|hid`) instead."""
    pat = re.compile(r"""(?:href|action|src|fetch\(|location)[^\n]{0,40}['"`]/[a-z][\w/-]*/(?:\{\{[^}]*\bid\b[^}]*\}\}|\$\{[^}]*\bid\b[^}]*\})""")
    bad = []
    for f in (ROOT / "app" / "templates").rglob("*.html"):
        if f.relative_to(ROOT / "app" / "templates").parts[0] in EXCLUDED:
            continue
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if pat.search(line):
                bad.append(f"{f.relative_to(ROOT)}:{n}: {line.strip()[:90]}")
    assert not bad, bad


@pytest.mark.parametrize("role", ["admin", "teacher"])
def test_a_tour_of_the_school_has_no_500_and_no_raw_id_link(happ, world, login_as, role):
    """Follow the site's own links from the dashboard (GET only, every
    module): no page answers 500, and no link carries a raw id in its path."""
    from urllib.parse import urlsplit
    A = world["A"]
    c = _client(happ, login_as, A, role)
    skip = re.compile(r"^/(static|files|api|auth/logout|logout|_support|superadmin|platform)\b"
                      r"|\.(pdf|xlsx|csv|zip|docx)$|/(export|download|print|template)\b")
    href = re.compile(r'href="(/[^"#]*)"')
    adapter = happ.url_map.bind(f"{A['school'].slug}.manasety.ai")
    seen, queue, raw, errors = set(), ["/dashboard"], set(), []
    while queue and len(seen) < 400:
        path = queue.pop(0)
        if path in seen:
            continue
        seen.add(path)
        r = c.get(path, base_url=host(A))
        if r.status_code >= 500:
            errors.append((path, r.status_code))
        if r.status_code != 200 or "text/html" not in (r.content_type or ""):
            continue
        for link in href.findall(r.get_data(as_text=True)):
            p = urlsplit(link).path
            if skip.search(p):
                continue
            if re.search(r"/\d+(/|$)", p) and _takes_a_raw_id(adapter, p):
                raw.add(p)
            if link not in seen:
                queue.append(link)
    assert not errors, errors
    assert not raw, sorted(raw)[:20]
    assert len(seen) > 40, len(seen)                          # the tour went somewhere


def _takes_a_raw_id(adapter, path) -> bool:
    """A number in a path is a raw id only where the matched route takes
    an `<int:…>` (a page named /360 or /2026 is not)."""
    from werkzeug.exceptions import HTTPException
    from werkzeug.routing import IntegerConverter
    try:
        rule, _ = adapter.match(path, return_rule=True)
    except HTTPException:
        return False
    return any(isinstance(c, IntegerConverter) for c in rule._converters.values())
