"""SAAS-026 — plans, subscriptions and the single effective_state()."""

from __future__ import annotations

import secrets
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services.subscriptions import effective_state

CONSOLE = "http://console.manasety.ai"
D = date(2026, 10, 1)


def _sub(starts=D, ends=date(2026, 10, 31), trial=None, grace=14, current=True):
    return SimpleNamespace(starts_on=starts, ends_on=ends, trial_ends_on=trial,
                           grace_days=grace, is_current=current)


ACTIVE = SimpleNamespace(status="active")


@pytest.mark.parametrize("today,school,sub,state,read_only,blocked", [
    (date(2026, 9, 30), ACTIVE, _sub(), "not_started", False, True),
    (D, ACTIVE, _sub(), "active", False, False),                               # first day
    (date(2026, 10, 31), ACTIVE, _sub(), "active", False, False),              # last day (inclusive)
    (date(2026, 11, 1), ACTIVE, _sub(), "grace", True, False),                 # last day + 1
    (date(2026, 11, 14), ACTIVE, _sub(), "grace", True, False),                # last grace day
    (date(2026, 11, 15), ACTIVE, _sub(), "expired", False, True),              # grace + 1
    (date(2030, 1, 1), ACTIVE, _sub(ends=None), "active", False, False),       # open-ended
    (D, SimpleNamespace(status="suspended"), _sub(), "suspended", False, True),
    (D, SimpleNamespace(status="archived"), _sub(), "archived", False, True),
    (D, SimpleNamespace(status="weird"), _sub(), "suspended", False, True),    # unknown → blocked
    (D, ACTIVE, None, "no_subscription", False, True),
    (D, ACTIVE, _sub(current=False), "no_subscription", False, True),
    (date(2026, 10, 5), ACTIVE, _sub(trial=date(2026, 10, 10)), "trial", False, False),
    (date(2026, 11, 1), ACTIVE, _sub(grace=0), "expired", False, True),
])
def test_effective_state_table(today, school, sub, state, read_only, blocked):
    st = effective_state(school, sub, today)
    assert (st.state, st.read_only, st.blocked) == (state, read_only, blocked)


def test_days_left_counts():
    assert effective_state(ACTIVE, _sub(), date(2026, 10, 30)).days_left == 1
    assert effective_state(ACTIVE, _sub(), date(2026, 11, 13)).grace_days_left == 1


def test_today_uses_platform_timezone_not_utc():
    from app.services.subscriptions import DEFAULT_SETTINGS, platform_today
    # 23:30 UTC on Oct 31 is already Nov 1 in Cairo (UTC+2/+3).
    late = datetime(2026, 10, 31, 23, 30, tzinfo=timezone.utc)
    assert platform_today(DEFAULT_SETTINGS, now=late) == date(2026, 11, 1)
    st = effective_state(ACTIVE, _sub(), platform_today(DEFAULT_SETTINGS, now=late))
    assert st.state == "grace"


# ─── service actions on real rows ────────────────────────────────────

@pytest.fixture
def sub_world(app, two_schools):
    """An internal-like plan + a current subscription for A and B."""
    from app.extensions import db
    from app.models import Plan
    from app.services import subscriptions as subs
    with app.app_context():
        plan = Plan(code=f"t-{secrets.token_hex(3)}", name_ar="خطة اختبار", modules=["*"],
                    billing_cycle="monthly", is_active=True)
        db.session.add(plan); db.session.flush()
        for key in ("A", "B"):
            school = db.session.get(__import__("app.models", fromlist=["School"]).School,
                                    two_schools[key]["school"].id)
            subs.create_subscription(school, plan, starts_on=date(2026, 9, 1),
                                     ends_on=date(2026, 12, 31), reason="test")
        db.session.commit()
        pid = plan.id
        db.session.remove()
    yield {**two_schools, "plan_id": pid}
    with app.app_context():
        from app.models import SchoolSubscription, SchoolSubscriptionEvent
        sids = [two_schools[k]["school"].id for k in ("A", "B")]
        SchoolSubscriptionEvent.query.filter(SchoolSubscriptionEvent.school_id.in_(sids)).delete(
            synchronize_session=False)
        SchoolSubscription.query.filter(SchoolSubscription.school_id.in_(sids)).delete(
            synchronize_session=False)
        Plan.query.filter_by(id=pid).delete()
        db.session.commit()
        db.session.remove()


