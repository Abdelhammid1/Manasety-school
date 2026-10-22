"""Daily cron — SAAS-010.

`run_tick()` processes every ACTIVE school (by id), each one inside
`tenant_context(school.id)` and its own try/except, so one school's
failure never stops or rolls back another's. A single run at a time:
Postgres advisory lock (process lock on SQLite dev/test).

SAAS-043 — safe to schedule:
  * `flask cron-tick --dry-run` runs every step, records what WOULD be
    sent (to whom — masked — and what) and writes / sends nothing: every
    commit becomes a flush and the whole run is rolled back.
  * External channels only for a school that enabled them explicitly;
    demo / test schools and a NOTIFY_IN_APP_ONLY server are in-app only
    (services.notifications.external_channels).
  * Each step is idempotent (reminder logs / reminder_sent_at / the
    daily attendance-report check), so two ticks send each notice once.
  * One summary line per run on the "manasety.cron" logger (schools,
    subscriptions, notifications, errors) — the crontab appends it to
    cron-tick.log. No payloads, no recipients in that line.

Entry points:
  * `flask cron-tick`  — preferred; run from the server's crontab.
  * POST/GET /cron/tick with `Authorization: Bearer <CRON_TOKEN>`
    for an external scheduler. `?token=` is refused (it ends up in
    access logs).

Transaction boundaries per school: the four ledger steps don't
commit themselves, so they commit together; attendance_rules and
risk_score each commit internally; the monthly report runs last.
A failure rolls back only the not-yet-committed part of that school.
"""
from __future__ import annotations

import hmac
import json
import logging
import sys
import threading
from collections import Counter
from contextlib import contextmanager
from datetime import date

import click
from flask import current_app, jsonify, request
from sqlalchemy import text

from . import bp
from ...extensions import csrf, db
from ...models import School
from ...services.attendance_pdf_report import send_reports_for_school
from ...services.attendance_rules import run_for_school as run_rules
from ...services.ledger import (
    generate_recurring_invoices,
    send_installment_reminders,
    send_payment_reminders,
    update_overdue_invoices,
)
from ...services.risk_score import run_for_school as run_risk
from ...services.tenancy import tenant_context

_ADVISORY_LOCK_KEY = 0x6D6E7374  # "mnst"
_local_lock = threading.Lock()
log = logging.getLogger("manasety.cron")


class TickAlreadyRunning(Exception):
    pass


@contextmanager
def tick_lock():
    """One tick at a time, so two schedulers firing together can't send
    duplicate reminders."""
    engine = db.engine
    if engine.dialect.name == "postgresql":
        # AUTOCOMMIT: the advisory lock is session-level, so no open
        # transaction is needed — and an "idle in transaction" connection
        # could be killed by idle_in_transaction_session_timeout mid-tick.
        conn = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        try:
            got = conn.execute(text("SELECT pg_try_advisory_lock(:k)"),
                               {"k": _ADVISORY_LOCK_KEY}).scalar()
            if not got:
                raise TickAlreadyRunning()
            try:
                yield
            finally:
                conn.execute(text("SELECT pg_advisory_unlock(:k)"),
                             {"k": _ADVISORY_LOCK_KEY})
        finally:
            conn.close()
    else:
        if not _local_lock.acquire(blocking=False):
            raise TickAlreadyRunning()
        try:
            yield
        finally:
            _local_lock.release()


def run_school_tick(school_id: int, today: date) -> dict:
    out: dict = {}
    # SAAS-030 — a module the school doesn't have gets no tasks.
    from ...services.modules import module_enabled
    skipped = []
    with tenant_context(school_id):
        if module_enabled(school_id, "finance"):
            # Recurring first so today's new invoices can flip overdue in
            # the same tick; reminders then read the fresh state.
            out["recurring"] = generate_recurring_invoices(school_id, today=today)
            out["overdue_flipped"] = update_overdue_invoices(school_id, today=today)
            out["reminders"] = send_payment_reminders(school_id, today=today)
            out["installment_reminders"] = send_installment_reminders(school_id)
            db.session.commit()
        else:
            skipped.append("finance")
        if module_enabled(school_id, "attendance"):
            out["attendance_rules_triggered"] = run_rules(school_id, today=today)
        else:
            skipped.append("attendance")
        out["risk_scores_updated"] = run_risk(school_id, today=today)
        if today.day == 1 and module_enabled(school_id, "attendance"):
            out["attendance_reports_sent"] = send_reports_for_school(school_id, day=today)
        db.session.commit()
    if skipped:
        out["skipped_modules"] = skipped
    return out


@contextmanager
def _nothing_is_written():
    """Dry run: every commit inside is only a flush (so later steps see
    the earlier ones, as in a real run), then everything is rolled back."""
    sess = db.session()
    sess.commit = sess.flush           # instance attribute shadows the method
    try:
        yield
    finally:
        del sess.commit
        sess.rollback()


def _new_notifications(since_id: int) -> int:
    from ...models import NotificationLog
    return NotificationLog.query.filter(NotificationLog.id > since_id).count()


def run_tick(today: date | None = None, *, dry_run: bool = False) -> dict:
    from ...models import NotificationLog
    from ...services.notifications import capture_dry_run
    today = today or date.today()
    results: dict[int, dict] = {}
    captured: list = []
    since_id = db.session.query(db.func.coalesce(db.func.max(NotificationLog.id), 0)).scalar()
    with tick_lock():
        if dry_run:
            with capture_dry_run() as captured, _nothing_is_written():
                states = _run_schools(today, results)
        else:
            states = _run_schools(today, results)
    sent = len(captured) if dry_run else _new_notifications(since_id)
    status = Counter(r["status"] for r in results.values())
    summary = {
        "dry_run": dry_run, "today": today.isoformat(), "schools": len(results),
        "ok": status["ok"], "skipped": status["skipped"], "failed": status["failed"],
        "subscriptions": dict(states),
        "notifications": sent,
    }
    log.info("cron-tick %s", json.dumps(summary, ensure_ascii=False))
    out = {
        "ok": all(r["status"] != "failed" for r in results.values()),
        "today": today.isoformat(),
        "schools": results,
        "summary": summary,
    }
    if dry_run:
        out["would_send"] = captured
    return out


