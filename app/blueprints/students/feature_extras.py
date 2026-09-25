"""Students Phase-3 quick-point endpoints (tickets S6, S8, S10, S11, S12).

Each route is school-scoped through _sid() and gated on the students
"edit" permission (except sibling detection which is a "view" op)."""

import os
import uuid as _uuid
from datetime import datetime

from flask import (
    abort, current_app, flash, jsonify, redirect, request, url_for,
)
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import (
    Guardian, Student, StudentGuardian, StudentNote, StudentTag,
)


def _sid():
    return current_user.school_id


def _get_student(student_id):
    stu = Student.query.filter_by(id=student_id, school_id=_sid()).first()
    if not stu:
        abort(404)
    return stu


# ─── S6 — Photo upload ─────────────────────────────────────────────
@bp.route("/<int:student_id>/photo", methods=["POST"],
          endpoint="student_photo_upload")
@login_required
@require_permission("students", "edit")
def student_photo_upload(student_id):
    student = _get_student(student_id)
    f = request.files.get("photo")
    if not f or not f.filename:
        flash("لم يتم رفع أي صورة.", "warning")
        return redirect(url_for("students.student_detail", student_id=student.id))
    ext = f.filename.rsplit(".", 1)[-1].lower()
    if ext not in {"png", "jpg", "jpeg", "webp", "gif"}:
        flash(f"صيغة الصورة .{ext} غير مدعومة.", "danger")
        return redirect(url_for("students.student_detail", student_id=student.id))
    safe = secure_filename(f.filename)
    unique = f"{_uuid.uuid4().hex[:12]}_{safe}"
    subdir = os.path.join(current_app.static_folder, "uploads",
                         "students", str(student.id))
    os.makedirs(subdir, exist_ok=True)
    f.save(os.path.join(subdir, unique))
    student.photo_url = url_for(
        "static", filename=f"uploads/students/{student.id}/{unique}"
    )
    db.session.commit()
    flash("تم تحديث الصورة.", "success")
    return redirect(url_for("students.student_detail", student_id=student.id))


# ─── S8 — Sibling detection ────────────────────────────────────────
@bp.route("/<int:student_id>/siblings.json", endpoint="student_siblings_json")
@login_required
@require_permission("students", "view")
def student_siblings_json(student_id):
    """Return every student that shares at least one Guardian with
    the target student. Used by the profile page + auto-fed into
    DiscountType.auto_rule for sibling discounts."""
    student = _get_student(student_id)
    guardian_ids = [l.guardian_id for l in student.guardian_links]
    if not guardian_ids:
        return jsonify({"siblings": []})
    rows = (
        db.session.query(Student)
        .join(StudentGuardian, StudentGuardian.student_id == Student.id)
        .filter(
            StudentGuardian.guardian_id.in_(guardian_ids),
            Student.id != student.id,
            Student.school_id == _sid(),
        ).distinct().all()
    )
    return jsonify({
        "siblings": [
            {"id": s.id,
             "full_name": s.full_name,
             "permanent_code": s.permanent_code}
            for s in rows
        ],
    })


def count_siblings(student):
    """Ticket S8 helper — expose the sibling count so the fee-schedule
    engine can drive DiscountType.auto_rule='sibling_count_2/3/...'
    without hitting the JSON endpoint."""
    if student is None:
        return 0
    ids = [l.guardian_id for l in student.guardian_links]
    if not ids:
        return 0
    return (
        db.session.query(Student.id)
        .join(StudentGuardian, StudentGuardian.student_id == Student.id)
        .filter(
            StudentGuardian.guardian_id.in_(ids),
            Student.id != student.id,
            Student.school_id == student.school_id,
        ).distinct().count()
    )


# ─── S10 — StudentNote timeline ────────────────────────────────────
@bp.route("/<int:student_id>/notes/add", methods=["POST"],
          endpoint="student_note_add")
@login_required
@require_permission("students", "edit")
def student_note_add(student_id):
    student = _get_student(student_id)
    body = (request.form.get("body") or "").strip()
    if not body:
        flash("نص الملاحظة مطلوب.", "danger")
        return redirect(url_for("students.student_detail", student_id=student.id))
    n = StudentNote(school_id=_sid(), student_id=student.id,
                    author_id=getattr(current_user, "id", None),
                    body=body)
    db.session.add(n)
    db.session.commit()
    flash("تمت إضافة الملاحظة.", "success")
    return redirect(url_for("students.student_detail", student_id=student.id))


@bp.route("/notes/<int:note_id>/delete", methods=["POST"],
          endpoint="student_note_delete")
@login_required
@require_permission("students", "edit")
def student_note_delete(note_id):
    n = StudentNote.query.filter_by(id=note_id, school_id=_sid()).first_or_404()
    sid = n.student_id
    db.session.delete(n)
    db.session.commit()
    flash("تم حذف الملاحظة.", "success")
    return redirect(url_for("students.student_detail", student_id=sid))


# ─── S11 — StudentTag CRUD + attach/detach ──────────────────────────
@bp.route("/tags/new", methods=["POST"], endpoint="student_tag_new")
@login_required
@require_permission("students", "edit")
def student_tag_new():
    name = (request.form.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    existing = StudentTag.query.filter_by(school_id=_sid(), name=name).first()
    if existing:
        return jsonify({"id": existing.id, "name": existing.name,
                        "color": existing.color, "existed": True})
    t = StudentTag(school_id=_sid(), name=name,
                   color=(request.form.get("color") or "").strip() or None)
    db.session.add(t); db.session.commit()
    return jsonify({"id": t.id, "name": t.name, "color": t.color})


@bp.route("/<int:student_id>/tags/attach", methods=["POST"],
          endpoint="student_tag_attach")
@login_required
@require_permission("students", "edit")
def student_tag_attach(student_id):
    student = _get_student(student_id)
    tag_id = request.form.get("tag_id", type=int)
    tag = StudentTag.query.filter_by(id=tag_id, school_id=_sid()).first_or_404()
    if tag not in student.tags:
        student.tags.append(tag)
        db.session.commit()
    if request.headers.get("Accept") == "application/json":
        return jsonify({"ok": True})
    return redirect(url_for("students.student_detail", student_id=student.id))


@bp.route("/<int:student_id>/tags/detach", methods=["POST"],
          endpoint="student_tag_detach")
@login_required
@require_permission("students", "edit")
def student_tag_detach(student_id):
    student = _get_student(student_id)
    tag_id = request.form.get("tag_id", type=int)
    tag = StudentTag.query.filter_by(id=tag_id, school_id=_sid()).first_or_404()
    if tag in student.tags:
        student.tags.remove(tag)
        db.session.commit()
    if request.headers.get("Accept") == "application/json":
        return jsonify({"ok": True})
    return redirect(url_for("students.student_detail", student_id=student.id))
