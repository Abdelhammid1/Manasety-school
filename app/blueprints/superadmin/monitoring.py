"""SAAS-034 — console home, server health, alerts (numbers only).
Read-only pages for every role; acknowledging an alert: owner + support."""
from __future__ import annotations

import click
from flask import abort, redirect, render_template, request, url_for

from . import bp, current_platform_user, require_platform_role
from ...extensions import db
from ...models import PlatformAlert
from ...services import monitoring
from ...services import subscriptions as subs


@bp.route("/dashboard", methods=["GET"], endpoint="dashboard")
def dashboard():
    today = subs.platform_today(subs.get_settings())
    return render_template("superadmin/dashboard.html", d=monitoring.dashboard(today),
                           health=monitoring.health(), today=today)


@bp.route("/health", methods=["GET"], endpoint="system_health")
def system_health():
    return render_template("superadmin/health.html", indicators=monitoring.health())


@bp.route("/alerts", methods=["GET"], endpoint="alerts")
def alerts():
    show = request.args.get("show") or "open"
    q = PlatformAlert.query
    if show == "open":
        q = q.filter(PlatformAlert.resolved_at.is_(None))
    rows = q.order_by(PlatformAlert.id.desc()).limit(300).all()
    return render_template("superadmin/alerts.html", rows=rows, show=show)


@bp.route("/alerts/<int:alert_id>/ack", methods=["POST"], endpoint="alert_ack")
@require_platform_role("owner", "support")
def alert_ack(alert_id):
    from ...services import platform_auth as pa
    a = db.session.get(PlatformAlert, alert_id) or abort(404)
    if a.acknowledged_by is None:
        a.acknowledged_by = current_platform_user().id
        pa.audit("alert_acknowledged", current_platform_user(), school_id=a.school_id, alert=a.kind)
        db.session.commit()
    return redirect(url_for("superadmin.alerts"))


@bp.cli.command("usage-snapshot")
@click.option("--date", "on_date", default=None, help="Snapshot day (YYYY-MM-DD).")
def usage_snapshot_command(on_date):
    """SAAS-034 — daily usage snapshot for every school (idempotent), then
    alert evaluation + the owners' digest of new alerts."""
    import json
    from datetime import date
    day = date.fromisoformat(on_date) if on_date else None
    result = monitoring.take_snapshots(day)
    result["alerts"] = monitoring.evaluate_alerts(day)
    click.echo(json.dumps(result, ensure_ascii=False, default=str))
