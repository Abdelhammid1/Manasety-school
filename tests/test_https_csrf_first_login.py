"""Regression for server fixes 9c373d5 / 01853cb (2026-10-21), which CI
missed:

1. `Referrer-Policy: no-referrer` made Flask-WTF refuse every HTTPS POST
   ("The referrer header is missing"): over HTTPS, WTF_CSRF_SSL_STRICT
   requires a same-origin Referer, and that policy tells the browser
   never to send one. The tests ran on http:// with CSRF off, so nobody
   saw it.
2. `qr_svg()` wrote bytes into a StringIO (segno 1.6.6) → the TOTP setup
   page was a 500. The old test only looked for "<svg" in the body, which
   the 500 page also contains.

Here everything runs over https:// with CSRF ON, and the test never
types a Referer: a small browser stand-in derives it from the
Referrer-Policy of the page that served the form, the way a browser
does. A policy that strips it makes the POST fail again, so the
regression can't come back.
"""

from __future__ import annotations

import re
import time
from urllib.parse import urlsplit

import pyotp
import pytest

from test_saas025_platform import papp, puser  # noqa: F401  (fixtures)

CONSOLE = "https://console.manasety.ai"
SCHOOL_A = "https://alpha.manasety.ai"
# What a browser does with the Referer of a same-origin form POST, per
# policy (https → https, same origin). Absent header = the browser
# default, strict-origin-when-cross-origin.
_SAME_ORIGIN_REFERER = {
    "no-referrer": None,
    "same-origin": "url",
    "origin": "origin",
    "strict-origin": "origin",
    "origin-when-cross-origin": "url",
    "strict-origin-when-cross-origin": "url",
    "no-referrer-when-downgrade": "url",
    "unsafe-url": "url",
}


class Browser:
    """test_client + the two browser behaviours CSRF depends on: it posts
    the form's csrf_token, and sends the Referer the serving page's
    Referrer-Policy allows. Nothing is set by hand."""

    def __init__(self, app, base):
        self.c = app.test_client()
        self.base = base
        self.page = None          # (url, response) of the last page shown

    def get(self, path, follow=True):
        r = self.c.get(path, base_url=self.base)
        hops = 0
        while follow and r.status_code in (301, 302, 303) and hops < 5:
            loc = urlsplit(r.headers["Location"])
            path = loc.path + (f"?{loc.query}" if loc.query else "")
            r = self.c.get(path, base_url=self.base)
            hops += 1
        self.page = (self.base + path, r)
        return r

    def submit(self, data):
        url, page = self.page
        html = page.get_data(as_text=True)
        m = re.search(r'name="csrf_token" value="([^"]+)"', html)
        assert m, "the page has no CSRF field"
        form = {"csrf_token": m.group(1), **data}
        policy = (page.headers.get("Referrer-Policy") or "strict-origin-when-cross-origin").split(",")[-1].strip()
        kind = _SAME_ORIGIN_REFERER[policy]
        headers = {}
        if kind == "url":
            headers["Referer"] = url
        elif kind == "origin":
            headers["Referer"] = self.base + "/"
        return self.c.post(urlsplit(url).path, base_url=self.base, data=form, headers=headers)


@pytest.fixture
def happ(papp, monkeypatch):
    monkeypatch.setitem(papp.config, "WTF_CSRF_ENABLED", True)       # the real setting
    monkeypatch.setitem(papp.config, "WTF_CSRF_SSL_STRICT", True)
    return papp


def _assert_csrf_ok(r):
    body = r.get_data(as_text=True)
    assert "referrer" not in body.lower() and "CSRF" not in body, body[:300]
    assert r.status_code != 400, body[:300]


def test_console_first_login_over_https(happ, puser):
    """CLI-created user: password → TOTP setup with a real QR → recovery
    codes → forced password change → console. Every POST is a real CSRF
    check over HTTPS."""
    from app.extensions import db
    from app.models import PlatformUser
    from app.services import platform_auth as pa
    import segno
    info = puser(totp=False, changed=False)
    b = Browser(happ, CONSOLE)

    assert b.get("/superadmin/login").status_code == 200
    r = b.submit({"email": info["email"], "password": info["password"]})
    _assert_csrf_ok(r)
    assert r.status_code == 302 and r.headers["Location"].endswith("/superadmin/login/totp/setup")

    page = b.get("/superadmin/login/totp/setup")
    assert page.status_code == 200                       # 01853cb: this was a 500
    with happ.app_context():
        secret = pa.decrypt(db.session.get(PlatformUser, info["id"]).totp_secret_encrypted)
        db.session.remove()
    expected_qr = segno.make(pa.provisioning_uri(secret, info["email"]), error="m").svg_inline(scale=5, border=2)
    html = page.get_data(as_text=True)
    assert expected_qr in html                           # the real QR for this user's secret
    assert secret in html                                # and the manual key

    totp = pyotp.TOTP(secret)
    r = b.submit({"code": totp.now()})
    _assert_csrf_ok(r)
    assert r.status_code == 200
    codes = re.findall(r"<div>([0-9a-f]{6}-[0-9a-f]{6})</div>", r.get_data(as_text=True))
    assert len(codes) == 10

    # CLI-created → the password must be changed before anything else
    r = b.get("/superadmin/schools")
    assert b.page[0].endswith("/superadmin/password") and r.status_code == 200
    new = "a-brand-new-console-pass-77"
    # the setup code's time step is used; the next step is accepted (±1)
    r = b.submit({"current_password": info["password"], "new_password": new, "confirm_password": new,
                  "code": totp.at(int(time.time()) + totp.interval)})
    _assert_csrf_ok(r)
    assert r.status_code == 302 and r.headers["Location"].endswith("/superadmin/schools")
    assert b.get("/superadmin/schools").status_code == 200


