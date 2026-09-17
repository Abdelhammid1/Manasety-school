"""Daily cron endpoint — pinged by an external scheduler (crontab).

Guarded by the CRON_TOKEN config value (Bearer token) so it can't be
hit from a normal browser. Runs every school through:
  · update_overdue_invoices — flips due_date<today unpaid invoices
    to status='overdue' so the aging report + reminder logic downstream
    have accurate state.

The endpoint is CSRF-exempt: it takes a token in a header, not a
session cookie, so there's no CSRF to protect against.
"""
from datetime import date

from flask import current_app, jsonify, request

from . import bp
from ...extensions import csrf, db
from ...models import School
from ...services.ledger import (
    generate_recurring_invoices,
    send_payment_reminders,
    update_overdue_invoices,
)


def _authorised() -> bool:
    """Accept `Authorization: Bearer <token>` OR `?token=<token>`."""
    expected = current_app.config.get("CRON_TOKEN")
    if not expected:
        return False
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        supplied = auth[len("Bearer "):].strip()
    else:
        supplied = request.args.get("token", "").strip()
    return bool(supplied) and supplied == expected


@bp.route("/tick", methods=["POST", "GET"])
@csrf.exempt
def tick():
    """Sweep every school. Idempotent — running twice on the same day
    is harmless (no invoice flips overdue → overdue)."""
    if not _authorised():
        return jsonify(ok=False, reason="unauthorised"), 401
    today = date.today()
    overdue_by_school: dict[int, int] = {}
    reminders_by_school: dict[int, dict] = {}
    recurring_by_school: dict[int, dict] = {}
    for s in School.query.all():
        # Order matters — generate recurring FIRST so newly-issued
        # invoices with today's issue_date can flip overdue later this
        # tick if their due dates already lapsed. Then flip overdue.
        # Reminders read the fresh state.
        recurring_by_school[s.id] = generate_recurring_invoices(s.id, today=today)
        overdue_by_school[s.id] = update_overdue_invoices(s.id, today=today)
        reminders_by_school[s.id] = send_payment_reminders(s.id, today=today)
    db.session.commit()
    return jsonify(
        ok=True, today=today.isoformat(),
        recurring=recurring_by_school,
        overdue_flipped=overdue_by_school,
        reminders=reminders_by_school,
    )
