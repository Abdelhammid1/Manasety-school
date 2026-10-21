"""SAAS-025 — platform identity, console login (+TOTP) and read-only school list."""

from __future__ import annotations

import re
import secrets
import time
from pathlib import Path

import pyotp
import pytest

from isolation_harness import host

CONSOLE = "http://console.manasety.ai"

# Every superadmin endpoint must be listed here (a new route fails the
# coverage test until it is classified). Value: allowed methods.
SUPERADMIN_ROUTES = {
    "superadmin.login": {"GET", "POST"},
    "superadmin.totp": {"GET", "POST"},
    "superadmin.totp_setup": {"GET", "POST"},
    "superadmin.logout": {"POST"},
    "superadmin.password": {"GET", "POST"},
    "superadmin.home": {"GET"},
    "superadmin.schools": {"GET"},
    "superadmin.school_detail": {"GET"},
    # SAAS-026
    "superadmin.plans": {"GET"},
    "superadmin.plan_new": {"POST"},
    "superadmin.plan_edit": {"POST"},
    "superadmin.plan_toggle": {"POST"},
    "superadmin.subscription_renew": {"POST"},
    "superadmin.subscription_extend": {"POST"},
    "superadmin.subscription_change_plan": {"POST"},
    "superadmin.subscription_trial": {"POST"},
    # SAAS-028
    "superadmin.school_new": {"GET"},
    "superadmin.school_new_step": {"POST"},
    "superadmin.school_create": {"POST"},
    "superadmin.slug_check": {"GET"},
}
# Writes allowed in the console, per ticket. Anything else must be GET.
CONSOLE_WRITES = {
    "superadmin.login", "superadmin.totp", "superadmin.totp_setup", "superadmin.logout",
    "superadmin.password",                                            # SAAS-025
    "superadmin.plan_new", "superadmin.plan_edit", "superadmin.plan_toggle",
    "superadmin.subscription_renew", "superadmin.subscription_extend",
    "superadmin.subscription_change_plan", "superadmin.subscription_trial",   # SAAS-026
    "superadmin.school_new_step", "superadmin.school_create",                 # SAAS-028
}


@pytest.fixture
def papp(app, monkeypatch):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "PLATFORM_HOSTS", ["console.manasety.ai"])
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    return app


@pytest.fixture
def puser(papp):
    """A ready platform user (TOTP enrolled, password set). Yields
    {id, email, password, secret}; removed afterwards."""
    from app.extensions import db
    from app.models import PlatformAuditLog, PlatformRecoveryCode, PlatformUser
    from app.services import platform_auth as pa
    created = []

    def make(role="owner", totp=True, changed=True):
        password = secrets.token_urlsafe(18)
        email = f"pu-{secrets.token_hex(4)}@manasety.test"
        with papp.test_request_context(base_url=CONSOLE):
            u = PlatformUser(email=email, full_name="Platform Person", role=role, is_active=True)
            u.set_password(password)
            secret = pa.new_totp_secret()
            if totp:
                u.totp_secret_encrypted = pa.encrypt(secret)
                u.totp_enabled = True
            if changed:
                u.password_changed_at = pa.utcnow()
            db.session.add(u)
            db.session.commit()
            created.append(u.id)
            info = {"id": u.id, "email": email, "password": password, "secret": secret}
            db.session.remove()
        return info

    yield make
    with papp.app_context():
        PlatformAuditLog.query.filter(PlatformAuditLog.platform_user_id.in_(created)).delete(
            synchronize_session=False)
        PlatformRecoveryCode.query.filter(PlatformRecoveryCode.platform_user_id.in_(created)).delete(
            synchronize_session=False)
        PlatformUser.query.filter(PlatformUser.id.in_(created)).delete(synchronize_session=False)
        db.session.commit()
        db.session.remove()


def _next_code(secret):
    """A code for the NEXT time-step: the one just used to log in can't
    be replayed (SAAS-025 review), and +1 step is inside the window."""
    return pyotp.TOTP(secret).at(time.time() + 30)


def _login(c, info, code=None):
    r = c.post("/superadmin/login", base_url=CONSOLE,
               data={"email": info["email"], "password": info["password"]})
    assert r.status_code == 302, r.status_code
    r = c.post("/superadmin/login/totp", base_url=CONSOLE,
               data={"code": code or pyotp.TOTP(info["secret"]).now()})
    return r


