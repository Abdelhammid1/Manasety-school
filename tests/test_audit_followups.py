"""Regression tests for the post-push audit of SAAS-025..038 (2026-10-21).

Each test pins one finding that was confirmed in the code and fixed;
the ticket test files keep the original behaviour tests."""

from __future__ import annotations

import secrets
import time
from datetime import datetime, timedelta, timezone

import pytest

from isolation_harness import host
from test_saas026_subscriptions import CONSOLE, _console_client, console  # noqa: F401
from test_saas027_enforcement import set_state
from test_saas029_nginx_sync import FakeRunner, _sync, clean_jobs, st  # noqa: F401


# ─── nginx-sync: interrupted runs, stuck jobs, retries ───────────────

def test_interrupted_run_is_revalidated_not_unchanged(app, st, two_schools):
    res = _sync(app, st, FakeRunner())
    assert res.status == "applied"
    # a run killed after writing leaves the marker behind
    (st.conf_dir / ".nginx-sync.pending").write_text("x", encoding="utf-8")
    r = FakeRunner()
    res = _sync(app, st, r)
    assert res.status == "applied" and "test" in r.calls and "reload" in r.calls
    assert not (st.conf_dir / ".nginx-sync.pending").exists()
    # and a normal next run is "unchanged" again
    assert _sync(app, st, FakeRunner()).status == "unchanged"


def test_failed_test_clears_the_marker(app, st, two_schools):
    res = _sync(app, st, FakeRunner(test_rc=[1, 0]))
    assert res.status == "failed" and not (st.conf_dir / ".nginx-sync.pending").exists()


def test_stuck_running_job_is_failed_and_failure_is_retried(app, st, two_schools, clean_jobs, monkeypatch):
    from app.extensions import db
    from app.models import PlatformJob
    from app.services import nginx_sync
    monkeypatch.setattr(nginx_sync, "run_sync", lambda **kw: nginx_sync.SyncResult(status="unchanged"))
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    with app.app_context():
        db.session.add(PlatformJob(kind="nginx_sync", status="running", started_at=old))
        db.session.commit()
        nginx_sync.run_queue()
        assert PlatformJob.query.filter_by(status="running").count() == 0
        stuck = PlatformJob.query.filter_by(status="failed").one()
        assert "interrupted" in stuck.log
        # the failure is retried once it's older than RETRY_AFTER …
        stuck.finished_at = old
        db.session.commit()
        nginx_sync.run_queue()
        retry = PlatformJob.query.filter_by(reason="retry after failure").one()
        assert retry.status == "succeeded"
        db.session.remove()


def test_retries_stop_after_three(app, clean_jobs):
    from app.extensions import db
    from app.models import PlatformJob
    from app.services import nginx_sync
    old = datetime.now(timezone.utc) - timedelta(hours=1)
    with app.app_context():
        for _ in range(nginx_sync.MAX_RETRIES):
            db.session.add(PlatformJob(kind="nginx_sync", status="failed", reason="retry after failure",
                                       finished_at=old))
        db.session.commit()
        assert nginx_sync.run_queue() is None
        assert PlatformJob.query.filter_by(status="pending").count() == 0
        db.session.remove()


# ─── offboarding: exports kept, file content verified ───────────────

def test_the_export_of_a_purged_school_is_never_pruned(console, two_schools, tmp_path, monkeypatch):
    import os
    from app.extensions import db
    from app.models import SchoolOffboarding
    from app.services import school_export
    monkeypatch.setitem(console.config, "UPLOAD_ROOT", str(tmp_path))
    with console.app_context():
        d = school_export.exports_dir()
        kept, other = d / "kept.zip", d / "other.zip"
        for f in (kept, other):
            f.write_bytes(b"zip")
            os.utime(f, (time.time() - 30 * 86400,) * 2)
        db.session.add(SchoolOffboarding(school_id=two_schools["A"]["school"].id, reason="x",
                                         requested_at=datetime.now(timezone.utc), export_file="kept.zip",
                                         purged_at=datetime.now(timezone.utc)))
        db.session.commit()
        try:
            assert school_export.prune_old_exports() == 1
            assert kept.exists() and not other.exists()
        finally:
            SchoolOffboarding.query.delete()
            db.session.commit()
            db.session.remove()


def test_verify_sees_a_same_size_file_edit(console, two_schools, tmp_path, monkeypatch):
    from app.services import school_export
    from app.services.file_storage import upload_root
    monkeypatch.setitem(console.config, "UPLOAD_ROOT", str(tmp_path))
    sid = two_schools["A"]["school"].id
    with console.app_context():
        f = upload_root() / str(sid) / "logo" / str(sid) / "a.png"
        f.parent.mkdir(parents=True)
        f.write_bytes(b"AAAA")
        path = school_export.export_school(sid)["path"]
        assert school_export.verify(path, school_id=sid) == []
        f.write_bytes(b"BBBB")                         # same size, new content
        assert "uploaded files changed since the export" in school_export.verify(path, school_id=sid)


# ─── console ─────────────────────────────────────────────────────────

