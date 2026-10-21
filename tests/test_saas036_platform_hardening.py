"""SAAS-036 — role × route matrix (every route, every role), last-owner
protection, platform users (invite / roles / resets), revocable server
sessions, immutable audit (ORM and raw SQL), IP allow-list, headers, CSRF,
and the pre-launch security checklist items that are testable."""

from __future__ import annotations

import time

import pytest
from werkzeug.routing import IntegerConverter

from isolation_harness import host
from test_saas026_subscriptions import CONSOLE, _console_client, console  # noqa: F401

ROLES = ("owner", "support", "finance")


def _fresh(c):
    with c.session_transaction(base_url=CONSOLE) as s:
        s["sa_totp_at"] = time.time()


# ─── the matrix ──────────────────────────────────────────────────────

def test_every_console_route_is_in_the_matrix(console):
    from app.services.platform_permissions import CAPABILITIES, ROUTES
    for rule in console.url_map.iter_rules():
        if not rule.endpoint.startswith("superadmin."):
            continue
        assert rule.endpoint in ROUTES, f"add {rule.endpoint} to services/platform_permissions.py"
        for m in (rule.methods or set()) - {"HEAD", "OPTIONS"}:
            assert m in ROUTES[rule.endpoint], (rule.endpoint, m)
    assert all(cap in CAPABILITIES for r in ROUTES.values() for cap in r.values())


@pytest.mark.parametrize("role", ROLES)
def test_role_against_every_route(console, two_schools, role):
    """Each role gets 403 exactly where the matrix says no (never a 200 /
    redirect it shouldn't), on every console route and method."""
    from app.services.platform_permissions import ROUTES, allowed, is_public
    c, _ = _console_client(console, role)
    sid = two_schools["A"]["school"].id
    adapter = console.url_map.bind("console.manasety.ai")
    checked = 0
    for rule in console.url_map.iter_rules():
        ep = rule.endpoint
        if not ep.startswith("superadmin.") or is_public(ep) or ep in ("superadmin.logout",):
            continue
        values = {a: (sid if a == "school_id" else 1) if isinstance(rule._converters[a], IntegerConverter) else "x"
                  for a in rule.arguments}
        url = adapter.build(ep, values)
        for m in sorted((rule.methods or set()) - {"HEAD", "OPTIONS"}):
            r = c.open(url, method=m, base_url=CONSOLE)
            checked += 1
            if allowed(ep, m, role):
                assert r.status_code != 403, (ep, m, role)
            else:
                assert r.status_code == 403, (ep, m, role, r.status_code)
    assert checked > 60


# ─── platform users ──────────────────────────────────────────────────

def test_invite_link_once_and_owner_notified(console, monkeypatch):
    import re
    from app.extensions import db
    from app.models import PlatformUser
    from app.services import platform_actions
    mails = []
    monkeypatch.setattr(platform_actions, "notify_owners", lambda s, b: mails.append(s) or 1)
    owner, _ = _console_client(console, "owner")
    _fresh(owner)
    email = f"new-{time.time_ns()}@manasety.test"
    r = owner.post("/superadmin/users", base_url=CONSOLE,
                   data={"email": email, "full_name": "New Person", "role": "support"})
    assert r.status_code == 200
    link = re.search(rb'value="([^"]*/superadmin/setup/[^"]+)"', r.data).group(1).decode()
    path = link.split("console.manasety.ai", 1)[1]
    anon = console.test_client()
    r = anon.get(path, base_url=CONSOLE)                                 # token leaves the URL
    assert r.status_code == 302 and r.headers["Location"].endswith("/superadmin/setup")
    assert r.headers["Referrer-Policy"] == "no-referrer"
    assert anon.get("/superadmin/setup", base_url=CONSOLE).status_code == 200
    pw = "a-long-unique-pass-9"
    assert anon.post("/superadmin/setup", base_url=CONSOLE,
                     data={"password": pw, "confirm": pw}).status_code == 302
    anon.get(path, base_url=CONSOLE)
    assert anon.get("/superadmin/setup", base_url=CONSOLE).status_code == 404   # single use
    assert mails
    with console.app_context():
        u = PlatformUser.query.filter_by(email=email).one()
        assert u.check_password(pw) and u.role == "support"
        db.session.remove()


