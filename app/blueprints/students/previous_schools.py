"""Ticket S3 — Previous Schools CRUD (student's academic history
before joining Manasety)."""


from flask import (
    abort, current_app, flash, redirect, request, url_for,
)
from flask_login import current_user, login_required

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import PreviousSchool, Student


def _sid() -> int:
    # SAAS-005 — central tenant source of truth. One function
    # here so no blueprint reads current_user.school_id directly.
    from ...services.tenancy import current_school_id
    return current_school_id()


def _get_student(student_id):
    stu = Student.query.filter_by(id=student_id, school_id=_sid()).first()
    if not stu:
        abort(404)
    return stu


@bp.route("/<hid:student_id>/previous-schools/add", methods=["POST"],
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
        from ...services import file_storage as fs
        try:
            row.document_url = fs.save(f, "previous_school", student.id)
        except fs.UploadRejected as e:
            flash(f"لم يُحفظ المرفق: {e}", "warning")
    db.session.commit()
    flash("تمت إضافة المدرسة السابقة.", "success")
    return redirect(url_for("students.student_detail", student_id=student.id))


@bp.route("/previous-schools/<hid:row_id>/delete", methods=["POST"],
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
