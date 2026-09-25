"""Ticket T3 admin — AttendanceRule CRUD + triggers listing.
Ticket T4 admin — Risk score dashboard."""

from flask import (
    flash, jsonify, redirect, render_template, request, url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import func

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import (
    AttendanceRule, AttendanceRuleTriggered, Student, StudentRiskScore,
)


def _sid():
    return current_user.school_id


# ─── T3: rule CRUD ─────────────────────────────────────────────────
@bp.route("/rules", methods=["GET", "POST"], endpoint="rules_list")
@login_required
@require_permission("attendance", "view")
def rules_list():
    if request.method == "POST":
        action = request.form.get("action", "add")
        if action == "delete":
            rid = request.form.get("id", type=int)
            r = AttendanceRule.query.filter_by(
                id=rid, school_id=_sid()).first_or_404()
            db.session.delete(r); db.session.commit()
            flash("تم حذف القاعدة.", "success")
        else:
            name = (request.form.get("name") or "").strip()
            kind = request.form.get("kind") or "consecutive"
            try:
                threshold = int(request.form.get("threshold") or 0)
            except ValueError:
                threshold = 0
            window = request.form.get("window") or "term"
            action_kind = request.form.get("rule_action") or "warning"
            if not name or threshold <= 0:
                flash("الاسم والعتبة (رقم موجب) مطلوبان.", "danger")
            elif kind not in ("consecutive", "cumulative"):
                flash("نوع القاعدة غير صالح.", "danger")
            elif action_kind not in ("warning", "notify_guardian", "escalate_admin"):
                flash("نوع الإجراء غير صالح.", "danger")
            else:
                db.session.add(AttendanceRule(
                    school_id=_sid(), name=name,
                    kind=kind, threshold=threshold,
                    window=window, action=action_kind,
                ))
                db.session.commit()
                flash("تم إضافة القاعدة.", "success")
        return redirect(url_for("attendance.rules_list"))

    rows = (
        AttendanceRule.query.filter_by(school_id=_sid())
        .order_by(AttendanceRule.threshold).all()
    )
    triggers = (
        AttendanceRuleTriggered.query.filter_by(school_id=_sid())
        .order_by(AttendanceRuleTriggered.triggered_on.desc())
        .limit(50).all()
    )
    return render_template(
        "attendance/rules_list.html",
        rows=rows, triggers=triggers,
    )


@bp.route("/rules/triggers/<int:trigger_id>/resolve",
          methods=["POST"], endpoint="rule_trigger_resolve")
@login_required
@require_permission("attendance", "edit")
def rule_trigger_resolve(trigger_id):
    t = AttendanceRuleTriggered.query.filter_by(
        id=trigger_id, school_id=_sid()).first_or_404()
    t.resolved = True
    db.session.commit()
    return redirect(url_for("attendance.rules_list"))


# ─── T4: risk dashboard ────────────────────────────────────────────
@bp.route("/risk", endpoint="risk_dashboard")
@login_required
@require_permission("attendance", "view")
def risk_dashboard():
    rows = (
        StudentRiskScore.query.filter_by(school_id=_sid())
        .order_by(StudentRiskScore.score.desc())
        .limit(200).all()
    )
    # Tier distribution.
    tiers = dict(
        db.session.query(StudentRiskScore.tier, func.count(StudentRiskScore.id))
        .filter(StudentRiskScore.school_id == _sid())
        .group_by(StudentRiskScore.tier).all()
    )
    return render_template(
        "attendance/risk_dashboard.html",
        rows=rows, tiers=tiers,
    )


@bp.route("/risk/recompute", methods=["POST"], endpoint="risk_recompute")
@login_required
@require_permission("attendance", "edit")
def risk_recompute():
    from ...services.risk_score import run_for_school
    n = run_for_school(_sid())
    flash(f"تم إعادة حساب مؤشر المخاطر لـ {n} طالب.", "success")
    return redirect(url_for("attendance.risk_dashboard"))
