"""Ticket A1 — SubjectPrerequisite CRUD (admin page).

A minimal "grid" view: list every declared prerequisite; add / remove
inline. Enrolment-time warning is registered in `_check_prereq_warnings`
and read by the enrol route (added as an advisory flash, not a
hard-block, per ticket A1's v1 scope)."""

from flask import (
    abort, flash, jsonify, redirect, render_template, request, url_for,
)
from flask_login import current_user, login_required

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import Subject, SubjectPrerequisite


def _sid():
    return current_user.school_id


@bp.route("/subjects/prerequisites",
          methods=["GET", "POST"],
          endpoint="subject_prerequisites")
@login_required
@require_permission("academic_years", "view")
def subject_prerequisites():
    if request.method == "POST":
        return _handle_prereq_write()
    rows = (
        SubjectPrerequisite.query.filter_by(school_id=_sid())
        .join(Subject, Subject.id == SubjectPrerequisite.subject_id)
        .order_by(Subject.name).all()
    )
    subjects = (
        Subject.query.filter_by(school_id=_sid())
        .order_by(Subject.name).all()
    )
    return render_template(
        "academic/subject_prerequisites.html",
        rows=rows, subjects=subjects,
    )


def _handle_prereq_write():
    action = request.form.get("action", "add")
    if action == "delete":
        rid = request.form.get("id", type=int)
        row = SubjectPrerequisite.query.filter_by(
            id=rid, school_id=_sid()).first_or_404()
        db.session.delete(row); db.session.commit()
        flash("تم حذف المتطلب.", "success")
    else:
        subject_id = request.form.get("subject_id", type=int)
        requires_id = request.form.get("requires_subject_id", type=int)
        if not subject_id or not requires_id:
            flash("المادة والمتطلب مطلوبان.", "danger")
        elif subject_id == requires_id:
            flash("لا يمكن أن تكون المادة متطلبًا لنفسها.", "danger")
        else:
            existing = SubjectPrerequisite.query.filter_by(
                school_id=_sid(),
                subject_id=subject_id,
                requires_subject_id=requires_id,
            ).first()
            if not existing:
                db.session.add(SubjectPrerequisite(
                    school_id=_sid(),
                    subject_id=subject_id,
                    requires_subject_id=requires_id,
                    note=(request.form.get("note") or "").strip() or None,
                ))
                db.session.commit()
                flash("تم إضافة المتطلب.", "success")
    return redirect(url_for("academic.subject_prerequisites"))


def check_prereq_warnings(student, target_grade_id):
    """Ticket A1 — advisory check. Returns list of (subject_name,
    required_subject_name, reason) tuples for prerequisites the
    student hasn't cleared before enrolling into `target_grade_id`.

    "cleared" = the student passed the required subject in any prior
    enrollment (GradeEntry.value >= 60 as a v1 default threshold)."""
    from ...models import GradeEntry
    # v1 policy — scan every declared prerequisite for the school and
    # flag any whose required-subject the student hasn't passed. A
    # finer-grained "only warn about subjects taught in this grade"
    # cut can slot in later without changing this signature.
    prereqs = (
        SubjectPrerequisite.query.filter_by(school_id=student.school_id).all()
    )
    if not prereqs:
        return []
    # Collect the student's passed subjects from any prior enrollment.
    prior_eids = [e.id for e in student.enrollments if e.id]
    passed = set()
    if prior_eids:
        entries = (
            GradeEntry.query.filter(
                GradeEntry.enrollment_id.in_(prior_eids)
            ).all()
        )
        for ge in entries:
            v = float(ge.value or 0)
            if v >= 60 and getattr(ge, "subject_id", None):
                passed.add(ge.subject_id)
    warnings = []
    for p in prereqs:
        if p.requires_subject_id in passed:
            continue
        warnings.append((
            p.subject.name if p.subject else "?",
            p.required_subject.name if p.required_subject else "?",
            p.note,
        ))
    return warnings
