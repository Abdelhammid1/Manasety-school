"""REST API for teacher + parent mobile apps (T-10.2, T-10.3).

All endpoints under /api/ — JWT auth via Authorization: Bearer <token>.
Routes auto-scope to the authenticated user's school_id.
"""
import os
import uuid
from datetime import datetime, date
from decimal import Decimal

from flask import current_app, g, jsonify, request
from werkzeug.utils import secure_filename

from . import bp
from ...extensions import bcrypt, csrf, db
from ...models import (
    AcademicYear, Announcement, Assignment, AssessmentComponent, Attendance,
    Conversation, ConversationParticipant, Course, CourseAssignment,
    DeviceToken, Enrollment, GradeEntry, Invoice, Material, Message,
    NotificationLog, Payment, Quiz, QuizAttempt, ScheduleSlot, School,
    Section, Student, Subject, Submission, Teacher, Term, User, YearResult,
)
from ...models.results import RESULT_STATUSES
from ...services.auth_jwt import issue_token, jwt_required
from ...services.notifications import send_notification

# CSRF exempt entire API (uses JWT instead of session cookies)
csrf.exempt(bp)


def _err(msg, code=400):
    return jsonify({"error": msg}), code


def _user():
    return g.api_user


def _sid():
    return _user().school_id


def _active_year():
    return AcademicYear.query.filter_by(school_id=_sid(), status="active").first()


def _teacher_for(user):
    return Teacher.query.filter_by(school_id=user.school_id, user_id=user.id).first()


# ---------- Auth ----------

