"""نداء — parent pickup call helpers.

Central place where a "parent has arrived and is waiting outside"
signal is created, resolved to the student's current section and
responsible teacher, and broadcast through the notifications
pipeline to the student + teacher.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..extensions import db
from ..models import PickupCall, Student, User
from ..models.teacher import Assignment


def _resolve_section_and_teacher(student: Student):
    """Pick the student's currently-active section, then the first
    teacher assigned to that section (any subject) as the responsible
    teacher. Falls back to None on both if nothing matches."""
    enrollment = next(
        (e for e in student.enrollments if e.status == "active"),
        None,
    )
    if not enrollment:
        return None, None
    section_id = enrollment.section_id
    asg = (
        Assignment.query
        .filter(Assignment.section_id == section_id,
                Assignment.is_active == True)  # noqa: E712
        .order_by(Assignment.id.asc())
        .first()
    )
    teacher_user_id = None
    if asg and asg.teacher and asg.teacher.user_id:
        teacher_user_id = asg.teacher.user_id
    return section_id, teacher_user_id


def find_active_call(parent_user_id: int, student_id: int) -> PickupCall | None:
    return (
        PickupCall.query
        .filter(PickupCall.parent_user_id == parent_user_id,
                PickupCall.student_id == student_id,
                PickupCall.released_at.is_(None))
        .order_by(PickupCall.called_at.desc())
        .first()
    )


def create_call(parent: User, student: Student,
                gate: str | None = None, note: str | None = None) -> PickupCall:
    """Idempotent — returns the existing open call if one is already
    active, otherwise creates a new one, notifies the student and the
    homeroom teacher, and returns it."""
    open_call = find_active_call(parent.id, student.id)
    if open_call is not None:
        return open_call
    section_id, teacher_user_id = _resolve_section_and_teacher(student)
    call = PickupCall(
        school_id=student.school_id,
        parent_user_id=parent.id,
        student_id=student.id,
        section_id=section_id,
        teacher_user_id=teacher_user_id,
        gate=(gate or "").strip() or None,
        note=(note or "").strip() or None,
    )
    db.session.add(call); db.session.flush()

    # Fan out via the existing notifications pipeline. Delivery to the
    # apps is handled by the notifications service — we only enqueue.
    try:
        from . import notifications as _n
        parent_name = parent.username or "ولي الأمر"
        body = f"{parent_name} في انتظار {student.full_name} خارج المدرسة الآن."
        if hasattr(_n, "notify_user") and teacher_user_id:
            _n.notify_user(teacher_user_id, "نداء ولي أمر",
                           body, kind="pickup_call", data={"call_id": call.id})
        # Notify the student (via their linked User row if any).
        if hasattr(_n, "notify_user"):
            st_uid = getattr(student, "user_id", None)
            if st_uid:
                _n.notify_user(st_uid, "ولي أمرك في انتظارك",
                               body, kind="pickup_call",
                               data={"call_id": call.id})
    except Exception:
        # Notifications are best-effort; the record is the source of truth.
        pass

    db.session.commit()
    return call


def release_call(call: PickupCall, released_by: User):
    call.released_at = datetime.now(timezone.utc)
    call.released_by_user_id = released_by.id if released_by else None
    db.session.commit()


def mark_seen_by_teacher(call: PickupCall):
    if call.seen_by_teacher_at is None:
        call.seen_by_teacher_at = datetime.now(timezone.utc)
        db.session.commit()


def mark_seen_by_student(call: PickupCall):
    if call.seen_by_student_at is None:
        call.seen_by_student_at = datetime.now(timezone.utc)
        db.session.commit()
