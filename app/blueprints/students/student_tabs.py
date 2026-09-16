"""Sprint 17 — additional student profile tabs.

Ticket #10: Health profile + incidents.
Ticket #11: Documents.
Ticket #12: Behavior incidents + actions.

Kept in a separate module to avoid ballooning routes.py — each ticket
gets its own section so future work is easy to locate.
"""
import os
import uuid
from datetime import datetime, date
from decimal import Decimal

from flask import (
    abort, current_app, flash, redirect, render_template, request, url_for,
)
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import (
    Student,
    StudentHealthProfile, HealthIncident,
    StudentDocument,
    BehaviorCategory, BehaviorIncident, BehaviorAction,
)


def _sid():
    return current_user.school_id


def _get_student(student_id):
    stu = Student.query.filter_by(id=student_id, school_id=_sid()).first()
    if not stu:
        abort(404)
    return stu


ALLOWED_DOC_EXT = {"pdf", "doc", "docx", "png", "jpg", "jpeg", "webp", "gif"}


# ─── Ticket #10 — Health ────────────────────────────────────────────

@bp.route("/<int:student_id>/health", methods=["GET", "POST"], endpoint="health_profile")
@login_required
@require_permission("students", "view")
def health_profile(student_id):
    student = _get_student(student_id)
    profile = student.health_profile
    if request.method == "POST":
        if profile is None:
            profile = StudentHealthProfile(school_id=_sid(), student_id=student.id)
            db.session.add(profile)
        for field in ("blood_type", "chronic_conditions", "allergies",
                      "regular_medications", "special_needs",
                      "emergency_instructions", "doctor_name", "doctor_phone",
                      "insurance_provider", "insurance_number"):
            setattr(profile, field, (request.form.get(field) or "").strip() or None)
        profile.updated_by_user_id = getattr(current_user, "id", None)
        db.session.commit()
        flash("تم حفظ السجل الصحي.", "success")
        return redirect(url_for("students.health_profile", student_id=student.id))
    return render_template(
        "students/health_profile.html",
        student=student, profile=profile,
        incidents=HealthIncident.query.filter_by(student_id=student.id)
            .order_by(HealthIncident.incident_date.desc()).limit(50).all(),
    )


@bp.route("/<int:student_id>/health/incident", methods=["POST"],
          endpoint="health_incident_add")
@login_required
@require_permission("students", "edit")
def health_incident_add(student_id):
    student = _get_student(student_id)
    when = request.form.get("incident_date")
    try:
        dt = datetime.fromisoformat(when) if when else datetime.now()
    except ValueError:
        dt = datetime.now()
    incident = HealthIncident(
        school_id=_sid(), student_id=student.id,
        incident_date=dt,
        incident_type=(request.form.get("incident_type") or "illness").strip(),
        description=(request.form.get("description") or "").strip(),
        action_taken=(request.form.get("action_taken") or "").strip() or None,
        guardian_notified=bool(request.form.get("guardian_notified")),
        referred_to_hospital=bool(request.form.get("referred_to_hospital")),
        recorded_by_user_id=getattr(current_user, "id", None),
    )
    if not incident.description:
        flash("وصف الحادث مطلوب.", "danger")
        return redirect(url_for("students.health_profile", student_id=student.id))
    if incident.guardian_notified:
        incident.notified_at = datetime.now()
    db.session.add(incident); db.session.commit()
    flash("تم تسجيل الحادث الصحي.", "success")
    return redirect(url_for("students.health_profile", student_id=student.id))


# ─── Ticket #11 — Documents ─────────────────────────────────────────

@bp.route("/<int:student_id>/documents", endpoint="documents")
@login_required
@require_permission("students", "view")
def documents(student_id):
    student = _get_student(student_id)
    items = (
        StudentDocument.query.filter_by(student_id=student.id)
        .order_by(StudentDocument.created_at.desc()).all()
    )
    return render_template("students/documents.html", student=student, documents=items)


