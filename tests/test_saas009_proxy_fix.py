"""SAAS-009 — client IP and scheme behind nginx (ProxyFix, flag-gated)."""

from __future__ import annotations

import pytest

from isolation_harness import host


@pytest.fixture
def proxied(app, monkeypatch):
    """The app as production will run it with TRUST_PROXY_HEADERS=true."""
    from app import install_proxy_fix
    original = app.wsgi_app
    monkeypatch.setitem(app.config, "TRUST_PROXY_HEADERS", True)
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    install_proxy_fix(app)
    yield app
    app.wsgi_app = original


def _probe(app, base, headers=None):
    with app.test_client() as c:
        return c.get("/__probe/request", base_url=base, headers=headers or {}).get_json()


def test_flag_on_reads_client_ip(proxied, two_schools):
    got = _probe(proxied, host(two_schools["A"]), {"X-Forwarded-For": "203.0.113.9"})
    assert got["remote_addr"] == "203.0.113.9"


def test_only_the_last_hop_is_trusted(proxied, two_schools):
    """nginx appends the real peer; anything the client sent comes first."""
    got = _probe(proxied, host(two_schools["A"]),
                 {"X-Forwarded-For": "6.6.6.6, 203.0.113.9"})
    assert got["remote_addr"] == "203.0.113.9"


def test_forwarded_proto_sets_https(proxied, two_schools):
    got = _probe(proxied, host(two_schools["A"]), {"X-Forwarded-Proto": "https"})
    assert got["scheme"] == "https"
    assert got["url_root"].startswith("https://alpha.manasety.ai")


def test_forged_forwarded_host_changes_neither_host_nor_tenant(proxied, two_schools):
    got = _probe(proxied, host(two_schools["A"]), {"X-Forwarded-Host": "beta.manasety.ai"})
    assert got["host"] == "alpha.manasety.ai"
    assert got["tenant"] == "alpha"


def test_flag_off_ignores_the_headers(app, two_schools, monkeypatch):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    got = _probe(app, host(two_schools["A"]),
                 {"X-Forwarded-For": "203.0.113.9", "X-Forwarded-Proto": "https"})
    assert got["remote_addr"] != "203.0.113.9"
    assert got["scheme"] == "http"


def test_flag_defaults_off(monkeypatch):
    import importlib
    import sys
    monkeypatch.delenv("TRUST_PROXY_HEADERS", raising=False)
    sys.modules.pop("app.config", None)
    cfg = importlib.import_module("app.config")
    assert cfg.Config.TRUST_PROXY_HEADERS is False
    sys.modules.pop("app.config", None)


def test_audit_row_records_client_ip(proxied, two_schools):
    """A watched-model change made through the app logs the real IP."""
    from app.extensions import db
    from app.models import AuditLog
    A = two_schools["A"]
    with proxied.test_client() as c:
        r = c.post("/auth/login", base_url=host(A),
                   data={"username": "t_alpha", "password": "test-password-12345"},
                   headers={"X-Forwarded-For": "6.6.6.6, 198.51.100.7"})
        assert r.status_code in (200, 302)
    with proxied.app_context():
        row = (AuditLog.query.filter_by(entity_type="User", entity_id=A["users"]["teacher"].id)
               .order_by(AuditLog.id.desc()).first())
        assert row is not None and row.ip_address == "198.51.100.7"
        db.session.remove()


def test_pdf_fetcher_serves_static_from_disk(app, two_schools):
    """With https host_url the PDF no longer depends on the server reaching
    itself; static files come from disk, uploads never do."""
    from pathlib import Path
    from app.services.file_storage import _static_file
    with app.test_request_context(base_url="https://alpha.manasety.ai"):
        css = next(Path(app.static_folder).rglob("*.css"))
        rel = css.relative_to(app.static_folder).as_posix()
        assert _static_file(f"/static/{rel}") == css.resolve()
        assert _static_file("/static/uploads/x.png") is None
        assert _static_file("/static/../config.py") is None
        assert _static_file("/elsewhere/x.css") is None