def _run_schools(today: date, results: dict) -> Counter:
    """Every active school in its own try/except: one failure never
    stops the others. Returns how many schools are in each
    subscription state."""
    states: Counter = Counter()
    school_ids = [sid for (sid,) in db.session.query(School.id)
                  .filter(School.status == "active").order_by(School.id)]
    # SAAS-027 — a school whose subscription blocks access gets no
    # tick (no generated rows, no reminders); the reason is recorded.
    from ...services.subscriptions import (
        current_subscription, effective_state, get_settings, platform_today)
    from ...services.tenancy import resolution_mode
    settings = get_settings()
    sub_today = platform_today(settings)
    enforce = resolution_mode() == "enforce"     # off / log: block nothing (no new behaviour)
    for sid in school_ids:
        state = effective_state(db.session.get(School, sid), current_subscription(sid),
                                sub_today, settings)
        states[state.state] += 1
        if enforce and state.blocked:
            results[sid] = {"status": "skipped", "reason": state.state}
            continue
        try:
            results[sid] = {"status": "ok", **run_school_tick(sid, today)}
            # SAAS-034 — the health page's "last successful tick"
            from ...services.monitoring import record_cron_ok
            record_cron_ok(sid)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception("cron tick failed for school %s", sid)
            # Type only — never the message or stack (may hold data).
            results[sid] = {"status": "failed", "error": type(e).__name__}
    return states


def _authorised() -> bool:
    """Bearer token only, constant-time compare. A token in the query
    string is refused even when correct."""
    if "token" in request.args:
        return False
    expected = current_app.config.get("CRON_TOKEN") or ""
    auth = request.headers.get("Authorization", "")
    if not expected or not auth.startswith("Bearer "):
        return False
    supplied = auth[len("Bearer "):].strip()
    return hmac.compare_digest(supplied.encode(), expected.encode())


@bp.route("/tick", methods=["POST", "GET"])
@csrf.exempt
def tick():
    if not _authorised():
        return jsonify(ok=False, reason="unauthorised"), 401
    try:
        return jsonify(run_tick())
    except TickAlreadyRunning:
        return jsonify(ok=False, reason="already_running"), 409


@bp.cli.command("cron-tick")
@click.option("--date", "on_date", default=None, help="Run as if today were YYYY-MM-DD.")
@click.option("--dry-run", is_flag=True,
              help="Show what would be generated / sent; write and send nothing.")
def cron_tick_command(on_date, dry_run):
    """Run the daily tick locally (no HTTP, no token)."""
    if not log.handlers and not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    log.setLevel(logging.INFO)
    try:
        result = run_tick(date.fromisoformat(on_date) if on_date else None, dry_run=dry_run)
    except TickAlreadyRunning:
        click.echo(json.dumps({"ok": False, "reason": "already_running"}))
        sys.exit(2)
    click.echo(json.dumps(result, ensure_ascii=False, default=str))
    if not result["ok"]:
        sys.exit(1)


@bp.cli.command("cron-tick-cronfile")
@click.option("--app-dir", default=None, help="The app checkout (default: this one).")
@click.option("--user", default=None, help="Run as this user (default: the checkout's owner).")
@click.option("--at", "at", default="05:00", show_default=True, help="Daily time, HH:MM (server clock).")
@click.option("--log-file", default=None, help="Default: <app-dir>/cron-tick.log")
def cron_tick_cronfile(app_dir, user, at, log_file):
    """SAAS-043 — print /etc/cron.d/manasety-school with the real paths of
    this install. Prints only: install it yourself after a reviewed
    `flask cron-tick --dry-run`."""
    import shutil
    from pathlib import Path
    from jinja2 import Environment, FileSystemLoader, StrictUndefined
    root = Path(current_app.root_path).parent
    app_dir = Path(app_dir or root).resolve()
    if not (app_dir / "wsgi.py").is_file():
        raise click.ClickException(f"{app_dir} has no wsgi.py - pass --app-dir <the lms checkout>")
    try:
        hour, minute = (int(x) for x in at.split(":"))
        assert 0 <= hour < 24 and 0 <= minute < 60
    except (ValueError, AssertionError):
        raise click.ClickException("--at must be HH:MM") from None
    if not user:
        try:
            user = app_dir.owner()  # type: ignore[attr-defined]  (POSIX only)
        except (NotImplementedError, KeyError):
            raise click.ClickException("pass --user (can't read the checkout's owner here)") from None
    flask_bin = Path(sys.executable).with_name("flask")
    if not flask_bin.exists():
        found = shutil.which("flask")
        if not found:
            raise click.ClickException("can't find the flask executable of this environment")
        flask_bin = Path(found)
    env = Environment(loader=FileSystemLoader(str(root / "deploy" / "cron")),
                      undefined=StrictUndefined, keep_trailing_newline=True, autoescape=False)
    click.echo(env.get_template("manasety-school.j2").render(
        minute=minute, hour=hour, user=user, app_dir=app_dir.as_posix(),
        flask=flask_bin.resolve().as_posix(),
        log_file=Path(log_file or app_dir / "cron-tick.log").as_posix()), nl=False)