def test_last_owner_cannot_be_deactivated_or_demoted(console):
    from app.extensions import db
    from app.models import PlatformUser
    owner, uid = _console_client(console, "owner")
    _fresh(owner)
    with console.app_context():
        PlatformUser.query.filter(PlatformUser.role == "owner", PlatformUser.id != uid).update({"is_active": False})
        db.session.commit()
    try:
        owner.post(f"/superadmin/users/{uid}/deactivate", base_url=CONSOLE)
        owner.post(f"/superadmin/users/{uid}/role", base_url=CONSOLE, data={"role": "support"})
        with console.app_context():
            u = db.session.get(PlatformUser, uid)
            assert u.is_active and u.role == "owner"
    finally:
        with console.app_context():
            PlatformUser.query.filter_by(role="owner").update({"is_active": True})
            db.session.commit()
            db.session.remove()


def test_role_change_revokes_sessions_and_mails_owners(console, monkeypatch):
    from app.services import platform_actions
    mails = []
    monkeypatch.setattr(platform_actions, "notify_owners", lambda s, b: mails.append(s) or 1)
    owner, _ = _console_client(console, "owner")
    _fresh(owner)
    target, tid = _console_client(console, "support")
    assert target.get("/superadmin/schools", base_url=CONSOLE).status_code == 200
    owner.post(f"/superadmin/users/{tid}/role", base_url=CONSOLE, data={"role": "finance"})
    r = target.get("/superadmin/schools", base_url=CONSOLE)
    assert r.status_code == 302 and "/superadmin/login" in r.headers["Location"]
    assert any("دور" in m for m in mails)


def test_reset_totp_not_for_yourself(console):
    from app.extensions import db
    from app.models import PlatformUser
    owner, uid = _console_client(console, "owner")
    _fresh(owner)
    owner.post(f"/superadmin/users/{uid}/reset_totp", base_url=CONSOLE)
    with console.app_context():
        assert db.session.get(PlatformUser, uid).totp_enabled is True
        db.session.remove()


def test_common_password_refused():
    from app.services.platform_auth import password_problem
    assert password_problem("password1234") is not None
    assert password_problem("short") is not None
    assert password_problem("a-long-unique-pass-9") is None


# ─── revocable sessions ──────────────────────────────────────────────

def test_revoked_session_refused_on_next_request(console):
    from app.extensions import db
    from app.models import PlatformSession
    c, uid = _console_client(console, "support")
    assert c.get("/superadmin/schools", base_url=CONSOLE).status_code == 200
    with console.app_context():
        PlatformSession.query.filter_by(platform_user_id=uid).update({"revoked_at": db.func.now()})
        db.session.commit()
    r = c.get("/superadmin/schools", base_url=CONSOLE)
    assert r.status_code == 302 and "/superadmin/login" in r.headers["Location"]


def test_own_sessions_page_and_revoke(console):
    from app.models import PlatformSession
    c, uid = _console_client(console, "finance")
    assert c.get("/superadmin/me/sessions", base_url=CONSOLE).status_code == 200
    with console.app_context():
        sid = PlatformSession.query.filter_by(platform_user_id=uid).first().id
    c.post(f"/superadmin/me/sessions/{sid}/revoke", base_url=CONSOLE)
    assert c.get("/superadmin/schools", base_url=CONSOLE).status_code == 302


def test_cookie_without_session_row_is_refused(console):
    from app.extensions import db
    from app.models import PlatformUser
    from app.services import platform_auth as pa
    import secrets
    with console.test_request_context(base_url=CONSOLE):
        u = PlatformUser(email=f"x-{secrets.token_hex(3)}@manasety.test", full_name="x", role="owner",
                         is_active=True, password_changed_at=pa.utcnow(), totp_enabled=True)
        u.set_password(secrets.token_urlsafe(16))
        db.session.add(u); db.session.commit()
        uid, ver = u.id, u.session_version
        db.session.remove()
    c = console.test_client()
    with c.session_transaction(base_url=CONSOLE) as s:
        s["_user_id"], s["_fresh"], s["sa_ver"] = f"p:{uid}", True, ver
        s["sa_login_at"] = s["sa_seen_at"] = time.time()
    r = c.get("/superadmin/schools", base_url=CONSOLE)
    assert r.status_code == 302 and "/superadmin/login" in r.headers["Location"]


# ─── immutable audit ─────────────────────────────────────────────────

