"""Ticket T2 — Leave management workflow.

Endpoints
- GET  /hr/leave                  — list + status filter
- POST /hr/leave/new              — file a request
- POST /hr/leave/<id>/approve     — approve + materialise StaffAttendance
- POST /hr/leave/<id>/reject      — reject with reason
- GET  /hr/leave/balances         — per-employee balance table
- POST /hr/leave/balances/new     — issue an annual balance row
- POST /hr/leave/balances/reset   — roll every balance forward at year-close
"""

from datetime import date, datetime

from flask import (
    flash, redirect, render_template, request, url_for,
)
from flask_login import current_user, login_required

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import (
    Employee, LeaveBalance, LeaveRequest,
    StaffAttendance,
)


def _sid():
    return current_user.school_id


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _balance_for(employee_id, year, leave_type):
    return LeaveBalance.query.filter_by(
        school_id=_sid(),
        employee_id=employee_id, year=year, leave_type=leave_type,
    ).first()


@bp.route("/leave", endpoint="leave_requests_list")
@login_required
@require_permission("payroll", "view")
def leave_requests_list():
    status = (request.args.get("status") or "").strip()
    q = LeaveRequest.query.filter_by(school_id=_sid())
    if status:
        q = q.filter(LeaveRequest.status == status)
    rows = q.order_by(LeaveRequest.created_at.desc()).limit(200).all()
    employees = (
        Employee.query.filter_by(school_id=_sid(), is_active=True)
        .order_by(Employee.full_name).all()
    )
    return render_template(
        "hr/leave_list.html",
        rows=rows, status=status, employees=employees,
    )


@bp.route("/leave/new", methods=["POST"], endpoint="leave_request_new")
@login_required
@require_permission("payroll", "add")
def leave_request_new():
    employee_id = request.form.get("employee_id", type=int)
    leave_type = (request.form.get("leave_type") or "").strip()
    start = _parse_date(request.form.get("start_date"))
    end   = _parse_date(request.form.get("end_date"))
    reason = (request.form.get("reason") or "").strip() or None
    if not (employee_id and leave_type and start and end):
        flash("كل الحقول مطلوبة.", "danger")
        return redirect(url_for("hr.leave_requests_list"))
    if end < start:
        flash("تاريخ النهاية يجب أن يكون بعد تاريخ البداية.", "danger")
        return redirect(url_for("hr.leave_requests_list"))
    days = (end - start).days + 1

    # Balance advisory (not a hard-block per ticket).
    bal = _balance_for(employee_id, start.year, leave_type)
    if bal and bal.remaining_days < days:
        flash(
            f"تنبيه: الرصيد المتبقي {bal.remaining_days} يوم أقل من "
            f"المطلوب {days}. الطلب سيُنشأ بحالة pending للاعتماد.",
            "warning",
        )

    db.session.add(LeaveRequest(
        school_id=_sid(), employee_id=employee_id,
        leave_type=leave_type,
        start_date=start, end_date=end, days_count=days,
        reason=reason, status="pending",
    ))
    db.session.commit()
    flash("تم تسجيل طلب الإجازة (بانتظار الاعتماد).", "success")
    return redirect(url_for("hr.leave_requests_list"))


@bp.route("/leave/<int:req_id>/approve",
          methods=["POST"], endpoint="leave_request_approve")
@login_required
@require_permission("payroll", "edit")
def leave_request_approve(req_id):
    r = LeaveRequest.query.filter_by(
        id=req_id, school_id=_sid()).first_or_404()
    if r.status != "pending":
        flash("لا يمكن اعتماد طلب غير قيد المراجعة.", "danger")
        return redirect(url_for("hr.leave_requests_list"))

    # Materialise StaffAttendance rows for every day in [start, end].
    from datetime import timedelta
    d = r.start_date
    added = 0
    while d <= r.end_date:
        existing = StaffAttendance.query.filter_by(
            school_id=_sid(), employee_id=r.employee_id, date=d,
        ).first()
        if existing:
            existing.status = "leave"
            existing.leave_type = r.leave_type
        else:
            db.session.add(StaffAttendance(
                school_id=_sid(), employee_id=r.employee_id,
                date=d, status="leave", leave_type=r.leave_type,
            ))
            added += 1
        d += timedelta(days=1)

    # Bump the used_days on the matching (employee, year, type) balance.
    bal = _balance_for(r.employee_id, r.start_date.year, r.leave_type)
    if bal:
        bal.used_days = (bal.used_days or 0) + r.days_count

    r.status = "approved"
    r.approved_by_user_id = getattr(current_user, "id", None)
    r.approved_at = datetime.utcnow()
    db.session.commit()
    flash(
        f"تم اعتماد الطلب — {added} يوم جديد على السجل + رصيد {r.leave_type} "
        f"تم تحديثه.",
        "success",
    )
    return redirect(url_for("hr.leave_requests_list"))