def test_expired_console_session_row_is_revoked(console):
    from app.extensions import db
    from app.models import PlatformSession
    c, uid = _console_client(console, "owner")
    with c.session_transaction(base_url=CONSOLE) as s:
        s["sa_seen_at"] = time.time() - 10 * 3600           # idle far too long
        sid = s.get("sa_sid")
    r = c.get("/superadmin/schools", base_url=CONSOLE)
    assert r.status_code == 302 and "/superadmin/login" in r.headers["Location"]
    with console.app_context():
        assert db.session.get(PlatformSession, sid).revoked_at is not None
        db.session.remove()


def test_password_change_is_generic_and_counts(console):
    from app.extensions import db
    from app.models import PlatformUser
    c, uid = _console_client(console, "owner")
    r = c.post("/superadmin/password", base_url=CONSOLE,
               data={"current_password": "not-it", "new_password": "x" * 16, "confirm_password": "x" * 16,
                     "code": "000000"})
    assert r.status_code == 400
    text = r.get_data(as_text=True)
    assert "كلمة المرور الحالية أو رمز التحقق غير صحيح" in text
    with console.app_context():
        assert db.session.get(PlatformUser, uid).failed_attempts == 1
        db.session.remove()


def test_cli_cannot_deactivate_the_last_owner(console):
    from app.extensions import db
    from app.models import PlatformUser
    _, uid = _console_client(console, "owner")
    with console.app_context():
        others = PlatformUser.query.filter(PlatformUser.role == "owner", PlatformUser.id != uid,
                                           PlatformUser.is_active.is_(True)).all()
        for o in others:
            o.is_active = False
        email = db.session.get(PlatformUser, uid).email
        db.session.commit()
        ids = [o.id for o in others]
    try:
        out = console.test_cli_runner().invoke(args=["platform-user-deactivate", "--email", email])
        assert out.exit_code != 0 and "last active owner" in out.output
        with console.app_context():
            assert db.session.get(PlatformUser, uid).is_active is True
    finally:
        with console.app_context():
            PlatformUser.query.filter(PlatformUser.id.in_(ids)).update({"is_active": True},
                                                                         synchronize_session=False)
            db.session.commit()
            db.session.remove()


@pytest.mark.parametrize("path", ["/superadmin/audit?page=abc", "/superadmin/audit?user=%C2%B2",
                                  "/superadmin/audit?school=%C2%B2"])
def test_bad_numbers_are_not_500(console, path):
    c, _ = _console_client(console, "owner")
    assert c.get(path, base_url=CONSOLE).status_code == 200


def test_extend_with_a_huge_number_is_not_500(console, two_schools, monkeypatch):
    monkeypatch.setitem(console.config, "WTF_CSRF_ENABLED", False)
    c, _ = _console_client(console, "owner")
    sid = two_schools["A"]["school"].id
    r = c.post(f"/superadmin/schools/{sid}/subscription/extend", base_url=CONSOLE,
               data={"days": "9" * 15, "reason": "x"})
    assert r.status_code in (302, 400)


def test_school_edit_sensitive_fields_need_totp(console, two_schools, monkeypatch):
    from app.extensions import db
    from app.models import School
    monkeypatch.setitem(console.config, "WTF_CSRF_ENABLED", False)
    A = two_schools["A"]["school"]
    c, _ = _console_client(console, "owner")
    with c.session_transaction(base_url=CONSOLE) as s:
        s.pop("sa_totp_at", None)
    r = c.post(f"/superadmin/schools/{A.id}/edit", base_url=CONSOLE,
               data={"blocked_message": "اتصلوا بنا"})
    assert r.status_code == 400
    with console.app_context():
        assert db.session.get(School, A.id).blocked_message != "اتصلوا بنا"
    with c.session_transaction(base_url=CONSOLE) as s:
        s["sa_totp_at"] = time.time()
    assert c.post(f"/superadmin/schools/{A.id}/edit", base_url=CONSOLE,
                  data={"blocked_message": "اتصلوا بنا"}).status_code == 302
    with console.app_context():
        s = db.session.get(School, A.id)
        assert s.blocked_message == "اتصلوا بنا"
        s.blocked_message = None
        db.session.commit()
        db.session.remove()


@pytest.mark.parametrize("name,secret", [
    ("totp_secret_encrypted", True), ("secret_value", True), ("api_token_v2", True),
    ("recovery_code_hash", True), ("tokenized", False), ("keyboard_layout", False)])
def test_redact_names(name, secret):
    from app.services.audit import is_secret_field
    assert is_secret_field(name) is secret


# ─── provisioning / support ──────────────────────────────────────────

@pytest.mark.parametrize("field,value", [
    ("admin_username", "__manasety_support__"),
    ("admin_email", "a@b.test\r\nBcc: x@evil.test"),
    ("admin_email", "a b@c.test")])
def test_provisioning_refuses_reserved_names_and_header_breaking_email(app, field, value):
    from test_saas028_provisioning import _spec
    from app.services import provisioning as prov
    with app.app_context():
        spec = _spec(**{"admin_username": "admin1", field: value})
        with pytest.raises(prov.ProvisionError):
            prov.validate_spec(spec)