def test_audit_rows_refuse_update_and_delete(console):
    from sqlalchemy import text
    from app.extensions import db
    from app.models import PlatformAuditLog
    from app.services import platform_auth as pa
    from app.services.platform_security import audit_prune
    with console.app_context():
        pa.audit("probe_row", None)
        db.session.commit()
        row = PlatformAuditLog.query.filter_by(action="probe_row").order_by(PlatformAuditLog.id.desc()).first()
        row.action = "tampered"
        with pytest.raises(Exception):
            db.session.commit()
        db.session.rollback()
        with pytest.raises(Exception):
            db.session.execute(text("DELETE FROM platform_audit_logs WHERE id = :i"), {"i": row.id})
            db.session.commit()
        db.session.rollback()
        with pytest.raises(Exception):
            with db.engine.begin() as conn:
                conn.execute(text("UPDATE platform_audit_logs SET action='x' WHERE id = :i"), {"i": row.id})
        # the sanctioned retention path works
        with audit_prune(db.session.connection()):
            PlatformAuditLog.query.filter_by(id=row.id).delete()
        db.session.commit()
        assert db.session.get(PlatformAuditLog, row.id) is None
        db.session.remove()


def test_audit_viewer_filters_and_export_is_audited(console):
    from app.models import PlatformAuditLog
    owner, uid = _console_client(console, "owner")
    assert owner.get("/superadmin/audit?action=login_success&page=1", base_url=CONSOLE).status_code == 200
    r = owner.get("/superadmin/audit?format=csv", base_url=CONSOLE)
    assert r.status_code == 200 and r.mimetype == "text/csv"
    with console.app_context():
        assert PlatformAuditLog.query.filter_by(platform_user_id=uid, action="audit_exported").count() == 1
    sup, _ = _console_client(console, "support")
    assert sup.get("/superadmin/audit", base_url=CONSOLE).status_code == 403


# ─── IP allow-list, headers, CSRF ────────────────────────────────────

def test_ip_allow_list(console, monkeypatch):
    import ipaddress
    c, _ = _console_client(console, "owner")
    monkeypatch.setitem(console.config, "PLATFORM_ALLOWED_IPS", [ipaddress.ip_network("10.0.0.0/8")])
    assert c.get("/superadmin/schools", base_url=CONSOLE, environ_base={"REMOTE_ADDR": "8.8.8.8"}).status_code == 404
    assert c.get("/superadmin/schools", base_url=CONSOLE, environ_base={"REMOTE_ADDR": "10.1.2.3"}).status_code == 200


def test_ip_allow_list_requires_trusted_proxy():
    from app.config import _resolve_platform_allowed_ips
    with pytest.raises(RuntimeError, match="TRUST_PROXY_HEADERS"):
        _resolve_platform_allowed_ips({"PLATFORM_ALLOWED_IPS": "10.0.0.0/8"})
    assert _resolve_platform_allowed_ips({"PLATFORM_ALLOWED_IPS": "10.0.0.0/8", "TRUST_PROXY_HEADERS": "1"})
    assert _resolve_platform_allowed_ips({}) is None


def test_security_headers_on_console_pages(console):
    c, _ = _console_client(console, "owner")
    for path in ("/superadmin/login", "/superadmin/schools", "/superadmin/dashboard"):
        h = (c if path != "/superadmin/login" else console.test_client()).get(path, base_url=CONSOLE).headers
        assert h["Cache-Control"] == "no-store" and h["X-Frame-Options"] == "DENY"
        assert h["Referrer-Policy"] == "no-referrer" and h["X-Content-Type-Options"] == "nosniff"
        csp = h["Content-Security-Policy"]
        assert "frame-ancestors 'none'" in csp and "'nonce-" in csp and "'unsafe-inline'" not in csp.split("style-src")[0]


def test_csrf_enforced_on_console_posts(console, monkeypatch):
    monkeypatch.setitem(console.config, "WTF_CSRF_ENABLED", True)
    c, _ = _console_client(console, "owner")
    r = c.post("/superadmin/plans/new", base_url=CONSOLE, data={"code": "x-plan", "name_ar": "x"})
    assert r.status_code == 400


# ─── pre-launch checklist (testable items) ───────────────────────────

def test_host_spoofing_school_host_cannot_reach_console(console, two_schools):
    A = two_schools["A"]
    c = console.test_client()
    assert c.get("/superadmin/login", base_url=host(A)).status_code == 404
    assert c.get("/superadmin/login", base_url=host(A),
                 headers={"X-Forwarded-Host": "console.manasety.ai"}).status_code == 404


