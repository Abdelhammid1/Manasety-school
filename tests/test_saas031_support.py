"""SAAS-031 — support sessions: token hand-off, modes and forbidden
endpoints, the hidden support user, attribution, expiry / idle / one
session, no /api, two-school isolation, banner and the admin's log."""

from __future__ import annotations

import time
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest

from isolation_harness import host, hid
from test_saas026_subscriptions import CONSOLE, _console_client, console  # noqa: F401


@pytest.fixture
def sapp(console, two_schools):
    """Console + both schools with a support user (the migration does it
    on real DBs; two_schools is built with create_all)."""
    from app.extensions import db
    from app.models import School
    from app.services.support_policy import ensure_support_user
    with console.app_context():
        for k in ("A", "B"):
            ensure_support_user(db.session.get(School, two_schools[k]["school"].id))
        db.session.commit()
        db.session.remove()
    return console


@pytest.fixture(autouse=True)
def _cleanup(console):
    yield
    from app.extensions import db
    from app.models import SupportSession, SupportSessionEvent
    with console.app_context():
        from app.services.platform_security import audit_prune
        with audit_prune(db.session.connection()):
            SupportSessionEvent.query.delete()
        SupportSession.query.delete()
        db.session.commit()
        db.session.remove()


def _start(c, school_id, fresh=True, **form):
    if fresh:                    # TOTP verified "just now" (step-up satisfied)
        with c.session_transaction(base_url=CONSOLE) as sess:
            sess["sa_totp_at"] = time.time()
    data = {"reason": "investigating a reported bug", "mode": "read_only", "minutes": "30"}
    data.update(form)
    return c.post(f"/superadmin/schools/{school_id}/support/start", base_url=CONSOLE, data=data)


def _enter(app, bundle, location):
    """Follow the console redirect onto the school host."""
    u = urlparse(location)
    c = app.test_client()
    r = c.get(f"{u.path}?{u.query}", base_url=host(bundle))
    return c, r, parse_qs(u.query)["t"][0]


def _support_client(app, owner, bundle, **form):
    r = _start(owner, bundle["school"].id, **form)
    assert r.status_code == 302, r.data[:300]
    c, r2, _tok = _enter(app, bundle, r.headers["Location"])
    assert r2.status_code == 302, r2.data[:300]
    return c


# ─── hand-off token ──────────────────────────────────────────────────

def test_token_works_once(sapp, two_schools):
    A = two_schools["A"]
    owner, _ = _console_client(sapp, "owner")
    r = _start(owner, A["school"].id)
    loc = r.headers["Location"]
    assert loc.startswith(f"https://{A['school'].slug}.manasety.ai/_support/enter?t=")
    c, r2, tok = _enter(sapp, A, loc)
    assert r2.status_code == 302
    assert c.get("/", base_url=host(A), follow_redirects=True).status_code == 200
    # replay → refused
    assert sapp.test_client().get(f"/_support/enter?t={tok}", base_url=host(A)).status_code == 403


def test_token_for_other_school_tampered_or_expired_refused(sapp, two_schools, monkeypatch):
    from app.models import PlatformAuditLog
    A, B = two_schools["A"], two_schools["B"]
    owner, _ = _console_client(sapp, "owner")
    tok = parse_qs(urlparse(_start(owner, A["school"].id).headers["Location"]).query)["t"][0]
    # on school B's host
    assert sapp.test_client().get(f"/_support/enter?t={tok}", base_url=host(B)).status_code == 403
    # tampered
    assert sapp.test_client().get(f"/_support/enter?t={tok[:-2]}xx", base_url=host(A)).status_code == 403
    # on the console host
    assert sapp.test_client().get(f"/_support/enter?t={tok}", base_url=CONSOLE).status_code == 404
    # expired (older than 60 s)
    from app.services import support_policy as sp
    monkeypatch.setattr(sp, "TOKEN_MAX_AGE", -1)
    assert sapp.test_client().get(f"/_support/enter?t={tok}", base_url=host(A)).status_code == 403
    # refused attempts are logged, not audited (anyone can hit the URL)
    with sapp.app_context():
        assert PlatformAuditLog.query.filter_by(action="support_enter_refused").count() == 0


def test_no_nesting(sapp, two_schools):
    """A live support session can't be stacked with another one."""
    A = two_schools["A"]
    owner, _ = _console_client(sapp, "owner")
    other, _ = _console_client(sapp, "support")
    c = _support_client(sapp, owner, A)
    tok = parse_qs(urlparse(_start(other, A["school"].id).headers["Location"]).query)["t"][0]
    assert c.get(f"/_support/enter?t={tok}", base_url=host(A)).status_code == 403