def _audit(papp, uid, action=None):
    from app.models import PlatformAuditLog
    with papp.app_context():
        q = PlatformAuditLog.query.filter_by(platform_user_id=uid)
        if action:
            q = q.filter_by(action=action)
        return [(a.action, a.meta, a.target_school_id) for a in q.order_by(PlatformAuditLog.id)]


# ─── schema / migration ──────────────────────────────────────────────

def test_single_alembic_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parents[1] / "migrations"))
    assert len(ScriptDirectory.from_config(cfg).get_heads()) == 1


def test_platform_tables_are_not_tenant_owned(app):
    from app.extensions import db
    from app.services.tenant_guard import PLATFORM_TABLES, owned_tables
    with app.app_context():
        for t in ("platform_users", "platform_recovery_codes", "platform_audit_logs"):
            assert "school_id" not in db.metadata.tables[t].c
        for t in PLATFORM_TABLES:
            assert t in db.metadata.tables and t not in owned_tables()


def test_production_requires_platform_enc_key():
    from app.config import _resolve_platform_enc_key
    with pytest.raises(RuntimeError, match="PLATFORM_ENC_KEY"):
        _resolve_platform_enc_key("s" * 40, {}, app_env="production")
    with pytest.raises(RuntimeError):
        _resolve_platform_enc_key("s" * 40, {"PLATFORM_ENC_KEY": "short"}, app_env="production")
    with pytest.raises(RuntimeError):
        _resolve_platform_enc_key("s" * 40, {"PLATFORM_ENC_KEY": "s" * 40}, app_env="production")
    assert _resolve_platform_enc_key("s" * 40, {"PLATFORM_ENC_KEY": "k" * 40}, app_env="production") == "k" * 40


def test_legacy_hosts_default_is_empty():
    from app.config import _resolve_legacy_hosts
    assert _resolve_legacy_hosts({}) == {}


@pytest.mark.parametrize("slug", ["console", "admin", "superadmin", "platform", "api", "www", "lms",
                                  "school", "demo-admin", "accountant", "chatwoot", "drporcelain",
                                  "easygo", "elmouhamy", "lamma", "lexoffice", "marsoud", "qafr",
                                  "whitemoon", "landing"])
def test_reserved_slugs(slug):
    from app.services.tenancy import RESERVED_SLUGS
    assert slug in RESERVED_SLUGS


# ─── host isolation ──────────────────────────────────────────────────

def test_every_superadmin_route_is_classified(app):
    actual = {r.endpoint: (r.methods or set()) - {"HEAD", "OPTIONS"}
              for r in app.url_map.iter_rules() if r.endpoint.startswith("superadmin.")}
    assert set(actual) == set(SUPERADMIN_ROUTES), sorted(set(actual) ^ set(SUPERADMIN_ROUTES))
    for ep, methods in actual.items():
        assert methods == SUPERADMIN_ROUTES[ep], ep
        if "POST" in methods:
            assert ep in CONSOLE_WRITES, ep


@pytest.mark.parametrize("path", ["/superadmin/login", "/superadmin/schools", "/superadmin/schools/1"])
def test_console_is_404_on_school_hosts(papp, two_schools, path):
    with papp.test_client() as c:
        assert c.get(path, base_url=host(two_schools["A"])).status_code == 404


def test_console_is_404_when_resolution_is_off(papp, monkeypatch):
    monkeypatch.setitem(papp.config, "TENANT_RESOLUTION_MODE", "off")
    with papp.test_client() as c:
        for path in ("/superadmin/login", "/superadmin/schools"):
            assert c.get(path, base_url=CONSOLE).status_code == 404


@pytest.mark.parametrize("path,expected", [
    ("/students", 404), ("/finance/invoices", 404), ("/api/student/courses", 404),
    ("/auth/login", 302), ("/", 302),
])
def test_school_routes_not_served_on_console(papp, path, expected):
    with papp.test_client() as c:
        r = c.get(path, base_url=CONSOLE)
    assert r.status_code == expected
    if expected == 302:
        assert r.headers["Location"].endswith("/superadmin/login")


def test_school_session_is_anonymous_on_console(papp, two_schools, login_as):
    A = two_schools["A"]
    with papp.test_client() as c:
        login_as(c, A["users"]["admin"], base_url=CONSOLE)
        r = c.get("/superadmin/schools", base_url=CONSOLE)
    assert r.status_code == 302 and r.headers["Location"].endswith("/superadmin/login")


