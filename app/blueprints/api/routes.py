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
    AcademicYear, Assignment, AssessmentComponent, Attendance, DeviceToken,
    Enrollment, GradeEntry, Invoice, Material, NotificationLog, Payment,
    ScheduleSlot, School, Section, Student, Subject, Teacher, Term, User,
    YearResult,
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
        return _err("missing credentials")
    user = User.query.filter_by(username=username).first()
    if not user or not user.is_active or not user.check_password(password):
        return _err("invalid credentials", 401)

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
    t = _teacher_for(_user())
    if not t:
        return _err("not a teacher", 403)
    year = _active_year()
    if not year:
        return jsonify({"sections": []})
    assignments = Assignment.query.filter_by(
        teacher_id=t.id, year_id=year.id, is_active=True
    ).all()
    seen = {}
    for a in assignments:
        if a.section_id not in seen:
            seen[a.section_id] = {
                "id": a.section.id,
                "name": f"{a.section.grade.name} / {a.section.name}",
                "subjects": [],
            }
        seen[a.section_id]["subjects"].append({"id": a.subject.id, "name": a.subject.name})
    return jsonify({"sections": list(seen.values())})


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