def test_start_requirements(sapp, two_schools):
    A = two_schools["A"]
    sid = A["school"].id
    owner, _ = _console_client(sapp, "owner")
    r = _start(owner, sid, reason="short")
    assert r.status_code == 302 and "/_support/" not in r.headers["Location"]
    fin, _ = _console_client(sapp, "finance")
    assert _start(fin, sid).status_code == 403
    # write: owner only, needs a fresh TOTP + the school name
    sup, _ = _console_client(sapp, "support")
    r = _start(sup, sid, mode="write", confirm_name=A["school"].name)
    assert "/_support/" not in r.headers.get("Location", "")
    r = _start(owner, sid, mode="write", confirm_name=A["school"].name)        # no TOTP code
    assert "/_support/" not in r.headers.get("Location", "")


def test_step_up_after_ten_minutes(sapp, two_schools):
    owner, _ = _console_client(sapp, "owner")
    with owner.session_transaction(base_url=CONSOLE) as s:
        s["sa_totp_at"] = time.time() - 601
    r = _start(owner, two_schools["A"]["school"].id, fresh=False)
    assert "/_support/" not in r.headers.get("Location", "")


# ─── modes ───────────────────────────────────────────────────────────

def test_read_only_refuses_every_write(sapp, two_schools):
    A = two_schools["A"]
    owner, _ = _console_client(sapp, "owner")
    c = _support_client(sapp, owner, A)
    for path in ("/students/new", "/admin/users/new", "/admin/roles/new", "/finance/fee-types"):
        r = c.post(path, base_url=host(A), data={"x": "1"})
        assert r.status_code == 403, path
    assert c.get("/students", base_url=host(A), follow_redirects=True).status_code == 200


def test_read_only_flush_guard_is_enforced(sapp, two_schools):
    from flask import g
    from app.extensions import db
    from app.models import Student
    A = two_schools["A"]
    with sapp.test_request_context("/", base_url=host(A)):
        g.subscription_read_only = True
        g.ro_flush_guard_enforce = True
        st = Student.query.filter_by(school_id=A["school"].id).first()
        st.full_name += "!"
        with pytest.raises(PermissionError):
            db.session.flush()
        db.session.rollback()


def test_write_mode_forbidden_endpoints(sapp, two_schools, monkeypatch):
    import pyotp
    from app.extensions import db
    from app.models import PlatformUser
    from app.services import platform_auth as pa
    A = two_schools["A"]
    owner, uid = _console_client(sapp, "owner")
    secret = pa.new_totp_secret()
    with sapp.app_context():
        u = db.session.get(PlatformUser, uid)
        u.totp_secret_encrypted = pa.encrypt(secret)
        db.session.commit()
        db.session.remove()
    c = _support_client(sapp, owner, A, mode="write", confirm_name=A["school"].name,
                        totp=pyotp.TOTP(secret).now())
    r = c.post("/admin/users/new", base_url=host(A), data={"username": "x"})
    assert r.status_code == 403
    r = c.post(f"/students/{hid(A['student'].id)}/account/reset-password", base_url=host(A))
    assert r.status_code == 403
    # a normal write gets through the support gate (the view decides)
    r = c.post("/admin/roles/new", base_url=host(A), data={"name": "sup-made", "name_ar": "x"})
    assert r.status_code in (200, 302)


def test_forbidden_endpoints_all_exist(app):
    from app.services.support_policy import ALWAYS_ALLOWED, FORBIDDEN_ENDPOINTS
    endpoints = {r.endpoint for r in app.url_map.iter_rules()}
    assert FORBIDDEN_ENDPOINTS <= endpoints, sorted(FORBIDDEN_ENDPOINTS - endpoints)
    assert ALWAYS_ALLOWED <= endpoints


def test_write_mode_not_for_grace_school(sapp, two_schools):
    import pyotp
    from app.extensions import db
    from app.models import PlatformUser
    from app.services import platform_auth as pa
    from test_saas027_enforcement import set_state
    A = two_schools["A"]
    set_state(sapp, A["school"].id, "grace")
    owner, uid = _console_client(sapp, "owner")
    secret = pa.new_totp_secret()
    with sapp.app_context():
        db.session.get(PlatformUser, uid).totp_secret_encrypted = pa.encrypt(secret)
        db.session.commit()
    r = _start(owner, A["school"].id, mode="write", confirm_name=A["school"].name,
               totp=pyotp.TOTP(secret).now())
    assert "/_support/" not in r.headers.get("Location", "")


