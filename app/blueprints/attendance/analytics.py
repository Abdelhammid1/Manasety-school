"""Phase-3 attendance analytics (tickets T1, T6, T7).

- attendance_dashboard  — T1  school-wide dashboard + chronic-absence list
- attendance_correlation — T6 attendance rate vs avg grade scatter table
- period_utilization    — T7  per-period attendance rates
"""

from datetime import date, timedelta
from decimal import Decimal

from flask import render_template
from flask_login import current_user, login_required
from sqlalchemy import func

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import (
    AcademicYear, Attendance, Enrollment, GradeEntry, Period, Student,
)


def _sid():
    return current_user.school_id


def _active_year():
    return AcademicYear.query.filter_by(school_id=_sid(), status="active").first()


@bp.route("/dashboards/overview", endpoint="attendance_dashboard")
@login_required
@require_permission("attendance", "view")
def attendance_dashboard():
    """Ticket T1 — school-wide attendance dashboard.

    Reads `_derive_day_status` from the routes module so numbers stay
    consistent with the per-student / per-section reports (avoids the
    double-count in `both` mode)."""
    from .routes import _derive_day_status
    year = _active_year()
    end = date.today()
    start = end - timedelta(days=30)

    # Aggregate raw statuses over the last 30 days.
    rows = (
        db.session.query(Attendance.status, func.count(Attendance.id))
        .filter(
            Attendance.school_id == _sid(),
            Attendance.date >= start, Attendance.date <= end,
        )
        .group_by(Attendance.status).all()
    )
    totals = {s: n for s, n in rows}
    grand = sum(totals.values())
    kpi = {
        "present":     totals.get("present", 0),
        "absent":      totals.get("absent", 0),
        "late":        totals.get("late", 0),
        "excused":     totals.get("excused", 0),
        "attendance_rate": (
            round(totals.get("present", 0) / grand * 100, 1)
            if grand else 0
        ),
    }

    # Chronic-absence list: students with >=5 absent days in the window.
    THRESHOLD = 5
    absent_by_student = (
        db.session.query(
            Enrollment.student_id, func.count(Attendance.id).label("n"),
        )
        .join(Attendance, Attendance.enrollment_id == Enrollment.id)
        .filter(
            Enrollment.school_id == _sid(),
            Enrollment.status == "active",
            Attendance.date >= start, Attendance.date <= end,
            Attendance.status == "absent",
        )
        .group_by(Enrollment.student_id)
        .having(func.count(Attendance.id) >= THRESHOLD)
        .order_by(func.count(Attendance.id).desc())
        .limit(30).all()
    )
    chronic = []
    for stu_id, cnt in absent_by_student:
        stu = Student.query.get(stu_id)
        if stu:
            chronic.append({
                "id": stu.id, "name": stu.full_name,
                "permanent_code": stu.permanent_code,
                "absent_days": cnt,
            })

    # Trend: absent count per day for a sparkline.
    trend = (
        db.session.query(Attendance.date, func.count(Attendance.id))
        .filter(
            Attendance.school_id == _sid(),
            Attendance.status == "absent",
            Attendance.date >= start, Attendance.date <= end,
        )
        .group_by(Attendance.date)
        .order_by(Attendance.date.asc()).all()
    )
    trend_data = [{"date": d.isoformat(), "n": n} for d, n in trend]

    return render_template(
        "attendance/dashboard.html",
        year=year, start=start, end=end,
        kpi=kpi, chronic=chronic, threshold=THRESHOLD,
        trend_data=trend_data,
    )


@bp.route("/dashboards/correlation", endpoint="attendance_correlation")
@login_required
@require_permission("attendance", "view")
def attendance_correlation():
    """Ticket T6 — pair each active student's attendance rate with
    their average grade so the pattern (falling attendance → falling
    grades) is visible."""
    year = _active_year()
    pairs = []
    if not year:
        return render_template(
            "attendance/correlation.html", pairs=[], year=year,
        )
    enrollments = (
        Enrollment.query.filter_by(
            school_id=_sid(), year_id=year.id, status="active")
        .join(Student).order_by(Student.full_name).all()
    )
    for e in enrollments:
        att = (
            db.session.query(Attendance.status, func.count(Attendance.id))
            .filter(Attendance.enrollment_id == e.id)
            .group_by(Attendance.status).all()
        )
        d = {s: n for s, n in att}
        p = d.get("present", 0); a = d.get("absent", 0); l = d.get("late", 0)
        total = p + a + l
        if total == 0:
            continue
        rate = round(p / total * 100, 1)
        avg = (
            db.session.query(func.avg(GradeEntry.value))
            .filter(GradeEntry.enrollment_id == e.id)
            .scalar()
        )
        pairs.append({
            "student":     e.student.full_name,
            "code":        e.student.permanent_code,
            "attendance":  rate,
            "avg_grade":   round(float(avg), 2) if avg is not None else None,
        })
    # Simple sort — worst attendance first so the pattern stands out.
    pairs.sort(key=lambda r: r["attendance"])
    return render_template(
        "attendance/correlation.html", pairs=pairs, year=year,
    )


@bp.route("/dashboards/per-period", endpoint="period_utilization")
@login_required
@require_permission("attendance", "view")
def period_utilization():
    """Ticket T7 — attendance rate per period. Rows without a
    period_id (daily-mode entries) are excluded — this analysis is
    only meaningful when at least some rows are per-period."""
    rows = (
        db.session.query(
            Attendance.period_id,
            func.count(Attendance.id).label("total"),
            func.sum(
                func.cast(Attendance.status == "present", db.Integer)
            ).label("present"),
        )
        .filter(
            Attendance.school_id == _sid(),
            Attendance.period_id.isnot(None),
        )
        .group_by(Attendance.period_id)
        .order_by(Attendance.period_id.asc())
        .all()
    )
    period_rows = []
    for pid, total, present in rows:
        p = Period.query.get(pid) if pid else None
        rate = round((present or 0) / total * 100, 1) if total else 0
        period_rows.append({
            "period_id":   pid,
            "period_name": (p.name if p else f"#{pid}"),
            "total":       total,
            "present":     present or 0,
            "rate":        rate,
        })
    return render_template(
        "attendance/period_utilization.html",
        rows=period_rows,
    )