@bp.route("/auth/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return _err("الرجاء إدخال اسم المستخدم وكلمة المرور.")
    user = User.query.filter_by(username=username).first()
    if not user or not user.is_active or not user.check_password(password):
        return _err("اسم المستخدم أو كلمة المرور غير صحيحة.", 401)

    user.last_login_at = datetime.utcnow()
    db.session.commit()
    return jsonify({
        "token": issue_token(user),
        "user": _user_dict(user),
    })


@bp.route("/me", methods=["GET"])
@jwt_required
def me():
    return jsonify({"user": _user_dict(_user())})


# ---------- Self-service profile edits (Sprint 11) ----------

import re as _re
_USERNAME_RE = _re.compile(r"^[a-zA-Z0-9._-]{3,32}$")


@bp.route("/me/username", methods=["POST"])
@jwt_required
def change_username():
    """Self-service username rename.

    Body: {"current_password": str, "new_username": str}
    - Requires the current password (defense in depth — a stolen JWT can't
      silently take over a username).
    - Enforces uniqueness within the caller's school.
    - Enforces `^[a-zA-Z0-9._-]{3,32}$` — same shape as any other username.
    """
    data = request.get_json(silent=True) or {}
    current_password = data.get("current_password") or ""
    new_username = (data.get("new_username") or "").strip()

    if not current_password or not new_username:
        return _err("بيانات ناقصة", 400)
    if not _USERNAME_RE.match(new_username):
        return _err(
            "اسم المستخدم يجب أن يكون ٣-٣٢ حرفًا لاتينيًا أو رقمًا أو . _ -",
            400,
        )

    u = _user()
    if not u.check_password(current_password):
        return _err("كلمة المرور الحالية غير صحيحة", 400)

    if new_username == u.username:
        # No-op — return the current user; keeps the client's UX predictable.
        return jsonify({"user": _user_dict(u)})

    # Uniqueness — case-sensitive, scoped to the same school. Excludes self
    # (harmless since we no-op'd equal case above, but explicit).
    exists = User.query.filter(
        User.school_id == u.school_id,
        User.username == new_username,
        User.id != u.id,
    ).first()
    if exists:
        return _err("اسم المستخدم مأخوذ بالفعل", 409)

    u.username = new_username
    db.session.commit()
    return jsonify({"user": _user_dict(u)})


@bp.route("/me/full-name", methods=["POST"])
@jwt_required
def change_full_name():
    """Self-service display-name update. No password required — the full
    name is display-only and doesn't affect login."""
    data = request.get_json(silent=True) or {}
    new_full_name = (data.get("full_name") or "").strip()

    if not new_full_name:
        return _err("الاسم مطلوب", 400)
    if len(new_full_name) > 128:
        return _err("الاسم طويل جدًا (حد أقصى ١٢٨ حرف)", 400)

    u = _user()
    u.full_name = new_full_name
    db.session.commit()
    return jsonify({"user": _user_dict(u)})


def _user_dict(user: User) -> dict:
    teacher = Teacher.query.filter_by(user_id=user.id).first()
    children = Student.query.filter_by(parent_user_id=user.id).all()
    school = School.query.get(user.school_id) if user.school_id else None
    return {
        "id": user.id,
        "school_id": user.school_id,
        "school_name": school.name if school else None,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role.name if user.role else None,
        "role_ar": user.role.name_ar if user.role else None,
        "is_teacher": bool(teacher),
        "teacher_id": teacher.id if teacher else None,
        "children_count": len(children),
        "children_ids": [c.id for c in children],
    }


# ============================================================
# Teacher endpoints
# ============================================================

@bp.route("/teacher/schedule", methods=["GET"])
@jwt_required
def teacher_schedule():
    t = _teacher_for(_user())
    if not t:
        return _err("not a teacher", 403)
    year = _active_year()
    if not year:
        return jsonify({"slots": []})
    slots = ScheduleSlot.query.filter_by(
        school_id=_sid(), year_id=year.id, teacher_id=t.id,
    ).all()
    return jsonify({
        "slots": [
            {
                "day_id": s.day_id, "day_name": s.day.name,
                "period_id": s.period_id, "period_name": s.period.name,
                "start_time": s.period.start_time.strftime("%H:%M"),
                "end_time": s.period.end_time.strftime("%H:%M"),
                "section_id": s.section_id,
                "section_name": f"{s.section.grade.name} / {s.section.name}",
                "subject_id": s.subject_id,
                "subject_name": s.subject.name,
            } for s in slots
        ]
    })


@bp.route("/teacher/terms", methods=["GET"])
@jwt_required
def teacher_terms():
    """List terms in the active academic year."""
    year = _active_year()
    if not year:
        return jsonify({"terms": []})
    terms = (
        Term.query.filter_by(school_id=_sid(), year_id=year.id)
        .order_by(Term.order_index).all()
    )
    return jsonify({"terms": [
        {"id": t.id, "name": t.name, "year_id": t.year_id,
         "start_date": t.start_date.isoformat() if t.start_date else None,
         "end_date": t.end_date.isoformat() if t.end_date else None}
        for t in terms
    ]})


@bp.route("/teacher/section/<int:section_id>/schedule", methods=["GET"])
@jwt_required
def teacher_section_schedule(section_id):
    """Weekly schedule for a specific section (not filtered by teacher)."""
    t = _teacher_for(_user())
    if not t:
        return _err("not a teacher", 403)
    section = Section.query.filter_by(id=section_id, school_id=_sid()).first()
    if not section:
        return _err("section not found", 404)
    slots = (
        ScheduleSlot.query.filter_by(
            school_id=_sid(), year_id=section.year_id, section_id=section.id,
        )
        .order_by(ScheduleSlot.day_id, ScheduleSlot.period_id).all()
    )
    return jsonify({"slots": [
        {
            "day_id": s.day_id, "day_name": s.day.name,
            "period_id": s.period_id, "period_name": s.period.name,
            "start_time": s.period.start_time.strftime("%H:%M"),
            "end_time": s.period.end_time.strftime("%H:%M"),
            "subject_id": s.subject_id, "subject_name": s.subject.name,
            "teacher_id": s.teacher_id, "teacher_name": s.teacher.full_name,
        } for s in slots
    ]})


@bp.route("/teacher/sections", methods=["GET"])
@jwt_required
def teacher_sections():
    """[TCH] Assigned sections roll-up for the "فصولي" screen.

    Returns one row per (section × subject) assignment with the counts
    that the design surfaces: enrolled students, weekly periods, and the
    first schedule room seen for that pair. Also returns aggregates.
    """
    from ...models import Enrollment as _Enr
    t = _teacher_for(_user())
    if not t:
        return _err("not a teacher", 403)
    year = _active_year()
    if not year:
        return jsonify({"sections": [], "totals": {
            "assignments": 0, "students": 0, "periods": 0}})
    assignments = Assignment.query.filter_by(
        teacher_id=t.id, year_id=year.id, is_active=True
    ).all()
    rows = []
    section_ids = set()
    total_periods = 0
    for a in assignments:
        # Weekly slots for this exact (section × subject) pair.
        slots = ScheduleSlot.query.filter_by(
            teacher_id=t.id, year_id=year.id,
            section_id=a.section_id, subject_id=a.subject_id,
        ).all()
        weekly = len(slots)
        room = None
        for s in slots:
            if s.room and s.room.name:
                room = s.room.name
                break
        # Active enrollments in this section.
        student_count = _Enr.query.filter_by(
            section_id=a.section_id, year_id=year.id, status="active"
        ).count()
        rows.append({
            "id": a.id,
            "section_id": a.section.id,
            "subject_id": a.subject.id,
            "subject": a.subject.name,
            "grade": a.section.grade.name if a.section.grade else None,
            "class_name": a.section.name,
            "student_count": student_count,
            "weekly_periods": weekly,
            "room": room,
        })
        section_ids.add(a.section_id)
        total_periods += weekly
    total_students = _Enr.query.filter(
        _Enr.section_id.in_(section_ids or [-1]),
        _Enr.year_id == year.id,
        _Enr.status == "active",
    ).count() if section_ids else 0
    return jsonify({
        "sections": rows,
        "totals": {
            "assignments": len(rows),
            "students": total_students,
            "periods": total_periods,
        },
    })


@bp.route("/teacher/home", methods=["GET"])
@jwt_required
def teacher_home():
    """Roll-up for the [TCH] Home screen: greeting, stats, today's
    periods, pending grading, new messages."""
    from datetime import date
    from ...models import (
        Announcement, Course, CourseAssignment, CourseSection,
        Submission, Enrollment as _Enr,
    )
    t = _teacher_for(_user())
    if not t:
        return _err("not a teacher", 403)
    year = _active_year()

    # Sections this teacher owns via Assignment(teacher_id=t.id).
    section_rows = Assignment.query.filter_by(
        teacher_id=t.id,
        year_id=year.id if year else None,
        is_active=True,
    ).all() if year else []
    section_ids = list({a.section_id for a in section_rows})

    # Total students across all owned sections (active enrollments only).
    student_count = 0
    if section_ids and year:
        student_count = _Enr.query.filter(
            _Enr.section_id.in_(section_ids),
            _Enr.year_id == year.id,
            _Enr.status == "active",
        ).count()

    # Today's periods this teacher teaches — filter by weekday. The `days`
    # table stores order_index 1..5 = Sunday..Thursday (KSA week).
    # date.weekday(): Mon=0 .. Sun=6. So map Sun→1, Mon→2, …, Thu→5;
    # Fri/Sat → no periods.
    from datetime import date as _d
    _wd_to_index = {6: 1, 0: 2, 1: 3, 2: 4, 3: 5}
    today_order = _wd_to_index.get(_d.today().weekday())
    today_periods = []
    if year and today_order is not None:
        slots = (ScheduleSlot.query
                 .join(ScheduleSlot.day)
                 .filter(ScheduleSlot.teacher_id == t.id,
                         ScheduleSlot.year_id == year.id)
                 .all())
        for s in slots:
            if not s.day or s.day.order_index != today_order:
                continue
            today_periods.append({
                "id": s.id,
                "day": s.day.name if s.day else None,
                "day_order": s.day.order_index if s.day else 0,
                "period_order": s.period.order_index if s.period else 0,
                "period_name": s.period.name if s.period else None,
                "start": s.period.start_time.strftime("%H:%M") if s.period and s.period.start_time else None,
                "end":   s.period.end_time.strftime("%H:%M")   if s.period and s.period.end_time else None,
                "subject": s.subject.name if s.subject else None,
                "section": f"{s.section.grade.name}/{s.section.name}" if s.section and s.section.grade else None,
                "room": s.room.name if s.room else None,
            })
        today_periods.sort(key=lambda p: (p["period_order"], p["id"]))

    # Pending-grading rollup: assignments that belong to my courses with
    # submissions I haven't scored yet.
    pending = []
    if section_ids:
        # Every course published to any of my sections.
        my_course_ids = list({
            cs.course_id for cs in CourseSection.query.filter(
                CourseSection.section_id.in_(section_ids),
            ).all()
        })
        if my_course_ids:
            cas = (
                CourseAssignment.query.filter(
                    CourseAssignment.course_id.in_(my_course_ids),
                    CourseAssignment.is_published.is_(True),
                ).all()
            )
            for c in cas:
                ungraded = Submission.query.filter_by(
                    assignment_id=c.id,
                ).filter(Submission.score.is_(None)).count()
                if ungraded > 0:
                    pending.append({
                        "id": c.id,
                        "title": c.title,
                        "subject": c.course.subject.name
                            if c.course and getattr(c.course, "subject", None) else None,
                        "ungraded_count": ungraded,
                    })
            pending.sort(key=lambda p: -p["ungraded_count"])
            pending = pending[:5]

    # Recent parent announcements OR messages (placeholder — messages
    # feature lands next).
    recent_messages = []
    for a in Announcement.query.filter_by(
        school_id=_sid(),
    ).order_by(Announcement.created_at.desc()).limit(2).all():
        author_name = None
        if a.author_id:
            u = User.query.get(a.author_id)
            author_name = u.full_name if u else None
        recent_messages.append({
            "id": a.id,
            "from": author_name or "إدارة المدرسة",
            "subject": a.title,
            "preview": (a.body or "")[:80],
            "created_at": a.created_at.isoformat() if a.created_at else None,
        })

    return jsonify({
        "teacher": {
            "id": t.id, "full_name": t.full_name,
            "specialization": t.specialization,
        },
        "stats": {
            "today_period_count": len(today_periods),
            "pending_grading": sum(p["ungraded_count"] for p in pending),
            "student_count": student_count,
            "section_count": len(section_ids),
        },
        "today_periods": today_periods,
        "pending_grading": pending,
        "recent_messages": recent_messages,
    })


@bp.route("/teacher/students", methods=["GET"])
@jwt_required
def teacher_students():
    section_id = request.args.get("section_id", type=int)
    if not section_id:
        return _err("section_id required")
    section = Section.query.filter_by(id=section_id, school_id=_sid()).first()
    if not section:
        return _err("section not found", 404)
    enrollments = (
        Enrollment.query.filter_by(
            school_id=_sid(), year_id=section.year_id, section_id=section.id, status="active"
        ).join(Student).order_by(Student.full_name).all()
    )
    return jsonify({"students": [
        {
            "enrollment_id": e.id,
            "student_id": e.student.id,
            "permanent_code": e.student.permanent_code,
            "full_name": e.student.full_name,
        } for e in enrollments
    ]})


@bp.route("/teacher/attendance", methods=["POST"])
@jwt_required
def teacher_attendance():
    """Body: {section_id, date, records: [{enrollment_id, status, notes?}]}"""
    t = _teacher_for(_user())
    if not t:
        return _err("not a teacher", 403)
    data = request.get_json(silent=True) or {}
    section_id = data.get("section_id")
    on_date = _parse_date(data.get("date")) or date.today()
    records = data.get("records") or []
    if not section_id or not records:
        return _err("missing section_id or records")

    section = Section.query.filter_by(id=section_id, school_id=_sid()).first()
    if not section:
        return _err("section not found", 404)

    # Ensure teacher is assigned to this section
    if not Assignment.query.filter_by(
        teacher_id=t.id, section_id=section.id, year_id=section.year_id, is_active=True
    ).first():
        return _err("teacher not assigned to this section", 403)

    creates = updates = absent_notifs = 0
    valid_ids = {e.id for e in Enrollment.query.filter_by(
        school_id=_sid(), year_id=section.year_id, section_id=section.id, status="active"
    ).all()}

    for r in records:
        eid = r.get("enrollment_id")
        status = r.get("status")
        if eid not in valid_ids or status not in ("present", "absent", "late"):
            continue
        existing = Attendance.query.filter_by(enrollment_id=eid, date=on_date).first()
        prev = existing.status if existing else None
        if existing:
            existing.status = status
            existing.notes = r.get("notes")
            existing.recorded_by_user_id = _user().id
            existing.recorded_at = datetime.utcnow()
            updates += 1
        else:
            existing = Attendance(
                school_id=_sid(), enrollment_id=eid, date=on_date,
                status=status, notes=r.get("notes"),
                recorded_by_user_id=_user().id,
            )
            db.session.add(existing)
            creates += 1
        db.session.flush()
        if status == "absent" and prev != "absent":
            e = Enrollment.query.get(eid)
            phone = (e.student.parent_phone or "").strip()
            if phone:
                send_notification(
                    school_id=_sid(), kind="absence",
                    payload={
                        "student": e.student.full_name,
                        "date": on_date.isoformat(),
                        "message": f"غياب: {e.student.full_name} بتاريخ {on_date.isoformat()}",
                    },
                    target_phone=phone,
                    student_id=e.student_id,  # Sprint 11: parent-scoping FK
                    related_kind="attendance", related_id=existing.id,
                )
                absent_notifs += 1
    db.session.commit()
    return jsonify({
        "creates": creates, "updates": updates, "absent_notifications": absent_notifs,
    })


@bp.route("/teacher/grades", methods=["POST"])
@jwt_required
def teacher_grades():
    """Body: {section_id, term_id, subject_id, entries: [{enrollment_id, component_id, score}]}"""
    t = _teacher_for(_user())
    if not t:
        return _err("not a teacher", 403)
    data = request.get_json(silent=True) or {}
    section_id = data.get("section_id")
    term_id = data.get("term_id")
    subject_id = data.get("subject_id")
    entries = data.get("entries") or []
    if not (section_id and term_id and subject_id and entries):
        return _err("missing fields")

    section = Section.query.filter_by(id=section_id, school_id=_sid()).first()
    if not section:
        return _err("section not found", 404)
    if not Assignment.query.filter_by(
        teacher_id=t.id, section_id=section.id, subject_id=subject_id,
        year_id=section.year_id, is_active=True
    ).first():
        return _err("teacher not assigned to this subject in this section", 403)

    if YearResult.query.join(Enrollment).filter(
        Enrollment.section_id == section.id, Enrollment.year_id == section.year_id
    ).first():
        return _err("results approved; grades locked", 403)

    saved = rejected = 0
    valid_eids = {e.id for e in Enrollment.query.filter_by(
        school_id=_sid(), year_id=section.year_id, section_id=section.id, status="active"
    ).all()}
    comps = {c.id: c for c in AssessmentComponent.query.filter_by(
        school_id=_sid(), term_id=term_id, subject_id=subject_id
    ).all()}

    for e in entries:
        eid = e.get("enrollment_id")
        cid = e.get("component_id")
        raw = e.get("score")
        if eid not in valid_eids or cid not in comps:
            rejected += 1; continue
        try:
            score = Decimal(str(raw))
        except Exception:  # noqa: BLE001
            rejected += 1; continue
        if score < 0 or score > comps[cid].max_score:
            rejected += 1; continue
        ge = GradeEntry.query.filter_by(enrollment_id=eid, component_id=cid).first()
        if ge:
            ge.score = score
            ge.recorded_by_user_id = _user().id
            ge.recorded_at = datetime.utcnow()
        else:
            ge = GradeEntry(
                school_id=_sid(), enrollment_id=eid, component_id=cid,
                score=score, recorded_by_user_id=_user().id,
            )
            db.session.add(ge)
        saved += 1
    db.session.commit()
    return jsonify({"saved": saved, "rejected": rejected})


@bp.route("/teacher/materials", methods=["GET", "POST"])
@jwt_required
def teacher_materials():
    t = _teacher_for(_user())
    if not t:
        return _err("not a teacher", 403)

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        section_id = data.get("section_id")
        subject_id = data.get("subject_id")
        title = (data.get("title") or "").strip()
        kind = data.get("kind") or "link"
        url = (data.get("external_url") or "").strip() or None
        desc = (data.get("description") or "").strip() or None
        if not (section_id and subject_id and title):
            return _err("missing fields")
        section = Section.query.filter_by(id=section_id, school_id=_sid()).first()
        if not section:
            return _err("section not found", 404)
        if kind not in ("file", "video", "link"):
            return _err("invalid kind")
        m = Material(
            school_id=_sid(), teacher_id=t.id, year_id=section.year_id,
            section_id=section.id, subject_id=subject_id, title=title,
            description=desc, kind=kind, external_url=url,
        )
        db.session.add(m)
        db.session.commit()
        return jsonify({"id": m.id, "title": m.title}), 201

    materials = Material.query.filter_by(school_id=_sid(), teacher_id=t.id).order_by(Material.created_at.desc()).all()
    return jsonify({"materials": [_material_dict(m) for m in materials]})


# ---------- Sprint 10 Phase 2: teacher-write pre-fill + upload + password ----------

@bp.route("/teacher/components", methods=["GET"])
@jwt_required
def teacher_components():
    """List active assessment components for a (subject, term)."""
    t = _teacher_for(_user())
    if not t:
        return _err("not a teacher", 403)
    subject_id = request.args.get("subject_id", type=int)
    term_id = request.args.get("term_id", type=int)
    if not (subject_id and term_id):
        return _err("subject_id and term_id required")
    comps = AssessmentComponent.query.filter_by(
        school_id=_sid(), subject_id=subject_id, term_id=term_id,
    ).order_by(AssessmentComponent.id).all()
    return jsonify({"components": [
        {"id": c.id, "name": c.name, "max_score": float(c.max_score)}
        for c in comps
    ]})


@bp.route("/teacher/grades", methods=["GET"])
@jwt_required
def teacher_grades_existing():
    """Fetch existing grades for (section, subject, term, component) for edit-mode pre-fill."""
    t = _teacher_for(_user())
    if not t:
        return _err("not a teacher", 403)
    section_id = request.args.get("section_id", type=int)
    subject_id = request.args.get("subject_id", type=int)
    term_id = request.args.get("term_id", type=int)
    component_id = request.args.get("component_id", type=int)
    if not all([section_id, subject_id, term_id, component_id]):
        return _err("missing query params")
    section = Section.query.filter_by(id=section_id, school_id=_sid()).first()
    if not section:
        return _err("section not found", 404)
    # Reuse the same scope check the POST already applies
    if not Assignment.query.filter_by(
        teacher_id=t.id, section_id=section.id, subject_id=subject_id,
        year_id=section.year_id, is_active=True,
    ).first():
        return _err("teacher not assigned to this subject in this section", 403)
    eids = [
        e.id for e in Enrollment.query.filter_by(
            school_id=_sid(), year_id=section.year_id,
            section_id=section.id, status="active",
        ).all()
    ]
    rows = GradeEntry.query.filter(
        GradeEntry.enrollment_id.in_(eids),
        GradeEntry.component_id == component_id,
    ).all()
    return jsonify({"entries": [
        {"enrollment_id": r.enrollment_id, "score": float(r.score)}
        for r in rows
    ]})


@bp.route("/teacher/attendance", methods=["GET"])
@jwt_required
def teacher_attendance_existing():
    """Fetch existing attendance for a (section, date) so the form pre-fills."""
    t = _teacher_for(_user())
    if not t:
        return _err("not a teacher", 403)
    section_id = request.args.get("section_id", type=int)
    if not section_id:
        return _err("section_id required")
    on_date = _parse_date(request.args.get("date")) or date.today()
    section = Section.query.filter_by(id=section_id, school_id=_sid()).first()
    if not section:
        return _err("section not found", 404)
    if not Assignment.query.filter_by(
        teacher_id=t.id, section_id=section.id,
        year_id=section.year_id, is_active=True,
    ).first():
        return _err("teacher not assigned to this section", 403)
    eids = [
        e.id for e in Enrollment.query.filter_by(
            school_id=_sid(), year_id=section.year_id,
            section_id=section.id, status="active",
        ).all()
    ]
    rows = Attendance.query.filter(
        Attendance.enrollment_id.in_(eids),
        Attendance.date == on_date,
    ).all()
    return jsonify({
        "date": on_date.isoformat(),
        "records": [
            {"enrollment_id": r.enrollment_id, "status": r.status, "notes": r.notes}
            for r in rows
        ],
    })


ALLOWED_UPLOAD_EXTS = {".pdf", ".jpg", ".jpeg", ".png"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


@bp.route("/teacher/upload", methods=["POST"])
@jwt_required
def teacher_upload():
    """Multipart upload: file + section_id + subject_id + title + optional description."""
    t = _teacher_for(_user())
    if not t:
        return _err("not a teacher", 403)
    file = request.files.get("file")
    section_id = request.form.get("section_id", type=int)
    subject_id = request.form.get("subject_id", type=int)
    title = (request.form.get("title") or "").strip()
    description = (request.form.get("description") or "").strip() or None
    if not (file and section_id and subject_id and title):
        return _err("missing file or fields")
    section = Section.query.filter_by(id=section_id, school_id=_sid()).first()
    if not section:
        return _err("section not found", 404)
    # Same Assignment scope check
    if not Assignment.query.filter_by(
        teacher_id=t.id, section_id=section.id, subject_id=subject_id,
        year_id=section.year_id, is_active=True,
    ).first():
        return _err("teacher not assigned to this subject in this section", 403)

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_UPLOAD_EXTS:
        return _err(f"unsupported file type ({ext})")
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    if size > MAX_UPLOAD_BYTES:
        return _err("file too large (max 10MB)", 413)

    upload_dir = os.path.join(
        current_app.root_path, "static", "uploads", "materials", str(_sid()),
    )
    os.makedirs(upload_dir, exist_ok=True)
    fname = f"{uuid.uuid4().hex}{ext}"
    fpath = os.path.join(upload_dir, fname)
    file.save(fpath)
    rel_path = f"/static/uploads/materials/{_sid()}/{fname}"

    m = Material(
        school_id=_sid(), teacher_id=t.id, year_id=section.year_id,
        section_id=section.id, subject_id=subject_id, title=title,
        description=description, kind="file", file_path=rel_path,
    )
    db.session.add(m)
    db.session.commit()
    return jsonify({
        "id": m.id, "title": m.title, "file_path": rel_path,
        "kind": "file", "section_name": f"{section.grade.name} / {section.name}",
    }), 201


@bp.route("/auth/change-password", methods=["POST"])
@jwt_required
def change_password():
    data = request.get_json(silent=True) or {}
    old_pw = data.get("old_password") or ""
    new_pw = data.get("new_password") or ""
    if len(new_pw) < 8:
        return _err("password must be at least 8 characters")
    u = _user()
    if not u.check_password(old_pw):
        return _err("current password incorrect", 401)
    u.set_password(new_pw)
    db.session.commit()
    return jsonify({"ok": True})


# ---------- Sprint 10 Phase 3: FCM device tokens + notification read ----------

@bp.route("/auth/device-token", methods=["POST"])
@jwt_required
def register_device_token():
    """Register/upsert an FCM device token for the current user's app install."""
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    platform = data.get("platform")
    app_name = data.get("app")
    if not token or platform not in ("ios", "android") or app_name not in ("teacher", "parent"):
        return _err("invalid payload: need token, platform=ios|android, app=teacher|parent")
    existing = DeviceToken.query.filter_by(token=token).first()
    if existing:
        # Re-associate to the current user (e.g. logged out and back in on same device)
        existing.user_id = _user().id
        existing.app = app_name
        existing.platform = platform
        existing.last_seen_at = datetime.utcnow()
    else:
        db.session.add(DeviceToken(
            school_id=_sid(),
            user_id=_user().id,
            platform=platform,
            token=token,
            app=app_name,
        ))
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/auth/device-token", methods=["DELETE"])
@jwt_required
def unregister_device_token():
    """Called on logout — removes the token so this device stops receiving pushes."""
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    if token:
        DeviceToken.query.filter_by(token=token, user_id=_user().id).delete()
        db.session.commit()
    return jsonify({"ok": True})


@bp.route("/notifications/<int:notif_id>/read", methods=["POST"])
@jwt_required
def mark_notification_read(notif_id):
    """Mark a parent notification as read (from a push tap or tab visit)."""
    n = NotificationLog.query.filter_by(id=notif_id, school_id=_sid()).first()
    if not n:
        return _err("not found", 404)
    n.read_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"ok": True, "read_at": n.read_at.isoformat()})