def test_support_write_mode_scans_json_and_query(console, two_schools):
    import pyotp
    from test_saas031_support import _support_client
    from app.extensions import db
    from app.models import PlatformUser, School
    from app.services import platform_auth as pa
    from app.services.support_policy import ensure_support_user
    A = two_schools["A"]
    with console.app_context():
        ensure_support_user(db.session.get(School, A["school"].id))
        db.session.commit()
    owner, uid = _console_client(console, "owner")
    secret = pa.new_totp_secret()
    with console.app_context():
        db.session.get(PlatformUser, uid).totp_secret_encrypted = pa.encrypt(secret)
        db.session.commit()
        db.session.remove()
    c = _support_client(console, owner, A, mode="write", confirm_name=A["school"].name,
                        totp=pyotp.TOTP(secret).now())
    assert c.post("/admin/roles/new?password=x", base_url=host(A),
                  data={"name": "r1", "name_ar": "x"}).status_code == 403
    assert c.post("/admin/roles/new", base_url=host(A), json={"name": "r2", "new_password": "x"}).status_code == 403
    from app.models import SupportSession, SupportSessionEvent
    from app.services.platform_security import audit_prune
    with console.app_context():
        with audit_prune(db.session.connection()):
            SupportSessionEvent.query.delete()
        SupportSession.query.delete()
        db.session.commit()
        db.session.remove()


# ─── public API / mobile ─────────────────────────────────────────────

@pytest.fixture
def eapp(app, monkeypatch):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    from app.blueprints.api import public
    public._hits.clear()
    yield app
    public._hits.clear()


def test_unknown_host_probes_count_toward_the_limit(eapp):
    from app.blueprints.api.public import SCHOOL_INFO_PER_MINUTE
    c = eapp.test_client()
    for i in range(SCHOOL_INFO_PER_MINUTE):
        assert c.get("/api/public/school-info", base_url=f"http://guess{i}.manasety.ai").status_code == 404
    r = c.get("/api/public/school-info", base_url="http://guess-more.manasety.ai")
    assert r.status_code == 429 and r.json["error"] == "rate_limited"


def test_app_config_answers_for_a_blocked_school(eapp, two_schools):
    A = two_schools["A"]
    set_state(eapp, A["school"].id, "suspended")
    try:
        r = eapp.test_client().get("/api/public/app-config", base_url=host(A))
        assert r.status_code == 200 and "min_app_version" in r.json
    finally:
        from app.extensions import db
        from app.models import School
        with eapp.app_context():
            s = db.session.get(School, A["school"].id)
            s.status, s.is_active = "active", True
            db.session.commit()
            db.session.remove()
        set_state(eapp, A["school"].id, "active")


def test_api_login_finds_the_user_of_the_host_school(eapp, two_schools):
    """Same username in A and B: the app on B's host gets B's account."""
    from app.extensions import db
    from app.models import User
    A, B = two_schools["A"], two_schools["B"]
    name = f"same-{secrets.token_hex(3)}"
    pw_a, pw_b = secrets.token_urlsafe(12), secrets.token_urlsafe(12)
    with eapp.app_context():
        ids = []
        for bundle, pw in ((A, pw_a), (B, pw_b)):
            u = User(school_id=bundle["school"].id, role_id=bundle["users"]["admin"].role_id,
                     username=name, full_name=name, is_active=True)
            u.set_password(pw)
            db.session.add(u)
            db.session.flush()
            ids.append(u.id)
        db.session.commit()
    try:
        c = eapp.test_client()
        r = c.post("/api/auth/login", base_url=host(B), json={"username": name, "password": pw_b})
        assert r.status_code == 200 and r.json["user"]["id"] == ids[1]
        r = c.post("/api/auth/login", base_url=host(B), json={"username": name, "password": pw_a})
        assert r.status_code == 401                       # A's password never works on B
    finally:
        with eapp.app_context():
            User.query.filter(User.id.in_(ids)).delete(synchronize_session=False)
            db.session.commit()
            db.session.remove()


def test_grace_allowlisted_write_is_not_a_flush_guard_offender(eapp, two_schools, monkeypatch, caplog):
    import logging
    from app.services.auth_jwt import issue_token
    monkeypatch.setitem(eapp.config, "SUBSCRIPTION_RO_FLUSH_GUARD", "enforce")
    A = two_schools["A"]
    set_state(eapp, A["school"].id, "grace")
    with eapp.app_context():
        tok = issue_token(A["users"]["admin"])
    caplog.set_level(logging.WARNING)
    r = eapp.test_client().post("/api/auth/device-token", base_url=host(A),
                                headers={"Authorization": f"Bearer {tok}"},
                                json={"token": "t-" + secrets.token_hex(8), "platform": "android", "app": "teacher"})
    set_state(eapp, A["school"].id, "active")
    assert r.status_code in (200, 201), r.data[:200]       # a real hit, not a 404
    assert "would refuse" not in caplog.text