@bp.route("/<int:student_id>/documents/upload", methods=["POST"], endpoint="document_upload")
@login_required
@require_permission("students", "edit")
def document_upload(student_id):
    student = _get_student(student_id)
    file = request.files.get("file")
    if not file or not file.filename:
        flash("اختر ملفاً للرفع.", "danger")
        return redirect(url_for("students.documents", student_id=student.id))
    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_DOC_EXT:
        flash(f"صيغة الملف .{ext} غير مدعومة.", "danger")
        return redirect(url_for("students.documents", student_id=student.id))
    safe = secure_filename(file.filename)
    unique = f"{uuid.uuid4().hex[:12]}_{safe}"
    subdir = os.path.join(current_app.static_folder, "uploads", "student_docs", str(student.id))
    os.makedirs(subdir, exist_ok=True)
    path = os.path.join(subdir, unique)
    file.save(path)

    doc = StudentDocument(
        school_id=_sid(), student_id=student.id,
        document_type=(request.form.get("document_type") or "other").strip(),
        title=(request.form.get("title") or "").strip() or None,
        file_path=url_for("static", filename=f"uploads/student_docs/{student.id}/{unique}"),
        file_size=os.path.getsize(path),
        mime_type=file.mimetype,
        document_number=(request.form.get("document_number") or "").strip() or None,
        issue_date=_parse_date(request.form.get("issue_date")),
        expiry_date=_parse_date(request.form.get("expiry_date")),
        notes=(request.form.get("notes") or "").strip() or None,
        uploaded_by_user_id=getattr(current_user, "id", None),
    )
    db.session.add(doc); db.session.commit()
    flash("تم رفع المستند.", "success")
    return redirect(url_for("students.documents", student_id=student.id))


@bp.route("/documents/<int:doc_id>/delete", methods=["POST"], endpoint="document_delete")
@login_required
@require_permission("students", "edit")
def document_delete(doc_id):
    doc = StudentDocument.query.get_or_404(doc_id)
    sid = doc.student_id
    # Try to remove the file too (best-effort).
    try:
        static_dir = current_app.static_folder or ""
        rel = doc.file_path.replace("/static/", "", 1)
        p = os.path.join(static_dir, rel)
        if os.path.isfile(p):
            os.remove(p)
    except Exception:
        pass
    db.session.delete(doc); db.session.commit()
    flash("تم حذف المستند.", "success")
    return redirect(url_for("students.documents", student_id=sid))


# ─── Ticket #12 — Behavior ──────────────────────────────────────────

@bp.route("/<int:student_id>/behavior", endpoint="behavior_home")
@login_required
@require_permission("students", "view")
def behavior_home(student_id):
    student = _get_student(student_id)
    incidents = (
        BehaviorIncident.query.filter_by(student_id=student.id)
        .order_by(BehaviorIncident.incident_date.desc()).limit(100).all()
    )
    total = sum(int(i.points or 0) for i in incidents)
    categories = (
        BehaviorCategory.query.filter_by(school_id=_sid(), is_active=True)
        .order_by(BehaviorCategory.name).all()
    )
    return render_template(
        "students/behavior.html",
        student=student, incidents=incidents, total=total, categories=categories,
    )


@bp.route("/<int:student_id>/behavior/add", methods=["POST"], endpoint="behavior_add")
@login_required
@require_permission("students", "edit")
def behavior_add(student_id):
    student = _get_student(student_id)
    cat = BehaviorCategory.query.filter_by(
        id=request.form.get("category_id", type=int),
        school_id=_sid(),
    ).first()
    if not cat:
        flash("اختر فئة سلوك صحيحة.", "danger")
        return redirect(url_for("students.behavior_home", student_id=student.id))
    d = _parse_date(request.form.get("incident_date")) or date.today()
    inc = BehaviorIncident(
        school_id=_sid(), student_id=student.id,
        category_id=cat.id,
        incident_date=d,
        description=(request.form.get("description") or "").strip() or cat.name,
        points=int(request.form.get("points") or cat.default_points or 0),
        reported_by_user_id=getattr(current_user, "id", None),
    )
    db.session.add(inc); db.session.commit()
    flash(f"تم تسجيل حادثة السلوك ({cat.name}).", "success")
    return redirect(url_for("students.behavior_home", student_id=student.id))


@bp.route("/behavior/categories", methods=["GET", "POST"], endpoint="behavior_categories")
@login_required
@require_permission("students", "edit")
def behavior_categories_page():
    """School-wide behaviour-category list. Admins add/toggle categories
    here; the student page picks from this list."""
    if request.method == "POST":
        cat = BehaviorCategory(
            school_id=_sid(),
            name=(request.form.get("name") or "").strip(),
            kind=(request.form.get("kind") or "negative").strip(),
            default_points=int(request.form.get("default_points") or 0),
            severity=(request.form.get("severity") or "medium").strip(),
        )
        if not cat.name:
            flash("اسم فئة السلوك مطلوب.", "danger")
        else:
            db.session.add(cat); db.session.commit()
            flash("تم إضافة الفئة.", "success")
        return redirect(url_for("students.behavior_categories"))
    items = (
        BehaviorCategory.query.filter_by(school_id=_sid())
        .order_by(BehaviorCategory.kind, BehaviorCategory.name).all()
    )
    return render_template("students/behavior_categories.html", categories=items)


# ─── local helper (parse date without importing from routes.py) ─────

def _parse_date(s):
    if not s:
        return None
    try:
        return date.fromisoformat(s.strip())
    except (ValueError, AttributeError):
        return None
