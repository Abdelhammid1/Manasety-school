"""SAAS-034 — snapshots (idempotent, failure isolated), health with
missing sources, alert rules (open / repeat / close + one digest),
constant query count on the console home, read-only pages without
personal data."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from test_saas026_subscriptions import CONSOLE, _console_client, console  # noqa: F401

D = date(2026, 11, 10)


@pytest.fixture(autouse=True)
def _clean(console):
    yield
    from app.extensions import db
    from app.models import PlatformAlert, PlatformSetting, PlatformUsageSnapshot
    with console.app_context():
        PlatformUsageSnapshot.query.delete()
        PlatformAlert.query.delete()
        PlatformSetting.query.filter_by(key="cron_tick_last_ok").delete()
        db.session.commit()
        db.session.remove()


def test_snapshot_two_schools_and_idempotent(console, two_schools):
    from app.models import PlatformAuditLog, PlatformUsageSnapshot
    from app.services.monitoring import take_snapshots
    with console.app_context():
        take_snapshots(D)
        take_snapshots(D)
        ids = {two_schools[k]["school"].id for k in ("A", "B")}
        rows = PlatformUsageSnapshot.query.filter(PlatformUsageSnapshot.school_id.in_(ids),
                                                  PlatformUsageSnapshot.day == D).all()
        assert len(rows) == 2
        assert all(r.students_active >= 1 and r.subscription_state == "active" for r in rows)
        assert PlatformAuditLog.query.filter_by(action="usage_snapshot_run").count() == 2


def test_one_school_failing_doesnt_stop_others(console, two_schools, monkeypatch):
    from app.models import PlatformUsageSnapshot
    from app.services import limits, monitoring
    A = two_schools["A"]["school"].id
    real = limits.school_usage

    def flaky(sid, **kw):
        if sid == A:
            raise RuntimeError("boom")
        return real(sid, **kw)
    monkeypatch.setattr(limits, "school_usage", flaky)
    with console.app_context():
        res = monitoring.take_snapshots(D)
        assert A in res["failed"]
        assert PlatformUsageSnapshot.query.filter_by(school_id=two_schools["B"]["school"].id, day=D).count() == 1


def test_retention_prunes_old_rows(console, two_schools):
    from app.extensions import db
    from app.models import PlatformUsageSnapshot
    from app.services.monitoring import take_snapshots
    A = two_schools["A"]["school"].id
    with console.app_context():
        db.session.add(PlatformUsageSnapshot(school_id=A, day=D - timedelta(days=401)))
        db.session.commit()
        take_snapshots(D)
        assert PlatformUsageSnapshot.query.filter_by(school_id=A, day=D - timedelta(days=401)).count() == 0


def test_health_unknown_when_sources_missing(console, monkeypatch, tmp_path):
    from app.services.monitoring import health
    monkeypatch.setitem(console.config, "BACKUP_DIR", str(tmp_path / "does-not-exist"))
    with console.app_context():
        ind = {i.key: i for i in health()}
    assert ind["backup"].status == "unknown"
    assert ind["cert"].status == "unknown" and ind["nginx"].status in ("unknown", "ok", "error")
    assert ind["cron"].status == "unknown"


def test_health_backup_age(console, monkeypatch, tmp_path):
    import os
    import time
    from app.services.monitoring import health
    f = tmp_path / "db.dump"
    f.write_text("x")
    monkeypatch.setitem(console.config, "BACKUP_DIR", str(tmp_path))
    with console.app_context():
        assert {i.key: i for i in health()}["backup"].status == "ok"
        old = time.time() - 30 * 3600
        os.utime(f, (old, old))
        assert {i.key: i for i in health()}["backup"].status == "warn"


def test_alert_opens_once_and_closes(console, two_schools, monkeypatch):
    from app.extensions import db
    from app.models import PlatformAlert
    from app.services import monitoring, platform_actions
    mails = []
    monkeypatch.setattr(platform_actions, "notify_owners", lambda subj, body: mails.append(body) or 1)
    monkeypatch.setattr(monitoring, "health", lambda: [])
    A = two_schools["A"]["school"].id
    with console.app_context():
        from app.services.subscriptions import current_subscription
        sub = current_subscription(A)
        sub.starts_on, sub.ends_on = D - timedelta(days=100), D + timedelta(days=10)
        db.session.commit()
        for day in (D, D + timedelta(days=1), D + timedelta(days=2)):    # condition lasts 3 days
            monitoring.take_snapshots(day)
            monitoring.evaluate_alerts(day)
        rows = PlatformAlert.query.filter_by(school_id=A, kind="expiring").all()
        assert len(rows) == 1 and rows[0].resolved_at is None
        assert len(mails) == 1                                         # mailed on the first day only
        sub.ends_on = None
        db.session.commit()
        monitoring.evaluate_alerts(D + timedelta(days=3))
        assert db.session.get(PlatformAlert, rows[0].id).resolved_at is not None
        db.session.remove()


def test_home_query_count_is_constant(console, two_schools):
    import secrets
    from sqlalchemy import event
    from app.extensions import db
    from app.models import School
    from app.services.monitoring import take_snapshots
    from world import give_subscription, purge_schools
    c, _ = _console_client(console, "support")

    def count():
        n = {"q": 0}

        def before(*a, **k):
            n["q"] += 1
        with console.app_context():
            engine = db.engine
        event.listen(engine, "before_cursor_execute", before)
        try:
            assert c.get("/superadmin/dashboard", base_url=CONSOLE).status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", before)
        return n["q"]

    base = count()
    extra = []
    with console.app_context():
        for i in range(3):
            s = School(code=f"MQ{i}{secrets.token_hex(2)}", name=f"MQ{i}", slug=f"mq{i}-{secrets.token_hex(2)}",
                       status="active", is_active=True)
            db.session.add(s); db.session.flush()
            give_subscription(s)
            extra.append(s.id)
        db.session.commit()
        take_snapshots(D)
        db.session.remove()
    try:
        assert count() == base
    finally:
        with console.app_context():
            from app.models import PlatformUsageSnapshot
            PlatformUsageSnapshot.query.filter(PlatformUsageSnapshot.school_id.in_(extra)).delete()
            db.session.commit()
            purge_schools(extra)
            db.session.remove()


def test_pages_read_only_and_no_personal_data(console, two_schools):
    from app.services.monitoring import take_snapshots
    with console.app_context():
        take_snapshots(D)
    A = two_schools["A"]
    fin, _ = _console_client(console, "finance")
    for path in ("/superadmin/dashboard", "/superadmin/health", "/superadmin/alerts",
                 f"/superadmin/schools/{A['school'].id}"):
        page = fin.get(path, base_url=CONSOLE)
        assert page.status_code == 200, path
        for u in A["users"].values():          # no e-mail / name of anyone at a school
            assert (u.email or "@@").encode() not in page.data, path
            assert u.full_name.encode() not in page.data, path
    assert fin.post("/superadmin/alerts/1/ack", base_url=CONSOLE).status_code == 403


def test_new_school_has_empty_usage(console, two_schools):
    c, _ = _console_client(console, "owner")
    page = c.get(f"/superadmin/schools/{two_schools['A']['school'].id}", base_url=CONSOLE)
    assert page.status_code == 200 and "لا توجد لقطات بعد".encode() in page.data
