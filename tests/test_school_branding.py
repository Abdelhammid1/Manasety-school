"""School Branding: a school's logo, name and primary colour on its own
pages only; a school without them looks exactly as before."""

from __future__ import annotations

import io
import re

import pytest
from PIL import Image

from isolation_harness import host

DEFAULT_TOKENS = ("rgb(var(--c-primary, 0 35 111) / <alpha-value>)",
                  "rgb(var(--c-primary-container, 30 58 138) / <alpha-value>)",
                  "rgb(var(--c-navy, 12 36 97) / <alpha-value>)",
                  "rgb(var(--c-secondary, 0 81 213) / <alpha-value>)")


@pytest.fixture
def bapp(app, monkeypatch, tmp_path):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setitem(app.config, "UPLOAD_ROOT", str(tmp_path / "uploads"))
    return app


def _png(w=120, h=60, color=(200, 30, 60), fmt="PNG") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, fmt)
    return buf.getvalue()


def _admin(app, login_as, bundle, role="admin"):
    c = app.test_client()
    login_as(c, bundle["users"][role], base_url=host(bundle))
    return c


def _school(app, sid):
    from app.extensions import db
    from app.models import School
    with app.app_context():
        s = db.session.get(School, sid)
        out = {"logo_url": s.logo_url, "primary_color": s.primary_color}
        db.session.remove()
    return out


def _save(c, bundle, data=None, file=None, name="logo.png"):
    form = {"name": bundle["school"].name, **(data or {})}
    if file is not None:
        form["logo_file"] = (io.BytesIO(file), name)
    return c.post("/admin/settings", base_url=host(bundle), data=form,
                  content_type="multipart/form-data", follow_redirects=True)


# ─── no branding: exactly as before ─────────────────────────────────

def test_a_school_without_branding_looks_the_same(bapp, two_schools, login_as):
    A = two_schools["A"]
    page = _admin(bapp, login_as, A).get("/dashboard", base_url=host(A)).get_data(as_text=True)
    for token in DEFAULT_TOKENS:
        assert token in page, token
    assert 'id="school-theme"' not in page
    assert "— منصتي</title>" in page and 'image/svg+xml' in page and "img/logo.svg" in page
    assert "var(--brand-gradient, linear-gradient(135deg, #1E3A8A 0%, #2563EB 55%, #0099CC 100%))" in page


# ─── the logo ───────────────────────────────────────────────────────

def test_a_logo_shows_on_the_schools_pages_and_login_and_only_there(bapp, two_schools, login_as):
    A, B = two_schools["A"], two_schools["B"]
    c = _admin(bapp, login_as, A)
    r = _save(c, A, file=_png())
    assert r.status_code == 200
    url = _school(bapp, A["school"].id)["logo_url"]
    assert url and url.startswith(f"/files/{A['school'].id}/logo/")
    page = c.get("/dashboard", base_url=host(A)).get_data(as_text=True)
    assert re.search(r'src="/branding/logo\?v=[0-9a-f]{10}"', page)
    assert A["school"].name in page and f"— {A['school'].name}</title>" in page
    assert 'type="image/svg+xml"' not in page                          # the SVG icon is gone
    # a visitor on A's login sees A's logo; the endpoint serves it without login
    anon = bapp.test_client()
    login_page = anon.get("/auth/login", base_url=host(A)).get_data(as_text=True)
    assert "/branding/logo?v=" in login_page
    r = anon.get("/branding/logo", base_url=host(A))
    assert r.status_code == 200 and r.mimetype == "image/png" and r.data[:8] == b"\x89PNG\r\n\x1a\n"
    assert r.headers["X-Content-Type-Options"] == "nosniff" and "sandbox" in r.headers["Content-Security-Policy"]
    # B's host: the platform logo, nothing of A
    rb = anon.get("/branding/logo", base_url=host(B))
    assert rb.mimetype == "image/svg+xml"
    assert "/branding/logo?v=" not in anon.get("/auth/login", base_url=host(B)).get_data(as_text=True)