def _school(world, key):
    from app.extensions import db
    from app.models import School
    return db.session.get(School, world[key]["school"].id)


def test_renew_extend_change_trial_keep_history(app, sub_world):
    from app.extensions import db
    from app.models import Plan, SchoolSubscription, SchoolSubscriptionEvent
    from app.services import subscriptions as subs
    with app.app_context():
        a = _school(sub_world, "A")
        subs.renew(a, None, "paid", months=12, today=date(2026, 10, 1))
        cur = subs.current_subscription(a.id)
        assert (cur.starts_on, cur.ends_on) == (date(2027, 1, 1), date(2027, 12, 31))
        subs.extend(a, None, 10, "goodwill")
        assert subs.current_subscription(a.id).ends_on == date(2028, 1, 10)
        other = Plan(code=f"o-{secrets.token_hex(3)}", name_ar="أخرى", modules=["students"],
                     billing_cycle="yearly", is_active=True)
        db.session.add(other); db.session.flush()
        subs.change_plan(a, other, None, "upgrade")
        assert subs.current_subscription(a.id).plan_id == other.id
        db.session.commit()
        rows = SchoolSubscription.query.filter_by(school_id=a.id).all()
        assert sum(r.is_current for r in rows) == 1 and len(rows) == 4
        kinds = [e.kind for e in SchoolSubscriptionEvent.query.filter_by(school_id=a.id)
                 .order_by(SchoolSubscriptionEvent.id)]
        assert kinds == ["created", "renewed", "extended", "plan_changed"]
        # B untouched
        assert subs.current_subscription(sub_world["B"]["school"].id).ends_on == date(2026, 12, 31)
        SchoolSubscription.query.filter_by(plan_id=other.id).update({"plan_id": sub_world["plan_id"]})
        db.session.delete(other)
        db.session.commit()
        db.session.remove()


def test_renew_after_expiry_starts_today(app, sub_world):
    from app.extensions import db
    from app.services import subscriptions as subs
    with app.app_context():
        a = _school(sub_world, "A")
        subs.renew(a, None, None, months=1, today=date(2027, 3, 15))
        cur = subs.current_subscription(a.id)
        assert (cur.starts_on, cur.ends_on) == (date(2027, 3, 15), date(2027, 4, 14))
        db.session.rollback()
        db.session.remove()


@pytest.mark.parametrize("call,needle", [
    (lambda subs, a: subs.extend(a, None, 5, ""), "سبب"),
    (lambda subs, a: subs.extend(a, None, 0, "x"), "موجب"),
    (lambda subs, a: subs.renew(a, None, None, ends_on=date(2020, 1, 1), today=date(2026, 10, 1)), "تاريخ النهاية"),
    (lambda subs, a: subs.renew(a, None, None, today=date(2026, 10, 1)), "حدد"),
])
def test_invalid_actions_are_refused(app, sub_world, call, needle):
    from app.extensions import db
    from app.services import subscriptions as subs
    with app.app_context():
        with pytest.raises(subs.SubscriptionError, match=needle):
            call(subs, _school(sub_world, "A"))
        db.session.rollback()
        db.session.remove()


def test_db_check_rejects_end_before_start(app, two_schools):
    from sqlalchemy.exc import IntegrityError
    from app.extensions import db
    from app.models import Plan, SchoolSubscription
    with app.app_context():
        plan = Plan(code=f"c-{secrets.token_hex(3)}", name_ar="x", modules=[], billing_cycle="monthly")
        db.session.add(plan); db.session.flush()
        db.session.add(SchoolSubscription(school_id=two_schools["A"]["school"].id, plan_id=plan.id,
                                          starts_on=date(2026, 10, 2), ends_on=date(2026, 10, 1)))
        with pytest.raises(IntegrityError):
            db.session.flush()
        db.session.rollback()
        db.session.remove()


