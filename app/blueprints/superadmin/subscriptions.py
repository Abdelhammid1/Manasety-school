"""SAAS-026 — subscription actions on a school (owner + finance).

Each action creates a new subscription row (history is kept), writes a
school_subscription_events row and a platform audit row.
"""
from __future__ import annotations

from datetime import date

from flask import abort, flash, redirect, request, url_for

from . import bp, current_platform_user, require_platform_role
from ...extensions import db
from ...models import Plan, School
from ...services import platform_auth as pa
from ...services import subscriptions as subs

EDIT_ROLES = ("owner", "finance")


def _school(school_id):
    return db.session.get(School, school_id) or abort(404)


def _back(school):
    return redirect(url_for("superadmin.school_detail", school_id=school.id))


def _date(name):
    raw = (request.form.get(name) or "").strip()
    return date.fromisoformat(raw) if raw else None


def _run(school, action, fn):
    user = current_platform_user()
    try:
        fn(user)
    except (subs.SubscriptionError, ValueError) as e:
        db.session.rollback()
        flash(str(e) or "قيمة غير صالحة.", "danger")
        return _back(school)
    pa.audit(f"subscription_{action}", user, school_id=school.id,
             reason=(request.form.get("reason") or "").strip() or None)
    db.session.commit()
    flash("تم الحفظ.", "success")
    return _back(school)


@bp.route("/schools/<int:school_id>/subscription/renew", methods=["POST"],
          endpoint="subscription_renew")
@require_platform_role(*EDIT_ROLES)
def subscription_renew(school_id):
    school = _school(school_id)
    months = (request.form.get("months") or "").strip()
    return _run(school, "renewed", lambda u: subs.renew(
        school, u, (request.form.get("reason") or "").strip() or None,
        months=int(months) if months.isdigit() and int(months) > 0 else None,
        ends_on=_date("ends_on")))


@bp.route("/schools/<int:school_id>/subscription/extend", methods=["POST"],
          endpoint="subscription_extend")
@require_platform_role(*EDIT_ROLES)
def subscription_extend(school_id):
    school = _school(school_id)
    days = (request.form.get("days") or "").strip()
    return _run(school, "extended", lambda u: subs.extend(
        school, u, int(days) if days.isdigit() else 0, request.form.get("reason") or ""))


@bp.route("/schools/<int:school_id>/subscription/plan", methods=["POST"],
          endpoint="subscription_change_plan")
@require_platform_role(*EDIT_ROLES)
def subscription_change_plan(school_id):
    school = _school(school_id)
    plan = db.session.get(Plan, request.form.get("plan_id", type=int) or 0) or abort(404)
    return _run(school, "plan_changed", lambda u: subs.change_plan(
        school, plan, u, (request.form.get("reason") or "").strip() or None))


@bp.route("/schools/<int:school_id>/subscription/trial", methods=["POST"],
          endpoint="subscription_trial")
@require_platform_role(*EDIT_ROLES)
def subscription_trial(school_id):
    school = _school(school_id)
    plan = db.session.get(Plan, request.form.get("plan_id", type=int) or 0) or abort(404)
    days = (request.form.get("days") or "").strip()
    return _run(school, "trial_started", lambda u: subs.start_trial(
        school, plan, u, days=int(days) if days.isdigit() and int(days) > 0 else None,
        reason=(request.form.get("reason") or "").strip() or None))


@bp.cli.command("subscriptions-tick")
def subscriptions_tick_command():
    """Record subscription state transitions and list due reminders."""
    import json
    import sys
    import click
    from ...services.locks import AlreadyRunning
    try:
        result = subs.run_subscriptions_tick()
        # SAAS-033 — expiry / grace / overdue notices (idempotent per day)
        from ...services.billing import send_due_notices
        result["notices"] = send_due_notices()
    except AlreadyRunning:
        click.echo(json.dumps({"ok": False, "reason": "already_running"}))
        sys.exit(2)
    click.echo(json.dumps(result, ensure_ascii=False, default=str))
