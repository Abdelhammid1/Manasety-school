"""SAAS-011 — the only way to read an uploaded file.

GET /files/<school_id>/<kind>/<owner_id>/<name>

Order of checks:
  1. key is well-formed, confined to UPLOAD_ROOT and on disk, else 404
  2. key's school == the request's school, else 404 (never confirm
     another school's file exists)
  3. a valid ?exp=&sig= (issued to the mobile apps) grants access;
     otherwise the viewer (session or Bearer JWT) must pass the kind's
     policy: 404 when the owning record is gone, 403 when the viewer
     simply lacks access
"""
from __future__ import annotations

from flask import Blueprint, abort, g, request, send_file
from flask_login import current_user

from ...extensions import db
from ...services import file_storage as fs

bp = Blueprint("files", __name__, cli_group=None)

NOT_FOUND, FORBIDDEN, OK = 404, 403, 200


def _viewer():
    if getattr(current_user, "is_authenticated", False):
        return current_user
    from ...services.auth_jwt import user_from_bearer
    return user_from_bearer()


def _request_school_id(user):
    resolved = getattr(g, "tenant_resolved", None)
    if resolved is not None and resolved.kind == "tenant" and resolved.school is not None:
        return resolved.school.id
    return getattr(user, "school_id", None)


def _student_links(user):
    """Student ids the user *is* or is the parent of."""
    from ...models import Student
    return {s.id for s in Student.query.filter(
        Student.school_id == user.school_id,
        db.or_(Student.user_id == user.id, Student.parent_user_id == user.id),
    )}


def _enrolled_section_ids(student_ids):
    from ...models import Enrollment
    if not student_ids:
        return set()
    return {e.section_id for e in Enrollment.query.filter(
        Enrollment.student_id.in_(student_ids), Enrollment.status == "active")}


def _owned(model, owner_id, school_id):
    return model.query.filter_by(id=owner_id, school_id=school_id).first()


# Each policy: (user, owner_id, school_id) -> OK | FORBIDDEN | NOT_FOUND

def _logo(user, owner_id, school_id):
    return OK if owner_id == school_id else NOT_FOUND


def _materials(user, owner_id, school_id):
    from ...models import Section
    if _owned(Section, owner_id, school_id) is None:
        return NOT_FOUND
    if user.can("lms", "edit") or user.can("students", "view"):
        return OK
    return OK if owner_id in _enrolled_section_ids(_student_links(user)) else FORBIDDEN


def _excuse(user, owner_id, school_id):
    from ...models import Enrollment
    enr = _owned(Enrollment, owner_id, school_id)
    if enr is None:
        return NOT_FOUND
    if user.can("attendance", "view"):
        return OK
    return OK if enr.student_id in _student_links(user) else FORBIDDEN


def _lessons(user, owner_id, school_id):
    from ...models import Course, CourseSection
    if _owned(Course, owner_id, school_id) is None:
        return NOT_FOUND
    if user.can("lms", "edit"):
        return OK
    sections = _enrolled_section_ids(_student_links(user))
    published = CourseSection.query.filter(
        CourseSection.course_id == owner_id,
        CourseSection.section_id.in_(sections or {0}),
        CourseSection.is_published.is_(True)).first()
    return OK if published else FORBIDDEN


def _submissions(user, owner_id, school_id):
    from ...models import Student, Submission
    sub = db.session.get(Submission, owner_id)
    stu = db.session.get(Student, sub.student_id) if sub else None
    if stu is None or stu.school_id != school_id:
        return NOT_FOUND
    if user.can("lms", "edit"):
        return OK
    return OK if stu.id in _student_links(user) else FORBIDDEN


def _messages(user, owner_id, school_id):
    from ...models import Conversation, ConversationParticipant
    if _owned(Conversation, owner_id, school_id) is None:
        return NOT_FOUND
    member = ConversationParticipant.query.filter_by(
        conversation_id=owner_id, user_id=user.id).first()
    return OK if member else FORBIDDEN


def _student_photo(user, owner_id, school_id):
    from ...models import Student
    if _owned(Student, owner_id, school_id) is None:
        return NOT_FOUND
    if user.can("students", "view"):
        return OK
    return OK if owner_id in _student_links(user) else FORBIDDEN