def test_only_one_current_subscription_per_school(app, sub_world):
    from sqlalchemy.exc import IntegrityError
    from app.extensions import db
    from app.models import SchoolSubscription
    with app.app_context():
        db.session.add(SchoolSubscription(school_id=sub_world["A"]["school"].id,
                                          plan_id=sub_world["plan_id"], starts_on=date(2026, 1, 1),
                                          is_current=True))
        with pytest.raises(IntegrityError):
            db.session.flush()
        db.session.rollback()
        db.session.remove()


def test_set_school_status_keeps_is_active_in_step(app, two_schools):
    from app.extensions import db
    from app.services.subscriptions import set_school_status
    with app.app_context():
        s = _school(two_schools, "A")
        set_school_status(s, "suspended")
        assert s.is_active is False
        set_school_status(s, "active")
        assert s.is_active is True
        with pytest.raises(ValueError):
            set_school_status(s, "deleted")
        db.session.rollback()
        db.session.remove()


# ─── daily tick ──────────────────────────────────────────────────────

def test_tick_records_transitions_in_order_and_is_idempotent(app, sub_world):
    from app.extensions import db
    from app.models import SchoolSubscriptionEvent
    from app.services import subscriptions as subs
    sid = sub_world["A"]["school"].id
    days = [date(2026, 8, 31), date(2026, 9, 1), date(2026, 12, 31), date(2027, 1, 1),
            date(2027, 1, 14), date(2027, 1, 15)]
    with app.app_context():
        seen = []
        for d in days:
            res = subs.run_subscriptions_tick(today=d)
            seen.append(res["schools"][sid]["state"])
            again = subs.run_subscriptions_tick(today=d)
            assert again["schools"][sid]["changed"] is False
        assert seen == ["not_started", "active", "active", "grace", "grace", "expired"]
        changes = [(e.from_value, e.to_value) for e in SchoolSubscriptionEvent.query
                   .filter_by(school_id=sid, kind="state_changed").order_by(SchoolSubscriptionEvent.id)]
        assert changes == [(None, "not_started"), ("not_started", "active"),
                           ("active", "grace"), ("grace", "expired")]
        db.session.remove()


def test_tick_prepares_reminders_without_sending(app, sub_world):
    from app.services import subscriptions as subs
    sid = sub_world["A"]["school"].id
    with app.app_context():
        r30 = subs.run_subscriptions_tick(today=date(2026, 12, 1))["schools"][sid]["reminder"]
        assert r30 == {"kind": "expiring", "days_left": 30}
        none = subs.run_subscriptions_tick(today=date(2026, 12, 2))["schools"][sid]["reminder"]
        assert none is None


def test_tick_isolates_a_failing_school(app, sub_world, monkeypatch):
    from app.services import subscriptions as subs
    a, b = sub_world["A"]["school"].id, sub_world["B"]["school"].id
    real = subs.current_subscription

    def boom(school_id):
        if school_id == a:
            raise RuntimeError("secret detail")
        return real(school_id)
    monkeypatch.setattr(subs, "current_subscription", boom)
    with app.app_context():
        res = subs.run_subscriptions_tick(today=date(2026, 10, 1))
    assert res["schools"][a] == {"status": "failed", "error": "RuntimeError"}
    assert res["schools"][b]["status"] == "ok"


# ─── console screens + roles ─────────────────────────────────────────

@pytest.fixture
def console(app, monkeypatch):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "PLATFORM_HOSTS", ["console.manasety.ai"])
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    return app


