"""SAAS-042 — `flask smoke-check`: green against a running app with the
seeded test schools, red (non-zero) when the service is down; read-only."""

from __future__ import annotations

from urllib.error import URLError
from urllib.parse import urlsplit

import pytest

from test_saas041_seed import _backup


class ClientTransport:
    """smoke.Transport on top of the Flask test client (one client = one
    browser session; redirects followed; no real network)."""

    def __init__(self, app, cert_days=200):
        self.app, self.cert_days, self.posts = app, cert_days, []

    def session(self):
        c = self.app.test_client()

        def fetch(method, url, data=None, headers=None):
            from flask import g, has_app_context
            from app.services.smoke import Resp
            if has_app_context():
                # the CLI runner keeps one app context open and Flask-WTF
                # caches the CSRF token in g — real HTTP never shares that
                g.pop("csrf_token", None)
            u = urlsplit(url)
            if method == "POST":
                self.posts.append(u.path)
            r = c.open(u.path + (f"?{u.query}" if u.query else ""), method=method,
                       base_url=f"{u.scheme}://{u.netloc}", data=data, headers=headers or {},
                       follow_redirects=True)
            final = f"{u.scheme}://{u.netloc}{r.request.path}"
            return Resp(r.status_code, final, r.get_data(as_text=True), dict(r.headers))
        return fetch

    def cert_days_left(self, host):
        return self.cert_days


class DeadTransport(ClientTransport):
    def session(self):
        def fetch(*a, **k):
            raise URLError("connection refused")
        return fetch

    def cert_days_left(self, host):
        raise OSError("connection refused")


@pytest.fixture
def seeded(app, monkeypatch, tmp_path):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "PLATFORM_HOSTS", ["console.manasety.ai"])
    acc = tmp_path / "acc.txt"
    res = app.test_cli_runner().invoke(args=["seed-test-schools", "--small", "--backup-file", _backup(tmp_path),
                                             "--accounts-file", str(acc)])
    assert res.exit_code == 0, res.output
    yield app, acc
    from app.extensions import db
    from app.services import test_seed as ts
    with app.app_context():
        ts.teardown()
        db.session.remove()


def _run(app, acc, transport, **kw):
    from app.services import smoke
    return smoke.run(base_url="http://test-a.manasety.ai", console_url="http://console.manasety.ai",
                     school_url="http://test-a.manasety.ai", accounts=smoke.read_accounts(acc),
                     transport=transport, **kw)


def test_green_when_the_app_runs(seeded):
    app, acc = seeded
    t = ClientTransport(app)
    rep = _run(app, acc, t)
    failed = [(r.name, r.detail) for r in rep.results if not r.ok]
    assert rep.ok, failed
    names = " ".join(r.name for r in rep.results)
    for role in ("admin", "teacher", "student", "parent"):
        assert f"login {role}" in names
    assert "health" in names and "console login page" in names and "certificate" in names
    # read-only: the only POSTs are the four logins
    assert t.posts == ["/auth/login"] * 4


def test_red_when_the_service_is_down(seeded):
    app, acc = seeded
    rep = _run(app, acc, DeadTransport(app))
    assert not rep.ok and all(not r.ok for r in rep.results)


def test_red_on_a_short_certificate_or_a_wrong_password(seeded):
    app, acc = seeded
    rep = _run(app, acc, ClientTransport(app, cert_days=5))
    assert not rep.ok and any("certificate" in r.name and not r.ok for r in rep.results)
    text = acc.read_text(encoding="utf-8")
    from app.services import smoke
    accounts = smoke.read_accounts(acc)
    user, pw = accounts["test-a"]["teacher"]
    acc.write_text(text.replace(pw, pw + "x"), encoding="utf-8")
    rep = _run(app, acc, ClientTransport(app))
    assert any(r.name.startswith("login teacher") and not r.ok for r in rep.results)


def test_cli_exit_code(seeded, monkeypatch):
    app, acc = seeded
    from app.services import smoke
    monkeypatch.setattr(smoke, "Transport", lambda timeout=15: DeadTransport(app))
    out = app.test_cli_runner().invoke(args=["smoke-check", "--accounts-file", str(acc)])
    assert out.exit_code != 0 and "FAIL" in out.output and "smoke-check: FAILED" in out.output
    monkeypatch.setattr(smoke, "Transport", lambda timeout=15: ClientTransport(app))
    out = app.test_cli_runner().invoke(args=["smoke-check", "--base-url", "http://test-a.manasety.ai",
                                             "--console-url", "http://console.manasety.ai",
                                             "--school-url", "http://test-a.manasety.ai",
                                             "--accounts-file", str(acc)])
    assert out.exit_code == 0, out.output
    assert "smoke-check: all green" in out.output and out.output.count("PASS") >= 7
