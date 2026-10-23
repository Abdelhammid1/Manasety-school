"""SEC-05 — every response of the school app carries the baseline
security headers (nosniff, SAMEORIGIN, Referrer-Policy), once each; the
console keeps its stronger set (CSP, DENY, no-store)."""

from __future__ import annotations

import io

import pytest
from werkzeug.datastructures import FileStorage

from isolation_harness import host

BASELINE = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "same-origin",
}
CONSOLE = "http://console.manasety.ai"
PDF = b"%PDF-1.4\n%sec05\n"


@pytest.fixture
def sapp(app, monkeypatch, tmp_path):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "PLATFORM_HOSTS", ["console.manasety.ai"])
    monkeypatch.setitem(app.config, "UPLOAD_ROOT", str(tmp_path / "uploads"))
    return app


def _baseline_once(r):
    for name, value in BASELINE.items():
        assert r.headers.getlist(name) == [value], (name, r.headers.getlist(name))


def test_login_page(sapp, two_schools):
    for key in ("A", "B"):
        r = sapp.test_client().get("/auth/login", base_url=host(two_schools[key]))
        assert r.status_code == 200
        _baseline_once(r)


def test_inner_page_after_login(sapp, two_schools, login_as):
    A = two_schools["A"]
    c = sapp.test_client()
    login_as(c, A["users"]["admin"], base_url=host(A))
    r = c.get("/dashboard", base_url=host(A))
    assert r.status_code == 200
    _baseline_once(r)


def test_not_found_static_and_json(sapp, two_schools, login_as):
    A = two_schools["A"]
    c = sapp.test_client()
    r = c.get("/no-such-page-sec05", base_url=host(A))
    assert r.status_code == 404
    _baseline_once(r)
    r = c.get("/static/css/app.css", base_url=host(A))
    assert r.status_code == 200
    _baseline_once(r)
    login_as(c, A["users"]["admin"], base_url=host(A))
    r = c.get("/search.json", query_string={"q": "zz"}, base_url=host(A))
    assert r.is_json
    _baseline_once(r)


def test_a_stored_file_has_nosniff_once(sapp, two_schools, login_as):
    from app.services import file_storage as fs
    from app.services.tenancy import tenant_context
    A = two_schools["A"]
    with sapp.app_context(), tenant_context(A["school"].id):
        url = fs.save(FileStorage(stream=io.BytesIO(PDF), filename="d.pdf"),
                      "student_docs", A["student"].id)
    c = sapp.test_client()
    login_as(c, A["users"]["admin"], base_url=host(A))
    r = c.get(url, base_url=host(A))
    assert r.status_code == 200
    _baseline_once(r)


def test_console_keeps_its_stronger_headers(sapp):
    r = sapp.test_client().get("/superadmin/login", base_url=CONSOLE)
    assert r.status_code == 200
    assert r.headers.getlist("X-Frame-Options") == ["DENY"]
    assert r.headers.getlist("Cache-Control") == ["no-store"]
    csp = r.headers.getlist("Content-Security-Policy")
    assert len(csp) == 1 and "frame-ancestors 'none'" in csp[0]
    assert r.headers.getlist("X-Content-Type-Options") == ["nosniff"]
    assert r.headers.getlist("Referrer-Policy") == ["same-origin"]