def test_replacing_the_logo_deletes_the_old_file_and_changes_the_version(bapp, two_schools, login_as):
    from pathlib import Path
    A = two_schools["A"]
    c = _admin(bapp, login_as, A)
    _save(c, A, file=_png(color=(10, 10, 10)))
    first = _school(bapp, A["school"].id)["logo_url"]
    root = Path(bapp.config["UPLOAD_ROOT"])
    assert (root / first[len("/files/"):]).exists()
    _save(c, A, file=_png(color=(250, 250, 0)))
    second = _school(bapp, A["school"].id)["logo_url"]
    assert second != first and not (root / first[len("/files/"):]).exists()
    _save(c, A, data={"remove_logo": "1"})
    assert _school(bapp, A["school"].id)["logo_url"] is None
    assert not (root / second[len("/files/"):]).exists()
    page = c.get("/dashboard", base_url=host(A)).get_data(as_text=True)
    assert "img/logo.svg" in page and "/branding/logo?v=" not in page


@pytest.mark.parametrize("data,name,message", [
    (b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', "logo.svg", "غير مدعومة"),
    (b"not an image at all, just text....", "logo.png", None),
    (_png(2100, 50), "logo.png", "2000"),
])
def test_bad_logos_are_refused_and_the_current_one_stays(bapp, two_schools, login_as, data, name, message):
    A = two_schools["A"]
    c = _admin(bapp, login_as, A)
    _save(c, A, file=_png())
    before = _school(bapp, A["school"].id)["logo_url"]
    body = _save(c, A, file=data, name=name).get_data(as_text=True)
    assert "ملف الشعار" in body and (message is None or message in body)
    assert _school(bapp, A["school"].id)["logo_url"] == before


def test_a_logo_over_2mb_is_refused(bapp, two_schools, login_as):
    import os
    A = two_schools["A"]
    big = b"\x89PNG\r\n\x1a\n" + os.urandom(2 * 1024 * 1024 + 10)
    body = _save(_admin(bapp, login_as, A), A, file=big).get_data(as_text=True)
    assert "يتجاوز 2 MB" in body and _school(bapp, A["school"].id)["logo_url"] is None


# ─── the colour ─────────────────────────────────────────────────────

def test_a_colour_themes_the_school_and_only_it(bapp, two_schools, login_as):
    A, B = two_schools["A"], two_schools["B"]
    c = _admin(bapp, login_as, A)
    _save(c, A, data={"primary_color": "#0f766e"})
    assert _school(bapp, A["school"].id)["primary_color"] == "#0F766E"
    page = c.get("/dashboard", base_url=host(A)).get_data(as_text=True)
    theme = re.search(r'<style id="school-theme">(.*?)</style>', page).group(1)
    assert "--c-primary-container:15 118 110" in theme and "--brand-gradient:linear-gradient" in theme
    for token in DEFAULT_TOKENS:                                       # still /<alpha-value> tokens
        assert token in page
    other = _admin(bapp, login_as, B).get("/dashboard", base_url=host(B)).get_data(as_text=True)
    assert 'id="school-theme"' not in other


def test_a_light_colour_is_darkened_and_text_stays_readable():
    from app.services.branding import MIN_CONTRAST, contrast_with_white, palette, readable, was_darkened
    for c in ("#FFE600", "#A3E635", "#FFFFFF", "#E11D48", "#111111"):
        p = palette(c)
        for key in ("primary", "primary-container", "secondary", "on-primary-fixed-variant",
                    "on-secondary-fixed-variant", "gradient-mid", "gradient-end"):
            assert contrast_with_white(p[key]) >= MIN_CONTRAST, (c, key, p[key])
    assert was_darkened("#FFE600") and readable("#FFE600") != "#FFE600"
    assert not was_darkened("#1E3A8A")


def test_the_settings_page_says_when_the_colour_was_darkened(bapp, two_schools, login_as):
    A = two_schools["A"]
    c = _admin(bapp, login_as, A)
    _save(c, A, data={"primary_color": "#FFE600"})
    page = c.get("/admin/settings", base_url=host(A)).get_data(as_text=True)
    assert "تم تغميق اللون لضمان وضوح النصوص" in page


@pytest.mark.parametrize("bad", ["red", "#12345", "#1234567", "#GGGGGG", "#123456;}body{x:y", "url(x)"])
def test_anything_but_a_hex_colour_is_refused(bapp, two_schools, login_as, bad):
    A = two_schools["A"]
    c = _admin(bapp, login_as, A)
    _save(c, A, data={"primary_color": "#123456"})
    body = _save(c, A, data={"primary_color": bad}).get_data(as_text=True)
    assert "#RRGGBB" in body and _school(bapp, A["school"].id)["primary_color"] == "#123456"
    from app.services.branding import theme_css
    assert theme_css(bad) == ""                                       # never reaches a page either


def test_restoring_the_default_colour(bapp, two_schools, login_as):
    A = two_schools["A"]
    c = _admin(bapp, login_as, A)
    _save(c, A, data={"primary_color": "#0F766E"})
    _save(c, A, data={"primary_color": "#0F766E", "reset_color": "1"})
    assert _school(bapp, A["school"].id)["primary_color"] is None
    # a save that doesn't post the field leaves it alone
    _save(c, A, data={"primary_color": "#0F766E"})
    _save(c, A, data={})
    assert _school(bapp, A["school"].id)["primary_color"] == "#0F766E"


# ─── permission, console, prints, backup ────────────────────────────

def test_without_users_edit_saving_is_refused(bapp, two_schools, login_as):
    from app.extensions import db
    from app.models import Role
    A = two_schools["A"]
    with bapp.app_context():
        role = db.session.get(Role, A["roles"]["teacher"].id)
        perms = dict(role.permissions or {})
        perms.pop("users", None)
        role.permissions = perms
        db.session.commit(); db.session.remove()
    c = _admin(bapp, login_as, A, role="teacher")
    r = c.post("/admin/settings", base_url=host(A), data={"name": "x", "primary_color": "#0F766E"})
    assert r.status_code == 403 and _school(bapp, A["school"].id)["primary_color"] is None


def test_the_console_keeps_its_own_identity(bapp, two_schools, login_as, monkeypatch):
    monkeypatch.setitem(bapp.config, "PLATFORM_HOSTS", ["console.manasety.ai"])
    A = two_schools["A"]
    _save(_admin(bapp, login_as, A), A, data={"primary_color": "#0F766E"}, file=_png())
    page = bapp.test_client().get("/superadmin/login", base_url="http://console.manasety.ai").get_data(as_text=True)
    assert "school-theme" not in page and "/branding/logo" not in page


def test_prints_show_the_logo_only_when_asked(bapp, world, login_as):
    from flask import url_for
    A = world["A"]
    c = _admin(bapp, login_as, A)
    _save(c, A, file=_png(), data={"show_logo_on_prints": "1"})
    logo = _school(bapp, A["school"].id)["logo_url"]
    with bapp.test_request_context():
        printing = url_for("finance.invoice_print", invoice_id=A["invoice"])
    assert f'src="{logo}"' in c.get(printing, base_url=host(A)).get_data(as_text=True)
    _save(c, A, data={})                                              # the checkbox off
    assert f'src="{logo}"' not in c.get(printing, base_url=host(A)).get_data(as_text=True)


def test_backup_restore_and_purge_know_the_colour():
    from app.services.school_backup import SCHOOL_ROW_RESTORABLE
    from app.services.school_purge import WIPE_FIELDS
    assert "primary_color" in SCHOOL_ROW_RESTORABLE and "primary_color" in WIPE_FIELDS