def test_support_can_view_blocked_school_read_only(sapp, two_schools):
    from test_saas027_enforcement import set_state
    A = two_schools["A"]
    set_state(sapp, A["school"].id, "suspended")
    owner, _ = _console_client(sapp, "owner")
    c = _support_client(sapp, owner, A)
    assert c.get("/students", base_url=host(A), follow_redirects=True).status_code == 200
    assert c.post("/students/new", base_url=host(A), data={}).status_code == 403
    # a normal user of that school still sees the blocked page
    assert sapp.test_client().get("/auth/login", base_url=host(A)).status_code == 403


def test_no_api_in_support_session(sapp, two_schools):
    A = two_schools["A"]
    owner, _ = _console_client(sapp, "owner")
    c = _support_client(sapp, owner, A)
    assert c.get("/api/me", base_url=host(A)).status_code in (401, 403)


# ─── the support user ───────────────────────────────────────────────

def test_support_user_hidden_and_cannot_log_in(sapp, two_schools, login_as):
    from app.extensions import db
    from app.models import User
    from app.services.limits import school_usage
    A = two_schools["A"]
    sid = A["school"].id
    with sapp.app_context():
        assert User.query.filter_by(school_id=sid, username="__manasety_support__").first() is None
        assert User.query.execution_options(include_support=True).filter_by(
            school_id=sid, is_platform_support=True).count() == 1
        staff = school_usage(sid).users
        names = {u.username for u in User.query.filter_by(school_id=sid)}
        assert "__manasety_support__" not in names and staff == len(
            [u for u in User.query.filter_by(school_id=sid, is_active=True)
             if u.role.name not in ("student", "parent")])
        db.session.remove()
    c = sapp.test_client()
    r = c.post("/auth/login", base_url=host(A), data={"username": "__manasety_support__", "password": "x"})
    assert r.status_code == 401
    r = c.post("/api/auth/login", base_url=host(A), json={"username": "__manasety_support__", "password": "x"})
    assert r.status_code in (400, 401)
    admin = sapp.test_client()
    login_as(admin, A["users"]["admin"], base_url=host(A))
    for path in ("/admin/users", "/msg/new"):
        page = admin.get(path, base_url=host(A), follow_redirects=True)
        assert "__manasety_support__".encode() not in page.data and "دعم منصتي".encode() not in page.data, path


def test_session_cookie_for_support_user_without_support_session_is_dead(sapp, two_schools):
    from app.extensions import db
    from app.models import User
    A = two_schools["A"]
    with sapp.app_context():
        uid = User.query.execution_options(include_support=True).filter_by(
            school_id=A["school"].id, is_platform_support=True).one().id
        db.session.remove()
    c = sapp.test_client()
    with c.session_transaction(base_url=host(A)) as s:
        s["_user_id"] = str(uid)
        s["_fresh"] = True
    r = c.get("/students", base_url=host(A))
    assert r.status_code == 302 and "/auth/login" in r.headers["Location"]


def test_actions_attributed_to_support_with_session_id(sapp, two_schools):
    import pyotp
    from app.extensions import db
    from app.models import AuditLog, PlatformUser, Role
    from app.services import platform_auth as pa
    A = two_schools["A"]
    owner, uid = _console_client(sapp, "owner")
    secret = pa.new_totp_secret()
    with sapp.app_context():
        db.session.get(PlatformUser, uid).totp_secret_encrypted = pa.encrypt(secret)
        db.session.commit()
    c = _support_client(sapp, owner, A, mode="write", confirm_name=A["school"].name,
                        totp=pyotp.TOTP(secret).now())
    c.post("/admin/roles/new", base_url=host(A), data={"name": "sup-attrib", "name_ar": "دعم"})
    with sapp.app_context():
        role = Role.query.filter_by(school_id=A["school"].id, name="sup-attrib").one()
        # newest row: SQLite reuses ids, older runs may have logged the same id
        log = (AuditLog.query.filter_by(entity_type="Role", entity_id=role.id, action="create")
               .order_by(AuditLog.id.desc()).first())
        assert log.support_session_id is not None
        db.session.delete(role)
        db.session.commit()
        db.session.remove()


# ─── lifetime ────────────────────────────────────────────────────────

def _row(app):
    from app.models import SupportSession
    with app.app_context():
        return SupportSession.query.order_by(SupportSession.id.desc()).first().id


def _set(app, sid, **values):
    from app.extensions import db
    from app.models import SupportSession
    with app.app_context():
        row = db.session.get(SupportSession, sid)
        for k, v in values.items():
            setattr(row, k, v)
        db.session.commit()
        db.session.remove()