def _console_client(app, role):
    """A logged-in console client for a fresh platform user of `role`."""
    import time
    from app.extensions import db
    from app.models import PlatformUser
    from app.services import platform_auth as pa
    with app.test_request_context(base_url=CONSOLE):
        u = PlatformUser(email=f"{role}-{secrets.token_hex(3)}@manasety.test", full_name=role,
                         role=role, is_active=True, password_changed_at=pa.utcnow(), totp_enabled=True)
        u.set_password(secrets.token_urlsafe(16))
        db.session.add(u); db.session.commit()
        uid, ver = u.id, u.session_version
        db.session.remove()
    c = app.test_client()
    with c.session_transaction(base_url=CONSOLE) as s:
        s["_user_id"] = f"p:{uid}"
        s["_fresh"] = True
        s["sa_ver"] = ver
        s["sa_login_at"] = s["sa_seen_at"] = time.time()
    return c, uid


def test_support_can_view_but_not_change(console, sub_world):
    c, _ = _console_client(console, "support")
    sid = sub_world["A"]["school"].id
    assert c.get(f"/superadmin/schools/{sid}", base_url=CONSOLE).status_code == 200
    assert c.get("/superadmin/plans", base_url=CONSOLE).status_code == 200
    for path, data in [
        (f"/superadmin/schools/{sid}/subscription/renew", {"months": "1"}),
        (f"/superadmin/schools/{sid}/subscription/extend", {"days": "3", "reason": "x"}),
        (f"/superadmin/schools/{sid}/subscription/plan", {"plan_id": sub_world["plan_id"]}),
        (f"/superadmin/schools/{sid}/subscription/trial", {"plan_id": sub_world["plan_id"]}),
        ("/superadmin/plans/new", {"code": "nope", "name_ar": "x"}),
        (f"/superadmin/plans/{sub_world['plan_id']}/toggle", {}),
    ]:
        assert c.post(path, base_url=CONSOLE, data=data).status_code == 403, path


def test_finance_extends_and_it_is_audited(console, sub_world):
    from app.models import PlatformAuditLog, SchoolSubscriptionEvent
    c, uid = _console_client(console, "finance")
    sid = sub_world["A"]["school"].id
    r = c.post(f"/superadmin/schools/{sid}/subscription/extend", base_url=CONSOLE,
               data={"days": "7", "reason": "late bank transfer"})
    assert r.status_code == 302
    with console.app_context():
        ev = SchoolSubscriptionEvent.query.filter_by(school_id=sid, kind="extended").one()
        assert ev.reason == "late bank transfer" and ev.platform_user_id == uid
        assert PlatformAuditLog.query.filter_by(platform_user_id=uid,
                                                action="subscription_extended",
                                                target_school_id=sid).count() == 1


def test_plan_in_use_cannot_be_disabled(console, sub_world):
    from app.models import Plan
    c, _ = _console_client(console, "owner")
    c.post(f"/superadmin/plans/{sub_world['plan_id']}/toggle", base_url=CONSOLE)
    with console.app_context():
        from app.extensions import db
        assert db.session.get(Plan, sub_world["plan_id"]).is_active is True


def test_plan_create_validates_modules(console):
    from app.extensions import db
    from app.models import Plan
    c, _ = _console_client(console, "owner")
    code = f"p-{secrets.token_hex(3)}"
    c.post("/superadmin/plans/new", base_url=CONSOLE,
           data={"code": code, "name_ar": "x", "modules": "students, flying"})
    with console.app_context():
        assert Plan.query.filter_by(code=code).first() is None
    c.post("/superadmin/plans/new", base_url=CONSOLE,
           data={"code": code, "name_ar": "x", "modules": "students, finance", "max_students": "50"})
    with console.app_context():
        p = Plan.query.filter_by(code=code).one()
        assert p.modules == ["finance", "students"] and p.max_students == 50
        db.session.delete(p); db.session.commit()


def test_school_list_shows_and_filters_by_state(console, sub_world):
    c, _ = _console_client(console, "support")
    html = c.get("/superadmin/schools?state=active", base_url=CONSOLE).get_data(as_text=True)
    assert sub_world["A"]["school"].slug in html
    html = c.get("/superadmin/schools?state=expired", base_url=CONSOLE).get_data(as_text=True)
    assert sub_world["A"]["school"].slug not in html
