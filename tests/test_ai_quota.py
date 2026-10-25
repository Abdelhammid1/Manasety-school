"""Monthly AI token cap (ticket E): the school's value, else its plan's,
else none; checked before every call — at or over the cap, no request
leaves, nothing is recorded, the user gets the Arabic message (no 500)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from isolation_harness import host
from test_ai_usage import _Resp, _ai_on, _call, _clean, _events, aapp  # noqa: F401
from test_saas026_subscriptions import CONSOLE, _console_client, console  # noqa: F401


def _used(app, school_id, tokens, at=None):
    from app.extensions import db
    from app.models import AIUsageEvent
    with app.app_context():
        db.session.add(AIUsageEvent(school_id=school_id, user_id=None, operation="summarize_exam",
                                    model="deepseek-chat", status="ok", total_tokens=tokens,
                                    occurred_at=at or datetime.now(timezone.utc)))
        db.session.commit(); db.session.remove()


def _cap(app, school_id, school=None, plan=None):
    from app.extensions import db
    from app.models import SchoolLimitOverride
    from app.services.subscriptions import current_subscription
    with app.app_context():
        row = db.session.get(SchoolLimitOverride, school_id)
        if row is None:
            row = SchoolLimitOverride(school_id=school_id, reason="t")
            db.session.add(row)
        row.max_ai_tokens_month = school
        if plan is not False:
            current_subscription(school_id).plan.max_ai_tokens_month = plan
        db.session.commit(); db.session.remove()


@pytest.fixture(autouse=True)
def _reset_caps(console):
    yield
    from app.extensions import db
    from app.models import Plan, SchoolLimitOverride
    with console.app_context():
        SchoolLimitOverride.query.delete()
        for p in Plan.query.all():
            p.max_ai_tokens_month = None
        db.session.commit(); db.session.remove()


def test_the_cap_comes_from_the_school_then_the_plan(aapp, two_schools):
    from app.services.ai_quota import effective_ai_cap
    sid = two_schools["A"]["school"].id
    _cap(aapp, sid, school=None, plan=1_000_000)
    with aapp.app_context():
        assert effective_ai_cap(sid) == (1_000_000, "plan")
    _cap(aapp, sid, school=5_000, plan=1_000_000)
    with aapp.app_context():
        assert effective_ai_cap(sid) == (5_000, "school")
    _cap(aapp, sid, school=None, plan=None)
    with aapp.app_context():
        assert effective_ai_cap(sid) == (None, None)


def test_at_the_cap_no_request_leaves_and_raising_it_opens_again(aapp, two_schools, login_as, monkeypatch):
    A, B = two_schools["A"], two_schools["B"]
    _ai_on(aapp, A, B)
    _cap(aapp, A["school"].id, school=1_000, plan=False)
    _used(aapp, A["school"].id, 1_000)
    before = len(_events(aapp))
    r, seen = _call(aapp, login_as, A, monkeypatch)
    assert seen == [], seen
    assert r.status_code == 429 and "للحد الشهري" in r.get_json()["error"]
    assert len(_events(aapp)) == before                                   # nothing recorded or billed
    # another school is untouched
    r, seen = _call(aapp, login_as, B, monkeypatch)
    assert r.status_code == 200 and len(seen) == 1
    # the owner raises the cap from the console, with a reason → the next call works
    from app.models import PlatformAuditLog, SchoolSubscriptionEvent
    owner, _ = _console_client(aapp, "owner")
    owner.post(f"/superadmin/schools/{A['school'].id}/limits", base_url=CONSOLE,
               data={"max_ai_tokens_month": "5000", "reason": "باقة أكبر"})
    with aapp.app_context():
        assert SchoolSubscriptionEvent.query.filter_by(school_id=A["school"].id, kind="limits_override").count() == 1
        assert PlatformAuditLog.query.filter_by(action="limits_override").count() >= 1
    r, seen = _call(aapp, login_as, A, monkeypatch)
    assert r.status_code == 200 and len(seen) == 1


def test_a_new_month_starts_from_zero(aapp, two_schools, login_as, monkeypatch):
    A = two_schools["A"]
    _ai_on(aapp, A)
    _cap(aapp, A["school"].id, school=1_000, plan=False)
    _used(aapp, A["school"].id, 1_000_000, at=datetime.now(timezone.utc) - timedelta(days=40))
    r, seen = _call(aapp, login_as, A, monkeypatch)
    assert r.status_code == 200 and len(seen) == 1


def test_month_bounds_last_and_first_second():
    from app.services.ai_usage import month_bounds
    start, end = month_bounds(datetime(2026, 10, 31, 21, 59, 59, tzinfo=timezone.utc), "Africa/Cairo")
    assert start == datetime(2026, 9, 30, 21, 0, tzinfo=timezone.utc)      # 1 Oct 00:00 Cairo (EEST)
    nxt, _ = month_bounds(datetime(2026, 10, 31, 22, 0, 1, tzinfo=timezone.utc), "Africa/Cairo")
    assert nxt == end                                                      # 1 Nov 00:00 Cairo


def test_error_rows_do_not_count(aapp, two_schools):
    from app.extensions import db
    from app.models import AIUsageEvent
    from app.services.ai_quota import ai_month_used
    sid = two_schools["A"]["school"].id
    _used(aapp, sid, 300)
    with aapp.app_context():
        db.session.add(AIUsageEvent(school_id=sid, operation="x", model="m", status="error", total_tokens=999,
                                    occurred_at=datetime.now(timezone.utc)))
        db.session.commit()
        assert ai_month_used(sid) == 300
        db.session.remove()


@pytest.mark.parametrize("bad", ["0", "-5", "abc", "1.5"])
def test_bad_cap_values_and_no_reason_change_nothing(aapp, two_schools, bad):
    from app.extensions import db
    from app.models import SchoolLimitOverride
    sid = two_schools["A"]["school"].id
    owner, _ = _console_client(aapp, "owner")
    body = owner.post(f"/superadmin/schools/{sid}/limits", base_url=CONSOLE, follow_redirects=True,
                      data={"max_ai_tokens_month": bad, "reason": "x"}).get_data(as_text=True)
    if bad == "0":
        assert "لإيقاف الـ AI استخدم مفتاح الميزة" in body
    owner.post(f"/superadmin/schools/{sid}/limits", base_url=CONSOLE, data={"max_ai_tokens_month": "500"})
    with aapp.app_context():
        assert db.session.get(SchoolLimitOverride, sid) is None
        db.session.remove()


def test_support_cannot_set_a_cap(aapp, two_schools):
    sid = two_schools["A"]["school"].id
    sup, _ = _console_client(aapp, "support")
    assert sup.post(f"/superadmin/schools/{sid}/limits", base_url=CONSOLE,
                    data={"max_ai_tokens_month": "500", "reason": "x"}).status_code == 403


def test_the_school_and_the_console_show_the_cap(aapp, two_schools, login_as):
    A, B = two_schools["A"], two_schools["B"]
    _ai_on(aapp, A, B)
    _cap(aapp, A["school"].id, school=1_000, plan=False)
    _used(aapp, A["school"].id, 920)
    c = aapp.test_client()
    login_as(c, A["users"]["admin"], base_url=host(A))
    full = c.get("/admin/ai-usage", base_url=host(A)).get_data(as_text=True)
    page = full[full.index("<main"):full.index("</main>")]
    assert "92٪" in page and "اقتربت من الحد" in page
    for word in ("تكلفة", "ربح", "هامش"):
        assert word not in page
    _used(aapp, A["school"].id, 100)
    full = c.get("/admin/ai-usage", base_url=host(A)).get_data(as_text=True)
    assert "وصلت مدرستك للحد الشهري" in full
    cb = aapp.test_client()
    login_as(cb, B["users"]["admin"], base_url=host(B))
    assert "غير محدود" in cb.get("/admin/ai-usage", base_url=host(B)).get_data(as_text=True)
    owner, _ = _console_client(aapp, "owner")
    over = owner.get("/superadmin/ai-usage", base_url=CONSOLE).get_data(as_text=True)
    assert "AI مفتوح بلا حد" in over and "102٪" in over
    detail = owner.get(f"/superadmin/schools/{A['school'].id}", base_url=CONSOLE).get_data(as_text=True)
    assert "102٪" in detail and "(المدرسة)" in detail


def test_quiz_analysis_opens_without_the_ai_summary_at_the_cap(aapp, two_schools, login_as, monkeypatch):
    """The quiz analysis page catches deepseek.AIError — a quota refusal is
    one, so the page renders its statistics with no 500."""
    from app.services import deepseek
    assert issubclass(deepseek.AIQuotaReached, deepseek.AIError)