def test_login_does_not_reveal_whether_an_email_exists(console, puser):
    info = puser()
    c = console.test_client()
    a = c.post("/superadmin/login", base_url=CONSOLE, data={"email": info["email"], "password": "wrong-pass-123"})
    b = c.post("/superadmin/login", base_url=CONSOLE, data={"email": "nobody@nowhere.test", "password": "wrong-pass-123"})
    # the CSRF token is timestamp-signed, so it differs across a second
    # boundary; everything else must be byte-identical
    import re
    strip = lambda r: re.sub(rb'name="csrf_token" value="[^"]*"', b"", r.data)  # noqa: E731
    assert a.status_code == b.status_code and strip(a) == strip(b)


def test_support_enter_has_no_open_redirect(console, two_schools):
    A = two_schools["A"]
    r = console.test_client().get("/_support/enter?t=x&next=https://evil.example", base_url=host(A))
    assert r.status_code in (403, 404) and "evil.example" not in (r.headers.get("Location") or "")


from test_saas025_platform import papp, puser  # noqa: E402,F401  (fixtures)


def test_no_new_owner_while_a_purge_waits(console, two_schools, monkeypatch):
    """SAAS-035 post-commit review: nobody gains (or loses) owner while a
    purge request waits — the approver must already be an owner."""
    from datetime import datetime, timedelta, timezone
    from app.extensions import db
    from app.models import PlatformAuditLog, PlatformUser, SchoolOffboarding
    from app.services import platform_actions
    monkeypatch.setattr(platform_actions, "notify_owners", lambda s, b: 1)
    owner, oid = _console_client(console, "owner")
    _fresh(owner)
    _, tid = _console_client(console, "support")
    now = datetime.now(timezone.utc)
    with console.app_context():
        db.session.add(SchoolOffboarding(school_id=two_schools["A"]["school"].id, reason="leaving",
                                         requested_at=now - timedelta(days=3),
                                         purge_requested_by=oid, purge_requested_at=now))
        db.session.commit()
    try:
        email = f"own-{time.time_ns()}@manasety.test"
        owner.post("/superadmin/users", base_url=CONSOLE,
                   data={"email": email, "full_name": "Owner Two", "role": "owner"})
        owner.post(f"/superadmin/users/{tid}/role", base_url=CONSOLE, data={"role": "owner"})
        with console.app_context():
            assert PlatformUser.query.filter_by(email=email).first() is None
            assert db.session.get(PlatformUser, tid).role == "support"
    finally:
        with console.app_context():
            SchoolOffboarding.query.delete()
            db.session.commit()
            db.session.remove()
    # outside a pending purge the role change goes through and logs the old role
    owner.post(f"/superadmin/users/{tid}/role", base_url=CONSOLE, data={"role": "finance"})
    with console.app_context():
        row = (PlatformAuditLog.query.filter_by(action="platform_user_role")
               .order_by(PlatformAuditLog.id.desc()).first())
        assert row.meta["old_role"] == "support" and row.meta["role"] == "finance"
        db.session.remove()



# ─── security review follow-ups ──────────────────────────────────────

def test_owner_credentials_are_never_reset_from_the_web(console, monkeypatch):
    """Review (HIGH): an owner who could see another owner's reset link and
    clear their TOTP would own that account (and the second approval)."""
    from app.extensions import db
    from app.models import PlatformSetupToken, PlatformUser
    from app.services import platform_actions
    monkeypatch.setattr(platform_actions, "notify_owners", lambda s, b: 1)
    owner, _ = _console_client(console, "owner")
    _fresh(owner)
    _, other = _console_client(console, "owner")
    for action in ("reset_password", "reset_totp"):
        r = owner.post(f"/superadmin/users/{other}/{action}", base_url=CONSOLE)
        assert r.status_code == 302 and b"/superadmin/setup/" not in r.data
    with console.app_context():
        u = db.session.get(PlatformUser, other)
        assert u.totp_enabled and PlatformSetupToken.query.filter_by(platform_user_id=other).count() == 0
        db.session.remove()
    # a support account still can be reset by an owner
    _, sup = _console_client(console, "support")
    r = owner.post(f"/superadmin/users/{sup}/reset_password", base_url=CONSOLE)
    assert r.status_code == 200 and b"/superadmin/setup/" in r.data


def test_cli_reset_link_for_an_owner(console, monkeypatch):
    from app.services import platform_actions
    monkeypatch.setattr(platform_actions, "notify_owners", lambda s, b: 1)
    _, oid = _console_client(console, "owner")
    from app.extensions import db
    from app.models import PlatformUser
    with console.app_context():
        email = db.session.get(PlatformUser, oid).email
        db.session.remove()
    out = console.test_cli_runner().invoke(args=["platform-user-reset-link", "--email", email])
    assert out.exit_code == 0, out.output
    assert "/superadmin/setup/" in out.output