def test_platform_session_is_anonymous_on_school_host(papp, two_schools, puser):
    info = puser()
    A = two_schools["A"]
    with papp.test_client() as c:
        with c.session_transaction(base_url=host(A)) as s:
            s["_user_id"] = f"p:{info['id']}"
            s["_fresh"] = True
        r = c.get("/students", base_url=host(A))
    assert r.status_code in (302, 401)


def test_id_collision_school_id_on_console(papp, two_schools, puser):
    """A school user whose id equals a platform user's id gets nothing."""
    info = puser()
    with papp.test_client() as c:
        with c.session_transaction(base_url=CONSOLE) as s:
            s["_user_id"] = str(info["id"])
            s["_fresh"] = True
        r = c.get("/superadmin/schools", base_url=CONSOLE)
    assert r.status_code == 302


def test_platform_users_never_get_or_use_mobile_tokens(papp, two_schools, puser):
    import jwt as pyjwt
    from datetime import datetime, timedelta
    from app.extensions import db
    from app.models import PlatformUser
    from app.services.auth_jwt import _jwt_key, issue_token
    info = puser()
    with papp.test_request_context(base_url=CONSOLE):
        with pytest.raises(ValueError):
            issue_token(db.session.get(PlatformUser, info["id"]))
        forged = pyjwt.encode({"sub": f"p:{info['id']}", "school": two_schools["A"]["school"].id,
                               "exp": datetime.utcnow() + timedelta(hours=1),
                               "iat": datetime.utcnow(), "iss": "manasety-api"},
                              _jwt_key(), algorithm="HS256")
        db.session.remove()
    with papp.test_client() as c:
        r = c.get("/api/me", base_url=host(two_schools["A"]),
                  headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code in (401, 404)


def test_platform_cookie_is_separate_and_strict(papp, puser):
    info = puser()
    with papp.test_client() as c:
        r = c.post("/superadmin/login", base_url=CONSOLE,
                   data={"email": info["email"], "password": info["password"]})
    cookie = r.headers.get("Set-Cookie", "")
    assert cookie.startswith(papp.config["PLATFORM_SESSION_COOKIE_NAME"] + "=")
    assert "SameSite=Strict" in cookie and "HttpOnly" in cookie


# ─── login + TOTP ────────────────────────────────────────────────────

def test_full_login_reaches_the_console(papp, puser):
    info = puser()
    with papp.test_client() as c:
        r = _login(c, info)
        assert r.status_code == 302 and r.headers["Location"].endswith("/superadmin/schools")
        assert c.get("/superadmin/schools", base_url=CONSOLE).status_code == 200
    assert ("login_success", None, None) in _audit(papp, info["id"])


def test_password_alone_never_opens_the_console(papp, puser):
    info = puser()
    with papp.test_client() as c:
        c.post("/superadmin/login", base_url=CONSOLE,
               data={"email": info["email"], "password": info["password"]})
        r = c.get("/superadmin/schools", base_url=CONSOLE)
    assert r.status_code == 302 and r.headers["Location"].endswith("/superadmin/login")


def test_wrong_password_and_unknown_email_look_the_same(papp, puser):
    info = puser()
    with papp.test_client() as c:
        bad = c.post("/superadmin/login", base_url=CONSOLE,
                     data={"email": info["email"], "password": "wrong-" + info["password"]})
        unknown = c.post("/superadmin/login", base_url=CONSOLE,
                         data={"email": "nobody@manasety.test", "password": "whatever-123456"})
    assert bad.status_code == unknown.status_code == 401
    msg = "بيانات الدخول غير صحيحة."
    assert msg in bad.get_data(as_text=True) and msg in unknown.get_data(as_text=True)


def test_lockout_after_five_failures(papp, puser):
    info = puser()
    with papp.test_client() as c:
        for _ in range(5):
            c.post("/superadmin/login", base_url=CONSOLE,
                   data={"email": info["email"], "password": "nope-nope-nope"})
        r = c.post("/superadmin/login", base_url=CONSOLE,
                   data={"email": info["email"], "password": info["password"]})
    assert r.status_code == 401
    assert any(a == "login_locked" for a, _m, _s in _audit(papp, info["id"]))


def test_wrong_totp_is_refused(papp, puser):
    info = puser()
    with papp.test_client() as c:
        r = _login(c, info, code="000000")
        assert r.status_code == 401
        assert c.get("/superadmin/schools", base_url=CONSOLE).status_code == 302


def test_first_login_enrols_totp_and_recovery_codes_work_once(papp, puser):
    info = puser(totp=False)
    from app.extensions import db
    from app.models import PlatformUser
    from app.services import platform_auth as pa
    with papp.test_client() as c:
        r = c.post("/superadmin/login", base_url=CONSOLE,
                   data={"email": info["email"], "password": info["password"]})
        assert r.headers["Location"].endswith("/superadmin/login/totp/setup")
        page = c.get("/superadmin/login/totp/setup", base_url=CONSOLE).get_data(as_text=True)
        assert "<svg" in page
        with papp.test_request_context(base_url=CONSOLE):
            secret = pa.decrypt(db.session.get(PlatformUser, info["id"]).totp_secret_encrypted)
            db.session.remove()
        r = c.post("/superadmin/login/totp/setup", base_url=CONSOLE,
                   data={"code": pyotp.TOTP(secret).now()})
        html = r.get_data(as_text=True)
        codes = re.findall(r"<div>([0-9a-f]{6}-[0-9a-f]{6})</div>", html)
        assert len(codes) == 10
        c.post("/superadmin/logout", base_url=CONSOLE)
    info["secret"] = secret
    for attempt, expected in ((1, 302), (2, 401)):
        with papp.test_client() as c:
            c.post("/superadmin/login", base_url=CONSOLE,
                   data={"email": info["email"], "password": info["password"]})
            r = c.post("/superadmin/login/totp", base_url=CONSOLE, data={"recovery_code": codes[0]})
            assert r.status_code == expected, attempt
    rows = _audit(papp, info["id"])
    assert ("recovery_code_used", None, None) in rows and ("totp_enabled", None, None) in rows
    blob = repr(rows)
    assert secret not in blob and not any(code in blob for code in codes)


def test_cli_created_user_must_change_password(papp, puser):
    info = puser(changed=False)
    with papp.test_client() as c:
        _login(c, info)
        r = c.get("/superadmin/schools", base_url=CONSOLE)
        assert r.status_code == 302 and r.headers["Location"].endswith("/superadmin/password")
        new = secrets.token_urlsafe(16)
        short = c.post("/superadmin/password", base_url=CONSOLE, data={
            "current_password": info["password"], "new_password": "short1", "confirm_password": "short1",
            "code": _next_code(info["secret"])})
        assert short.status_code == 400
        notp = c.post("/superadmin/password", base_url=CONSOLE, data={
            "current_password": info["password"], "new_password": new, "confirm_password": new,
            "code": "000000"})
        assert notp.status_code == 400
        ok = c.post("/superadmin/password", base_url=CONSOLE, data={
            "current_password": info["password"], "new_password": new, "confirm_password": new,
            "code": _next_code(info["secret"])})
        assert ok.status_code == 302
        assert c.get("/superadmin/schools", base_url=CONSOLE).status_code == 200


def test_idle_session_expires(papp, puser):
    info = puser()
    with papp.test_client() as c:
        _login(c, info)
        with c.session_transaction(base_url=CONSOLE) as s:
            s["sa_seen_at"] = time.time() - papp.config["PLATFORM_SESSION_MINUTES"] * 60 - 5
        r = c.get("/superadmin/schools", base_url=CONSOLE)
    assert r.status_code == 302 and r.headers["Location"].endswith("/superadmin/login")


def test_ip_throttle(papp, puser, monkeypatch):
    from app.services import platform_auth as pa
    monkeypatch.setattr(pa, "LOGIN_FAILS_PER_IP", 3)
    info = puser()
    with papp.test_client() as c:
        for _ in range(3):
            c.post("/superadmin/login", base_url=CONSOLE,
                   data={"email": "x@manasety.test", "password": "nope-nope-nope"})
        r = c.post("/superadmin/login", base_url=CONSOLE,
                   data={"email": info["email"], "password": info["password"]})
    assert r.status_code == 429


# ─── CLI ─────────────────────────────────────────────────────────────

def test_cli_creates_user_and_refuses_duplicates_and_short_passwords(papp):
    from app.extensions import db
    from app.models import PlatformAuditLog, PlatformUser
    runner = papp.test_cli_runner()
    email = f"cli-{secrets.token_hex(3)}@manasety.test"
    pw = secrets.token_urlsafe(16)
    try:
        short = runner.invoke(args=["platform-user-create", "--email", email, "--name", "X",
                                    "--role", "owner"], input="short\nshort\n")
        assert short.exit_code != 0
        ok = runner.invoke(args=["platform-user-create", "--email", email, "--name", "X",
                                 "--role", "owner"], input=f"{pw}\n{pw}\n")
        assert ok.exit_code == 0, ok.output
        assert pw not in ok.output
        dup = runner.invoke(args=["platform-user-create", "--email", email.upper(), "--name", "X",
                                  "--role", "owner"], input=f"{pw}\n{pw}\n")
        assert dup.exit_code != 0
        with papp.app_context():
            u = PlatformUser.query.filter_by(email=email).one()
            assert u.password_changed_at is None and not u.totp_enabled
    finally:
        with papp.app_context():
            u = PlatformUser.query.filter_by(email=email).first()
            if u:
                PlatformAuditLog.query.filter_by(platform_user_id=u.id).delete()
                db.session.delete(u)
                db.session.commit()
            db.session.remove()


def test_no_default_platform_password_in_code_or_migrations():
    root = Path(__file__).parents[1]
    files = list((root / "migrations").rglob("*saas025*.py")) + list((root / "app").rglob("*.py"))
    for f in files:
        text = f.read_text(encoding="utf-8")
        assert not re.search(r"set_password\(\s*[\"']", text), f


# ─── school list / detail ────────────────────────────────────────────

def test_school_list_and_detail_are_read_only_stats(papp, world, puser):
    info = puser()
    A, B = world["A"], world["B"]
    with papp.test_client() as c:
        _login(c, info)
        lst = c.get("/superadmin/schools", base_url=CONSOLE).get_data(as_text=True)
        assert A["school"].slug in lst and B["school"].slug in lst
        r = c.get(f"/superadmin/schools/{A['school'].id}", base_url=CONSOLE)
        assert r.status_code == 200
        body = r.get_data(as_text=True)
    for marker in A["markers"]:          # no personal / school data, only counts
        if marker.startswith(("Student-", "PC-", "INV-", "Emp-")):
            assert marker not in body and marker not in lst
    assert ("school_viewed", None, A["school"].id) in _audit(papp, info["id"])
    assert any(a == "schools_listed" for a, _m, _s in _audit(papp, info["id"]))


def test_school_list_query_count_is_constant(papp, two_schools, puser):
    from sqlalchemy import event
    from app.extensions import db
    from app.models import School
    from world import purge_schools
    info = puser()

    client = papp.test_client()
    _login(client, info)
    with papp.app_context():
        engine = db.engine

    def count_queries():
        n = {"q": 0}

        def before(*_a, **_k):
            n["q"] += 1
        event.listen(engine, "before_cursor_execute", before)
        try:
            assert client.get("/superadmin/schools", base_url=CONSOLE).status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", before)
        return n["q"]

    base = count_queries()
    extra = []
    with papp.app_context():
        for i in range(3):
            s = School(code=f"QC-{i}-{secrets.token_hex(2)}", name=f"QC{i}",
                       slug=f"qc{i}-{secrets.token_hex(2)}", status="active", is_active=True)
            db.session.add(s); db.session.flush(); extra.append(s.id)
        db.session.commit()
        db.session.remove()
    try:
        assert count_queries() == base
    finally:
        with papp.app_context():
            purge_schools(extra)
            db.session.remove()


def test_unknown_school_detail_is_404(papp, puser):
    info = puser()
    with papp.test_client() as c:
        _login(c, info)
        assert c.get("/superadmin/schools/987654", base_url=CONSOLE).status_code == 404


# ─── platform_read_scope ─────────────────────────────────────────────

def test_read_scope_refuses_school_writes(papp, two_schools, puser):
    from app.extensions import db
    from app.models import PlatformUser, Student
    from app.services.platform_scope import PlatformReadOnlyError, platform_read_scope
    info = puser()
    with papp.test_request_context(base_url=CONSOLE):
        u = db.session.get(PlatformUser, info["id"])
        with platform_read_scope("probe", u):
            s = db.session.get(Student, two_schools["A"]["student"].id)
            assert s is not None
            s.full_name = "changed"
            with pytest.raises(PlatformReadOnlyError):
                db.session.flush()
            db.session.rollback()
        db.session.remove()


def test_read_scope_used_only_by_platform_code():
    root = Path(__file__).parents[1] / "app"
    allowed = ("blueprints/superadmin/", "services/platform")
    offenders = []
    for f in root.rglob("*.py"):
        rel = f.relative_to(root).as_posix()
        lines = f.read_text(encoding="utf-8").splitlines()
        code = " ".join(l for l in lines if not l.lstrip().startswith("#"))
        if "platform_read_scope" in code and not rel.startswith(allowed):
            offenders.append(rel)
    assert offenders == []


def test_console_pages_send_security_headers(papp, puser):
    info = puser()
    with papp.test_client() as c:
        _login(c, info)
        r = c.get("/superadmin/schools", base_url=CONSOLE)
    assert r.headers["Cache-Control"] == "no-store"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Referrer-Policy"] == "no-referrer"


# ─── security review follow-ups ──────────────────────────────────────

def test_totp_code_cannot_be_replayed(papp, puser):
    info = puser()
    code = pyotp.TOTP(info["secret"]).now()
    with papp.test_client() as c:
        assert _login(c, info, code=code).status_code == 302
    with papp.test_client() as c:
        assert _login(c, info, code=code).status_code == 401


def test_three_wrong_totp_codes_reset_to_password_step(papp, puser):
    info = puser()
    with papp.test_client() as c:
        c.post("/superadmin/login", base_url=CONSOLE,
               data={"email": info["email"], "password": info["password"]})
        for _ in range(2):
            assert c.post("/superadmin/login/totp", base_url=CONSOLE,
                          data={"code": "000000"}).status_code == 401
        r = c.post("/superadmin/login/totp", base_url=CONSOLE, data={"code": "000000"})
        assert r.status_code == 302 and r.headers["Location"].endswith("/superadmin/login")
        r = c.post("/superadmin/login/totp", base_url=CONSOLE,
                   data={"code": pyotp.TOTP(info["secret"]).now()})
        assert r.status_code == 302 and r.headers["Location"].endswith("/superadmin/login")


def test_locked_account_cannot_use_the_totp_step(papp, puser):
    from app.extensions import db
    from app.models import PlatformUser
    from app.services import platform_auth as pa
    from datetime import timedelta
    info = puser()
    with papp.test_client() as c:
        c.post("/superadmin/login", base_url=CONSOLE,
               data={"email": info["email"], "password": info["password"]})
        with papp.app_context():
            u = db.session.get(PlatformUser, info["id"])
            u.locked_until = pa.utcnow() + timedelta(minutes=15)
            db.session.commit()
            db.session.remove()
        r = c.post("/superadmin/login/totp", base_url=CONSOLE,
                   data={"code": pyotp.TOTP(info["secret"]).now()})
        assert r.status_code == 302 and r.headers["Location"].endswith("/superadmin/login")
        assert c.get("/superadmin/schools", base_url=CONSOLE).status_code == 302


def test_attempts_while_locked_do_not_extend_the_lock(papp, puser):
    from app.extensions import db
    from app.models import PlatformUser
    info = puser()
    with papp.test_client() as c:
        for _ in range(5):
            c.post("/superadmin/login", base_url=CONSOLE,
                   data={"email": info["email"], "password": "nope-nope-nope"})
        with papp.app_context():
            first = db.session.get(PlatformUser, info["id"]).locked_until
            db.session.remove()
        for _ in range(5):
            c.post("/superadmin/login", base_url=CONSOLE,
                   data={"email": info["email"], "password": "nope-nope-nope"})
        with papp.app_context():
            u = db.session.get(PlatformUser, info["id"])
            assert u.locked_until == first and u.failed_attempts == 5
            db.session.remove()


def test_logout_revokes_the_users_other_sessions(papp, puser):
    info = puser()
    first, other = papp.test_client(), papp.test_client()
    _login(first, info)
    _login(other, info, code=_next_code(info["secret"]))
    assert other.get("/superadmin/schools", base_url=CONSOLE).status_code == 200
    first.post("/superadmin/logout", base_url=CONSOLE)
    r = other.get("/superadmin/schools", base_url=CONSOLE)
    assert r.status_code == 302 and r.headers["Location"].endswith("/superadmin/login")
