"""Ticket S3 — Previous Schools CRUD (student's academic history
before joining Manasety)."""

import os
import uuid as _uuid

from flask import (
    abort, current_app, flash, redirect, request, url_for,
)
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import PreviousSchool, Student


def _sid():
    return current_user.school_id


def _get_student(student_id):
    stu = Student.query.filter_by(id=student_id, school_id=_sid()).first()
    if not stu:
        abort(404)
    return stu


@bp.route("/<int:student_id>/previous-schools/add", methods=["POST"],
          endpoint="previous_school_add")
@login_required
@require_permission("students", "edit")
def previous_school_add(student_id):
    student = _get_student(student_id)
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("اسم المدرسة السابقة مطلوب.", "danger")
        return redirect(url_for("students.student_detail", student_id=student.id))
    row = PreviousSchool(
        school_id=_sid(), student_id=student.id,
        name=name,
        city=(request.form.get("city") or "").strip() or None,
        from_year=(request.form.get("from_year") or "").strip() or None,
        to_year=(request.form.get("to_year") or "").strip() or None,
        reason=(request.form.get("reason") or "").strip() or None,
    )
    db.session.add(row)
    db.session.flush()

    # Optional attached transcript / school certificate.
    f = request.files.get("document")
    if f and f.filename:
        ext = f.filename.rsplit(".", 1)[-1].lower()
        if ext in {"pdf", "png", "jpg", "jpeg", "webp"}:
            safe = secure_filename(f.filename)
            unique = f"{_uuid.uuid4().hex[:12]}_{safe}"
            subdir = os.path.join(
                current_app.static_folder, "uploads",
                "students", str(student.id), "previous",
            )
            os.makedirs(subdir, exist_ok=True)
            f.save(os.path.join(subdir, unique))
            row.document_url = url_for(
                "static",
                filename=f"uploads/students/{student.id}/previous/{unique}",
            )
    db.session.commit()
    flash("تمت إضافة المدرسة السابقة.", "success")
    return redirect(url_for("students.student_detail", student_id=student.id))


@bp.route("/previous-schools/<int:row_id>/delete", methods=["POST"],
          endpoint="previous_school_delete")
@login_required
@require_permission("students", "edit")
def previous_school_delete(row_id):
    row = PreviousSchool.query.filter_by(
        id=row_id, school_id=_sid()).first_or_404()
    sid = row.student_id
    db.session.delete(row); db.session.commit()
    flash("تم حذف السجل.", "success")
    return redirect(url_for("students.student_detail", student_id=sid))