def _material_dict(m):
    return {
        "id": m.id, "title": m.title, "description": m.description,
        "kind": m.kind, "external_url": m.external_url, "file_path": m.file_path,
        "section_name": f"{m.section.grade.name} / {m.section.name}",
        "subject_name": m.subject.name,
        "created_at": m.created_at.isoformat(),
    }


# ============================================================
# Sprint 12 — LMS teacher endpoints for the mobile app
#
# These back the four detail flows the Stitch designs asked for:
# assignments, quizzes, announcements, parent messages. All are
# scoped to the calling teacher (teacher.Assignment on the section
# for LMS content, ConversationParticipant for messages) so nothing
# leaks between staff.
# ============================================================

def _teacher_courses(t, year):
    """Every LMS Course the teacher can act on = a Course whose
    (year, grade, subject) matches a live teacher.Assignment row."""
    from ...models import Course
    if not year: return []
    my_pairs = {
        (a.section.grade_id, a.subject_id) for a in Assignment.query.filter_by(
            teacher_id=t.id, year_id=year.id, is_active=True
        ).all() if a.section and a.subject_id
    }
    if not my_pairs: return []
    grade_ids = {g for g, _ in my_pairs}
    subject_ids = {s for _, s in my_pairs}
    courses = Course.query.filter(
        Course.school_id == _sid(),
        Course.academic_year_id == year.id,
        Course.grade_id.in_(grade_ids),
        Course.subject_id.in_(subject_ids),
    ).all()
    return [c for c in courses if (c.grade_id, c.subject_id) in my_pairs]


# ---------- Assignments ----------