@pytest.mark.parametrize("why", ["expired", "idle", "revoked"])
def test_session_ends(sapp, two_schools, why):
    from app.services.support_policy import utcnow
    A = two_schools["A"]
    owner, _ = _console_client(sapp, "owner")
    c = _support_client(sapp, owner, A)
    sid = _row(sapp)
    if why == "expired":
        _set(sapp, sid, expires_at=utcnow() - timedelta(seconds=1))
    elif why == "idle":
        _set(sapp, sid, last_seen_at=utcnow() - timedelta(minutes=16))
    else:
        assert owner.post(f"/superadmin/support/{sid}/revoke", base_url=CONSOLE).status_code == 302
    r = c.get("/students", base_url=host(A))
    assert r.status_code == 302 and "/auth/login" in r.headers["Location"]
    # no way back
    assert c.get("/students", base_url=host(A)).status_code == 302


def test_session_on_other_school_host_ends(sapp, two_schools):
    A, B = two_schools["A"], two_schools["B"]
    owner, _ = _console_client(sapp, "owner")
    c = _support_client(sapp, owner, A)
    # replay A's cookie on B's host
    cookie = c.get_cookie("session", domain=f"{A['school'].slug}.manasety.ai")
    other = sapp.test_client()
    other.set_cookie("session", cookie.value, domain=f"{B['school'].slug}.manasety.ai")
    r = other.get("/students", base_url=host(B))
    assert r.status_code == 302 and "/auth/login" in r.headers["Location"]


def test_one_active_session_per_staff_member(sapp, two_schools):
    from app.models import SupportSession
    A, B = two_schools["A"], two_schools["B"]
    owner, uid = _console_client(sapp, "owner")
    c1 = _support_client(sapp, owner, A)
    _support_client(sapp, owner, B)
    with sapp.app_context():
        live = SupportSession.query.filter_by(platform_user_id=uid, ended_at=None).all()
        assert len(live) == 1 and live[0].school_id == B["school"].id
    assert c1.get("/students", base_url=host(A)).status_code == 302


def test_end_button_and_platform_logout(sapp, two_schools):
    from app.models import SupportSession
    A = two_schools["A"]
    owner, uid = _console_client(sapp, "owner")
    c = _support_client(sapp, owner, A)
    r = c.post("/_support/end", base_url=host(A))
    assert r.status_code == 302 and "/superadmin/schools/" in r.headers["Location"]
    assert c.get("/students", base_url=host(A)).status_code == 302
    c = _support_client(sapp, owner, A)
    owner.post("/superadmin/logout", base_url=CONSOLE)
    with sapp.app_context():
        assert SupportSession.query.filter_by(platform_user_id=uid, ended_at=None).count() == 0
    assert c.get("/students", base_url=host(A)).status_code == 302


# ─── trail, banner, transparency ────────────────────────────────────

def test_every_request_has_an_event_without_values(sapp, two_schools):
    from app.models import SupportSessionEvent
    A = two_schools["A"]
    owner, _ = _console_client(sapp, "owner")
    c = _support_client(sapp, owner, A)
    c.get("/students?secret=abc", base_url=host(A))
    c.post("/students/new", base_url=host(A), data={"full_name": "Hidden Value"})
    with sapp.app_context():
        events = SupportSessionEvent.query.filter_by(support_session_id=_row(sapp)).all()
        paths = [(e.method, e.path) for e in events]
        assert ("GET", "/students") in paths and ("POST", "/students/new") in paths
        blob = repr([(e.path, e.field_names) for e in events])
        assert "secret=abc" not in blob and "Hidden Value" not in blob
        assert any(e.field_names == ["full_name"] for e in events)


def test_banner_on_every_sidebar_page(sapp, two_schools):
    A = two_schools["A"]
    owner, _ = _console_client(sapp, "owner")
    c = _support_client(sapp, owner, A)
    for path in ("/", "/students", "/admin/users", "/finance/invoices", "/academic/years"):
        page = c.get(path, base_url=host(A), follow_redirects=True)
        assert page.status_code == 200, path
        assert "أنت داخل كدعم منصتي".encode() in page.data, path
        assert "وضع القراءة فقط".encode() in page.data


def test_school_admin_sees_support_log(sapp, two_schools, login_as):
    A, B = two_schools["A"], two_schools["B"]
    owner, _ = _console_client(sapp, "owner")
    _support_client(sapp, owner, A)
    admin = sapp.test_client()
    login_as(admin, A["users"]["admin"], base_url=host(A))
    page = admin.get("/support/log", base_url=host(A))
    assert page.status_code == 200 and "investigating a reported bug".encode() in page.data
    assert b"@manasety.test" not in page.data                     # no staff identity
    other = sapp.test_client()
    login_as(other, B["users"]["admin"], base_url=host(B))
    assert "investigating a reported bug".encode() not in other.get("/support/log", base_url=host(B)).data
    teacher = sapp.test_client()
    login_as(teacher, A["users"]["teacher"], base_url=host(A))
    assert teacher.get("/support/log", base_url=host(A)).status_code == 403