def _student_records(user, owner_id, school_id):
    from ...models import Student
    if _owned(Student, owner_id, school_id) is None:
        return NOT_FOUND
    return OK if user.can("students", "view") else FORBIDDEN


POLICIES = {
    "logo": _logo,
    "materials": _materials,
    "excuse": _excuse,
    "lessons": _lessons,
    "submissions": _submissions,
    "messages": _messages,
    "student_photo": _student_photo,
    "previous_school": _student_records,
    "student_docs": _student_records,
}


@bp.route("/files/<path:key>", endpoint="download")
def download(key):
    fk = fs.parse_key(key)
    if fk is None:
        abort(404)
    user = _viewer()
    signed = fs.signature_valid(key, request.args.get("exp"), request.args.get("sig"))
    if user is None and not signed:
        abort(401)
    request_school = _request_school_id(user) if user is not None else None
    if user is not None and fk.school_id != request_school:
        abort(404)
    if signed and user is None:
        resolved = getattr(g, "tenant_resolved", None)
        if resolved is not None and resolved.kind == "tenant" and \
                resolved.school is not None and resolved.school.id != fk.school_id:
            abort(404)
    elif not signed:
        verdict = POLICIES[fk.kind](user, fk.owner_id, fk.school_id)
        if verdict != OK:
            abort(verdict)
    resp = send_file(fk.path, conditional=True, max_age=0)
    # Neutralise active content (e.g. an SVG opened directly).
    resp.headers["Content-Security-Policy"] = "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Cache-Control"] = "private, no-store"
    return resp


# ─── `flask files-migrate-static` ───────────────────────────────────

def _legacy_targets():
    """(model, column, kind, school_id(row), owner_id(row))."""
    from ...models import (
        Attendance, Course, Lesson, Material, Message, Conversation,
        PreviousSchool, School, Student, StudentDocument, Submission,
    )

    def via(model, fk):
        return lambda r: getattr(db.session.get(model, getattr(r, fk)), "school_id", None)

    return [
        (School, "logo_url", "logo", lambda r: r.id, lambda r: r.id),
        (Material, "file_path", "materials", lambda r: r.school_id, lambda r: r.section_id),
        (Attendance, "excuse_document", "excuse", lambda r: r.school_id, lambda r: r.enrollment_id),
        (Lesson, "media_url", "lessons", via(Course, "course_id"), lambda r: r.course_id),
        (Submission, "file_url", "submissions", via(Student, "student_id"), lambda r: r.id),
        (Message, "attachment_path", "messages", via(Conversation, "conversation_id"),
         lambda r: r.conversation_id),
        (Student, "photo_url", "student_photo", lambda r: r.school_id, lambda r: r.id),
        (PreviousSchool, "document_url", "previous_school", via(Student, "student_id"),
         lambda r: r.student_id),
        (StudentDocument, "file_path", "student_docs", lambda r: r.school_id,
         lambda r: r.student_id),
    ]


def migrate_static_uploads(static_folder) -> dict:
    """Idempotent: rows already pointing at /files/ are untouched; a row
    whose old file is missing is left as-is and counted as missing."""
    from pathlib import Path
    from sqlalchemy import select
    static_root = Path(static_folder).resolve()
    report = {}
    for model, col, kind, school_of, owner_of in _legacy_targets():
        column = getattr(model, col)
        rows = db.session.execute(
            select(model).where(column.like("/static/uploads/%"))
            .execution_options(include_deleted=True)).scalars().all()
        moved = missing = 0
        for r in rows:
            rel = getattr(r, col)[len("/static/"):].split("?", 1)[0]
            src = (static_root / rel).resolve()
            school_id = school_of(r)
            if static_root not in src.parents or not src.is_file() or school_id is None:
                missing += 1
                continue
            setattr(r, col, fs.import_legacy_file(src, school_id, kind, owner_of(r)))
            moved += 1
        db.session.commit()
        report[f"{model.__tablename__}.{col}"] = {"moved": moved, "missing": missing}
    return report


@bp.cli.command("files-migrate-static")
def files_migrate_static_command():
    """Move files referenced as /static/uploads/... into UPLOAD_ROOT."""
    import json
    from flask import current_app
    import click
    click.echo(json.dumps(migrate_static_uploads(current_app.static_folder), indent=2))
