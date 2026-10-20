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
    with tenant_context(school_id):
        # Recurring first so today's new invoices can flip overdue in
        # the same tick; reminders then read the fresh state.
        out["recurring"] = generate_recurring_invoices(school_id, today=today)
        out["overdue_flipped"] = update_overdue_invoices(school_id, today=today)
        out["reminders"] = send_payment_reminders(school_id, today=today)
        out["installment_reminders"] = send_installment_reminders(school_id)
        db.session.commit()
        out["attendance_rules_triggered"] = run_rules(school_id, today=today)
        out["risk_scores_updated"] = run_risk(school_id, today=today)
        if today.day == 1:
            out["attendance_reports_sent"] = send_reports_for_school(school_id)
        db.session.commit()
    return out


def run_tick(today: date | None = None) -> dict:
    today = today or date.today()
    results: dict[int, dict] = {}
    with tick_lock():
        school_ids = [sid for (sid,) in db.session.query(School.id)
                      .filter(School.status == "active").order_by(School.id)]
        for sid in school_ids:
            try:
                results[sid] = {"status": "ok", **run_school_tick(sid, today)}
            except Exception as e:
                db.session.rollback()
                current_app.logger.exception("cron tick failed for school %s", sid)
                # Type only — never the message or stack (may hold data).
                results[sid] = {"status": "failed", "error": type(e).__name__}
    return {
        "ok": all(r["status"] == "ok" for r in results.values()),
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