def test_setup_link_claimed_once(console):
    from app.extensions import db
    from app.services import platform_security as psec
    _, uid = _console_client(console, "support")
    from app.models import PlatformUser
    with console.test_request_context(base_url=CONSOLE):
        raw = psec.issue_setup_link(db.session.get(PlatformUser, uid), purpose="reset")
        db.session.commit()
        row = psec.redeem_setup_link(raw)
        assert psec.claim_setup_token(row.id) is True
        assert psec.claim_setup_token(row.id) is False                 # the parallel loser
        db.session.commit()
        assert psec.redeem_setup_link(raw) is None
        db.session.remove()


def test_audit_prune_guard_is_cleared_when_the_body_raises(console):
    from sqlalchemy import text
    from app.extensions import db
    from app.services.platform_security import audit_prune
    with console.app_context():
        conn = db.session.connection()
        with pytest.raises(RuntimeError):
            with audit_prune(conn):
                raise RuntimeError("boom")
        if conn.dialect.name == "sqlite":                  # the guard table is SQLite's mechanism
            assert conn.execute(text("SELECT COUNT(*) FROM audit_prune_guard")).scalar() == 0
        db.session.rollback()
        db.session.remove()


def test_a_new_owner_comes_only_from_the_server(console, monkeypatch):
    """Commit review (HIGH): the console never mints an owner — the owner
    who sees the link would control the second account of the two-person
    rule. Invite-as-owner and promote-to-owner are CLI only."""
    from app.extensions import db
    from app.models import PlatformUser
    from app.services import platform_actions
    monkeypatch.setattr(platform_actions, "notify_owners", lambda s, b: 1)
    owner, _ = _console_client(console, "owner")
    _fresh(owner)
    _, tid = _console_client(console, "support")
    email = f"own2-{time.time_ns()}@manasety.test"
    r = owner.post("/superadmin/users", base_url=CONSOLE,
                   data={"email": email, "full_name": "Owner Two", "role": "owner"})
    assert b"/superadmin/setup/" not in r.data
    owner.post(f"/superadmin/users/{tid}/role", base_url=CONSOLE, data={"role": "owner"})
    with console.app_context():
        assert PlatformUser.query.filter_by(email=email).first() is None
        target = db.session.get(PlatformUser, tid)
        assert target.role == "support"
        target_email = target.email
        db.session.remove()
    out = console.test_cli_runner().invoke(
        args=["platform-user-set-role", "--email", target_email, "--role", "owner"])
    assert out.exit_code == 0, out.output
    assert "/superadmin/setup/" in out.output and "credentials reset" in out.output
    with console.app_context():
        promoted = db.session.get(PlatformUser, tid)
        assert promoted.role == "owner"
        # nothing a console owner may have set carries over
        assert promoted.totp_enabled is False and promoted.totp_secret_encrypted is None
        from app.models import PlatformSetupToken
        assert PlatformSetupToken.query.filter_by(platform_user_id=tid, used_at=None).count() == 1
        promoted.role = "support"
        db.session.commit()
        db.session.remove()


def test_reactivating_an_owner_waits_for_a_pending_purge(console, two_schools, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from app.extensions import db
    from app.models import PlatformUser, SchoolOffboarding
    from app.services import platform_actions
    monkeypatch.setattr(platform_actions, "notify_owners", lambda s, b: 1)
    owner, oid = _console_client(console, "owner")
    _fresh(owner)
    _, other = _console_client(console, "owner")
    now = datetime.now(timezone.utc)
    with console.app_context():
        db.session.get(PlatformUser, other).is_active = False
        db.session.add(SchoolOffboarding(school_id=two_schools["A"]["school"].id, reason="leaving",
                                         requested_at=now - timedelta(days=3),
                                         purge_requested_by=oid, purge_requested_at=now))
        db.session.commit()
    try:
        owner.post(f"/superadmin/users/{other}/activate", base_url=CONSOLE)
        with console.app_context():
            assert db.session.get(PlatformUser, other).is_active is False
    finally:
        with console.app_context():
            SchoolOffboarding.query.delete()
            db.session.commit()
            db.session.remove()
    owner.post(f"/superadmin/users/{other}/activate", base_url=CONSOLE)
    with console.app_context():
        assert db.session.get(PlatformUser, other).is_active is True
        db.session.remove()
