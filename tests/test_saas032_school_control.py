"""SAAS-032 — full school control: the dangerous-action pattern,
suspend / resume / archive / end sessions, slug change with redirect and
reservation, editing, staff tools, notes / contacts / tags isolation,
targeted announcements. Two schools: B is never touched."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

from isolation_harness import host
from test_saas026_subscriptions import CONSOLE, _console_client, console  # noqa: F401


@pytest.fixture
def capp(console):
    return console


def _owner(app):
    c, uid = _console_client(app, "owner")
    with c.session_transaction(base_url=CONSOLE) as s:
        s["sa_totp_at"] = time.time()
    return c, uid


def _act(c, school, action, **form):
    data = {"reason": "contract ended", "confirm_slug": school.slug}
    data.update(form)
    return c.post(f"/superadmin/schools/{school.id}/lifecycle/{action}", base_url=CONSOLE, data=data)


def _status(app, sid):
    from app.extensions import db
    from app.models import School
    with app.app_context():
        s = db.session.get(School, sid)
        out = (s.status, s.auth_epoch, s.slug)
        db.session.remove()
        return out


@pytest.fixture(autouse=True)
def _restore(capp, two_schools):
    yield
    from app.extensions import db
    from app.models import (PlatformAnnouncement, PlatformAuditLog, PlatformSchoolNote, School,
                            SchoolContact, SchoolSlugHistory, SchoolTag)
    with capp.app_context():
        for key, slug in (("A", "alpha"), ("B", "beta")):
            s = db.session.get(School, two_schools[key]["school"].id)
            s.status, s.is_active, s.slug = "active", True, slug
        for m in (SchoolSlugHistory, PlatformSchoolNote, SchoolContact, SchoolTag, PlatformAnnouncement):
            m.query.delete()
        PlatformAuditLog.query.filter(PlatformAuditLog.target_school_id.isnot(None)).delete()
        db.session.commit()
        db.session.remove()


# ─── the dangerous-action pattern ────────────────────────────────────

def test_dangerous_action_needs_reason_slug_totp_owner(capp, two_schools):
    A = two_schools["A"]["school"]
    c, _ = _owner(capp)
    for form in ({"reason": ""}, {"confirm_slug": "beta"}, {"confirm_slug": ""}):
        _act(c, A, "suspend", **form)
        assert _status(capp, A.id)[0] == "active", form
    stale, _ = _console_client(capp, "owner")
    with stale.session_transaction(base_url=CONSOLE) as s:
        s["sa_totp_at"] = time.time() - 601
    _act(stale, A, "suspend")
    assert _status(capp, A.id)[0] == "active"
    sup, _ = _console_client(capp, "support")
    assert _act(sup, A, "suspend").status_code == 403
    # never via GET
    assert c.get(f"/superadmin/schools/{A.id}/lifecycle/suspend", base_url=CONSOLE).status_code == 405


def test_rate_limit_five_per_hour(capp, two_schools, monkeypatch):
    from app.services import platform_actions as pact
    monkeypatch.setattr(pact, "DANGEROUS_PER_HOUR", 2)
    A = two_schools["A"]["school"]
    c, _ = _owner(capp)
    _act(c, A, "end_sessions")
    _act(c, A, "end_sessions")
    epoch = _status(capp, A.id)[1]
    r = _act(c, A, "end_sessions")
    assert _status(capp, A.id)[1] == epoch and r.status_code == 302


# ─── lifecycle ───────────────────────────────────────────────────────

def test_suspend_resume_archive(capp, two_schools, login_as, monkeypatch):
    from app.extensions import db
    from app.models import PlatformAuditLog, SchoolSubscriptionEvent, Student
    monkeypatch.setitem(capp.config, "TENANT_RESOLUTION_MODE", "enforce")
    A, B = two_schools["A"], two_schools["B"]
    c, _ = _owner(capp)
    ua = capp.test_client()
    login_as(ua, A["users"]["admin"], base_url=host(A))
    _act(c, A["school"], "suspend")
    assert _status(capp, A["school"].id)[0] == "suspended"
    assert ua.get("/", base_url=host(A)).status_code in (302, 403)     # session killed / blocked
    assert capp.test_client().get("/auth/login", base_url=host(A)).status_code == 403
    assert capp.test_client().get("/auth/login", base_url=host(B)).status_code == 200
    _act(c, A["school"], "resume")
    assert _status(capp, A["school"].id)[0] == "active"
    with capp.app_context():
        n = Student.query.filter_by(school_id=A["school"].id).count()
    _act(c, A["school"], "archive")
    assert _status(capp, A["school"].id)[0] == "archived"
    assert capp.test_client().get("/auth/login", base_url=host(A)).status_code == 404
    _act(c, A["school"], "unarchive")
    assert _status(capp, A["school"].id)[0] == "suspended"
    with capp.app_context():
        assert Student.query.filter_by(school_id=A["school"].id).count() == n     # nothing lost
        actions = {a.action for a in PlatformAuditLog.query.filter_by(target_school_id=A["school"].id)}
        assert {"school_suspended", "school_resumed", "school_archived", "school_unarchived"} <= actions
        kinds = [e.kind for e in SchoolSubscriptionEvent.query.filter_by(school_id=A["school"].id)]
        assert kinds.count("suspended") == 1             # no duplicate events
        db.session.remove()


def test_end_all_sessions_without_suspending(capp, two_schools, login_as):
    A = two_schools["A"]
    c, _ = _owner(capp)
    before = _status(capp, A["school"].id)
    _act(c, A["school"], "end_sessions")
    after = _status(capp, A["school"].id)
    assert after[0] == "active" and after[1] == before[1] + 1


def test_blocked_page_shows_console_message(capp, two_schools, monkeypatch):
    monkeypatch.setitem(capp.config, "TENANT_RESOLUTION_MODE", "enforce")
    A = two_schools["A"]["school"]
    c, _ = _owner(capp)
    from app.extensions import db
    from app.models import School
    with capp.app_context():
        db.session.get(School, A.id).blocked_message = "المدرسة في صيانة حتى الأحد"
        db.session.commit()
    _act(c, A, "suspend")
    page = capp.test_client().get("/auth/login", base_url=host(two_schools["A"]))
    assert page.status_code == 403 and "المدرسة في صيانة حتى الأحد".encode() in page.data


# ─── slug change ─────────────────────────────────────────────────────

def test_slug_change_redirects_reserves_and_closes_sessions(capp, two_schools, monkeypatch):
    from app.extensions import db
    from app.models import PlatformJob, SchoolSlugHistory
    from app.services.provisioning import slug_available
    monkeypatch.setitem(capp.config, "TENANT_RESOLUTION_MODE", "enforce")
    A = two_schools["A"]["school"]
    c, _ = _owner(capp)
    epoch = _status(capp, A.id)[1]
    r = c.post(f"/superadmin/schools/{A.id}/slug", base_url=CONSOLE,
               data={"reason": "rebrand", "confirm_slug": "alpha", "new_slug": "alpha-new"})
    assert r.status_code == 302
    status, new_epoch, slug = _status(capp, A.id)
    assert slug == "alpha-new" and new_epoch == epoch + 1
    old = capp.test_client()
    r = old.get("/students?page=2", base_url="http://alpha.manasety.ai")
    assert r.status_code == 301 and r.headers["Location"] == "https://alpha-new.manasety.ai/students?page=2"
    r = old.get("/api/me", base_url="http://alpha.manasety.ai")
    assert r.status_code == 410 and r.json == {"error": "school_moved", "new_host": "alpha-new.manasety.ai"}
    assert old.post("/auth/login", base_url="http://alpha.manasety.ai").status_code == 404
    with capp.app_context():
        ok, msg = slug_available("alpha")
        assert not ok and "محجوز" in msg
        assert PlatformJob.query.filter_by(kind="nginx_sync", status="pending").count() >= 1
        # window over → plain unknown
        h = SchoolSlugHistory.query.filter_by(old_slug="alpha").one()
        h.redirect_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.session.commit()
        PlatformJob.query.delete()
        db.session.commit()
        db.session.remove()
    assert capp.test_client().get("/students", base_url="http://alpha.manasety.ai").status_code == 404


def test_slug_change_validates_new_slug(capp, two_schools):
    A = two_schools["A"]["school"]
    c, _ = _owner(capp)
    for bad in ("beta", "console", "-x"):
        c.post(f"/superadmin/schools/{A.id}/slug", base_url=CONSOLE,
               data={"reason": "x", "confirm_slug": "alpha", "new_slug": bad})
        assert _status(capp, A.id)[2] == "alpha", bad


# ─── edit ────────────────────────────────────────────────────────────

def test_edit_school_audits_before_after_and_ignores_secrets(capp, two_schools):
    from app.extensions import db
    from app.models import PlatformAuditLog, School
    A = two_schools["A"]["school"]
    c, _ = _owner(capp)
    form = {"name": "Alpha Renamed", "currency": "EGP", "invoice_prefix": "INV", "fiscal_year_start_month": "9",
            "default_tax_rate": "0", "attendance_mode": "daily", "smtp_password_encrypted": "evil",
            "smtp_host": "evil.example"}
    r = c.post(f"/superadmin/schools/{A.id}/edit", base_url=CONSOLE, data=form)
    assert r.status_code == 302
    with capp.app_context():
        s = db.session.get(School, A.id)
        assert s.name == "Alpha Renamed" and s.smtp_host != "evil.example"
        log = PlatformAuditLog.query.filter_by(action="school_edited", target_school_id=A.id).one()
        assert log.meta["after"]["name"] == "Alpha Renamed" and log.meta["before"]["name"] == "Alpha School"
        s.name = "Alpha School"
        db.session.commit()
        db.session.remove()
    page = c.get(f"/superadmin/schools/{A.id}/edit", base_url=CONSOLE)
    assert b'name="smtp' not in page.data


def test_edit_validates_and_is_owner_only(capp, two_schools):
    A = two_schools["A"]["school"]
    c, _ = _owner(capp)
    r = c.post(f"/superadmin/schools/{A.id}/edit", base_url=CONSOLE,
               data={"name": "", "currency": "EGP", "invoice_prefix": "INV", "attendance_mode": "daily"})
    assert r.status_code == 400
    sup, _ = _console_client(capp, "support")
    assert sup.get(f"/superadmin/schools/{A.id}/edit", base_url=CONSOLE).status_code == 403


# ─── staff tools ─────────────────────────────────────────────────────

def test_staff_tools(capp, two_schools):
    from app.extensions import db
    from app.models import AccountSetupToken, User
    A = two_schools["A"]
    sup, _ = _console_client(capp, "support")
    page = sup.get(f"/superadmin/schools/{A['school'].id}/staff", base_url=CONSOLE)
    assert page.status_code == 200
    assert A["users"]["admin"].full_name.encode() in page.data
    assert A["users"]["parent"].full_name.encode() not in page.data
    assert b"password_hash" not in page.data and b"$2b$" not in page.data
    uid = A["users"]["teacher"].id
    with capp.app_context():
        u = db.session.get(User, uid)
        u.failed_attempts, u.locked_until = 5, datetime.utcnow() + timedelta(hours=1)
        db.session.commit()
    sup.post(f"/superadmin/schools/{A['school'].id}/staff/{uid}/unlock", base_url=CONSOLE)
    r = sup.post(f"/superadmin/schools/{A['school'].id}/staff/{uid}/setup_link", base_url=CONSOLE)
    assert r.status_code == 200 and b"/set-password/" in r.data
    with capp.app_context():
        u = db.session.get(User, uid)
        assert u.locked_until is None and u.failed_attempts == 0
        assert AccountSetupToken.query.filter_by(user_id=uid, used_at=None).count() == 1
        db.session.remove()
    # a parent / another school's user is not reachable
    pid = A["users"]["parent"].id
    assert sup.post(f"/superadmin/schools/{A['school'].id}/staff/{pid}/deactivate",
                    base_url=CONSOLE).status_code == 404
    bid = two_schools["B"]["users"]["admin"].id
    assert sup.post(f"/superadmin/schools/{A['school'].id}/staff/{bid}/deactivate",
                    base_url=CONSOLE).status_code == 404
    fin, _ = _console_client(capp, "finance")
    assert fin.get(f"/superadmin/schools/{A['school'].id}/staff", base_url=CONSOLE).status_code == 403


# ─── notes / contacts / tags ─────────────────────────────────────────

def test_notes_never_reach_a_school_host(capp, two_schools, login_as, monkeypatch):
    monkeypatch.setitem(capp.config, "TENANT_RESOLUTION_MODE", "enforce")
    A = two_schools["A"]
    c, _ = _owner(capp)
    c.post(f"/superadmin/schools/{A['school'].id}/notes", base_url=CONSOLE, data={"body": "SECRET-NOTE-123"})
    c.post(f"/superadmin/schools/{A['school'].id}/tags", base_url=CONSOLE, data={"tags": "VIP, متأخر في الدفع"})
    c.post(f"/superadmin/schools/{A['school'].id}/contacts", base_url=CONSOLE,
           data={"name": "CONTACT-XYZ", "email": "billing@alpha.test", "is_billing_contact": "1"})
    detail = c.get(f"/superadmin/schools/{A['school'].id}", base_url=CONSOLE)
    assert b"SECRET-NOTE-123" in detail.data and b"CONTACT-XYZ" in detail.data
    ua = capp.test_client()
    login_as(ua, A["users"]["admin"], base_url=host(A))
    for path in ("/", "/admin/settings", "/admin/audit-log", "/admin/users"):
        page = ua.get(path, base_url=host(A), follow_redirects=True)
        assert b"SECRET-NOTE-123" not in page.data and b"CONTACT-XYZ" not in page.data, path
    listing = c.get("/superadmin/schools?tag=VIP", base_url=CONSOLE)
    assert b"alpha" in listing.data and b">beta<" not in listing.data


# ─── announcements ───────────────────────────────────────────────────

def test_targeted_announcement(capp, two_schools, login_as, monkeypatch):
    monkeypatch.setitem(capp.config, "TENANT_RESOLUTION_MODE", "enforce")
    A, B = two_schools["A"], two_schools["B"]
    c, _ = _owner(capp)
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("Africa/Cairo")).replace(tzinfo=None)
    c.post("/superadmin/announcements", base_url=CONSOLE, data={
        "message_ar": "صيانة الليلة ANN-1", "severity": "warning",
        "starts_at": (now - timedelta(hours=1)).isoformat(timespec="minutes"),
        "ends_at": (now + timedelta(hours=5)).isoformat(timespec="minutes"),
        "school_ids": [str(A["school"].id)]})
    c.post("/superadmin/announcements", base_url=CONSOLE, data={
        "message_ar": "انتهت ANN-OLD", "severity": "info",
        "starts_at": (now - timedelta(days=3)).isoformat(timespec="minutes"),
        "ends_at": (now - timedelta(days=1)).isoformat(timespec="minutes")})
    ua, ub = capp.test_client(), capp.test_client()
    login_as(ua, A["users"]["admin"], base_url=host(A))
    login_as(ub, B["users"]["admin"], base_url=host(B))
    pa_ = ua.get("/students", base_url=host(A), follow_redirects=True).data.decode()
    pb_ = ub.get("/students", base_url=host(B), follow_redirects=True).data.decode()
    assert "ANN-1" in pa_ and "ANN-1" not in pb_
    assert "ANN-OLD" not in pa_ and "ANN-OLD" not in pb_
    sup, _ = _console_client(capp, "support")
    assert sup.get("/superadmin/announcements", base_url=CONSOLE).status_code == 403
