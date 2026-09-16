"""Ticket #9b — Staff attendance daily grid + substitutions log."""
from datetime import date
from decimal import Decimal

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import (
    Employee, StaffAttendance,
    Teacher, SubstitutionLog,
)


def _sid():
    return current_user.school_id


@bp.route("/staff-attendance", endpoint="staff_attendance")
@login_required
@require_permission("payroll", "view")
def staff_attendance_page():
    on_date = request.args.get("date") or date.today().isoformat()
    try:
        d = date.fromisoformat(on_date)
    except ValueError:
        d = date.today()
    employees = (
        Employee.query.filter_by(school_id=_sid(), is_active=True)
        .order_by(Employee.full_name).all()
    )
    existing = {
        r.employee_id: r for r in
        StaffAttendance.query.filter(
            StaffAttendance.employee_id.in_([e.id for e in employees]),
            StaffAttendance.date == d,
        ).all()
    }
    return render_template(
        "platform/staff_attendance.html",
        employees=employees, existing=existing, on_date=d,
    )


@bp.route("/staff-attendance", methods=["POST"], endpoint="staff_attendance_save")
@login_required
@require_permission("payroll", "edit")
def staff_attendance_save():
    try:
        d = date.fromisoformat(request.form.get("date") or "")
    except ValueError:
        d = date.today()
    employees = Employee.query.filter_by(school_id=_sid(), is_active=True).all()
    saved = 0
    for e in employees:
        status = request.form.get(f"status_{e.id}")
        if not status:
            continue
        row = StaffAttendance.query.filter_by(
            employee_id=e.id, date=d,
        ).first()
        if row is None:
            row = StaffAttendance(school_id=_sid(), employee_id=e.id, date=d)
            db.session.add(row)
        row.status = status
        row.leave_type = (request.form.get(f"leave_type_{e.id}") or "").strip() or None
        row.notes = (request.form.get(f"notes_{e.id}") or "").strip() or None
        saved += 1
    db.session.commit()
    flash(f"تم رصد حضور {saved} موظف بتاريخ {d}.", "success")
    return redirect(url_for("platform.staff_attendance", date=d.isoformat()))


# ─── Substitutions ─────────────────────────────────────────────────

@bp.route("/substitutions", endpoint="substitutions_list")
@login_required
@require_permission("schedule", "view")
def substitutions_list():
    items = (
        SubstitutionLog.query.filter_by(school_id=_sid())
        .order_by(SubstitutionLog.date.desc()).limit(200).all()
    )
    teachers = (
        Teacher.query.filter_by(school_id=_sid(), is_active=True)
        .order_by(Teacher.full_name).all()
    )
    from ...models import ScheduleSlot
    slots = (
        ScheduleSlot.query.filter_by(school_id=_sid())
        .order_by(ScheduleSlot.day_id, ScheduleSlot.period_id).all()
    )
    return render_template(
        "platform/substitutions.html",
        subs=items, teachers=teachers, slots=slots,
    )


@bp.route("/substitutions/new", methods=["POST"], endpoint="substitution_new")
@login_required
@require_permission("schedule", "edit")
def substitution_new():
    try:
        d = date.fromisoformat(request.form.get("date") or "")
    except ValueError:
        flash("التاريخ غير صالح.", "danger")
        return redirect(url_for("platform.substitutions_list"))
    slot_id = request.form.get("schedule_slot_id", type=int)
    original = request.form.get("original_teacher_id", type=int)
    sub = request.form.get("substitute_teacher_id", type=int)
    if not (slot_id and original and sub):
        flash("اختر الحصة والمعلم الأصلي والبديل.", "danger")
        return redirect(url_for("platform.substitutions_list"))
    if original == sub:
        flash("المعلم البديل لا يمكن أن يكون هو نفسه الأصلي.", "danger")
        return redirect(url_for("platform.substitutions_list"))
    log = SubstitutionLog(
        school_id=_sid(),
        schedule_slot_id=slot_id, date=d,
        original_teacher_id=original, substitute_teacher_id=sub,
        reason=(request.form.get("reason") or "").strip() or None,
        created_by_user_id=getattr(current_user, "id", None),
    )
    db.session.add(log); db.session.commit()
    flash("تم تسجيل التغطية.", "success")
    return redirect(url_for("platform.substitutions_list"))
