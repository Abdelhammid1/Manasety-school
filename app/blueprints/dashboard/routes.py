"""School-admin dashboard — operational metrics, alerts, quick actions.

Every query is scoped by ``sid = current_user.school_id`` and (where relevant)
by the active academic year. Everything is wrapped in try/except so one
query that trips on a missing table / bad column doesn't blank the whole
page — a widget just shows its safe default (0, empty list) instead.
"""
from datetime import date, datetime, timedelta

from flask import render_template
from flask_login import current_user, login_required
from sqlalchemy import func

from . import bp
from ..utils import admin_only
from ...extensions import db
from ...models import (
    AcademicYear, Account, Attendance, Enrollment, Expense, Grade, Installment,
    Invoice, NotificationLog, Payment, Section, Student, Subject, Teacher, User,
)


def _safe(fn, default=None):
    """Run ``fn()``, swallow any exception, return ``default``."""
    try:
        return fn()
    except Exception:
        db.session.rollback()
        return default


def _sections_unmarked_today(sid: int, yid: int, cap: int = 8):
    """Return up to ``cap`` active sections in the year that have NO attendance
    row for today across their active enrollments.

    Implementation is a Python-side anti-join — a single SELECT of every
    enrollment_id that WAS marked today, then filter sections whose active
    enrollments don't intersect that set. Small N — fine at school scale.
    """
    today = date.today()
    marked_ids = {
        r[0]
        for r in db.session.query(Attendance.enrollment_id)
        .filter(Attendance.school_id == sid, Attendance.date == today)
        .all()
    }
    sections = (
        Section.query.filter_by(school_id=sid, year_id=yid)
        .join(Grade, Grade.id == Section.grade_id)
        .order_by(Grade.order_index.asc(), Section.name.asc())
        .all()
    )
    rows = []
    for sec in sections:
        active_enrolls = [e for e in sec.enrollments if e.status == "active"]
        if not active_enrolls:
            continue
        active_ids = {e.id for e in active_enrolls}
        if active_ids & marked_ids:
            continue
        rows.append({
            "section_id": sec.id,
            "section_name": sec.name,
            "grade_name": sec.grade.name if sec.grade else "—",
            "students_count": len(active_enrolls),
        })
        if len(rows) >= cap:
            break
    return rows


def _installments_due_next_7d(sid: int, cap: int = 8):
    """Installments due today→+7d that aren't fully paid, with student names."""
    today = date.today()
    horizon = today + timedelta(days=7)
    q = (
        db.session.query(Installment, Invoice, Student)
        .join(Invoice, Invoice.id == Installment.invoice_id)
        .join(Enrollment, Enrollment.id == Invoice.enrollment_id)
        .join(Student, Student.id == Enrollment.student_id)
        .filter(
            Invoice.school_id == sid,
            Installment.due_date >= today,
            Installment.due_date <= horizon,
            Installment.status != "paid",
        )
        .order_by(Installment.due_date.asc())
        .limit(cap)
    )
    return [
        {
            "installment_id": inst.id,
            "invoice_id": inv.id,
            "student_name": stu.full_name,
            "due_date": inst.due_date,
            "amount": float(inst.remaining),
        }
        for inst, inv, stu in q.all()
    ]


def _attendance_today(sid: int):
    """Aggregate attendance counts + rate for today."""
    today = date.today()
    rows = (
        db.session.query(Attendance.status, func.count(Attendance.id))
        .filter(Attendance.school_id == sid, Attendance.date == today)
        .group_by(Attendance.status)
        .all()
    )
    by_status = {s: int(c) for s, c in rows}
    present = by_status.get("present", 0)
    absent = by_status.get("absent", 0)
    late = by_status.get("late", 0)
    total = present + absent + late
    rate = round((present / total) * 100) if total else 0
    return {"present": present, "absent": absent, "late": late, "total": total, "rate": rate}


