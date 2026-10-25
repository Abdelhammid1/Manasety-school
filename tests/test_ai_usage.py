"""AI usage metering (ticket D): every DeepSeek call is recorded for its
school and user (tokens only), priced with the card in effect at the
time, reported to the console (cost / price / profit) and to the school
(tokens and price — never our cost or margin)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from isolation_harness import host
from test_saas026_subscriptions import CONSOLE, _console_client, console  # noqa: F401

USAGE = {"prompt_cache_hit_tokens": 1000, "prompt_cache_miss_tokens": 2000, "completion_tokens": 500,
         "total_tokens": 3500}
CARD = {"model": "deepseek-chat", "currency": "USD",
        "cost_hit": "0.07", "cost_miss": "0.27", "cost_output": "1.10",
        "price_hit": "0.20", "price_miss": "0.60", "price_output": "2.00"}
# 1000×0.07 + 2000×0.27 + 500×1.10 = 70 + 540 + 550 = 1160 / 1e6
COST = Decimal("0.00116000")
# 1000×0.20 + 2000×0.60 + 500×2.00 = 200 + 1200 + 1000 = 2400 / 1e6
PRICE = Decimal("0.00240000")


class _Resp:
    def __init__(self, status=200, usage=USAGE, model="deepseek-chat"):
        self.status_code = status
        self._usage = usage
        self._model = model
        self.text = "boom" if status >= 400 else ""

    def json(self):
        body = {"model": self._model,
                "choices": [{"message": {"content": json.dumps({"easy": 5, "medium": 10, "hard": 5})}}]}
        if self._usage is not None:
            body["usage"] = self._usage
        return body


@pytest.fixture
def aapp(console, monkeypatch):
    console.config["WTF_CSRF_ENABLED"] = False
    console.config["TENANT_RESOLUTION_MODE"] = "enforce"
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-not-a-real-key")
    return console


@pytest.fixture(autouse=True)
def _clean(console):
    yield
    from app.extensions import db
    from app.models import AIPriceCard, AIUsageCharge, AIUsageEvent, SchoolFeatureOverride
    with console.app_context():
        AIUsageCharge.query.delete()
        AIUsageEvent.query.delete()
        AIPriceCard.query.delete()
        SchoolFeatureOverride.query.delete()
        db.session.commit()
        db.session.remove()


def _ai_on(app, *bundles):
    from app.extensions import db
    from app.models import SchoolFeatureOverride
    with app.app_context():
        for b in bundles:
            db.session.add(SchoolFeatureOverride(school_id=b["school"].id, feature_key="lms.ai", enabled=True,
                                                 reason="test"))
        db.session.commit()
        db.session.remove()


def _card(app, **over):
    from app.extensions import db
    from app.models import AIPriceCard
    values = {**CARD, **over}
    with app.app_context():
        c = AIPriceCard(model=values["model"], currency=values["currency"],
                        effective_from=values.get("effective_from") or datetime(2020, 1, 1, tzinfo=timezone.utc),
                        **{k: Decimal(values[k]) for k in ("cost_hit", "cost_miss", "cost_output",
                                                           "price_hit", "price_miss", "price_output")})
        db.session.add(c); db.session.commit(); cid = c.id
        db.session.remove()
    return cid


def _call(app, login_as, bundle, monkeypatch, role="teacher", resp=None):
    import requests
    seen = []
    monkeypatch.setattr(requests, "post", lambda *a, **k: seen.append(k) or (resp or _Resp()))
    c = app.test_client()
    login_as(c, bundle["users"][role], base_url=host(bundle))
    r = c.post("/lms/exams/blueprint/ai-suggest", base_url=host(bundle),
               json={"subject": "رياضيات", "grade": "الأول", "total": 20})
    return r, seen


def _events(app, sid=None):
    from app.extensions import db
    from app.models import AIUsageCharge, AIUsageEvent
    with app.app_context():
        q = AIUsageEvent.query
        if sid:
            q = q.filter_by(school_id=sid)
        out = []
        for e in q.order_by(AIUsageEvent.id):
            ch = AIUsageCharge.query.filter_by(event_id=e.id).first()
            out.append({c.name: getattr(e, c.name) for c in e.__table__.c} |
                       {"cost": ch.cost if ch else None, "price": ch.price if ch else None})
        db.session.remove()
    return out


# ─── recording ──────────────────────────────────────────────────────

def test_one_call_one_row_with_the_tokens_the_school_and_the_user(aapp, two_schools, login_as, monkeypatch):
    A = two_schools["A"]
    _ai_on(aapp, A)
    _card(aapp)
    r, seen = _call(aapp, login_as, A, monkeypatch)
    assert r.status_code == 200 and len(seen) == 1
    rows = _events(aapp)
    assert len(rows) == 1
    e = rows[0]
    assert e["school_id"] == A["school"].id and e["user_id"] == A["users"]["teacher"].id
    assert (e["prompt_cache_hit_tokens"], e["prompt_cache_miss_tokens"], e["completion_tokens"],
            e["total_tokens"]) == (1000, 2000, 500, 3500)
    assert e["status"] == "ok" and e["operation"] == "suggest_blueprint"
    assert e["cost"] == COST and e["price"] == PRICE                      # the formula, by hand
    # nothing of the prompt or the answer anywhere in the row
    assert not any(isinstance(v, str) and ("رياضيات" in v or "easy" in v) for v in e.values())


def test_a_failed_call_is_an_error_row_and_a_write_failure_keeps_the_answer(aapp, two_schools, login_as,
                                                                            monkeypatch, caplog):
    A = two_schools["A"]
    _ai_on(aapp, A)
    r, _ = _call(aapp, login_as, A, monkeypatch, resp=_Resp(status=500))
    assert r.status_code == 502
    rows = _events(aapp)
    assert [(e["status"], e["total_tokens"]) for e in rows] == [("error", 0)]
    # the billing write fails: the teacher still gets the answer, an ERROR is logged
    from app.models import AIUsageEvent

    def broken(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(AIUsageEvent.__table__, "insert", broken)
    with caplog.at_level("ERROR"):
        r, _ = _call(aapp, login_as, A, monkeypatch)
    monkeypatch.undo()
    assert r.status_code == 200 and r.get_json()["medium"] == 10
    assert any("could not record" in m for m in caplog.messages)


def test_a_response_without_usage_is_recorded_with_zero_tokens(aapp, two_schools, login_as, monkeypatch):
    A = two_schools["A"]
    _ai_on(aapp, A)
    r, _ = _call(aapp, login_as, A, monkeypatch, resp=_Resp(usage=None))
    assert r.status_code == 200
    assert [(e["status"], e["total_tokens"]) for e in _events(aapp)] == [("ok", 0)]


# ─── pricing ────────────────────────────────────────────────────────

def test_without_a_card_unpriced_then_priced_and_a_new_card_changes_nothing_old(aapp, two_schools, login_as,
                                                                                monkeypatch):
    from app.extensions import db
    from app.models import PlatformUser
    from app.services import platform_ai_usage as pai
    A = two_schools["A"]
    _ai_on(aapp, A)
    _call(aapp, login_as, A, monkeypatch)
    assert _events(aapp)[0]["price"] is None                              # «بدون تسعيرة»
    _card(aapp)
    with aapp.test_request_context():
        owner = PlatformUser.query.filter_by(role="owner").first()
        assert pai.price_pending(owner) == 1
        db.session.commit()
        db.session.remove()
    assert _events(aapp)[0]["price"] == PRICE
    # a later card (doubled prices) applies only from its date
    _card(aapp, effective_from=datetime.now(timezone.utc) + timedelta(seconds=1),
          price_hit="0.40", price_miss="1.20", price_output="4.00")
    with aapp.test_request_context():
        owner = PlatformUser.query.filter_by(role="owner").first()
        assert pai.price_pending(owner) == 0
        db.session.commit(); db.session.remove()
    assert _events(aapp)[0]["price"] == PRICE


@pytest.mark.parametrize("bad", [{"cost_hit": "-1"}, {"currency": ""}, {"model": ""}, {"price_output": "abc"}])
def test_a_bad_card_is_refused(aapp, two_schools, bad):
    from app.models import AIPriceCard
    c, _ = _console_client(aapp, "owner")
    c.post("/superadmin/ai-usage/prices", base_url=CONSOLE, data={**CARD, **bad})
    with aapp.app_context():
        assert AIPriceCard.query.count() == 0


# ─── the console ────────────────────────────────────────────────────

def test_the_overview_sums_per_school_and_roles_see_what_they_may(aapp, two_schools, login_as, monkeypatch):
    A, B = two_schools["A"], two_schools["B"]
    _ai_on(aapp, A, B)
    _card(aapp)
    _call(aapp, login_as, A, monkeypatch)
    _call(aapp, login_as, A, monkeypatch, role="admin")
    _call(aapp, login_as, B, monkeypatch)
    owner, _ = _console_client(aapp, "owner")
    page = owner.get("/superadmin/ai-usage", base_url=CONSOLE).get_data(as_text=True)
    assert A["school"].name in page and B["school"].name in page and "الربح" in page
    csv_text = owner.get("/superadmin/ai-usage?format=csv", base_url=CONSOLE).get_data(as_text=True)
    lines = [ln.split(",") for ln in csv_text.strip().splitlines()[1:]]
    by_school = {int(ln[0].lstrip("﻿")): ln for ln in lines}
    assert int(by_school[A["school"].id][3]) == 7000 and int(by_school[B["school"].id][3]) == 3500
    price_col = csv_text.splitlines()[0].split(",").index("price")
    assert Decimal(by_school[A["school"].id][price_col]) + Decimal(by_school[B["school"].id][price_col]) == PRICE * 3
    # finance sees money but can't add a card; support sees no amount at all
    fin, _ = _console_client(aapp, "finance")
    assert "الربح" in fin.get("/superadmin/ai-usage", base_url=CONSOLE).get_data(as_text=True)
    assert fin.get("/superadmin/ai-usage/prices", base_url=CONSOLE).status_code == 200
    assert fin.post("/superadmin/ai-usage/prices", base_url=CONSOLE, data=CARD).status_code == 403
    sup, _ = _console_client(aapp, "support")
    page = sup.get("/superadmin/ai-usage", base_url=CONSOLE).get_data(as_text=True)
    assert "7,000" in page and "الربح" not in page and "التكلفة" not in page and "USD" not in page
    assert sup.get("/superadmin/ai-usage/prices", base_url=CONSOLE).status_code == 403
    sup_csv = sup.get("/superadmin/ai-usage?format=csv", base_url=CONSOLE).get_data(as_text=True)
    assert "cost" not in sup_csv and "profit" not in sup_csv
    school_page = sup.get(f"/superadmin/schools/{A['school'].id}", base_url=CONSOLE).get_data(as_text=True)
    assert "الذكاء الاصطناعي" in school_page and "الربح" not in school_page


# ─── the school's page ──────────────────────────────────────────────

def test_the_school_sees_its_own_usage_never_our_cost(aapp, two_schools, login_as, monkeypatch):
    A, B = two_schools["A"], two_schools["B"]
    _ai_on(aapp, A, B)
    _card(aapp)
    _call(aapp, login_as, A, monkeypatch)
    _call(aapp, login_as, B, monkeypatch)
    c = aapp.test_client()
    login_as(c, A["users"]["admin"], base_url=host(A))
    full = c.get("/admin/ai-usage", base_url=host(A)).get_data(as_text=True)
    page = full[full.index("<main"):full.index("</main>")]          # the page itself, not the sidebar
    csv_text = c.get("/admin/ai-usage?format=csv", base_url=host(A)).get_data(as_text=True)
    teacher_a = A["users"]["teacher"].full_name
    assert teacher_a in page and "3,500" in page and "0.00 USD" in page
    assert B["users"]["teacher"].full_name not in page
    for text in (page, csv_text):
        for word in ("تكلفة", "التكلفة", "ربح", "الربح", "هامش", "cost", "profit", "margin"):
            assert word not in text, word
    assert str(COST) not in csv_text and "0.0024" in csv_text
    # the AI turned off later: the page still opens, its sidebar item stays, the AI pages 404
    from app.extensions import db
    from app.models import SchoolFeatureOverride
    with aapp.app_context():
        SchoolFeatureOverride.query.filter_by(school_id=A["school"].id).delete()
        db.session.commit(); db.session.remove()
    r = c.get("/admin/ai-usage", base_url=host(A))
    assert r.status_code == 200 and "/admin/ai-usage" in c.get("/dashboard", base_url=host(A)).get_data(as_text=True)
    assert c.post("/lms/exams/blueprint/ai-suggest", base_url=host(A), json={}).status_code == 404


@pytest.mark.parametrize("role", ["teacher", "parent"])
def test_teachers_and_parents_cannot_open_it(aapp, two_schools, login_as, role):
    A = two_schools["A"]
    c = aapp.test_client()
    login_as(c, A["users"][role], base_url=host(A))
    assert c.get("/admin/ai-usage", base_url=host(A)).status_code == 403


# ─── backups ────────────────────────────────────────────────────────

def test_a_school_backup_never_carries_or_restores_its_usage():
    from app.services.school_backup import BACKUP_EXCLUDED, backup_tables
    assert "ai_usage_events" in BACKUP_EXCLUDED
    assert "ai_usage_events" not in {t.name for t in backup_tables()}


def test_csv_cells_never_run_as_formulas(aapp, two_schools, login_as, monkeypatch):
    from app.extensions import db
    from app.models import School, User
    A = two_schools["A"]
    with aapp.app_context():
        db.session.get(User, A["users"]["teacher"].id).full_name = "=HYPERLINK(\"http://x\")"
        db.session.get(School, A["school"].id).name = "+cmd|' /C calc'!A0"
        db.session.commit(); db.session.remove()
    _ai_on(aapp, A)
    _call(aapp, login_as, A, monkeypatch)
    c = aapp.test_client()
    login_as(c, A["users"]["admin"], base_url=host(A))
    school_csv = c.get("/admin/ai-usage?format=csv", base_url=host(A)).get_data(as_text=True)
    assert "'=HYPERLINK" in school_csv and ",=HYPERLINK" not in school_csv
    owner, _ = _console_client(aapp, "owner")
    console_csv = owner.get("/superadmin/ai-usage?format=csv", base_url=CONSOLE).get_data(as_text=True)
    assert "'+cmd" in console_csv and ",+cmd" not in console_csv
