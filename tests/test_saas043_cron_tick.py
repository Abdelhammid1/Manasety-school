"""SAAS-043 — cron-tick safe to schedule: --dry-run writes and sends
nothing, two ticks send each notice once, external channels only when a
school enabled them (never for demo / test schools), one summary log
line per run, and the generated /etc/cron.d file."""

from __future__ import annotations

import json
import logging
import re
from datetime import date

import pytest

DAY = date(2026, 10, 1)       # the 1st: the monthly attendance report runs too


@pytest.fixture
def no_external(monkeypatch):
    """Fail loudly if anything tries to leave the process."""
    from app.services import mailer, notifications

    def boom(*a, **k):
        raise AssertionError("external send attempted")
    monkeypatch.setattr(mailer, "send", boom)
    monkeypatch.setattr(notifications, "send_push", boom)


def _state(app):
    from sqlalchemy import func
    from app.extensions import db
    from app.models import (AttendanceRuleTriggered, Invoice, NotificationLog, PlatformSetting)
    with app.app_context():
        out = (NotificationLog.query.count(), Invoice.query.count(),
               AttendanceRuleTriggered.query.count(),
               db.session.query(func.count(PlatformSetting.key)).scalar(),
               [(p.key, p.value) for p in PlatformSetting.query.order_by(PlatformSetting.key)])
        db.session.remove()
    return out


def test_dry_run_writes_nothing_and_sends_nothing(app, world, no_external):
    from app.blueprints.cron import routes
    from app.extensions import db
    before = _state(app)
    with app.app_context():
        result = routes.run_tick(DAY, dry_run=True)
        db.session.remove()
    assert _state(app) == before
    assert result["summary"]["dry_run"] is True
    sent = result["would_send"]
    assert sent, "the 1st of the month has attendance reports to show"
    assert result["summary"]["notifications"] == len(sent)
    for item in sent:
        assert set(item) == {"school_id", "kind", "channels", "to"}
        assert item["to"] is None or item["to"].startswith(("***",)) or "***@" in item["to"]


def test_dry_run_from_the_cli(app, world, no_external):
    before = _state(app)
    out = app.test_cli_runner().invoke(args=["cron-tick", "--dry-run", "--date", DAY.isoformat()])
    assert out.exit_code == 0, out.output
    body = json.loads(out.output[out.output.index("{"):])
    assert body["summary"]["dry_run"] is True and body["would_send"]
    assert _state(app) == before
    # Masked: no full phone number of any guardian in the output.
    assert not re.search(r"\d{7,}", json.dumps(body["would_send"]))


def test_two_ticks_send_each_notice_once(app, world, no_external):
    from app.blueprints.cron import routes
    from app.extensions import db
    from app.models import NotificationLog
    with app.app_context():
        n0 = NotificationLog.query.count()
        first = routes.run_tick(DAY)
        n1 = NotificationLog.query.count()
        second = routes.run_tick(DAY)
        n2 = NotificationLog.query.count()
        reports = NotificationLog.query.filter_by(kind="attendance_report").count()
        db.session.remove()
    assert first["summary"]["notifications"] == n1 - n0 > 0
    assert n2 == n1, "the second tick sent something again"
    assert second["summary"]["notifications"] == 0
    assert reports >= 1


@pytest.mark.parametrize("slug,channels,server_in_app_only,expect_email", [
    ("alpha", "in_app,email", False, True),      # explicitly enabled: sent
    ("alpha", "in_app", False, False),           # not enabled: never sent
    ("alpha", "", False, False),
    ("test-a", "in_app,email", False, False),    # test school: in-app only, always
    ("demo", "in_app,email,whatsapp", False, False),
    ("alpha", "in_app,email", True, False),      # NOTIFY_IN_APP_ONLY server
])
def test_external_channel_only_when_explicitly_enabled(app, two_schools, monkeypatch,
                                                       slug, channels, server_in_app_only,
                                                       expect_email):
    from app.extensions import db
    from app.models import School
    from app.services import mailer, notifications
    calls = []
    monkeypatch.setattr(mailer, "send", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(notifications, "send_push", lambda *a, **k: calls.append(("push",) + a))
    monkeypatch.setitem(app.config, "NOTIFY_IN_APP_ONLY", server_in_app_only)
    A = two_schools["A"]
    with app.app_context():
        s = db.session.get(School, A["school"].id)
        old = (s.slug, s.notify_channels, s.smtp_host, s.smtp_from_email)
        s.slug, s.notify_channels = slug, channels
        s.smtp_host, s.smtp_from_email = "smtp.example.test", "school@example.test"
        db.session.commit()
        try:
            log = notifications.send_notification(A["school"].id, "announcement",
                                                  {"subject": "x", "body": "y"},
                                                  target_email="parent@example.test")
            assert bool([c for c in calls if c[0] != "push"]) is expect_email
            assert log.status in ("sent", "failed")
        finally:
            s = db.session.get(School, A["school"].id)
            s.slug, s.notify_channels, s.smtp_host, s.smtp_from_email = old
            db.session.commit()
            db.session.remove()


def test_real_gateway_needs_the_channel(app, two_schools, monkeypatch):
    """A non-stub WhatsApp provider is not even attempted for a school
    without whatsapp / sms in notify_channels."""
    from app.extensions import db
    from app.models import School
    from app.services import notifications
    monkeypatch.setitem(app.config, "WHATSAPP_PROVIDER", "some-gateway")
    A = two_schools["A"]
    with app.app_context():
        s = db.session.get(School, A["school"].id)
        old = s.notify_channels
        s.notify_channels = "in_app"
        db.session.commit()
        try:
            log = notifications.send_notification(A["school"].id, "absence", {"student": "x"},
                                                  target_phone="0100000000")
            assert (log.status, log.error) == ("skipped", "channel not enabled for this school")
        finally:
            db.session.get(School, A["school"].id).notify_channels = old
            db.session.commit()
            db.session.remove()


def test_one_summary_line_per_run_without_recipients(app, world, no_external, caplog):
    from app.blueprints.cron import routes
    from app.extensions import db
    caplog.set_level(logging.INFO, logger="manasety.cron")
    with app.app_context():
        routes.run_tick(DAY, dry_run=True)
        db.session.remove()
    lines = [r.getMessage() for r in caplog.records if r.name == "manasety.cron"]
    assert len(lines) == 1 and lines[0].startswith("cron-tick ")
    summary = json.loads(lines[0][len("cron-tick "):])
    assert set(summary) == {"dry_run", "today", "schools", "ok", "skipped", "failed",
                            "subscriptions", "notifications"}
    assert summary["schools"] >= 2 and summary["failed"] == 0
    assert not re.search(r"\d{7,}|@", lines[0])


def test_cronfile_has_the_real_paths(app):
    out = app.test_cli_runner().invoke(args=["cron-tick-cronfile", "--user", "manasety", "--at", "04:30"])
    assert out.exit_code == 0, out.output
    line = [l for l in out.output.splitlines() if l and not l.startswith(("#", "SHELL", "MAILTO"))]
    assert len(line) == 1
    assert line[0].startswith("30 4 * * * manasety cd ")
    assert " cron-tick >> " in line[0] and line[0].endswith("cron-tick.log 2>&1")
    assert "--dry-run" not in line[0]
    bad = app.test_cli_runner().invoke(args=["cron-tick-cronfile", "--user", "x", "--at", "25:00"])
    assert bad.exit_code != 0
