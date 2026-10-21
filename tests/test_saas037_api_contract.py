"""SAAS-037 — the mobile contract on the backend: public school-info /
app-config, the error-code contract (exact shapes, one line each in
docs/api-error-codes.md), upgrade_required, the console app card and
app settings. Two schools: A's state never shows on B."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from isolation_harness import host
from test_saas026_subscriptions import CONSOLE, _console_client, console  # noqa: F401
from test_saas027_enforcement import _bearer, set_state

DOC = Path(__file__).resolve().parents[1] / "docs" / "api-error-codes.md"
INFO_KEYS = {"name_ar", "logo_url", "state", "reason", "message_ar", "api_version", "support"}
SUPPORT_KEYS = {"email", "phone"}


@pytest.fixture
def papp(app, monkeypatch):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    from app.blueprints.api import public
    public._hits.clear()
    yield app
    public._hits.clear()


def _settings(app, **values):
    from app.extensions import db
    from app.models import PlatformSetting
    with app.app_context():
        for k, v in values.items():
            row = db.session.get(PlatformSetting, k)
            if v is None:
                if row is not None:
                    db.session.delete(row)
                continue
            row = row or PlatformSetting(key=k)
            row.value = v
            db.session.add(row)
        db.session.commit()
        db.session.remove()


@pytest.fixture(autouse=True)
def _restore(app, two_schools):
    yield
    from app.extensions import db
    from app.models import PlatformSetting, School, SchoolSlugHistory
    with app.app_context():
        for key, slug in (("A", "alpha"), ("B", "beta")):
            s = db.session.get(School, two_schools[key]["school"].id)
            s.status, s.is_active, s.slug, s.logo_url = "active", True, slug, None
        SchoolSlugHistory.query.delete()
        PlatformSetting.query.filter(PlatformSetting.key.like("min_app_version_%")).delete(
            synchronize_session=False)
        for k in ("app_download_url", "support_email", "support_phone"):
            PlatformSetting.query.filter_by(key=k).delete()
        db.session.commit()
        db.session.remove()
    for key in ("A", "B"):
        set_state(app, two_schools[key]["school"].id, "active")


def _info(app, bundle_or_host):
    h = bundle_or_host if isinstance(bundle_or_host, str) else host(bundle_or_host)
    return app.test_client().get("/api/public/school-info", base_url=h)


# ─── school-info ─────────────────────────────────────────────────────

def test_school_info_ok_is_whitelisted(papp, two_schools):
    _settings(papp, support_email="help@manasety.test", support_phone="+20 100")
    r = _info(papp, two_schools["A"])
    assert r.status_code == 200 and r.headers["Cache-Control"] == "no-store"
    body = r.json
    assert set(body) == INFO_KEYS and set(body["support"]) == SUPPORT_KEYS
    assert body["name_ar"] == two_schools["A"]["school"].name
    assert (body["state"], body["reason"], body["message_ar"]) == ("ok", None, "")
    assert body["api_version"] == "1" and body["logo_url"] is None
    assert body["support"] == {"email": "help@manasety.test", "phone": "+20 100"}
    # nothing personal or countable: no user's username / email anywhere
    text = r.get_data(as_text=True)
    for u in two_schools["A"]["users"].values():
        assert u.username not in text and (not u.email or u.email not in text)


@pytest.mark.parametrize("h", ["http://nowhere.manasety.ai", CONSOLE])
def test_school_info_unknown_or_platform_host_is_404(papp, h):
    assert _info(papp, h).status_code == 404


def test_school_info_archived_or_resolution_off_is_404(papp, two_schools, monkeypatch):
    from app.extensions import db
    from app.models import School
    A = two_schools["A"]
    with papp.app_context():
        s = db.session.get(School, A["school"].id)
        s.status, s.is_active = "archived", False
        db.session.commit()
        db.session.remove()
    assert _info(papp, A).status_code == 404
    monkeypatch.setitem(papp.config, "TENANT_RESOLUTION_MODE", "off")
    assert _info(papp, two_schools["B"]).status_code == 404


@pytest.mark.parametrize("state,expected,reason", [
    ("suspended", "blocked", "suspended"), ("expired", "blocked", "expired"),
    ("grace", "read_only", "grace"), ("trial", "ok", None)])
def test_school_info_states_and_isolation(papp, two_schools, state, expected, reason):
    from app.services.subscription_enforcement import MESSAGES_AR
    set_state(papp, two_schools["A"]["school"].id, state)
    r = _info(papp, two_schools["A"])
    assert r.status_code == 200
    assert (r.json["state"], r.json["reason"]) == (expected, reason)
    if expected == "blocked":
        assert r.json["message_ar"] == MESSAGES_AR[reason] and r.json["logo_url"] is None
    # B never shows A's state
    assert _info(papp, two_schools["B"]).json["state"] == "ok"


def test_school_info_signs_the_logo(papp, two_schools):
    from app.extensions import db
    from app.models import School
    from app.services.file_storage import upload_root
    A = two_schools["A"]
    sid = A["school"].id
    key = f"{sid}/logo/{sid}/logo037.png"
    with papp.app_context():
        path = upload_root() / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
        s = db.session.get(School, sid)
        s.logo_url = f"/files/{key}"
        db.session.commit()
        db.session.remove()
    try:
        url = _info(papp, A).json["logo_url"]
        assert url.startswith(f"/files/{key}?exp=") and "&sig=" in url
        c = papp.test_client()
        assert c.get(url, base_url=host(A)).status_code == 200            # anonymous, signed
        assert c.get(url, base_url=host(two_schools["B"])).status_code == 404
        assert c.get(f"/files/{key}", base_url=host(A)).status_code in (302, 401)  # unsigned: refused
    finally:
        path.unlink(missing_ok=True)


def test_school_info_is_rate_limited_per_ip(papp, two_schools):
    from app.blueprints.api.public import SCHOOL_INFO_PER_MINUTE
    c = papp.test_client()
    for _ in range(SCHOOL_INFO_PER_MINUTE):
        assert c.get("/api/public/school-info", base_url=host(two_schools["A"])).status_code == 200
    r = c.get("/api/public/school-info", base_url=host(two_schools["B"]))
    assert r.status_code == 429 and set(r.json) == {"error", "message_ar"}
    assert r.json["error"] == "rate_limited"
    other = c.get("/api/public/school-info", base_url=host(two_schools["A"]),
                  environ_base={"REMOTE_ADDR": "10.9.9.9"})
    assert other.status_code == 200


# ─── app-config / upgrade_required ───────────────────────────────────

def test_app_config(papp, two_schools):
    r = papp.test_client().get("/api/public/app-config", base_url=host(two_schools["A"]))
    assert r.status_code == 200
    assert r.json == {"api_version": "1",
                      "min_app_version": {"student": None, "teacher": None, "parent": None}}
    _settings(papp, min_app_version_student="1.2.0", min_app_version_parent="not-a-version")
    r = papp.test_client().get("/api/public/app-config", base_url=host(two_schools["B"]))
    assert r.json["min_app_version"] == {"student": "1.2.0", "teacher": None, "parent": None}
    assert papp.test_client().get("/api/public/app-config",
                                  base_url="http://nowhere.manasety.ai").status_code == 404


@pytest.mark.parametrize("app_name,version,refused", [
    ("student", "1.1.9", True), ("student", "1.2", False), ("student", "1.2.0", False),
    ("student", "2.0.0", False), ("student", "abc", True), ("Student", "1.0.0", True),
    ("teacher", "0.0.1", False), ("", "0.0.1", False)])
def test_upgrade_required(papp, two_schools, app_name, version, refused):
    _settings(papp, min_app_version_student="1.2.0")
    A = two_schools["A"]
    hdr = _bearer(papp, A["users"]["admin"])
    hdr.update({"X-App-Name": app_name, "X-App-Version": version})
    r = papp.test_client().get("/api/me", base_url=host(A), headers=hdr)
    if refused:
        assert r.status_code == 426
        assert r.json == {"error": "upgrade_required", "app": "student", "min_version": "1.2.0",
                          "message_ar": r.json["message_ar"]} and r.json["message_ar"]
    else:
        assert r.status_code == 200


def test_upgrade_check_skips_public_and_headerless(papp, two_schools):
    _settings(papp, min_app_version_student="9.0.0")
    A = two_schools["A"]
    old = {"X-App-Name": "student", "X-App-Version": "1.0.0"}
    c = papp.test_client()
    assert c.get("/api/public/school-info", base_url=host(A), headers=old).status_code == 200
    assert c.get("/api/public/app-config", base_url=host(A), headers=old).status_code == 200
    # an app that doesn't send the header (today's behaviour) isn't checked
    assert c.get("/api/me", base_url=host(A), headers=_bearer(papp, A["users"]["admin"])).status_code == 200
    # refused before authentication: an old app learns to update, not to log in again
    assert c.get("/api/me", base_url=host(A), headers=old).status_code == 426


# ─── the error-code contract ─────────────────────────────────────────

CODES = ("unauthorized", "subscription_blocked", "subscription_read_only", "module_disabled",
         "limit_reached", "school_moved", "upgrade_required", "rate_limited")


def test_every_code_has_one_line_in_the_doc():
    text = DOC.read_text(encoding="utf-8")
    for code in CODES:
        assert len(re.findall(rf"^\| `{code}` \|", text, re.M)) == 1, code


def test_contract_unauthorized(papp, two_schools):
    r = papp.test_client().get("/api/me", base_url=host(two_schools["A"]))
    assert r.status_code == 401 and r.json == {"error": "unauthorized"}


def test_contract_cross_school_token_is_unauthorized(papp, two_schools):
    """A's token on B's host — refused, and B's own token still works."""
    A, B = two_schools["A"], two_schools["B"]
    c = papp.test_client()
    r = c.get("/api/me", base_url=host(B), headers=_bearer(papp, A["users"]["admin"]))
    assert r.status_code == 401 and r.json == {"error": "unauthorized"}
    assert c.get("/api/me", base_url=host(B), headers=_bearer(papp, B["users"]["admin"])).status_code == 200


