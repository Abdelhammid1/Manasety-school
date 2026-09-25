"""Phase-3 student lifecycle endpoints (tickets S1, S4, S5, S7).

- GET  /<sid>/360               — Student 360 view (uses services.student_360)
- GET  /<sid>/360.json          — same, JSON
- POST /enrollments/<eid>/graduate — S4 mark as graduated
- POST /enrollments/<eid>/exit-checklist — S5 save exit-interview data
- GET  /<sid>/id-card.pdf       — S7 printable ID card (falls back to
                                     HTML when reportlab isn't installed)"""

import base64
import io

from flask import (
    abort, current_app, flash, jsonify, redirect, render_template,
    request, url_for, Response,
)
from flask_login import current_user, login_required

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import Enrollment, Student
from ...services.student_360 import build_student_360


def _sid():
    return current_user.school_id


def _get_student(student_id):
    stu = Student.query.filter_by(id=student_id, school_id=_sid()).first()
    if not stu:
        abort(404)
    return stu


# ─── S1 — 360 ──────────────────────────────────────────────────────
@bp.route("/<int:student_id>/360", endpoint="student_360")
@login_required
@require_permission("students", "view")
def student_360(student_id):
    student = _get_student(student_id)
    data = build_student_360(student.id)
    return render_template("students/student_360.html",
                           student=student, data=data)


@bp.route("/<int:student_id>/360.json", endpoint="student_360_json")
@login_required
@require_permission("students", "view")
def student_360_json(student_id):
    student = _get_student(student_id)
    return jsonify(build_student_360(student.id))


# ─── S4 — Graduation ───────────────────────────────────────────────
@bp.route("/enrollments/<int:enrollment_id>/graduate",
          methods=["POST"], endpoint="graduate_enrollment")
@login_required
@require_permission("students", "edit")
def graduate_enrollment(enrollment_id):
    from datetime import date as _date
    e = Enrollment.query.filter_by(
        id=enrollment_id, school_id=_sid()).first_or_404()
    if e.status == "graduated":
        flash("هذا القيد مسجّل بالفعل كخريج.", "info")
        return redirect(url_for("students.student_detail",
                                student_id=e.student_id))
    # Very light "requirements met" check — final_result must be 'pass'.
    # A stricter rulebook can slot in later without touching this route.
    if e.final_result != "pass":
        if request.form.get("confirm_force") != "1":
            flash(
                "النتيجة النهائية ليست 'ناجح' — أكّد التخرج يدويًا لو مسموح.",
                "warning",
            )
            return redirect(url_for("students.student_detail",
                                    student_id=e.student_id))
    e.status = "graduated"
    e.status_changed_at = _date.today()
    e.status_reason = (request.form.get("reason") or "").strip() or None
    e.graduation_date = _date.today()
    db.session.commit()
    flash("تم اعتماد التخرج.", "success")
    return redirect(url_for("students.student_detail",
                            student_id=e.student_id))


# ─── S5 — Exit interview ───────────────────────────────────────────
@bp.route("/enrollments/<int:enrollment_id>/exit-checklist",
          methods=["POST"], endpoint="save_exit_checklist")
@login_required
@require_permission("students", "edit")
def save_exit_checklist(enrollment_id):
    """Persist the exit-interview checklist. The form submits an
    arbitrary JSON blob (docs returned, dues cleared, etc.) which we
    store on Enrollment.exit_checklist. Freeform so the school can
    iterate on the list without a migration."""
    e = Enrollment.query.filter_by(
        id=enrollment_id, school_id=_sid()).first_or_404()
    checklist = {}
    for k in (
        "docs_returned", "financial_cleared", "belongings_returned",
        "gate_pass_signed", "notes",
    ):
        v = request.form.get(k)
        if k == "notes":
            checklist[k] = (v or "").strip() or None
        else:
            checklist[k] = (v == "1")
    # Optional structured reason picker.
    reason = (request.form.get("exit_reason") or "").strip() or None
    if reason:
        checklist["reason"] = reason
    e.exit_checklist = checklist
    db.session.commit()
    flash("تم حفظ خطوات الخروج.", "success")
    return redirect(url_for("students.student_detail",
                            student_id=e.student_id))


# ─── S7 — Printable ID card ────────────────────────────────────────
@bp.route("/<int:student_id>/id-card", endpoint="student_id_card")
@login_required
@require_permission("students", "view")
def student_id_card(student_id):
    """Printable ID card. Renders as HTML with print CSS; the print
    button in the browser handles PDF export cleanly. Includes a QR
    encoding the permanent_code so a phone scan reveals the student."""
    student = _get_student(student_id)
    qr_svg = _qr_svg_for(student.permanent_code)
    return render_template(
        "students/id_card.html",
        student=student, qr_svg=qr_svg,
    )


def _qr_svg_for(text: str) -> str:
    """Best-effort QR SVG. Uses the `segno` library when available;
    otherwise renders a plain-text fallback. The card template shows
    the fallback as a code without an image so the print stays legible."""
    try:
        import segno
        qr = segno.make(text, error="m")
        buf = io.StringIO()
        qr.save(buf, kind="svg", scale=6, border=0)
        return buf.getvalue()
    except Exception:
        return f'<div class="fallback-qr">{text}</div>'
