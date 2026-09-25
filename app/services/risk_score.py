"""Ticket T4 — Attendance-based risk score.

Feeds into `StudentRiskScore`. Weights and thresholds are hard-coded
for the v1; a settings surface can slot in later without changing the
signature."""

from datetime import date, datetime, timedelta

from ..extensions import db
from ..models import (
    Attendance, AttendanceRuleTriggered, BehaviorIncident,
    Enrollment, Student, StudentRiskScore,
)


# Component weights (must sum to 100).
W_ATTENDANCE_RATE   = 40
W_CHRONIC_ABSENCE   = 25
W_UNRESOLVED_RULES  = 20
W_BEHAVIOR_POINTS   = 15


def compute_for_student(student_id, *, ref_date=None):
    """Recompute the risk score for one student. Upserts the
    `StudentRiskScore` row and returns the score as an int."""
    student = Student.query.get(student_id)
    if student is None:
        return 0
    ref_date = ref_date or date.today()
    inputs = {}
    total = 0

    # 1) Attendance rate (last 30 days). Lower rate → higher risk.
    eids = [e.id for e in student.enrollments if e.status == "active"]
    if eids:
        window_start = ref_date - timedelta(days=30)
        rows = (
            Attendance.query.filter(
                Attendance.enrollment_id.in_(eids),
                Attendance.date >= window_start,
                Attendance.date <= ref_date,
            ).all()
        )
        p = sum(1 for r in rows if r.status == "present")
        a = sum(1 for r in rows if r.status == "absent")
        l = sum(1 for r in rows if r.status == "late")
        n = p + a + l
        att_rate = (p / n * 100) if n else 100
        # 100% attendance → 0; 0% attendance → full weight.
        att_component = int(round(W_ATTENDANCE_RATE * (100 - att_rate) / 100))
        inputs["attendance_rate"] = round(att_rate, 1)
        inputs["attendance_component"] = att_component
        total += att_component

        # 2) Chronic absence — days absent in the last 30 days.
        absent_days = len({r.date for r in rows if r.status == "absent"})
        # cap at 15 absent days → full weight.
        chr_component = int(round(
            W_CHRONIC_ABSENCE * min(absent_days, 15) / 15
        ))
        inputs["chronic_absence_days"] = absent_days
        inputs["chronic_component"] = chr_component
        total += chr_component
    else:
        inputs["attendance_rate"] = None
        inputs["attendance_component"] = 0
        inputs["chronic_absence_days"] = 0
        inputs["chronic_component"] = 0

    # 3) Unresolved rule triggers — cap at 5.
    unresolved = AttendanceRuleTriggered.query.filter_by(
        student_id=student.id, resolved=False,
    ).count()
    rule_component = int(round(
        W_UNRESOLVED_RULES * min(unresolved, 5) / 5
    ))
    inputs["unresolved_rule_triggers"] = unresolved
    inputs["rules_component"] = rule_component
    total += rule_component

    # 4) Behavior points (last term ≈ 90 days). Negative points push
    # risk up; positive/none contribute zero.
    win = ref_date - timedelta(days=90)
    bhv = sum(int(i.points or 0) for i in BehaviorIncident.query.filter_by(
        student_id=student.id,
    ).all() if i.incident_date and i.incident_date >= win)
    neg_points = abs(min(bhv, 0))
    behavior_component = int(round(
        W_BEHAVIOR_POINTS * min(neg_points, 20) / 20
    ))
    inputs["behavior_points_negative"] = neg_points
    inputs["behavior_component"] = behavior_component
    total += behavior_component

    total = max(0, min(100, total))
    tier = (
        "critical" if total >= 80 else
        "high"     if total >= 60 else
        "medium"   if total >= 40 else "low"
    )

    row = StudentRiskScore.query.filter_by(student_id=student.id).first()
    if row is None:
        row = StudentRiskScore(
            school_id=student.school_id, student_id=student.id,
        )
        db.session.add(row)
    row.score = total
    row.tier  = tier
    row.inputs = inputs
    row.computed_at = datetime.utcnow()
    db.session.commit()
    return total


def run_for_school(school_id, *, today=None):
    """Cron entrypoint — recompute for every active enrollment. Returns
    the count of students whose score was refreshed."""
    today = today or date.today()
    seen = set()
    updated = 0
    for e in Enrollment.query.filter_by(
        school_id=school_id, status="active",
    ).all():
        if e.student_id in seen:
            continue
        seen.add(e.student_id)
        compute_for_student(e.student_id, ref_date=today)
        updated += 1
    return updated