def test_contract_subscription_codes(papp, two_schools):
    from app.services.subscription_enforcement import MESSAGES_AR
    A = two_schools["A"]
    hdr = _bearer(papp, A["users"]["admin"])
    set_state(papp, A["school"].id, "suspended")
    r = papp.test_client().get("/api/me", base_url=host(A), headers=hdr)
    assert r.status_code == 403
    assert r.json == {"error": "subscription_blocked", "reason": "suspended",
                      "message_ar": MESSAGES_AR["suspended"]}
    from app.extensions import db
    from app.models import School
    with papp.app_context():
        s = db.session.get(School, A["school"].id)
        s.status, s.is_active = "active", True
        db.session.commit()
        db.session.remove()
    set_state(papp, A["school"].id, "grace")
    hdr = _bearer(papp, A["users"]["admin"])
    r = papp.test_client().post("/api/me/full-name", base_url=host(A), headers=hdr, json={"full_name": "x"})
    assert r.status_code == 403
    assert r.json == {"error": "subscription_read_only", "reason": "grace",
                      "message_ar": MESSAGES_AR["read_only"]}


def test_contract_module_disabled(papp, two_schools):
    from app.extensions import db
    from app.models import School, SchoolModuleOverride
    from app.services.auth_jwt import issue_token
    from app.services.modules import set_override
    A = two_schools["A"]
    with papp.app_context():
        set_override(db.session.get(School, A["school"].id), "finance", False, "test", None)
        db.session.commit()
        tok = issue_token(A["users"]["parent"])
        db.session.remove()
    try:
        r = papp.test_client().get(f"/api/parent/child/{A['student'].id}/invoices", base_url=host(A),
                                   headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 403 and r.json == {"error": "module_disabled", "module": "finance"}
    finally:
        with papp.app_context():
            SchoolModuleOverride.query.delete()
            db.session.commit()
            db.session.remove()


def test_contract_limit_reached():
    from app.services.limits import LimitReached
    body = LimitReached("students", 10).api_body()
    assert set(body) == {"error", "limit", "message_ar"}
    assert (body["error"], body["limit"]) == ("limit_reached", "students") and body["message_ar"]


def test_contract_school_moved(papp, two_schools):
    from app.extensions import db
    from app.models import SchoolSlugHistory
    A = two_schools["A"]
    with papp.app_context():
        db.session.add(SchoolSlugHistory(school_id=A["school"].id, old_slug="alpha-old",
                                         redirect_until=datetime.now(timezone.utc) + timedelta(days=30)))
        db.session.commit()
        db.session.remove()
    c = papp.test_client()
    for path in ("/api/me", "/api/public/school-info"):
        r = c.get(path, base_url="http://alpha-old.manasety.ai")
        assert r.status_code == 410 and r.json == {"error": "school_moved", "new_host": "alpha.manasety.ai"}


# ─── console: app card + app settings ────────────────────────────────

@pytest.mark.parametrize("role", ["owner", "support", "finance"])
def test_app_card(console, two_schools, role):
    A = two_schools["A"]["school"]
    c, _ = _console_client(console, role)
    r = c.get(f"/superadmin/schools/{A.id}/app-card", base_url=CONSOLE)
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "https://alpha.manasety.ai/app" in html and "<svg" in html and ">alpha<" in html
    assert "onclick" not in html


def test_app_card_qr_encodes_the_school_link(console, two_schools):
    import segno
    from app.blueprints.superadmin.app_card import app_link
    A = two_schools["A"]["school"]
    with console.test_request_context(base_url=CONSOLE):
        link = app_link(A)
        assert link == "https://alpha.manasety.ai/app"
        expected = segno.make(link, error="m").svg_inline(scale=5, border=2)
    c, _ = _console_client(console, "owner")
    assert expected in c.get(f"/superadmin/schools/{A.id}/app-card", base_url=CONSOLE).get_data(as_text=True)
    B = two_schools["B"]["school"]
    c, _ = _console_client(console, "owner")
    assert "https://beta.manasety.ai/app" in c.get(f"/superadmin/schools/{B.id}/app-card",
                                                   base_url=CONSOLE).get_data(as_text=True)


def test_app_card_not_on_school_host_or_archived(console, two_schools):
    from app.extensions import db
    from app.models import School
    A = two_schools["A"]
    c, _ = _console_client(console, "owner")
    assert c.get(f"/superadmin/schools/{A['school'].id}/app-card", base_url=host(A)).status_code == 404
    with console.app_context():
        s = db.session.get(School, A["school"].id)
        s.status = "archived"
        db.session.commit()
        db.session.remove()
    assert c.get(f"/superadmin/schools/{A['school'].id}/app-card", base_url=CONSOLE).status_code == 404


def test_app_settings_owner_only_validated_audited(console, two_schools, monkeypatch):
    from app.models import PlatformAuditLog
    from app.services.subscriptions import get_settings
    monkeypatch.setitem(console.config, "WTF_CSRF_ENABLED", False)
    form = {"min_app_version_student": "1.4.0", "app_download_url": "https://get.manasety.test",
            "support_email": "help@manasety.test"}
    for role in ("support", "finance"):
        c, _ = _console_client(console, role)
        assert c.post("/superadmin/settings/apps", base_url=CONSOLE, data=form).status_code == 403
    c, uid = _console_client(console, "owner")
    assert c.get("/superadmin/settings/apps", base_url=CONSOLE).status_code == 200
    bad = dict(form, min_app_version_teacher="v2")
    assert c.post("/superadmin/settings/apps", base_url=CONSOLE, data=bad).status_code == 400
    bad = dict(form, app_download_url="http://get.manasety.test")
    assert c.post("/superadmin/settings/apps", base_url=CONSOLE, data=bad).status_code == 400
    assert c.post("/superadmin/settings/apps", base_url=CONSOLE, data=form).status_code == 302
    with console.app_context():
        s = get_settings()
        assert s["min_app_version_student"] == "1.4.0" and s["support_email"] == "help@manasety.test"
        row = PlatformAuditLog.query.filter_by(platform_user_id=uid, action="app_settings_changed").one()
        assert row.meta["keys"] == ["app_download_url", "min_app_version_student", "support_email"]


# ─── /app landing on the school host ─────────────────────────────────

def test_app_landing(papp, two_schools):
    c = papp.test_client()
    r = c.get("/app", base_url=host(two_schools["A"]))
    assert r.status_code == 200 and "alpha" in r.get_data(as_text=True)
    assert "قيد الإصدار" in r.get_data(as_text=True)
    _settings(papp, app_download_url="https://get.manasety.test")
    assert 'href="https://get.manasety.test"' in c.get("/app", base_url=host(two_schools["B"])).get_data(as_text=True)
    assert c.get("/app", base_url="http://nowhere.manasety.ai").status_code == 404
    assert c.get("/app", base_url=CONSOLE).status_code == 404