def test_console_pages_owner_only(sapp, two_schools):
    owner, _ = _console_client(sapp, "owner")
    _support_client(sapp, owner, two_schools["A"])
    sid = _row(sapp)
    assert owner.get("/superadmin/support", base_url=CONSOLE).status_code == 200
    assert owner.get(f"/superadmin/support/{sid}", base_url=CONSOLE).status_code == 200
    sup, _ = _console_client(sapp, "support")
    assert sup.get("/superadmin/support", base_url=CONSOLE).status_code == 403


def test_support_session_key_policy():
    from app.config import _resolve_support_session_key
    with pytest.raises(RuntimeError, match="SUPPORT_SESSION_KEY"):
        _resolve_support_session_key("s" * 40, {}, app_env="production")
    with pytest.raises(RuntimeError, match="SUPPORT_SESSION_KEY"):
        _resolve_support_session_key("s" * 40, {"SUPPORT_SESSION_KEY": "short"}, app_env="production")
    with pytest.raises(RuntimeError, match="SUPPORT_SESSION_KEY"):
        _resolve_support_session_key("s" * 40, {"SUPPORT_SESSION_KEY": "s" * 40}, app_env="production")
    assert _resolve_support_session_key("s" * 40, {"SUPPORT_SESSION_KEY": "k" * 40},
                                        app_env="production") == "k" * 40


# ─── security-review follow-ups ──────────────────────────────────────

def _write_client(app, bundle):
    import pyotp
    from app.extensions import db
    from app.models import PlatformUser
    from app.services import platform_auth as pa
    owner, uid = _console_client(app, "owner")
    secret = pa.new_totp_secret()
    with app.app_context():
        db.session.get(PlatformUser, uid).totp_secret_encrypted = pa.encrypt(secret)
        db.session.commit()
        db.session.remove()
    c = _support_client(app, owner, bundle, mode="write", confirm_name=bundle["school"].name,
                        totp=pyotp.TOTP(secret).now())
    return c, owner, uid


def test_write_mode_refuses_any_credential_field(sapp, two_schools):
    A = two_schools["A"]
    c, _owner, _uid = _write_client(sapp, A)
    for path, field in (("/teachers/new", "account_password"), ("/hr/employees/new", "account_password"),
                        (f"/students/{hid(A['student'].id)}/edit", "login_password"),
                        ("/admin/roles/new", "email")):
        r = c.post(path, base_url=host(A), data={field: "planted-secret-1", "name": "x"})
        assert r.status_code == 403, path


def test_session_dies_with_platform_user(sapp, two_schools):
    from app.extensions import db
    from app.models import PlatformUser
    A = two_schools["A"]
    owner, uid = _console_client(sapp, "owner")
    c = _support_client(sapp, owner, A)
    with sapp.app_context():
        db.session.get(PlatformUser, uid).is_active = False
        db.session.commit()
        db.session.remove()
    r = c.get("/students", base_url=host(A))
    assert r.status_code == 302 and "/auth/login" in r.headers["Location"]


def test_dead_support_cookie_does_not_block_new_entry(sapp, two_schools):
    from app.services.support_policy import utcnow
    A = two_schools["A"]
    owner, _ = _console_client(sapp, "owner")
    c = _support_client(sapp, owner, A)
    _set(sapp, _row(sapp), expires_at=utcnow() - timedelta(seconds=1))
    tok = parse_qs(urlparse(_start(owner, A["school"].id).headers["Location"]).query)["t"][0]
    r = c.get(f"/_support/enter?t={tok}", base_url=host(A))
    assert r.status_code == 302 and "/_support" not in r.headers["Location"]


def test_reserved_username_refused(sapp, two_schools, login_as):
    from app.extensions import db
    from app.models import Role
    A = two_schools["A"]
    with sapp.app_context():
        rid = Role.query.filter_by(school_id=A["school"].id, name="admin").first().id
        db.session.remove()
    c = sapp.test_client()
    login_as(c, A["users"]["admin"], base_url=host(A))
    r = c.post("/admin/users/new", base_url=host(A), data={
        "username": "__manasety_support__", "full_name": "x", "password": "long-enough-1",
        "role_id": rid, "is_active": "1"})
    assert "اسم المستخدم محجوز".encode() in r.data
