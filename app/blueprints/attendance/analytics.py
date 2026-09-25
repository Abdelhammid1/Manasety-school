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

    # Ticket T3-aware: pull every row and derive one status per
    # (enrollment, date) so `both`-mode schools don't double-count.
    # Raw GROUP BY over Attendance.status would count a period row +
    # a daily row for the same date as two events, which is exactly
    # the bug T3 killed for the per-student report.
    raw_rows = (
        Attendance.query.filter(
            Attendance.school_id == _sid(),
            Attendance.date >= start, Attendance.date <= end,
        ).all()
    )
    grouped = {}
    for r in raw_rows:
        grouped.setdefault((r.enrollment_id, r.date), []).append(r)
    totals = {"present": 0, "absent": 0, "late": 0,
              "excused": 0, "partial": 0, "left_early": 0}
    for day_records in grouped.values():
        s = _derive_day_status(day_records)
        if s and s in totals:
            totals[s] += 1
    grand = sum(totals.values())
    kpi = {
        "present":     totals["present"],
        "absent":      totals["absent"],
        "late":        totals["late"],
        "excused":     totals["excused"],
        "attendance_rate": (
            round(totals["present"] / grand * 100, 1)
            if grand else 0
        ),
    }

    # Chronic-absence list: students with >=5 absent DAYS (post-derive)
    # in the window. Uses the already-grouped structure above to make
    # this consistent with the KPI numbers.
    THRESHOLD = 5
    from ...models import Enrollment as _Enr
    absent_days_by_student = {}
    for (eid, _d), day_records in grouped.items():
        if _derive_day_status(day_records) != "absent":
            continue
        e = _Enr.query.get(eid)
        if not e:
            continue
        absent_days_by_student[e.student_id] = (
            absent_days_by_student.get(e.student_id, 0) + 1
        )
    absent_by_student = sorted(
        [(sid, n) for sid, n in absent_days_by_student.items()
         if n >= THRESHOLD],
        key=lambda x: -x[1],
    )[:30]
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
