"""Daily cron — SAAS-010.

`run_tick()` processes every ACTIVE school (by id), each one inside
`tenant_context(school.id)` and its own try/except, so one school's
failure never stops or rolls back another's. A single run at a time:
Postgres advisory lock (process lock on SQLite dev/test).

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
import sys
import threading
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
            out["attendance_reports_sent"] = send_reports_for_school(school_id)
        db.session.commit()
    if skipped:
        out["skipped_modules"] = skipped
    return out


def run_tick(today: date | None = None) -> dict:
    today = today or date.today()
    results: dict[int, dict] = {}
    with tick_lock():
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
    return {
        "ok": all(r["status"] != "failed" for r in results.values()),
        "today": today.isoformat(),
        "schools": results,
    }


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
def cron_tick_command(on_date):
    """Run the daily tick locally (no HTTP, no token)."""
    try:
        result = run_tick(date.fromisoformat(on_date) if on_date else None)
    except TickAlreadyRunning:
        click.echo(json.dumps({"ok": False, "reason": "already_running"}))
        sys.exit(2)
    click.echo(json.dumps(result, ensure_ascii=False, default=str))
    if not result["ok"]:
        sys.exit(1)
