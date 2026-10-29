"""Which guardian a list shows for a student — the students list and the
section page use the same rule."""

from __future__ import annotations

from ..extensions import db


def shown_guardians(school_id: int, student_ids) -> dict:
    """{student_id: (name, phone)}: the primary guardian link, else the
    first one linked — one query for the page. Students with no link are
    absent (the caller falls back to the old parent_name)."""
    from ..models import Guardian, StudentGuardian
    student_ids = list(student_ids or ())
    if not student_ids:
        return {}
    rows = (db.session.query(StudentGuardian.student_id, Guardian.full_name, Guardian.phone)
            .join(Guardian, Guardian.id == StudentGuardian.guardian_id)
            .filter(StudentGuardian.student_id.in_(student_ids), Guardian.school_id == school_id)
            .order_by(StudentGuardian.student_id, StudentGuardian.is_primary.desc(),
                      StudentGuardian.id)
            .all())
    out = {}
    for sid, name, phone in rows:
        out.setdefault(sid, (name, phone))
    return out