def _outstanding_ar(sid: int, yid: int) -> float:
    """Sum of Invoice.total_amount - Invoice.paid_amount for the active year.

    Filter by year via join through Enrollment (Invoice has no year_id).
    """
    q = (
        db.session.query(
            func.coalesce(func.sum(Invoice.total_amount - Invoice.paid_amount), 0)
        )
        .join(Enrollment, Enrollment.id == Invoice.enrollment_id)
        .filter(
            Invoice.school_id == sid,
            Enrollment.year_id == yid,
            Invoice.status != "paid",
        )
    )
    return float(q.scalar() or 0)


def _overdue_invoices_count(sid: int) -> int:
    """Dynamic overdue — Invoice.status is not auto-flipped, so compute:
    due_date < today AND paid_amount < total_amount AND status != 'paid'.
    """
    today = date.today()
    return int(
        Invoice.query.filter(
            Invoice.school_id == sid,
            Invoice.due_date < today,
            Invoice.paid_amount < Invoice.total_amount,
            Invoice.status != "paid",
        ).count()
    )


def _payments_sum(sid: int, since: date) -> float:
    q = (
        db.session.query(func.coalesce(func.sum(Payment.amount), 0))
        .filter(
            Payment.school_id == sid,
            Payment.is_refund.is_(False),
            Payment.payment_date >= since,
        )
    )
    return float(q.scalar() or 0)


def _expenses_sum(sid: int, since: date) -> float:
    q = (
        db.session.query(func.coalesce(func.sum(Expense.amount), 0))
        .filter(Expense.school_id == sid, Expense.date >= since)
    )
    return float(q.scalar() or 0)


def _cash_on_hand(sid: int) -> float:
    """Sum balances of asset accounts of the school (best-effort proxy for
    liquid cash). Uses ``Account.balance`` @property from the finance model.
    """
    accts = Account.query.filter_by(school_id=sid, type="asset", is_active=True).all()
    return sum(a.balance for a in accts)


def _students_by_grade(sid: int, yid: int):
    """List of {grade_name, count} for active enrollments this year, ordered
    by ``Grade.order_index``."""
    rows = (
        db.session.query(Grade.name, Grade.order_index, func.count(Enrollment.id))
        .join(Enrollment, Enrollment.grade_id == Grade.id)
        .filter(
            Enrollment.school_id == sid,
            Enrollment.year_id == yid,
            Enrollment.status == "active",
        )
        .group_by(Grade.id, Grade.name, Grade.order_index)
        .order_by(Grade.order_index.asc())
        .all()
    )
    return [{"grade_name": n, "count": int(c)} for (n, _o, c) in rows]


def _sections_near_capacity(sid: int, yid: int, threshold: float = 0.9, cap: int = 8):
    """Sections in the active year that are ≥ ``threshold`` full."""
    sections = Section.query.filter_by(school_id=sid, year_id=yid).all()
    out = []
    for sec in sections:
        current = sec.current_count  # uses model @property
        cap_int = int(sec.capacity or 0)
        if cap_int <= 0:
            continue
        pct = current / cap_int
        if pct < threshold:
            continue
        out.append({
            "section_id": sec.id,
            "section_name": sec.name,
            "grade_name": sec.grade.name if sec.grade else "—",
            "current_count": current,
            "capacity": cap_int,
            "pct": round(pct * 100),
        })
    out.sort(key=lambda r: -r["pct"])
    return out[:cap]


def _new_students_this_month(sid: int) -> int:
    start = date.today().replace(day=1)
    return int(
        Student.query.filter(
            Student.school_id == sid,
            Student.created_at >= datetime.combine(start, datetime.min.time()),
        ).count()
    )


def _failed_notifications_last_7d(sid: int) -> int:
    since = datetime.utcnow() - timedelta(days=7)
    return int(
        NotificationLog.query.filter(
            NotificationLog.school_id == sid,
            NotificationLog.status == "failed",
            NotificationLog.created_at >= since,
        ).count()
    )


def _users_locked_now(sid: int) -> int:
    now = datetime.utcnow()
    return int(
        User.query.filter(
            User.school_id == sid,
            User.locked_until.isnot(None),
            User.locked_until > now,
        ).count()
    )


