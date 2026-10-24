"""A login writes one short, attributed security event — not a full copy
of the user (email, phone…) as an `update User` row. Updates to any
other field of a user are recorded in full as before."""

from __future__ import annotations

import pytest

from isolation_harness import host

PASSWORD = "test-password-12345"          # conftest's shared test-user password


@pytest.fixture
def aapp(app, monkeypatch):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    return app


def _rows(app, user_id):
    from app.extensions import db
    from app.models import AuditLog
    with app.app_context():
        rows = (AuditLog.query.filter_by(entity_type="User", entity_id=user_id)
                .order_by(AuditLog.id).all())
        out = [(r.action, r.user_id, r.school_id, r.old_value, r.new_value) for r in rows]
        db.session.remove()
    return out


def _web(app, bundle, username, password):
    return app.test_client().post("/auth/login", base_url=host(bundle),
                                  data={"username": username, "password": password})


def _new(app, user_id, before):
    return _rows(app, user_id)[len(before):]


def test_web_login_writes_one_short_event_and_no_snapshot(aapp, two_schools):
    A = two_schools["A"]
    u = A["users"]["teacher"]
    before = _rows(aapp, u.id)
    assert _web(aapp, A, u.username, PASSWORD).status_code == 302
    new = _new(aapp, u.id, before)
    assert [r[0] for r in new] == ["login"], new
    _, user_id, school_id, old, detail = new[0]
    assert user_id == u.id and school_id == A["school"].id and old is None
    assert detail == {"via": "web"}                          # no email / phone / snapshot


def test_api_login_writes_one_short_event(aapp, two_schools):
    A = two_schools["A"]
    u = A["users"]["teacher"]
    before = _rows(aapp, u.id)
    r = aapp.test_client().post("/api/auth/login", base_url=host(A),
                                json={"username": u.username, "password": PASSWORD})
    assert r.status_code == 200
    new = _new(aapp, u.id, before)
    assert [(n[0], n[1], n[4]) for n in new] == [("login", u.id, {"via": "api"})], new


def test_failures_and_the_lock(aapp, two_schools, monkeypatch):
    monkeypatch.setitem(aapp.config, "LOCKOUT_MAX_ATTEMPTS", 2)
    A = two_schools["A"]
    u = A["users"]["student"]
    before = _rows(aapp, u.id)
    assert _web(aapp, A, u.username, "wrong-1").status_code == 401
    assert _web(aapp, A, u.username, "wrong-2").status_code == 401       # reaches the limit
    assert _web(aapp, A, u.username, PASSWORD).status_code == 423        # locked now
    new = _new(aapp, u.id, before)
    assert [(n[0], n[1], n[4]) for n in new] == [
        ("login_failed", u.id, {"via": "web", "reason": "password"}),
        ("login_locked", u.id, {"via": "web"}),
        ("login_failed", u.id, {"via": "web", "reason": "locked"}),
    ], new
    r = aapp.test_client().post("/api/auth/login", base_url=host(A),
                                json={"username": u.username, "password": "wrong"})
    assert r.status_code == 401
    assert _new(aapp, u.id, before)[-1][0] == "login_failed"
    # an unknown name: nobody to attribute, nothing written
    from app.extensions import db
    from app.models import AuditLog
    with aapp.app_context():
        n = AuditLog.query.count()
        db.session.remove()
    _web(aapp, A, "no-such-user-xyz", "x")
    with aapp.app_context():
        assert AuditLog.query.count() == n
        db.session.remove()


def test_other_user_changes_are_recorded_in_full(aapp, two_schools):
    """A role / password / email change (even alongside the login
    counters) keeps the full update row, with the hash redacted."""
    from datetime import datetime
    from app.extensions import db
    from app.models import User
    A = two_schools["A"]
    uid = A["users"]["parent"].id
    before = _rows(aapp, uid)
    with aapp.app_context():
        u = db.session.get(User, uid)
        assert u is not None
        u.set_password("another-password-678")
        u.email = "changed@a.test"
        u.last_login_at = datetime.utcnow()
        db.session.commit()
        db.session.remove()
    new = _new(aapp, uid, before)
    assert [n[0] for n in new] == ["update"], new
    old, snap = new[0][3], new[0][4]
    assert snap["email"] == "changed@a.test" and snap["password_hash"] == "[REDACTED]"
    assert old["password_hash"] == "[REDACTED]" and "last_login_at" in old


def test_login_in_read_only_school_still_works(aapp, two_schools):
    from test_saas027_enforcement import set_state
    A = two_schools["A"]
    set_state(aapp, A["school"].id, "grace")
    u = A["users"]["admin"]
    before = _rows(aapp, u.id)
    assert _web(aapp, A, u.username, PASSWORD).status_code == 302
    assert [n[0] for n in _new(aapp, u.id, before)] == ["login"]


def test_school_audit_page_opens(aapp, two_schools, login_as):
    A = two_schools["A"]
    _web(aapp, A, A["users"]["teacher"].username, PASSWORD)
    c = aapp.test_client()
    login_as(c, A["users"]["admin"], base_url=host(A))
    assert c.get("/admin/audit", base_url=host(A)).status_code == 200
    assert c.get("/admin/audit?action=login", base_url=host(A)).status_code == 200