@bp.route("/leave/<int:req_id>/reject",
          methods=["POST"], endpoint="leave_request_reject")
@login_required
@require_permission("payroll", "edit")
def leave_request_reject(req_id):
    r = LeaveRequest.query.filter_by(
        id=req_id, school_id=_sid()).first_or_404()
    if r.status != "pending":
        flash("الطلب معالج بالفعل.", "danger")
        return redirect(url_for("hr.leave_requests_list"))
    r.status = "rejected"
    r.reject_reason = (request.form.get("reason") or "").strip() or None
    r.approved_by_user_id = getattr(current_user, "id", None)
    r.approved_at = datetime.utcnow()
    db.session.commit()
    flash("تم رفض الطلب.", "success")
    return redirect(url_for("hr.leave_requests_list"))


# ─── Balances ──────────────────────────────────────────────────────
@bp.route("/leave/balances", endpoint="leave_balances_list")
@login_required
@require_permission("payroll", "view")
def leave_balances_list():
    year = request.args.get("year", type=int) or date.today().year
    rows = (
        LeaveBalance.query.filter_by(school_id=_sid(), year=year)
        .join(Employee).order_by(Employee.full_name).all()
    )
    employees = (
        Employee.query.filter_by(school_id=_sid(), is_active=True)
        .order_by(Employee.full_name).all()
    )
    return render_template(
        "hr/leave_balances.html",
        rows=rows, year=year, employees=employees,
    )


@bp.route("/leave/balances/new",
          methods=["POST"], endpoint="leave_balance_new")
@login_required
@require_permission("payroll", "edit")
def leave_balance_new():
    employee_id = request.form.get("employee_id", type=int)
    leave_type = (request.form.get("leave_type") or "").strip()
    year = request.form.get("year", type=int) or date.today().year
    total = request.form.get("total_days", type=float) or 0
    if not (employee_id and leave_type and total > 0):
        flash("الموظف ونوع الإجازة والرصيد مطلوبان.", "danger")
        return redirect(url_for("hr.leave_balances_list", year=year))
    row = _balance_for(employee_id, year, leave_type)
    if row is None:
        row = LeaveBalance(
            school_id=_sid(), employee_id=employee_id,
            year=year, leave_type=leave_type, total_days=total,
        )
        db.session.add(row)
    else:
        row.total_days = total
    db.session.commit()
    flash("تم تحديث الرصيد.", "success")
    return redirect(url_for("hr.leave_balances_list", year=year))


@bp.route("/leave/balances/reset",
          methods=["POST"], endpoint="leave_balances_reset")
@login_required
@require_permission("payroll", "edit")
def leave_balances_reset():
    """Ticket T2 — roll every prior-year balance forward at year-close.

    Copies each row's `total_days` to a fresh row for the target year
    with `used_days=0`. Existing rows in the target year are left
    alone so re-runs are safe."""
    target = request.form.get("target_year", type=int) or (date.today().year + 1)
    source = target - 1
    n = 0
    for src in LeaveBalance.query.filter_by(
        school_id=_sid(), year=source,
    ).all():
        existing = _balance_for(src.employee_id, target, src.leave_type)
        if existing:
            continue
        db.session.add(LeaveBalance(
            school_id=_sid(), employee_id=src.employee_id,
            year=target, leave_type=src.leave_type,
            total_days=src.total_days, used_days=0,
        ))
        n += 1
    db.session.commit()
    flash(f"تم تجديد {n} رصيد للسنة {target}.", "success")
    return redirect(url_for("hr.leave_balances_list", year=target))