def test_https_post_without_any_referer_is_still_refused(happ, puser):
    """The other half: CSRF over HTTPS really does need the Referer (so
    the test above proves the policy lets it through)."""
    info = puser()
    b = Browser(happ, CONSOLE)
    page = b.get("/superadmin/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.get_data(as_text=True)).group(1)
    r = b.c.post("/superadmin/login", base_url=CONSOLE,
                 data={"csrf_token": token, "email": info["email"], "password": info["password"]})
    assert r.status_code == 400


@pytest.mark.parametrize("path", ["/superadmin/login", "/superadmin/login/totp/setup"])
def test_console_forms_never_ship_no_referrer(happ, puser, path):
    info = puser(totp=False)
    b = Browser(happ, CONSOLE)
    if path != "/superadmin/login":
        b.get("/superadmin/login")
        b.submit({"email": info["email"], "password": info["password"]})
    r = b.get(path)
    assert r.status_code == 200
    assert "no-referrer" not in (r.headers.get("Referrer-Policy") or "")


def test_school_admin_set_password_over_https(happ, two_schools):
    """The provisioned admin's one-time link on the school's own host:
    GET /set-password/<token> → clean URL → POST, CSRF on, over HTTPS."""
    import secrets as _secrets
    from datetime import datetime, timedelta
    from app.extensions import db
    from app.models import AccountSetupToken, User
    from app.services.provisioning import hash_token
    A = two_schools["A"]
    raw = _secrets.token_urlsafe(32)
    with happ.app_context():
        admin = db.session.get(User, A["users"]["admin"].id)
        old_hash = admin.password_hash
        db.session.add(AccountSetupToken(user_id=admin.id, token_hash=hash_token(raw),
                                         expires_at=datetime.utcnow() + timedelta(hours=1)))
        db.session.commit()
        db.session.remove()
    try:
        b = Browser(happ, SCHOOL_A)
        r = b.get(f"/set-password/{raw}")
        assert r.status_code == 200 and b.page[0] == SCHOOL_A + "/set-password"   # token left the URL
        assert "no-referrer" not in (r.headers.get("Referrer-Policy") or "")
        pw = "school-admin-new-pass-55"
        r = b.submit({"password": pw, "confirm": pw})
        _assert_csrf_ok(r)
        assert r.status_code == 302 and "/auth/login" in r.headers["Location"]
        with happ.app_context():
            admin = db.session.get(User, A["users"]["admin"].id)
            assert admin.check_password(pw)
            admin.password_hash = old_hash          # the shared fixture keeps its password
            db.session.commit()
            db.session.remove()
    finally:
        with happ.app_context():
            AccountSetupToken.query.filter_by(user_id=A["users"]["admin"].id).delete()
            db.session.commit()
            db.session.remove()


def test_console_500_is_its_own_self_contained_page(happ, puser, monkeypatch):
    """A crash inside the console shows the console's own page: no CDN,
    no outside fonts or icon font (the CSP blocks them), still under the
    console CSP, nothing from the failure in the body."""
    from test_saas026_subscriptions import _console_client
    monkeypatch.setitem(happ.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setitem(happ.config, "PROPAGATE_EXCEPTIONS", False)
    c, _ = _console_client(happ, "owner")

    def boom():
        raise RuntimeError("secret-internal-detail")
    monkeypatch.setitem(happ.view_functions, "superadmin.alerts", boom)
    r = c.get("/superadmin/alerts", base_url="http://console.manasety.ai")
    assert r.status_code == 500
    html = r.get_data(as_text=True)
    assert "حصل خطأ" in html and "secret-internal-detail" not in html
    assert not re.search(r'(?:src|href)="https?://', html), "external resource on the console error page"
    assert "material-symbols" not in html.lower() and "fonts.googleapis" not in html
    csp = r.headers.get("Content-Security-Policy") or ""
    assert "default-src 'self'" in csp


def test_console_403_uses_the_console_page(happ, monkeypatch):
    from test_saas026_subscriptions import _console_client
    monkeypatch.setitem(happ.config, "WTF_CSRF_ENABLED", False)
    c, _ = _console_client(happ, "support")
    r = c.get("/superadmin/users", base_url="http://console.manasety.ai")    # owner only
    assert r.status_code == 403
    html = r.get_data(as_text=True)
    assert "غير مسموح" in html and "fonts.googleapis" not in html
