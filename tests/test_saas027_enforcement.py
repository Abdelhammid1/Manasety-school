"""SAAS-027 — subscription enforcement matrix.

state × (web GET / POST, API GET / POST, files, login page, cron),
the read-only allow-list, the flush guard, the auth_epoch kill switch,
log mode, and two-school isolation (blocking A never touches B).
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from isolation_harness import host

ALL_STATES = ("active", "trial", "grace", "expired", "not_started", "no_subscription", "suspended")
BLOCKED = {"expired", "not_started", "no_subscription", "suspended"}


@pytest.fixture
def eapp(app, monkeypatch):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    return app


def set_state(app, school_id, state):
    """Put school `school_id` into `state` by editing its rows directly."""
    from app.extensions import db
    from app.models import School, SchoolSubscription
    from app.services.subscriptions import get_settings, platform_today
    with app.app_context():
        school = db.session.get(School, school_id)
        sub = SchoolSubscription.query.filter_by(school_id=school_id, is_current=True).first()
        today = platform_today(get_settings())
        sub.starts_on, sub.ends_on, sub.trial_ends_on, sub.grace_days = today - timedelta(days=60), None, None, 14
        if state == "trial":
            sub.ends_on = sub.trial_ends_on = today + timedelta(days=10)
        elif state == "grace":
            sub.ends_on = today - timedelta(days=1)
        elif state == "expired":
            sub.ends_on = today - timedelta(days=30)
        elif state == "not_started":
            sub.starts_on = today + timedelta(days=5)
        elif state == "no_subscription":
            sub.is_current = False
        elif state == "suspended":
            school.status, school.is_active = "suspended", False
        db.session.commit()
        db.session.remove()


def _token(app, user):
    from app.services.auth_jwt import issue_token
    with app.app_context():
        return issue_token(user)


def _bearer(app, user):
    return {"Authorization": f"Bearer {_token(app, user)}"}


@pytest.mark.parametrize("state", ALL_STATES)
def test_state_matrix(eapp, two_schools, login_as, state):
    A, B = two_schools["A"], two_schools["B"]
    set_state(eapp, A["school"].id, state)
    admin = A["users"]["admin"]
    hdr = _bearer(eapp, admin)
    blocked, read_only = state in BLOCKED, state == "grace"

    c = eapp.test_client()
    login_as(c, admin, base_url=host(A))
    web_get = c.get("/", base_url=host(A))
    web_post = c.post("/students/new", base_url=host(A), data={})
    api_get = c.get("/api/me", base_url=host(A), headers=hdr)
    api_post = c.post("/api/me/full-name", base_url=host(A), headers=hdr, json={"full_name": "x"})
    files = c.get("/files/anything.pdf", base_url=host(A))
    login_page = eapp.test_client().get("/auth/login", base_url=host(A))

    if blocked:
        assert web_get.status_code == 403
        assert web_post.status_code == 403
        assert api_get.status_code == 403 and api_get.json["error"] == "subscription_blocked"
        assert api_get.json["reason"] == state
        assert api_post.status_code == 403 and api_post.json["error"] == "subscription_blocked"
        assert files.status_code == 404
        assert login_page.status_code == 403
        assert b'name="password"' not in login_page.data       # no login form
    else:
        assert web_get.status_code in (200, 302)
        assert api_get.status_code == 200
        assert login_page.status_code == 200
        if read_only:
            assert web_post.status_code == 403
            assert api_post.status_code == 403
            assert api_post.json["error"] == "subscription_read_only"
        else:
            assert web_post.status_code != 403
            assert api_post.status_code != 403

    # B is never affected by A's state
    cb = eapp.test_client()
    login_as(cb, B["users"]["admin"], base_url=host(B))
    assert cb.get("/", base_url=host(B)).status_code in (200, 302)
    assert cb.get("/api/me", base_url=host(B), headers=_bearer(eapp, B["users"]["admin"])).status_code == 200


def test_grace_refuses_every_write_route_except_allowlist(eapp, two_schools, login_as):
    """No POST/PUT/PATCH/DELETE route on a school host escapes read-only."""
    from app.services.subscription_enforcement import READ_ONLY_ALLOWED_ENDPOINTS, WRITE_METHODS
    A = two_schools["A"]
    set_state(eapp, A["school"].id, "grace")
    c = eapp.test_client()
    login_as(c, A["users"]["admin"], base_url=host(A))
    hdr = _bearer(eapp, A["users"]["admin"])
    from werkzeug.routing import IntegerConverter
    adapter = eapp.url_map.bind("localhost")
    escaped, checked = [], 0
    for rule in eapp.url_map.iter_rules():
        ep = rule.endpoint
        if ep in READ_ONLY_ALLOWED_ENDPOINTS or ep.startswith("superadmin.") or ep == "static":
            continue
        values = {a: 1 if isinstance(rule._converters[a], IntegerConverter) else "x"
                  for a in rule.arguments}
        url = adapter.build(ep, values, force_external=False)
        for method in sorted((rule.methods or set()) & WRITE_METHODS):
            r = c.open(url, method=method, base_url=host(A), headers=hdr)
            checked += 1
            if r.status_code != 403:
                escaped.append((ep, method, url, r.status_code))
    assert checked > 50
    assert not escaped, escaped


def test_grace_allows_sign_in(eapp, two_schools):
    A = two_schools["A"]
    set_state(eapp, A["school"].id, "grace")
    c = eapp.test_client()
    r = c.post("/auth/login", base_url=host(A),
               data={"username": A["users"]["admin"].username, "password": "test-password-12345"})
    assert r.status_code == 302
    r = c.post("/api/auth/login", base_url=host(A),
               json={"username": A["users"]["admin"].username, "password": "test-password-12345"})
    assert r.status_code != 403


def test_log_mode_only_observes(app, two_schools, login_as, monkeypatch):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "log")
    A = two_schools["A"]
    set_state(app, A["school"].id, "expired")
    c = app.test_client()
    login_as(c, A["users"]["admin"], base_url=host(A))
    assert c.get("/", base_url=host(A)).status_code in (200, 302)


def test_cron_skips_blocked_school(eapp, two_schools):
    from app.blueprints.cron.routes import run_tick
    A, B = two_schools["A"], two_schools["B"]
    set_state(eapp, A["school"].id, "expired")
    with eapp.app_context():
        res = run_tick()
    assert res["schools"][A["school"].id] == {"status": "skipped", "reason": "expired"}
    assert res["schools"][B["school"].id]["status"] == "ok"
    assert res["ok"] is True


# ─── flush guard ─────────────────────────────────────────────────────

@pytest.mark.parametrize("mode", ["log", "enforce"])
def test_flush_guard(eapp, two_schools, monkeypatch, mode, caplog):
    from flask import g
    from app.extensions import db
    from app.models import Student, User
    monkeypatch.setitem(eapp.config, "SUBSCRIPTION_RO_FLUSH_GUARD", mode)
    A = two_schools["A"]
    with eapp.test_request_context("/", base_url=host(A)):
        g.subscription_read_only = True
        # login bookkeeping on users is always allowed
        u = db.session.get(User, A["users"]["admin"].id)
        u.failed_attempts = 1
        db.session.flush()
        st = Student.query.filter_by(school_id=A["school"].id).first()
        st.full_name = st.full_name + "!"
        if mode == "enforce":
            with pytest.raises(PermissionError):
                db.session.flush()
        else:
            db.session.flush()
            assert "would refuse" in caplog.text
        db.session.rollback()


# ─── kill switch ─────────────────────────────────────────────────────

def test_suspend_kills_sessions_and_tokens(eapp, two_schools, login_as):
    from app.extensions import db
    from app.models import School
    from app.services.subscriptions import resume_school, suspend_school
    A, B = two_schools["A"], two_schools["B"]
    admin = A["users"]["admin"]
    old_hdr = _bearer(eapp, admin)
    c = eapp.test_client()
    login_as(c, admin, base_url=host(A))
    cb = eapp.test_client()
    login_as(cb, B["users"]["admin"], base_url=host(B))
    b_hdr = _bearer(eapp, B["users"]["admin"])

    with eapp.app_context():
        s = db.session.get(School, A["school"].id)
        suspend_school(s, None, "test")
        assert s.auth_epoch == 1
        db.session.commit()
        with pytest.raises(Exception):
            suspend_school(s, None, "again")
        resume_school(s, None, "test")
        db.session.commit()
        db.session.remove()

    # resumed school — but the old session and the old token are dead
    r = c.get("/", base_url=host(A))
    assert r.status_code == 302 and "/auth/login" in r.headers["Location"]
    assert c.get("/api/me", base_url=host(A), headers=old_hdr).status_code == 401
    # a fresh token works
    assert c.get("/api/me", base_url=host(A), headers=_bearer(eapp, admin)).status_code == 200
    # school B untouched
    assert cb.get("/", base_url=host(B)).status_code in (200, 302)
    assert cb.get("/", base_url=host(B)).status_code != 302 or \
        "/auth/login" not in cb.get("/", base_url=host(B)).headers.get("Location", "")
    assert cb.get("/api/me", base_url=host(B), headers=b_hdr).status_code == 200


def test_login_stamps_epoch(eapp, two_schools):
    from app.extensions import db
    from app.models import School
    A = two_schools["A"]
    with eapp.app_context():
        db.session.get(School, A["school"].id).auth_epoch = 3
        db.session.commit()
        db.session.remove()
    c = eapp.test_client()
    r = c.post("/auth/login", base_url=host(A),
               data={"username": A["users"]["admin"].username, "password": "test-password-12345"})
    assert r.status_code == 302
    with c.session_transaction(base_url=host(A)) as s:
        assert s["ae"] == 3
    assert c.get("/", base_url=host(A)).status_code == 200


def test_reason_text_comes_from_one_place():
    from app.services.subscription_enforcement import MESSAGES_AR
    assert BLOCKED <= set(MESSAGES_AR)
