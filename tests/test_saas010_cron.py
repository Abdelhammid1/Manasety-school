"""SAAS-010 — per-school cron: failure isolation, status filter, lock,
token, CLI parity, idempotency."""

from __future__ import annotations

import json
from datetime import date

import pytest

TOKEN = "t" * 40


@pytest.fixture
def cron_app(app, monkeypatch):
    monkeypatch.setitem(app.config, "CRON_TOKEN", TOKEN)
    return app


@pytest.fixture
def three_schools(app, two_schools):
    """A, B (active, from two_schools) + C active, S suspended, R archived."""
    from app.extensions import db
    from app.models import School
    from world import purge_schools
    extra = {}
    with app.app_context():
        for slug, status in (("gamma", "active"), ("susp", "suspended"), ("arch", "archived")):
            s = School(code=f"TEST-{slug.upper()}", name=slug, slug=slug,
                       status=status, is_active=True)
            db.session.add(s)
            db.session.flush()
            if status == "active":
                from world import give_subscription
                give_subscription(s)
            extra[slug] = s.id
        db.session.commit()
        db.session.remove()
    ids = {"A": two_schools["A"]["school"].id, "B": two_schools["B"]["school"].id,
           "C": extra["gamma"], "S": extra["susp"], "R": extra["arch"]}
    yield ids
    with app.app_context():
        purge_schools([extra["gamma"], extra["susp"], extra["arch"]])
        db.session.remove()


def _vendor_names(app, school_id):
    from app.models import Vendor
    with app.app_context():
        return {v.name for v in Vendor.query.filter_by(school_id=school_id)}


def test_failure_in_one_school_is_isolated(cron_app, three_schools, monkeypatch):
    """Each school writes a marker row in its first step; B then fails.
    A and C keep their row and report ok; B's row is rolled back and its
    status says failed with the exception type only."""
    from app.blueprints.cron import routes
    from app.extensions import db
    from app.models import Vendor
    ids = three_schools
    real = routes.generate_recurring_invoices

    def step(school_id, today):
        db.session.add(Vendor(school_id=school_id, name=f"cron-mark-{school_id}"))
        db.session.flush()
        if school_id == ids["B"]:
            raise RuntimeError("secret detail that must not leak")
        return real(school_id, today=today)

    monkeypatch.setattr(routes, "generate_recurring_invoices", step)
    with cron_app.app_context():
        result = routes.run_tick(date(2026, 10, 20))
        db.session.remove()

    sch = result["schools"]
    assert sch[ids["A"]]["status"] == "ok"
    assert sch[ids["C"]]["status"] == "ok"
    assert sch[ids["B"]] == {"status": "failed", "error": "RuntimeError"}
    assert "secret detail" not in json.dumps(result)
    assert result["ok"] is False
    assert f"cron-mark-{ids['A']}" in _vendor_names(cron_app, ids["A"])
    assert f"cron-mark-{ids['C']}" in _vendor_names(cron_app, ids["C"])
    assert f"cron-mark-{ids['B']}" not in _vendor_names(cron_app, ids["B"])


def test_suspended_and_archived_are_skipped(cron_app, three_schools):
    from app.blueprints.cron import routes
    from app.extensions import db
    with cron_app.app_context():
        result = routes.run_tick(date(2026, 10, 20))
        db.session.remove()
    assert three_schools["S"] not in result["schools"]
    assert three_schools["R"] not in result["schools"]
    assert three_schools["A"] in result["schools"]


def test_each_school_runs_inside_its_tenant_context(cron_app, three_schools, monkeypatch):
    from app.blueprints.cron import routes
    from app.extensions import db
    from app.services.tenancy import current_tenant_id
    seen = {}

    def step(school_id, today):
        seen[school_id] = current_tenant_id()
        return {}

    monkeypatch.setattr(routes, "generate_recurring_invoices", step)
    with cron_app.app_context():
        routes.run_tick(date(2026, 10, 20))
        db.session.remove()
    for key in ("A", "B", "C"):
        assert seen[three_schools[key]] == three_schools[key]


def test_concurrent_run_gets_409(cron_app, two_schools):
    from app.blueprints.cron.routes import tick_lock
    with cron_app.app_context():
        with tick_lock():
            with cron_app.test_client() as c:
                r = c.post("/cron/tick", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 409
    assert r.get_json()["reason"] == "already_running"


@pytest.mark.parametrize("headers,query,expected", [
    ({}, "", 401),
    ({"Authorization": "Bearer wrong"}, "", 401),
    ({"Authorization": TOKEN}, "", 401),
    ({}, f"?token={TOKEN}", 401),
    ({"Authorization": f"Bearer {TOKEN}"}, f"?token={TOKEN}", 401),
    ({"Authorization": f"Bearer {TOKEN}"}, "", 200),
])
def test_token_rules(cron_app, two_schools, headers, query, expected):
    with cron_app.test_client() as c:
        r = c.post(f"/cron/tick{query}", headers=headers)
    assert r.status_code == expected


@pytest.mark.parametrize("value", [None, "", "dev-cron-token-change-me", "short-token"])
def test_production_refuses_weak_cron_token(value):
    from app.config import _resolve_cron_token
    env = {} if value is None else {"CRON_TOKEN": value}
    with pytest.raises(RuntimeError, match="CRON_TOKEN"):
        _resolve_cron_token(env, app_env="production")


def test_production_accepts_strong_cron_token():
    from app.config import _resolve_cron_token
    assert _resolve_cron_token({"CRON_TOKEN": "x" * 48}, app_env="production") == "x" * 48


def test_cli_matches_endpoint(cron_app, two_schools):
    with cron_app.test_client() as c:
        http = c.post("/cron/tick", headers={"Authorization": f"Bearer {TOKEN}"}).get_json()
    out = cron_app.test_cli_runner().invoke(args=["cron-tick"])
    assert out.exit_code == 0, out.output
    cli = json.loads(out.output)
    assert cli["ok"] == http["ok"] and cli["today"] == http["today"]
    assert set(cli["schools"]) == set(http["schools"])
    for sid, res in http["schools"].items():
        assert set(cli["schools"][sid]) == set(res)


def test_second_run_same_day_creates_nothing(cron_app, world):
    """Idempotency: recurring invoices / reminders aren't duplicated."""
    from app.blueprints.cron import routes
    from app.extensions import db
    from app.models import Invoice, NotificationLog
    day = date(2026, 10, 1)
    with cron_app.app_context():
        routes.run_tick(day)
        inv1, notes1 = Invoice.query.count(), NotificationLog.query.count()
        second = routes.run_tick(day)
        assert (Invoice.query.count(), NotificationLog.query.count()) == (inv1, notes1)
        assert second["schools"][world["A"]["school"].id]["status"] == "ok"
        db.session.remove()
