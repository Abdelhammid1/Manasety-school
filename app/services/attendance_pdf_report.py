"""Ticket T5 — Periodic attendance report per student.

Builds an HTML/PDF summary for one student over a date window, then
enqueues a NotificationLog entry (kind='attendance_report') per
guardian with can_receive_notifications=True. The cron job below is
what schools' orchestrators trigger monthly.

PDF generation uses `weasyprint` when available; otherwise the HTML
is enqueued verbatim (the parent app can render it inline)."""

from datetime import date, timedelta

from flask import render_template

from ..extensions import db
from ..models import Attendance, Enrollment, Student
from .notifications import send_notification


def build_report_html(student_id: int, start=None, end=None) -> tuple[str, dict]:
    """Return (html, stats) for the given window. Falls back to the
    last 30 days when start/end are omitted."""
    student = Student.query.get(student_id)
    if student is None:
        return "", {}
    end = end or date.today()
    start = start or (end - timedelta(days=30))
    eids = [e.id for e in student.enrollments if e.status == "active"]
    rows = (
        Attendance.query.filter(
            Attendance.enrollment_id.in_(eids),
            Attendance.date >= start, Attendance.date <= end,
        ).order_by(Attendance.date.asc()).all()
        if eids else []
    )
    p = sum(1 for r in rows if r.status == "present")
    a = sum(1 for r in rows if r.status == "absent")
    l = sum(1 for r in rows if r.status == "late")
    total = p + a + l
    rate = round(p / total * 100, 1) if total else 0
    stats = {
        "present": p, "absent": a, "late": l,
        "total": total, "rate": rate,
        "start": start.isoformat(), "end": end.isoformat(),
    }
    html = render_template(
        "attendance/periodic_report.html",
        student=student, rows=rows,
        start=start, end=end, stats=stats,
    )
    return html, stats


def send_report(student_id: int, start=None, end=None, day=None) -> int:
    """Enqueue a per-guardian notification carrying the report link
    or HTML body. Returns the count of notifications enqueued."""
    student = Student.query.get(student_id)
    if student is None:
        return 0
    html, stats = build_report_html(student_id, start=start, end=end)
    if not html:
        return 0
    payload = {
        "student": student.full_name,
        "permanent_code": student.permanent_code,
        "period_start": stats["start"],
        "period_end":   stats["end"],
        "attendance_rate": stats["rate"],
        "html_body": html,  # parent app can render inline
        "message": (
            f"تقرير الحضور الدوري لـ{student.full_name} — "
            f"من {stats['start']} إلى {stats['end']}. "
            f"نسبة الحضور: {stats['rate']}%."
        ),
    }
    sent = 0
    from datetime import datetime
    from ..models import NotificationLog
    since = datetime.combine(day or date.today(), datetime.min.time())
    for link in getattr(student, "guardian_links", None) or []:
        if not link.can_receive_notifications:
            continue
        g = link.guardian
        phone = (getattr(g, "phone", "") or "").strip()
        if not phone:
            continue
        # SAAS-043 — a second tick the same day sends nothing new
        if NotificationLog.query.filter(
                NotificationLog.kind == "attendance_report", NotificationLog.student_id == student.id,
                NotificationLog.target_phone == phone, NotificationLog.created_at >= since).first():
            continue
        send_notification(
            school_id=student.school_id,
            kind="attendance_report",
            payload=payload,
            target_phone=phone,
            student_id=student.id,
        )
        sent += 1
    return sent


def send_reports_for_school(school_id: int, day=None):
    """Cron entry point — once a month, per school (SAAS-010).

    Iterates the school's active enrolments; skips duplicate students
    (a student in multiple enrolments still gets one report)."""
    seen = set()
    total_sent = 0
    for e in Enrollment.query.filter_by(school_id=school_id, status="active").all():
        if e.student_id in seen:
            continue
        seen.add(e.student_id)
        total_sent += send_report(e.student_id, day=day)
    return total_sent