def _assignment_dict(ca, *, with_counts=True):
    d = {
        "id": ca.id,
        "title": ca.title,
        "instructions": ca.instructions or "",
        "max_score": float(ca.max_score or 0),
        "due_at": ca.due_at.isoformat() if ca.due_at else None,
        "is_published": bool(ca.is_published),
        "allow_late": bool(ca.allow_late),
        "created_at": ca.created_at.isoformat() if ca.created_at else None,
        "course_title": ca.course.title if ca.course else None,
        "subject": ca.course.subject.name if ca.course and getattr(ca.course, "subject", None) else None,
        "grade":   ca.course.grade.name   if ca.course and ca.course.grade else None,
    }
    if with_counts:
        d["submission_count"] = Submission.query.filter_by(assignment_id=ca.id).count()
        d["ungraded_count"]   = Submission.query.filter_by(assignment_id=ca.id).filter(
            Submission.score.is_(None)).count()
    return d


@bp.route("/teacher/assignments", methods=["GET", "POST"])
@jwt_required
def teacher_assignments():
    from ...models import CourseAssignment
    t = _teacher_for(_user())
    if not t:
        return _err("not a teacher", 403)
    year = _active_year()
    course_ids = [c.id for c in _teacher_courses(t, year)]

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        course_id = data.get("course_id")
        title = (data.get("title") or "").strip()
        if course_id not in course_ids or not title:
            return _err("course_id (own course) and title are required")
        try:
            max_score = float(data.get("max_score") or 100)
        except (TypeError, ValueError):
            max_score = 100.0
        due_at = _parse_dt(data.get("due_at"))
        ca = CourseAssignment(
            course_id=course_id, title=title,
            instructions=(data.get("instructions") or "").strip(),
            max_score=max_score, due_at=due_at,
            is_published=bool(data.get("is_published", True)),
            allow_late=bool(data.get("allow_late", True)),
        )
        db.session.add(ca)
        db.session.commit()
        return jsonify({"assignment": _assignment_dict(ca)}), 201

    if not course_ids:
        return jsonify({"assignments": []})
    rows = CourseAssignment.query.filter(
        CourseAssignment.course_id.in_(course_ids),
    ).order_by(CourseAssignment.created_at.desc()).all()
    return jsonify({"assignments": [_assignment_dict(r) for r in rows]})


@bp.route("/teacher/assignments/<int:aid>", methods=["GET", "DELETE"])
@jwt_required
def teacher_assignment_detail(aid):
    from ...models import CourseAssignment
    t = _teacher_for(_user())
    if not t:
        return _err("not a teacher", 403)
    ca = CourseAssignment.query.get(aid)
    if not ca:
        return _err("not found", 404)
    my_courses = {c.id for c in _teacher_courses(t, _active_year())}
    if ca.course_id not in my_courses:
        return _err("forbidden", 403)
    if request.method == "DELETE":
        db.session.delete(ca)
        db.session.commit()
        return jsonify({"ok": True})
    return jsonify({"assignment": _assignment_dict(ca)})


@bp.route("/teacher/assignments/<int:aid>/submissions", methods=["GET"])
@jwt_required
def teacher_assignment_submissions(aid):
    from ...models import CourseAssignment
    t = _teacher_for(_user())
    if not t:
        return _err("not a teacher", 403)
    ca = CourseAssignment.query.get(aid)
    if not ca:
        return _err("not found", 404)
    my_courses = {c.id for c in _teacher_courses(t, _active_year())}
    if ca.course_id not in my_courses:
        return _err("forbidden", 403)
    subs = Submission.query.filter_by(assignment_id=aid).all()
    out = []
    for s in subs:
        stu = Student.query.get(s.student_id)
        out.append({
            "student_id": s.student_id,
            "student_name": stu.full_name if stu else None,
            "permanent_code": stu.permanent_code if stu else None,
            "submitted_at": s.submitted_at.isoformat() if s.submitted_at else None,
            "score": float(s.score) if s.score is not None else None,
            "max_score": float(ca.max_score or 0),
            "feedback": s.feedback or "",
            "has_body": bool(s.body),
            "has_file": bool(s.file_url),
            "is_graded": s.score is not None,
        })
    return jsonify({"submissions": out})


@bp.route("/teacher/assignments/<int:aid>/submissions/<int:sid>/grade",
          methods=["POST"])
@jwt_required
def teacher_assignment_grade(aid, sid):
    from ...models import CourseAssignment
    t = _teacher_for(_user())
    if not t:
        return _err("not a teacher", 403)
    ca = CourseAssignment.query.get(aid)
    if not ca:
        return _err("not found", 404)
    my_courses = {c.id for c in _teacher_courses(t, _active_year())}
    if ca.course_id not in my_courses:
        return _err("forbidden", 403)
    data = request.get_json(silent=True) or {}
    try:
        score = float(data.get("score"))
    except (TypeError, ValueError):
        return _err("score must be numeric")
    if score < 0 or (ca.max_score and score > float(ca.max_score)):
        return _err(f"score must be between 0 and {ca.max_score}")
    sub = Submission.query.filter_by(assignment_id=aid, student_id=sid).first()
    if not sub:
        return _err("submission not found", 404)
    sub.score = score
    sub.feedback = data.get("feedback") or sub.feedback
    sub.graded_by_id = _user().id
    sub.graded_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"ok": True, "score": float(sub.score)})


# ---------- Quizzes ----------

def _quiz_dict(q, *, with_counts=True):
    d = {
        "id": q.id, "title": q.title,
        "description": getattr(q, "description", "") or "",
        "is_published": bool(getattr(q, "is_published", False)),
        "opens_at":  q.opens_at.isoformat()  if getattr(q, "opens_at", None) else None,
        "closes_at": q.closes_at.isoformat() if getattr(q, "closes_at", None) else None,
        "duration_minutes": getattr(q, "duration_minutes", None),
        "max_attempts": getattr(q, "max_attempts", 1),
        "course_title": q.course.title if q.course else None,
        "subject": q.course.subject.name if q.course and getattr(q.course, "subject", None) else None,
        "grade":   q.course.grade.name   if q.course and q.course.grade else None,
    }
    if with_counts:
        d["question_count"] = len(q.questions) if hasattr(q, "questions") else 0
        d["attempt_count"] = QuizAttempt.query.filter_by(quiz_id=q.id).count() \
            if 'QuizAttempt' in globals() else 0
    return d


@bp.route("/teacher/quizzes", methods=["GET", "POST"])
@jwt_required
def teacher_quizzes():
    from ...models import Quiz
    t = _teacher_for(_user())
    if not t:
        return _err("not a teacher", 403)
    year = _active_year()
    course_ids = [c.id for c in _teacher_courses(t, year)]

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        course_id = data.get("course_id")
        title = (data.get("title") or "").strip()
        if course_id not in course_ids or not title:
            return _err("course_id (own course) and title are required")
        try:
            duration = int(data.get("duration_minutes") or 30)
        except (TypeError, ValueError):
            duration = 30
        opens = _parse_dt(data.get("opens_at"))
        closes = _parse_dt(data.get("closes_at"))
        q = Quiz(
            course_id=course_id, title=title,
            description=(data.get("description") or "").strip(),
            is_published=bool(data.get("is_published", True)),
            opens_at=opens, closes_at=closes,
            duration_minutes=duration,
        )
        db.session.add(q)
        db.session.commit()
        return jsonify({"quiz": _quiz_dict(q)}), 201

    if not course_ids:
        return jsonify({"quizzes": []})
    rows = Quiz.query.filter(Quiz.course_id.in_(course_ids)).order_by(
        Quiz.created_at.desc() if hasattr(Quiz, "created_at") else Quiz.id.desc()
    ).all()
    return jsonify({"quizzes": [_quiz_dict(q) for q in rows]})


@bp.route("/teacher/quizzes/<int:qid>/stats", methods=["GET"])
@jwt_required
def teacher_quiz_stats(qid):
    from ...models import Quiz, QuizAttempt as _QA
    t = _teacher_for(_user())
    if not t:
        return _err("not a teacher", 403)
    q = Quiz.query.get(qid)
    if not q:
        return _err("not found", 404)
    my_courses = {c.id for c in _teacher_courses(t, _active_year())}
    if q.course_id not in my_courses:
        return _err("forbidden", 403)
    attempts = _QA.query.filter_by(quiz_id=qid).all()
    if not attempts:
        return jsonify({"quiz": _quiz_dict(q, with_counts=False),
                        "attempts": 0, "average": 0, "highest": 0, "lowest": 0,
                        "students": []})
    scored = [a for a in attempts if getattr(a, "score", None) is not None]
    scores = [float(a.score) for a in scored]
    students = []
    for a in attempts:
        stu = Student.query.get(a.student_id) if a.student_id else None
        students.append({
            "student_id": a.student_id,
            "student_name": stu.full_name if stu else None,
            "started_at":   a.started_at.isoformat()   if getattr(a, "started_at", None) else None,
            "submitted_at": a.submitted_at.isoformat() if getattr(a, "submitted_at", None) else None,
            "score": float(a.score) if getattr(a, "score", None) is not None else None,
        })
    return jsonify({
        "quiz": _quiz_dict(q, with_counts=False),
        "attempts": len(attempts),
        "average": sum(scores) / len(scores) if scores else 0,
        "highest": max(scores) if scores else 0,
        "lowest":  min(scores) if scores else 0,
        "students": students,
    })


# ---------- Announcements ----------

