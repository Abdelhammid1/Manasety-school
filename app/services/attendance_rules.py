"""Ticket T3 — Attendance rules engine.

Given a student + a fresh absence, evaluate every active
`AttendanceRule` for the school and enqueue notifications when a
threshold is crossed. Deduplicated by an idempotent write to
`AttendanceRuleTriggered`.

Also exposes `run_for_school(school_id)` for a scheduled sweep so the
same evaluator can be called from cron even without a new absence
event (catches back-dated entries)."""

from datetime import date, timedelta
from typing import Iterable

from ..extensions import db
from ..models import (
    Attendance, AttendanceRule, AttendanceRuleTriggered,
    Enrollment, Student,
)
from .notifications import send_notification


def evaluate_after_absence(*, student, absence_date):
    """Called from attendance.mark right after an 'absent' row is
    persisted. Runs every active rule for this school and fires the
    action once per (rule, student, ISO week) so a rerun in the same
    week stays a no-op."""
    return _run_for_student(student, ref_date=absence_date)


def run_for_school(school_id, *, today=None):
    """Cron entrypoint. Sweeps every active enrollment, feeds each
    student through the same evaluator. Returns the count of rows
    inserted into AttendanceRuleTriggered."""
    today = today or date.today()
    seen_students = set()
    inserted = 0
    active = (
        Enrollment.query.filter_by(school_id=school_id, status="active")
        .all()
    )
    for e in active:
        if e.student_id in seen_students:
            continue
        seen_students.add(e.student_id)
        stu = Student.query.get(e.student_id)
        if stu:
            inserted += _run_for_student(stu, ref_date=today)
    return inserted


def _run_for_student(student, *, ref_date):
    rules = AttendanceRule.query.filter_by(
        school_id=student.school_id, is_active=True,
    ).all()
    if not rules:
        return 0
    inserted = 0
    for rule in rules:
        count = _count_for_rule(student, rule, ref_date=ref_date)
        if count < rule.threshold:
            continue
        # Idempotency: one trigger per (rule, student, week).
        iso_year, iso_week, _ = ref_date.isocalendar()
        week_start = ref_date - timedelta(days=ref_date.weekday())
        already = AttendanceRuleTriggered.query.filter_by(
            rule_id=rule.id, student_id=student.id,
            triggered_on=week_start,
        ).first()
        if already:
            continue
        trig = AttendanceRuleTriggered(
            school_id=student.school_id, rule_id=rule.id,
            student_id=student.id,
            triggered_on=week_start,
            count_at_trigger=count,
        )
        db.session.add(trig)
        inserted += 1
        _do_action(rule, student, count)
    db.session.commit()
    return inserted


def _count_for_rule(student, rule, *, ref_date):
    eids = [e.id for e in student.enrollments if e.status == "active"]
    if not eids:
        return 0
    window_start = _window_start(rule.window, ref_date=ref_date, student=student)
    rows = (
        Attendance.query.filter(
            Attendance.enrollment_id.in_(eids),
            Attendance.status == "absent",
            Attendance.date >= window_start,
            Attendance.date <= ref_date,
        ).order_by(Attendance.date.asc()).all()
    )
    if rule.kind == "consecutive":
        # Longest run of consecutive absent days ending on ref_date.
        # Walk backwards from ref_date; break on any gap or non-absent.
        days = {r.date for r in rows}
        run = 0
        d = ref_date
        while d in days:
            run += 1
            d = d - timedelta(days=1)
        return run
    # cumulative
    return len({r.date for r in rows})


def _window_start(window, *, ref_date, student):
    if window and window.startswith("days:"):
        try:
            n = int(window.split(":", 1)[1])
        except ValueError:
            n = 30
        return ref_date - timedelta(days=n)
    if window == "year":
        active = next(
            (e for e in student.enrollments if e.status == "active"), None,
        )
        if active and active.year and active.year.start_date:
            return active.year.start_date
    # Default: term start ≈ the last 90 days.
    return ref_date - timedelta(days=90)


def _do_action(rule, student, count):
    """Attach the actual side-effect of a rule trigger."""
    if rule.action == "notify_guardian":
        payload = {
            "student": student.full_name,
            "permanent_code": student.permanent_code,
            "rule": rule.name,
            "count": count,
            "message": (
                f"تنبيه: تم رصد {count} غياب على ابنكم "
                f"{student.full_name} — {rule.name}."
            ),
        }
        for link in getattr(student, "guardian_links", None) or []:
            if not link.can_receive_notifications:
                continue
            g = link.guardian
            phone = (getattr(g, "phone", "") or "").strip()
            if not phone:
                continue
            send_notification(
                school_id=student.school_id,
                kind="attendance_rule",
                payload=payload,
                target_phone=phone,
                student_id=student.id,
            )
    # `warning` and `escalate_admin` are surfaced via the
    # AttendanceRuleTriggered row itself — admins can query for
    # unresolved rows via a dashboard filter.
