"""Ticket S1 — Student 360° view service.

Assembles the "most-recent one signal per system" snapshot the
unified profile page will render. Reads only, no side-effects.

Called by both the web dashboard and the parent app JSON endpoint —
keep this pure so both surfaces stay consistent."""

from decimal import Decimal
from sqlalchemy import func

from ..extensions import db
from ..models import (
    Attendance, BehaviorIncident, Enrollment, GradeEntry, HealthIncident,
    Invoice, Payment, Student, StudentDocument, StudentHealthProfile,
)


def build_student_360(student_id: int) -> dict:
    """Return a nested dict with the most-recent indicator from every
    relevant table for `student_id`. Never raises when a table is
    empty — missing indicators come back as None."""
    student = Student.query.get(student_id)
    if student is None:
        return {}

    result = {
        "student": {
            "id": student.id,
            "full_name": student.full_name,
            "permanent_code": student.permanent_code,
            "gender": student.gender,
            "photo_url": student.photo_url,
        },
        "academic": _academic_snapshot(student),
        "attendance": _attendance_snapshot(student),
        "behavior": _behavior_snapshot(student),
        "financial": _financial_snapshot(student),
        "health": _health_snapshot(student),
        "documents": _documents_snapshot(student),
        "siblings": _siblings_snapshot(student),
    }
    return result


# ─── Individual snapshots ──────────────────────────────────────────
def _academic_snapshot(student):
    eids = [e.id for e in student.enrollments if e.status == "active"]
    if not eids:
        return {"last_grade": None, "avg_grade": None,
                "current_section": None}
    last_grade = (
        GradeEntry.query.filter(GradeEntry.enrollment_id.in_(eids))
        .order_by(GradeEntry.id.desc()).first()
    )
    avg = (
        db.session.query(func.avg(GradeEntry.value))
        .filter(GradeEntry.enrollment_id.in_(eids)).scalar()
    )
    active = next((e for e in student.enrollments if e.status == "active"), None)
    return {
        "last_grade": (
            {"value": float(last_grade.value) if last_grade.value else None,
             "recorded_at": last_grade.recorded_at.isoformat()
                            if last_grade.recorded_at else None}
            if last_grade else None
        ),
        "avg_grade": round(float(avg), 2) if avg is not None else None,
        "current_section": (
            {"grade": active.grade.name if active and active.grade else None,
             "section": active.section.name if active and active.section else None}
            if active else None
        ),
    }


def _attendance_snapshot(student):
    eids = [e.id for e in student.enrollments if e.status == "active"]
    if not eids:
        return {"last_seen": None, "rate": 0}
    last = (
        Attendance.query.filter(Attendance.enrollment_id.in_(eids))
        .order_by(Attendance.date.desc()).first()
    )
    rows = dict(
        db.session.query(Attendance.status, func.count(Attendance.id))
        .filter(Attendance.enrollment_id.in_(eids))
        .group_by(Attendance.status).all()
    )
    p = rows.get("present", 0); a = rows.get("absent", 0); l = rows.get("late", 0)
    total = p + a + l
    return {
        "last_seen": (
            {"date": last.date.isoformat() if last and last.date else None,
             "status": last.status if last else None}
            if last else None
        ),
        "rate": round(p / total * 100, 1) if total else 0,
    }


def _behavior_snapshot(student):
    rows = BehaviorIncident.query.filter_by(student_id=student.id).all()
    total = sum(int(r.points or 0) for r in rows)
    last = max(rows, key=lambda r: r.incident_date, default=None) if rows else None
    return {
        "total_points": total,
        "incidents_count": len(rows),
        "last_incident": (
            {"date": last.incident_date.isoformat() if last and last.incident_date else None,
             "points": int(last.points or 0)}
            if last else None
        ),
    }


def _financial_snapshot(student):
    eids = [e.id for e in student.enrollments]
    if not eids:
        return {"invoiced": 0, "paid": 0, "remaining": 0}
    invoiced = paid = Decimal("0")
    invoices = Invoice.query.filter(Invoice.enrollment_id.in_(eids)).all()
    for inv in invoices:
        invoiced += inv.total_amount or 0
        paid     += inv.paid_amount or 0
    return {
        "invoiced":  float(invoiced),
        "paid":      float(paid),
        "remaining": float(invoiced - paid),
    }


def _health_snapshot(student):
    profile = StudentHealthProfile.query.filter_by(student_id=student.id).first()
    incidents = HealthIncident.query.filter_by(student_id=student.id).count()
    return {
        "has_profile": profile is not None,
        "blood_type":  getattr(profile, "blood_type", None) if profile else None,
        "allergies":   getattr(profile, "allergies", None) if profile else None,
        "chronic_conditions": (
            getattr(profile, "chronic_conditions", None) if profile else None
        ),
        "incidents_count": incidents,
    }


def _documents_snapshot(student):
    docs = StudentDocument.query.filter_by(student_id=student.id).count()
    return {"count": docs}


def _siblings_snapshot(student):
    from ..blueprints.students.feature_extras import count_siblings
    return {"count": count_siblings(student)}