def _announcement_dict(a):
    author = User.query.get(a.author_id) if a.author_id else None
    section = None
    if a.section_id:
        sec = Section.query.get(a.section_id)
        if sec and sec.grade:
            section = f"{sec.grade.name}/{sec.name}"
    return {
        "id": a.id,
        "title": a.title,
        "body": a.body or "",
        "is_pinned": bool(a.is_pinned),
        "section_id": a.section_id,
        "section_name": section,
        "author_name": author.full_name if author else None,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


@bp.route("/teacher/announcements", methods=["GET", "POST"])
@jwt_required
def teacher_announcements():
    from ...models import Announcement
    t = _teacher_for(_user())
    if not t:
        return _err("not a teacher", 403)
    year = _active_year()
    my_section_ids = list({
        a.section_id for a in Assignment.query.filter_by(
            teacher_id=t.id, year_id=year.id if year else None, is_active=True,
        ).all()
    }) if year else []

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        title = (data.get("title") or "").strip()
        if not title:
            return _err("title is required")
        section_id = data.get("section_id")
        if section_id is not None and section_id not in my_section_ids:
            return _err("you are not assigned to this section", 403)
        a = Announcement(
            school_id=_sid(),
            section_id=section_id,
            author_id=_user().id,
            title=title,
            body=(data.get("body") or "").strip(),
            is_pinned=bool(data.get("is_pinned", False)),
        )
        db.session.add(a)
        db.session.commit()
        return jsonify({"announcement": _announcement_dict(a)}), 201

    q = Announcement.query.filter_by(school_id=_sid())
    # A teacher only sees THEIR OWN announcements + school-wide ones.
    from sqlalchemy import or_ as _or
    q = q.filter(_or(
        Announcement.author_id == _user().id,
        Announcement.section_id.is_(None),
        Announcement.section_id.in_(my_section_ids or [-1]),
    ))
    q = q.order_by(Announcement.is_pinned.desc(), Announcement.created_at.desc())
    return jsonify({"announcements": [_announcement_dict(a) for a in q.all()]})


@bp.route("/teacher/announcements/<int:aid>", methods=["DELETE"])
@jwt_required
def teacher_announcement_delete(aid):
    from ...models import Announcement
    t = _teacher_for(_user())
    if not t:
        return _err("not a teacher", 403)
    a = Announcement.query.filter_by(id=aid, school_id=_sid()).first()
    if not a:
        return _err("not found", 404)
    # Only the author can delete.
    if a.author_id != _user().id:
        return _err("forbidden", 403)
    db.session.delete(a)
    db.session.commit()
    return jsonify({"ok": True})


# ---------- Messages ----------

def _conversation_dict(c, uid):
    from ...models import ConversationParticipant, Message as _Msg
    last = _Msg.query.filter_by(conversation_id=c.id).order_by(
        _Msg.created_at.desc()).first()
    me = ConversationParticipant.query.filter_by(
        conversation_id=c.id, user_id=uid).first()
    unread = 0
    if me:
        q = _Msg.query.filter_by(conversation_id=c.id).filter(
            _Msg.sender_user_id != uid)
        if me.last_read_at is not None:
            q = q.filter(_Msg.created_at > me.last_read_at)
        unread = q.count()
    others = [p for p in c.participants if p.user_id != uid]
    other_user = User.query.get(others[0].user_id) if others else None
    return {
        "id": c.id,
        "subject": c.subject or "",
        "context_type": c.context_type,
        "context_id": c.context_id,
        "status": c.status,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "last_message_at": c.last_message_at.isoformat() if c.last_message_at else None,
        "other_name": other_user.full_name if other_user else None,
        "other_role": (
            "ولي أمر" if others and other_user and other_user.role and
            other_user.role.name == "parent" else
            "معلم" if others and other_user and other_user.role and
            other_user.role.name == "teacher" else
            None
        ),
        "last_preview": (last.body[:120] if last else "") if last else "",
        "unread_count": unread,
    }


@bp.route("/teacher/messages", methods=["GET", "POST"])
@jwt_required
def teacher_messages():
    from ...models import ConversationParticipant, Conversation, Message as _Msg
    t = _teacher_for(_user())
    if not t:
        return _err("not a teacher", 403)
    uid = _user().id

    if request.method == "POST":
        # Start a new conversation with a specific user (usually a parent).
        data = request.get_json(silent=True) or {}
        recipient_user_id = data.get("recipient_user_id")
        subject = (data.get("subject") or "").strip() or None
        body = (data.get("body") or "").strip()
        if not recipient_user_id or not body:
            return _err("recipient_user_id and body are required")
        c = Conversation(
            school_id=_sid(), subject=subject,
            context_type=data.get("context_type") or "general",
            context_id=data.get("context_id"),
            status="open", created_by_user_id=uid,
            last_message_at=datetime.utcnow(),
        )
        db.session.add(c)
        db.session.flush()
        db.session.add(ConversationParticipant(
            conversation_id=c.id, user_id=uid, role="initiator"))
        db.session.add(ConversationParticipant(
            conversation_id=c.id, user_id=recipient_user_id, role="recipient"))
        db.session.add(_Msg(
            conversation_id=c.id, sender_user_id=uid, body=body))
        db.session.commit()
        return jsonify({"conversation": _conversation_dict(c, uid)}), 201

    parts = ConversationParticipant.query.filter_by(user_id=uid).all()
    conv_ids = [p.conversation_id for p in parts]
    convs = Conversation.query.filter(
        Conversation.id.in_(conv_ids or [-1]),
        Conversation.school_id == _sid(),
    ).order_by(Conversation.last_message_at.desc().nullslast()).all() \
      if conv_ids else []
    return jsonify({
        "conversations": [_conversation_dict(c, uid) for c in convs],
    })


@bp.route("/teacher/messages/<int:conv_id>", methods=["GET", "POST"])
@jwt_required
def teacher_message_thread(conv_id):
    from ...models import ConversationParticipant, Conversation, Message as _Msg
    t = _teacher_for(_user())
    if not t:
        return _err("not a teacher", 403)
    uid = _user().id
    me = ConversationParticipant.query.filter_by(
        conversation_id=conv_id, user_id=uid).first()
    if not me:
        return _err("forbidden", 403)
    conv = Conversation.query.get(conv_id)
    if not conv or conv.school_id != _sid():
        return _err("not found", 404)

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        body = (data.get("body") or "").strip()
        if not body:
            return _err("body is required")
        m = _Msg(conversation_id=conv_id, sender_user_id=uid, body=body)
        db.session.add(m)
        conv.last_message_at = datetime.utcnow()
        db.session.commit()
        return jsonify({"message": {
            "id": m.id, "body": m.body,
            "sender_user_id": uid,
            "sender_name": _user().full_name,
            "is_mine": True,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }}), 201

    # GET: mark thread as read + return messages.
    me.last_read_at = datetime.utcnow()
    msgs = _Msg.query.filter_by(conversation_id=conv_id).order_by(
        _Msg.created_at.asc()).all()
    db.session.commit()
    return jsonify({
        "conversation": _conversation_dict(conv, uid),
        "messages": [{
            "id": m.id, "body": m.body,
            "sender_user_id": m.sender_user_id,
            "sender_name": User.query.get(m.sender_user_id).full_name
                if m.sender_user_id else None,
            "is_mine": m.sender_user_id == uid,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        } for m in msgs],
    })


# ============================================================
# Parent endpoints
# ============================================================

@bp.route("/parent/children", methods=["GET"])
@jwt_required
def parent_children():
    # Sprint 11 — belt-and-braces: the .parent_user_id filter already excludes
    # unrelated students, but the explicit isnot(None) makes the intent
    # unmistakable to code review and guards against any future refactor
    # that might accidentally pass through students with a NULL FK.
    uid = _user().id
    children = (
        Student.query
        .filter(Student.school_id == _sid())
        .filter(Student.parent_user_id.isnot(None))
        .filter(Student.parent_user_id == uid)
        .all()
    )
    current_app.logger.info(
        "parent_children(school=%s, user=%s) -> %d rows",
        _sid(), uid, len(children),
    )
    out = []
    year = _active_year()
    for s in children:
        enr = None
        if year:
            enr = next((e for e in s.enrollments if e.year_id == year.id and e.status == "active"), None)
        out.append({
            "id": s.id, "permanent_code": s.permanent_code, "full_name": s.full_name,
            "current_section": (
                f"{enr.grade.name} / {enr.section.name}" if enr else None
            ),
            "current_year": year.name if year else None,
        })
    return jsonify({"children": out})


def _check_child(student_id):
    s = Student.query.filter_by(id=student_id, school_id=_sid(), parent_user_id=_user().id).first()
    return s


@bp.route("/parent/child/<int:student_id>/attendance", methods=["GET"])
@jwt_required
def parent_child_attendance(student_id):
    s = _check_child(student_id)
    if not s:
        return _err("child not found", 404)
    eids = [e.id for e in s.enrollments if e.status == "active"]
    records = (
        Attendance.query.filter(Attendance.enrollment_id.in_(eids))
        .order_by(Attendance.date.desc()).limit(60).all()
    )
    p = sum(1 for r in records if r.status == "present")
    a = sum(1 for r in records if r.status == "absent")
    l = sum(1 for r in records if r.status == "late")
    total = p + a + l
    return jsonify({
        "summary": {"present": p, "absent": a, "late": l, "total": total,
                    "rate": round((p / total * 100) if total else 0, 1)},
        "records": [
            {"date": r.date.isoformat(), "status": r.status, "notes": r.notes}
            for r in records
        ],
    })


@bp.route("/parent/child/<int:student_id>/results", methods=["GET"])
@jwt_required
def parent_child_results(student_id):
    s = _check_child(student_id)
    if not s:
        return _err("child not found", 404)
    # Only APPROVED results (T-10.3 acceptance)
    out = []
    for enr in s.enrollments:
        yr = YearResult.query.filter_by(enrollment_id=enr.id).first()
        if not yr:
            continue
        out.append({
            "year": enr.year.name,
            "grade": enr.grade.name,
            "section": enr.section.name,
            "status": yr.status,
            "average": float(yr.average),
            "subject_scores": yr.subject_scores,
            "approved_at": yr.approved_at.isoformat(),
        })
    return jsonify({"results": out})


@bp.route("/parent/child/<int:student_id>/invoices", methods=["GET"])
@jwt_required
def parent_child_invoices(student_id):
    s = _check_child(student_id)
    if not s:
        return _err("child not found", 404)
    eids = [e.id for e in s.enrollments]
    invoices = Invoice.query.filter(Invoice.enrollment_id.in_(eids)).order_by(Invoice.issue_date.desc()).all()
    return jsonify({"invoices": [
        {
            "id": i.id, "number": i.number,
            "issue_date": i.issue_date.isoformat(),
            "due_date": i.due_date.isoformat(),
            "total_amount": float(i.total_amount),
            "paid_amount": float(i.paid_amount),
            "remaining": float(i.remaining),
            "status": i.status,
        } for i in invoices
    ]})


@bp.route("/parent/notifications", methods=["GET"])
@jwt_required
def parent_notifications():
    # Sprint 11 — filter by direct student_id FK, not target_phone.
    # The old phone-based filter cross-leaked when two families shared a
    # phone number; the FK path guarantees a notification only reaches the
    # parent whose Student row it was recorded against.
    child_ids = [
        r[0] for r in db.session.query(Student.id).filter(
            Student.school_id == _sid(),
            Student.parent_user_id.isnot(None),
            Student.parent_user_id == _user().id,
        ).all()
    ]
    if not child_ids:
        return jsonify({"notifications": []})
    notifs = (
        NotificationLog.query
        .filter(
            NotificationLog.school_id == _sid(),
            NotificationLog.student_id.in_(child_ids),
        )
        .order_by(NotificationLog.created_at.desc())
        .limit(50)
        .all()
    )
    return jsonify({"notifications": [
        {
            "id": n.id, "kind": n.kind, "status": n.status,
            "payload": n.payload, "created_at": n.created_at.isoformat(),
        } for n in notifs
    ]})


@bp.route("/parent/child/<int:student_id>/schedule", methods=["GET"])
@jwt_required
def parent_child_schedule(student_id):
    """Weekly schedule for a child's current section."""
    s = _check_child(student_id)
    if not s:
        return _err("child not found", 404)
    year = _active_year()
    if not year:
        return jsonify({"slots": []})
    enr = next(
        (e for e in s.enrollments if e.year_id == year.id and e.status == "active"),
        None,
    )
    if not enr:
        return jsonify({"slots": []})
    slots = (
        ScheduleSlot.query.filter_by(
            school_id=_sid(), year_id=year.id, section_id=enr.section_id,
        )
        .order_by(ScheduleSlot.day_id, ScheduleSlot.period_id).all()
    )
    return jsonify({"slots": [
        {
            "day_id": s.day_id, "day_name": s.day.name,
            "period_id": s.period_id, "period_name": s.period.name,
            "start_time": s.period.start_time.strftime("%H:%M"),
            "end_time": s.period.end_time.strftime("%H:%M"),
            "subject_id": s.subject_id, "subject_name": s.subject.name,
            "teacher_id": s.teacher_id, "teacher_name": s.teacher.full_name,
        } for s in slots
    ]})


@bp.route("/parent/child/<int:student_id>/materials", methods=["GET"])
@jwt_required
def parent_child_materials(student_id):
    s = _check_child(student_id)
    if not s:
        return _err("child not found", 404)
    year = _active_year()
    if not year:
        return jsonify({"materials": []})
    enr = next((e for e in s.enrollments if e.year_id == year.id and e.status == "active"), None)
    if not enr:
        return jsonify({"materials": []})
    materials = Material.query.filter_by(
        school_id=_sid(), section_id=enr.section_id, year_id=year.id
    ).order_by(Material.created_at.desc()).all()
    return jsonify({"materials": [_material_dict(m) for m in materials]})


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _parse_dt(s):
    """Accept ISO 8601 timestamps (`2026-10-20T14:30:00`, `2026-10-20T14:30:00Z`,
    `2026-10-20T14:30:00+03:00`) or a bare date. Trailing `Z` is treated
    as UTC. Returns a naive `datetime` in the local tz for storage."""
    if not s:
        return None
    if isinstance(s, datetime):
        return s
    try:
        txt = s.strip()
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        if "T" in txt or " " in txt:
            dt = datetime.fromisoformat(txt.replace(" ", "T"))
            return dt.replace(tzinfo=None) if dt.tzinfo else dt
        return datetime.strptime(txt, "%Y-%m-%d")
    except (ValueError, TypeError, AttributeError):
        return None


# ═══════════════════════════════════════════════════════════════════════
# Student mobile app endpoints (added 2026-09-21).
#
# A student user is linked to their `Student` row via `Student.user_id`
# (see migration `k9r1s3u5v7w9_students_user_id`). Every route below
# resolves the caller into a Student first, then scopes queries to that
# student's active enrollment.
# ═══════════════════════════════════════════════════════════════════════

def _student_for(user):
    """Resolve the current authenticated user to their Student row.

    Returns None if no linked Student — the app should treat that as
    "your account isn't linked to a student profile yet" and show a
    friendly error rather than crashing.
    """
    return Student.query.filter_by(school_id=user.school_id, user_id=user.id).first()


def _active_enrollment(student):
    year = _active_year()
    if not year:
        return None
    return Enrollment.query.filter_by(
        student_id=student.id, year_id=year.id, status="active",
    ).first()


@bp.route("/student/home", methods=["GET"])
@jwt_required
def student_home():
    """Roll-up for the [STU] Home screen: greeting, stats, today's
    periods, upcoming deadlines, latest announcements."""
    from ...models import Announcement, CourseAssignment, Submission
    from ...models.attendance import Attendance as _Att   # noqa: F401
    student = _student_for(_user())
    if not student:
        return _err("student profile not linked", 404)
    year = _active_year()
    enr = _active_enrollment(student)

    # ── Stats
    stats = {"gpa_pct": None, "attendance_pct": None,
             "assignments_submitted": 0, "assignments_total": 0}
    if enr:
        from ...models import Course, CourseAssignment, CourseSection, Submission
        yr = YearResult.query.filter_by(enrollment_id=enr.id).first()
        stats["gpa_pct"] = float(yr.average) if yr and yr.average else None

        att_total = Attendance.query.filter_by(enrollment_id=enr.id).count()
        att_present = Attendance.query.filter_by(
            enrollment_id=enr.id, status="present",
        ).count()
        stats["attendance_pct"] = (
            round(att_present * 100.0 / att_total, 1) if att_total else None
        )

        # Assignments visible to this student's section — via CourseSection.
        section_course_ids = [
            cs.course_id for cs in CourseSection.query.filter_by(
                section_id=enr.section_id,
            ).all()
        ]
        stats["assignments_total"] = (
            CourseAssignment.query.filter(
                CourseAssignment.course_id.in_(section_course_ids),
                CourseAssignment.is_published.is_(True),
            ).count() if section_course_ids else 0
        )
        stats["assignments_submitted"] = Submission.query.filter_by(
            student_id=student.id,
        ).count()

    # ── Today's periods (from ScheduleSlot filtered by weekday name).
    periods = []
    today_wd = date.today().weekday()   # Mon=0..Sun=6
    if enr and year:
        slots = (
            ScheduleSlot.query.filter_by(
                year_id=year.id, section_id=enr.section_id,
            ).all()
        )
        # Day.name is Arabic; keep the slot with a numeric `order_index` we can sort by.
        for s in slots:
            periods.append({
                "id": s.id,
                "day": s.day.name if s.day else None,
                "day_order": s.day.order_index if s.day else 0,
                "period_order": s.period.order_index if s.period else 0,
                "period_name": s.period.name if s.period else None,
                "start": s.period.start_time.strftime("%H:%M") if s.period and s.period.start_time else None,
                "end":   s.period.end_time.strftime("%H:%M")   if s.period and s.period.end_time   else None,
                "subject": s.subject.name if s.subject else None,
                "teacher": s.teacher.full_name if s.teacher else None,
                "room": s.room.name if s.room else None,
            })
        periods.sort(key=lambda p: (p["day_order"], p["period_order"]))

    # ── Upcoming assignments (next 5 by due date).
    upcoming = []
    if enr:
        from ...models import Course, CourseAssignment, CourseSection
        section_course_ids = [
            cs.course_id for cs in CourseSection.query.filter_by(
                section_id=enr.section_id,
            ).all()
        ]
        if section_course_ids:
            cas = (
                CourseAssignment.query.filter(
                    CourseAssignment.course_id.in_(section_course_ids),
                    CourseAssignment.is_published.is_(True),
                )
                .order_by(CourseAssignment.due_at.asc().nullslast())
                .limit(5).all()
            )
            # Batch course→subject lookup.
            course_map = {c.id: c for c in Course.query.filter(
                Course.id.in_(section_course_ids),
            ).all()}
            subjects_by_id = {
                s.id: s.name for s in Subject.query.filter(
                    Subject.id.in_({c.subject_id for c in course_map.values() if c.subject_id}),
                ).all()
            }
            for c in cas:
                course = course_map.get(c.course_id)
                upcoming.append({
                    "id": c.id,
                    "title": c.title,
                    "kind": "assignment",
                    "due_at": c.due_at.isoformat() if c.due_at else None,
                    "subject": subjects_by_id.get(course.subject_id) if course else None,
                })

    # ── Announcements — visible to this student's section.
    announcements = []
    from sqlalchemy import or_
    if enr:
        anns = (
            Announcement.query.filter_by(school_id=_sid())
            .filter(or_(Announcement.section_id.is_(None),
                        Announcement.section_id == enr.section_id))
            .order_by(Announcement.created_at.desc())
            .limit(3).all()
        )
        for a in anns:
            announcements.append({
                "id": a.id,
                "title": a.title,
                "preview": (a.body or "")[:120],
                "created_at": a.created_at.isoformat() if a.created_at else None,
            })

    return jsonify({
        "student": {
            "id": student.id,
            "full_name": student.full_name,
            "permanent_code": student.permanent_code,
            "class": (
                f"{enr.section.grade.name} — {enr.section.name}"
                if enr and enr.section else None
            ),
        },
        "stats": stats,
        "today_periods": periods,
        "upcoming": upcoming,
        "announcements": announcements,
    })


@bp.route("/student/courses", methods=["GET"])
@jwt_required
def student_courses():
    from ...models import Course, CourseSection, Lesson
    student = _student_for(_user())
    if not student:
        return _err("student profile not linked", 404)
    enr = _active_enrollment(student)
    if not enr:
        return jsonify({"courses": []})

    # Every Course bound to this student's section via CourseSection.
    cs_rows = CourseSection.query.filter_by(
        section_id=enr.section_id, is_published=True,
    ).all()
    course_ids = [cs.course_id for cs in cs_rows]
    courses = Course.query.filter(Course.id.in_(course_ids)).all() if course_ids else []
    # Batch subject lookup so we don't re-query per course.
    subject_ids = {c.subject_id for c in courses if c.subject_id}
    subjects_by_id = {
        s.id: s.name for s in Subject.query.filter(Subject.id.in_(subject_ids)).all()
    } if subject_ids else {}
    out = []
    for c in courses:
        total_lessons = (
            db.session.query(db.func.count()).select_from(
                __import__('sqlalchemy').text('lms_lessons')
            ) if False else Lesson.query.filter_by(course_id=c.id, is_published=True).count()
        )
        out.append({
            "id": c.id,
            "title": c.title,
            "subject": subjects_by_id.get(c.subject_id),
            "teacher": None,   # resolved per-section via teacher.Assignment; wire later
            "total_lessons": total_lessons,
            "cover_url": c.cover_url or None,
        })
    return jsonify({"courses": out})


@bp.route("/student/courses/<int:course_id>", methods=["GET"])
@jwt_required
def student_course_detail(course_id):
    from ...models import Course, Unit, Lesson
    student = _student_for(_user())
    if not student:
        return _err("student profile not linked", 404)
    course = Course.query.get(course_id)
    if not course:
        return _err("course not found", 404)
    subject_name = None
    if course.subject_id:
        subj = Subject.query.get(course.subject_id)
        subject_name = subj.name if subj else None
    units = Unit.query.filter_by(course_id=course.id).order_by(Unit.order_index).all()
    unit_rows = []
    for u in units:
        lessons = (
            Lesson.query.filter_by(unit_id=u.id, is_published=True)
            .order_by(Lesson.order_index).all()
        )
        unit_rows.append({
            "id": u.id, "title": u.title,
            "lessons": [{
                "id": l.id, "title": l.title, "kind": l.kind,
                "duration_minutes": l.duration_minutes,
                "media_url": l.media_url,
            } for l in lessons],
        })
    orphan = (
        Lesson.query.filter_by(course_id=course.id, unit_id=None, is_published=True)
        .order_by(Lesson.order_index).all()
    )
    return jsonify({
        "course": {
            "id": course.id, "title": course.title,
            "teacher": None,   # resolved per-section via teacher.Assignment; wire later
            "subject": subject_name,
        },
        "units": unit_rows,
        "orphan_lessons": [{
            "id": l.id, "title": l.title, "kind": l.kind,
            "duration_minutes": l.duration_minutes,
            "media_url": l.media_url,
        } for l in orphan],
    })


@bp.route("/student/assignments", methods=["GET"])
@jwt_required
def student_assignments():
    from ...models import Course, CourseAssignment, CourseSection, Submission
    student = _student_for(_user())
    if not student:
        return _err("student profile not linked", 404)
    enr = _active_enrollment(student)
    if not enr:
        return jsonify({"assignments": []})
    section_course_ids = [
        cs.course_id for cs in CourseSection.query.filter_by(
            section_id=enr.section_id,
        ).all()
    ]
    if not section_course_ids:
        return jsonify({"assignments": []})
    cas = (
        CourseAssignment.query.filter(
            CourseAssignment.course_id.in_(section_course_ids),
            CourseAssignment.is_published.is_(True),
        )
        .order_by(CourseAssignment.due_at.asc().nullslast()).all()
    )
    subs_by_ca = {s.assignment_id: s for s in Submission.query.filter_by(
        student_id=student.id,
    ).all()}
    course_map = {c.id: c for c in Course.query.filter(
        Course.id.in_(section_course_ids),
    ).all()}
    subjects_by_id = {
        s.id: s.name for s in Subject.query.filter(
            Subject.id.in_({c.subject_id for c in course_map.values() if c.subject_id}),
        ).all()
    }
    out = []
    for c in cas:
        sub = subs_by_ca.get(c.id)
        course = course_map.get(c.course_id)
        out.append({
            "id": c.id,
            "title": c.title,
            "subject": subjects_by_id.get(course.subject_id) if course else None,
            "due_at": c.due_at.isoformat() if c.due_at else None,
            "status": (
                "graded" if sub and sub.score is not None
                else "submitted" if sub
                else "not_started"
            ),
            "score": float(sub.score) if sub and sub.score is not None else None,
        })
    return jsonify({"assignments": out})


@bp.route("/student/schedule", methods=["GET"])
@jwt_required
def student_schedule():
    student = _student_for(_user())
    if not student:
        return _err("student profile not linked", 404)
    year = _active_year()
    enr = _active_enrollment(student)
    if not (enr and year):
        return jsonify({"schedule": []})
    slots = ScheduleSlot.query.filter_by(
        year_id=year.id, section_id=enr.section_id,
    ).all()
    out = [{
        "day": s.day.name if s.day else None,
        "day_order": s.day.order_index if s.day else 0,
        "period_order": s.period.order_index if s.period else 0,
        "period_name": s.period.name if s.period else None,
        "start": s.period.start_time.strftime("%H:%M") if s.period and s.period.start_time else None,
        "end":   s.period.end_time.strftime("%H:%M")   if s.period and s.period.end_time   else None,
        "subject": s.subject.name if s.subject else None,
        "teacher": s.teacher.full_name if s.teacher else None,
        "room": s.room.name if s.room else None,
    } for s in slots]
    return jsonify({"schedule": out})


@bp.route("/student/attendance", methods=["GET"])
@jwt_required
def student_attendance():
    student = _student_for(_user())
    if not student:
        return _err("student profile not linked", 404)
    # All enrollments (any year) for a complete attendance history.
    enrollment_ids = [e.id for e in student.enrollments]
    if not enrollment_ids:
        return jsonify({"attendance": []})
    rows = (
        Attendance.query.filter(Attendance.enrollment_id.in_(enrollment_ids))
        .order_by(Attendance.date.desc()).limit(200).all()
    )
    return jsonify({"attendance": [{
        "date": r.date.isoformat() if r.date else None,
        "status": r.status,
        "reason": r.notes or getattr(r, "excuse_reason", None),
    } for r in rows]})


@bp.route("/student/grades", methods=["GET"])
@jwt_required
def student_grades():
    from ...models import GradeEntry
    student = _student_for(_user())
    if not student:
        return _err("student profile not linked", 404)
    year = _active_year()
    enrollment_ids = [e.id for e in student.enrollments]
    entries = (
        GradeEntry.query.filter(GradeEntry.enrollment_id.in_(enrollment_ids))
        .order_by(GradeEntry.id.desc()).limit(200).all()
        if enrollment_ids else []
    )
    out = []
    for g in entries:
        comp = g.component
        out.append({
            "id": g.id,
            "term":      comp.term.name    if comp and comp.term else None,
            "subject":   comp.subject.name if comp and comp.subject else None,
            "component": comp.name         if comp else None,
            "score": float(g.score) if g.score is not None else None,
            "max":   float(comp.max_score) if comp and comp.max_score is not None else None,
        })
    yr = None
    if year and enrollment_ids:
        yr_row = YearResult.query.filter(
            YearResult.enrollment_id.in_(enrollment_ids),
        ).first()
        if yr_row:
            yr = {
                "overall_percent": float(yr_row.average) if yr_row.average else None,
                "status": yr_row.status,
            }
    return jsonify({"entries": out, "year_result": yr})


@bp.route("/student/announcements", methods=["GET"])
@jwt_required
def student_announcements():
    from ...models import Announcement
    from sqlalchemy import or_
    student = _student_for(_user())
    if not student:
        return _err("student profile not linked", 404)
    enr = _active_enrollment(student)
    q = Announcement.query.filter_by(school_id=_sid())
    if enr:
        q = q.filter(or_(Announcement.section_id.is_(None),
                         Announcement.section_id == enr.section_id))
    rows = q.order_by(Announcement.created_at.desc()).limit(50).all()
    return jsonify({"announcements": [{
        "id": a.id,
        "title": a.title,
        "body": a.body,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "author": a.author.full_name if getattr(a, "author", None) else None,
    } for a in rows]})


@bp.route("/student/announcements/<int:aid>", methods=["GET"])
@jwt_required
def student_announcement_detail(aid):
    from ...models import Announcement
    student = _student_for(_user())
    if not student:
        return _err("student profile not linked", 404)
    a = Announcement.query.filter_by(id=aid, school_id=_sid()).first()
    if not a:
        return _err("not found", 404)
    author_name = None
    if a.author_id:
        u = User.query.get(a.author_id)
        author_name = u.full_name if u else None
    return jsonify({
        "id": a.id,
        "title": a.title,
        "body": a.body,
        "author": author_name,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "pinned": a.is_pinned,
    })


@bp.route("/student/lessons/<int:lid>", methods=["GET"])
@jwt_required
def student_lesson_view(lid):
    from ...models import Lesson, CourseSection
    student = _student_for(_user())
    if not student:
        return _err("student profile not linked", 404)
    lesson = Lesson.query.get(lid)
    if not lesson or not lesson.is_published:
        return _err("not found", 404)
    # Access check: student must be enrolled in a section that publishes
    # the parent course.
    enr = _active_enrollment(student)
    if enr:
        allowed = CourseSection.query.filter_by(
            course_id=lesson.course_id, section_id=enr.section_id,
        ).first()
        if not allowed:
            return _err("not authorised", 403)
    return jsonify({
        "id": lesson.id,
        "course_id": lesson.course_id,
        "unit_id": lesson.unit_id,
        "title": lesson.title,
        "kind": lesson.kind,
        "body": lesson.body,
        "media_url": lesson.media_url,
        "duration_minutes": lesson.duration_minutes,
    })


@bp.route("/student/assignments/<int:aid>", methods=["GET"])
@jwt_required
def student_assignment_detail(aid):
    from ...models import (
        CourseAssignment, Submission,
        AssignmentQuestion, AssignmentChoice,
    )
    student = _student_for(_user())
    if not student:
        return _err("student profile not linked", 404)
    a = CourseAssignment.query.get(aid)
    if not a or not a.is_published:
        return _err("not found", 404)
    # Questions + choices, if the assignment has any (smart assignments).
    qs = (
        AssignmentQuestion.query.filter_by(assignment_id=a.id)
        .order_by(AssignmentQuestion.order_index).all()
    )
    out_qs = []
    for q in qs:
        choices = (
            AssignmentChoice.query.filter_by(question_id=q.id)
            .order_by(AssignmentChoice.order_index).all()
        )
        out_qs.append({
            "id": q.id,
            "kind": q.kind,
            "prompt": q.prompt,
            "points": float(q.points) if q.points is not None else None,
            "choices": [{"id": ch.id, "label": ch.label} for ch in choices],
        })
    sub = Submission.query.filter_by(assignment_id=a.id, student_id=student.id).first()
    return jsonify({
        "id": a.id,
        "title": a.title,
        "instructions": a.instructions,
        "due_at": a.due_at.isoformat() if a.due_at else None,
        "max_score": float(a.max_score) if a.max_score is not None else None,
        "questions": out_qs,
        "submission": {
            "id": sub.id,
            "body": sub.body,
            "file_url": sub.file_url,
            "submitted_at": sub.submitted_at.isoformat() if sub.submitted_at else None,
            "score": float(sub.score) if sub.score is not None else None,
            "feedback": sub.feedback,
        } if sub else None,
    })


@bp.route("/student/assignments/<int:aid>/submit", methods=["POST"])
@jwt_required
def student_assignment_submit(aid):
    from ...models import (
        CourseAssignment, Submission,
        AssignmentAnswer, AssignmentChoice,
    )
    student = _student_for(_user())
    if not student:
        return _err("student profile not linked", 404)
    a = CourseAssignment.query.get(aid)
    if not a or not a.is_published:
        return _err("not found", 404)

    data = request.get_json(silent=True) or {}
    sub = Submission.query.filter_by(assignment_id=a.id, student_id=student.id).first()
    if sub is None:
        sub = Submission(assignment_id=a.id, student_id=student.id)
        db.session.add(sub); db.session.flush()
    sub.body = data.get("body") or ""
    sub.file_url = data.get("file_url") or ""
    sub.submitted_at = datetime.utcnow()

    # MCQ answers — { question_id: choice_id | text }
    answers = data.get("answers") or {}
    for qid_raw, val in answers.items():
        try:
            qid = int(qid_raw)
        except (TypeError, ValueError):
            continue
        ans = AssignmentAnswer.query.filter_by(
            submission_id=sub.id, question_id=qid,
        ).first()
        if ans is None:
            ans = AssignmentAnswer(submission_id=sub.id, question_id=qid)
            db.session.add(ans)
        # Choice id (int) → choice_id; anything else → text_answer.
        if isinstance(val, int) or (isinstance(val, str) and val.isdigit()):
            ans.choice_id = int(val)
            ans.text_answer = ""
        else:
            ans.choice_id = None
            ans.text_answer = str(val or "")
    db.session.commit()
    return jsonify({"ok": True, "submission_id": sub.id})


@bp.route("/student/quizzes", methods=["GET"])
@jwt_required
def student_quizzes():
    from ...models import Course, CourseSection, Quiz, QuizAttempt
    student = _student_for(_user())
    if not student:
        return _err("student profile not linked", 404)
    enr = _active_enrollment(student)
    if not enr:
        return jsonify({"quizzes": []})
    section_course_ids = [
        cs.course_id for cs in CourseSection.query.filter_by(
            section_id=enr.section_id,
        ).all()
    ]
    if not section_course_ids:
        return jsonify({"quizzes": []})
    quizzes = (
        Quiz.query.filter(
            Quiz.course_id.in_(section_course_ids),
            Quiz.is_published.is_(True),
        )
        .order_by(Quiz.opens_at.asc().nullslast()).all()
    )
    attempts_by_qz = {a.quiz_id: a for a in QuizAttempt.query.filter_by(
        student_id=student.id,
    ).all()}
    course_map = {c.id: c for c in Course.query.filter(
        Course.id.in_(section_course_ids),
    ).all()}
    subjects_by_id = {
        s.id: s.name for s in Subject.query.filter(
            Subject.id.in_({c.subject_id for c in course_map.values() if c.subject_id}),
        ).all()
    }
    out = []
    for q in quizzes:
        att = attempts_by_qz.get(q.id)
        course = course_map.get(q.course_id)
        out.append({
            "id": q.id,
            "title": q.title,
            "subject": subjects_by_id.get(course.subject_id) if course else None,
            "duration_minutes": q.duration_minutes,
            "opens_at":  q.opens_at.isoformat()  if q.opens_at  else None,
            "closes_at": q.closes_at.isoformat() if q.closes_at else None,
            "status": (
                "graded"    if att and att.score is not None
                else "submitted" if att and att.submitted_at
                else "in_progress" if att
                else "not_started"
            ),
            "score": float(att.score) if att and att.score is not None else None,
        })
    return jsonify({"quizzes": out})


@bp.route("/student/quizzes/<int:qid>/attempt", methods=["GET"])
@jwt_required
def student_quiz_attempt(qid):
    from ...models import Quiz, Question, Choice
    student = _student_for(_user())
    if not student:
        return _err("student profile not linked", 404)
    q = Quiz.query.get(qid)
    if not q or not q.is_published:
        return _err("not found", 404)
    questions = (
        Question.query.filter_by(quiz_id=q.id)
        .order_by(Question.order_index).all()
    )
    out_qs = []
    for qu in questions:
        choices = (
            Choice.query.filter_by(question_id=qu.id)
            .order_by(Choice.order_index).all()
        )
        out_qs.append({
            "id": qu.id,
            "kind": qu.kind,
            "prompt": qu.prompt,
            "points": float(qu.points) if qu.points is not None else None,
            "choices": [{"id": ch.id, "label": ch.label} for ch in choices],
        })
    return jsonify({
        "quiz": {
            "id": q.id, "title": q.title, "description": q.description,
            "duration_minutes": q.duration_minutes,
        },
        "questions": out_qs,
    })


@bp.route("/student/quizzes/<int:qid>/submit", methods=["POST"])
@jwt_required
def student_quiz_submit(qid):
    from ...models import Quiz, Question, Choice, QuizAttempt, Answer
    student = _student_for(_user())
    if not student:
        return _err("student profile not linked", 404)
    q = Quiz.query.get(qid)
    if not q or not q.is_published:
        return _err("not found", 404)

    data = request.get_json(silent=True) or {}
    answers = data.get("answers") or {}   # { question_id: choice_id | text }

    attempt = QuizAttempt(quiz_id=q.id, student_id=student.id,
                          submitted_at=datetime.utcnow(), auto_graded=True)
    db.session.add(attempt); db.session.flush()

    total_points = Decimal(0)
    awarded = Decimal(0)
    for question in q.questions:
        total_points += (question.points or Decimal(0))
        val = answers.get(str(question.id)) or answers.get(question.id)
        ans = Answer(attempt_id=attempt.id, question_id=question.id)
        if question.kind in ("mcq", "tf") and (isinstance(val, int) or (isinstance(val, str) and val.isdigit())):
            ans.choice_id = int(val)
            chosen = Choice.query.get(ans.choice_id)
            ans.is_correct = bool(chosen and chosen.is_correct)
            if ans.is_correct:
                ans.awarded_points = question.points or Decimal(0)
                awarded += ans.awarded_points
        elif question.kind == "short" and val is not None:
            ans.text_answer = str(val)
            correct = (question.correct_short or "").strip().lower()
            ans.is_correct = bool(correct) and ans.text_answer.strip().lower() == correct
            if ans.is_correct:
                ans.awarded_points = question.points or Decimal(0)
                awarded += ans.awarded_points
        else:
            ans.text_answer = str(val) if val is not None else ""
        db.session.add(ans)

    if total_points > 0:
        attempt.score = (awarded * Decimal(100) / total_points).quantize(Decimal("0.01"))
    else:
        attempt.score = Decimal(0)
    db.session.commit()
    return jsonify({
        "ok": True,
        "attempt_id": attempt.id,
        "score": float(attempt.score),
        "awarded": float(awarded),
        "total_points": float(total_points),
    })


@bp.route("/student/report-card/<int:term_id>", methods=["GET"])
@jwt_required
def student_report_card(term_id):
    from ...models import GradeEntry, AssessmentComponent
    student = _student_for(_user())
    if not student:
        return _err("student profile not linked", 404)
    enrollment_ids = [e.id for e in student.enrollments]
    if not enrollment_ids:
        return jsonify({"subjects": [], "summary": None})
    # Every grade entry for this student whose component belongs to the
    # requested term.
    comps = AssessmentComponent.query.filter_by(term_id=term_id).all()
    comp_ids = [c.id for c in comps]
    if not comp_ids:
        return jsonify({"subjects": [], "summary": None})
    entries = GradeEntry.query.filter(
        GradeEntry.enrollment_id.in_(enrollment_ids),
        GradeEntry.component_id.in_(comp_ids),
    ).all()

    # Bucket by subject: accumulate awarded / max.
    per_subject: dict[int, dict] = {}
    for e in entries:
        c = e.component
        if not c or not c.subject_id:
            continue
        b = per_subject.setdefault(c.subject_id, {
            "subject_id": c.subject_id, "awarded": 0.0, "max": 0.0,
            "components": [],
        })
        b["awarded"] += float(e.score or 0)
        b["max"]     += float(c.max_score or 0)
        b["components"].append({
            "name": c.name,
            "score": float(e.score) if e.score is not None else None,
            "max":   float(c.max_score) if c.max_score is not None else None,
        })
    # Attach subject names.
    if per_subject:
        subjects_by_id = {
            s.id: s.name for s in Subject.query.filter(
                Subject.id.in_(per_subject.keys()),
            ).all()
        }
        for sid, b in per_subject.items():
            b["subject"] = subjects_by_id.get(sid)
            b["pct"] = round(b["awarded"] * 100 / b["max"], 2) if b["max"] else None
    subjects = list(per_subject.values())
    subjects.sort(key=lambda x: -(x["pct"] or 0))

    # Summary.
    tot_awarded = sum(b["awarded"] for b in subjects)
    tot_max     = sum(b["max"]     for b in subjects)
    summary = {
        "overall_pct": round(tot_awarded * 100 / tot_max, 2) if tot_max else None,
        "subject_count": len(subjects),
    }
    return jsonify({"subjects": subjects, "summary": summary})