@bp.route("/dashboard")
@login_required
@admin_only
def home():
    sid = current_user.school_id
    active_year = _safe(
        lambda: AcademicYear.query.filter_by(school_id=sid, status="active").first()
    )
    yid = active_year.id if active_year else 0

    today = date.today()
    start_of_month = today.replace(day=1)

    # ── baseline counts (already on the old dashboard) ──────────────────────
    students_total = _safe(
        lambda: Student.query.filter_by(school_id=sid).count(), 0)
    students_active = _safe(
        lambda: Enrollment.query.filter_by(
            school_id=sid, year_id=yid, status="active").count(), 0) if yid else 0

    # ── daily-ops metrics ───────────────────────────────────────────────────
    attendance_today = _safe(lambda: _attendance_today(sid),
                             {"present": 0, "absent": 0, "late": 0, "total": 0, "rate": 0})
    sections_unmarked = _safe(
        lambda: _sections_unmarked_today(sid, yid), []) if yid else []
    installments_due_7d = _safe(lambda: _installments_due_next_7d(sid), [])

    # ── money row ───────────────────────────────────────────────────────────
    outstanding_ar = _safe(lambda: _outstanding_ar(sid, yid), 0.0) if yid else 0.0
    overdue_invoices = _safe(lambda: _overdue_invoices_count(sid), 0)
    collections_today = _safe(lambda: _payments_sum(sid, today), 0.0)
    collections_mtd = _safe(lambda: _payments_sum(sid, start_of_month), 0.0)
    expenses_mtd = _safe(lambda: _expenses_sum(sid, start_of_month), 0.0)
    cash_on_hand = _safe(lambda: _cash_on_hand(sid), 0.0)

    # ── academic snapshot ───────────────────────────────────────────────────
    students_by_grade = _safe(
        lambda: _students_by_grade(sid, yid), []) if yid else []
    sections_at_capacity = _safe(
        lambda: _sections_near_capacity(sid, yid), []) if yid else []
    new_students_month = _safe(lambda: _new_students_this_month(sid), 0)

    # ── system health ───────────────────────────────────────────────────────
    users_active = _safe(
        lambda: User.query.filter_by(school_id=sid, is_active=True).count(), 0)
    users_locked = _safe(lambda: _users_locked_now(sid), 0)
    notifications_failed = _safe(lambda: _failed_notifications_last_7d(sid), 0)
    teachers_active = _safe(
        lambda: Teacher.query.filter_by(school_id=sid, is_active=True).count(), 0)

    # ── baseline structural counts (kept for footer stats) ──────────────────
    grades_count = _safe(lambda: Grade.query.filter_by(school_id=sid).count(), 0)
    sections_count = _safe(
        lambda: Section.query.filter_by(school_id=sid, year_id=yid).count(), 0) if yid else 0
    subjects_count = _safe(lambda: Subject.query.filter_by(school_id=sid).count(), 0)

    stats = {
        # baseline
        "active_year": active_year.name if active_year else "—",
        "students_total": students_total,
        "students_active": students_active,
        "grades_count": grades_count,
        "sections_count": sections_count,
        "subjects_count": subjects_count,
        # daily ops
        "attendance_today": attendance_today,
        "sections_unmarked": sections_unmarked,
        "installments_due_7d": installments_due_7d,
        "installments_due_7d_total": sum(r["amount"] for r in installments_due_7d),
        # money
        "outstanding_ar": outstanding_ar,
        "overdue_invoices": overdue_invoices,
        "collections_today": collections_today,
        "collections_mtd": collections_mtd,
        "expenses_mtd": expenses_mtd,
        "cash_on_hand": cash_on_hand,
        # academic
        "students_by_grade": students_by_grade,
        "students_by_grade_max": max((r["count"] for r in students_by_grade), default=0),
        "sections_at_capacity": sections_at_capacity,
        "new_students_month": new_students_month,
        # system
        "users_active": users_active,
        "users_locked": users_locked,
        "notifications_failed": notifications_failed,
        "teachers_active": teachers_active,
    }
    return render_template("dashboard/home.html", stats=stats, today=today)
