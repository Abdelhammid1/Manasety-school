"""Sprint 17 — Ticket #15 (Grading scales) + Ticket #16 (Rubrics) +
Ticket #18 (Transcript snapshots). Adds routes on the results blueprint
without touching the legacy grade-entry flow."""
import json
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from flask import (
    flash, redirect, render_template, request, url_for,
)
from flask_login import current_user, login_required

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import (
    GradingScale, GradingScaleLevel,
    Rubric, RubricCriterion,
    TranscriptSnapshot, YearResult, Student, Enrollment,
    Subject,
)


def _sid():
    return current_user.school_id


# ─── Ticket #15 — Grading scales ────────────────────────────────────

@bp.route("/scales", endpoint="scales_list")
@login_required
@require_permission("results", "view")
def scales_list():
    scales = (
        GradingScale.query.filter_by(school_id=_sid())
        .order_by(GradingScale.is_default.desc(), GradingScale.name).all()
    )
    return render_template("results/scales_list.html", scales=scales)


@bp.route("/scales/new", methods=["GET", "POST"], endpoint="scale_new")
@login_required
@require_permission("results", "edit")
def scale_new():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("اسم السلم مطلوب.", "danger")
            return redirect(url_for("results.scale_new"))
        s = GradingScale(
            school_id=_sid(), name=name,
            scale_type=(request.form.get("scale_type") or "numeric").strip(),
            applies_to_stage=(request.form.get("applies_to_stage") or "").strip() or None,
            is_default=bool(request.form.get("is_default")),
        )
        if s.is_default:
            # only one default per school — flip everyone else off
            GradingScale.query.filter_by(school_id=_sid(), is_default=True).update({"is_default": False})
        db.session.add(s); db.session.commit()
        flash(f"تم إنشاء سلم درجات ({s.name}).", "success")
        return redirect(url_for("results.scale_edit", scale_id=s.id))
    return render_template("results/scale_form.html", scale=None)


@bp.route("/scales/<int:scale_id>/edit", methods=["GET", "POST"], endpoint="scale_edit")
@login_required
@require_permission("results", "edit")
def scale_edit(scale_id):
    scale = GradingScale.query.filter_by(id=scale_id, school_id=_sid()).first_or_404()
    if request.method == "POST":
        # form has repeat rows: label[], min[], max[], gpa[], is_passing[], color[]
        for l in list(scale.levels):
            db.session.delete(l)
        db.session.flush()
        labels = request.form.getlist("label")
        mins = request.form.getlist("min")
        maxs = request.form.getlist("max")
        gpas = request.form.getlist("gpa")
        passing = set(request.form.getlist("is_passing"))
        colors = request.form.getlist("color")
        for i, lbl in enumerate(labels):
            lbl = (lbl or "").strip()
            if not lbl: continue
            try:
                mn = Decimal(mins[i] or "0"); mx = Decimal(maxs[i] or "0")
            except Exception:
                continue
            gpa = None
            if i < len(gpas) and gpas[i]:
                try: gpa = Decimal(gpas[i])
                except Exception: gpa = None
            db.session.add(GradingScaleLevel(
                scale_id=scale.id, label=lbl, min_score=mn, max_score=mx,
                gpa_points=gpa, is_passing=(str(i) in passing),
                color=(colors[i] if i < len(colors) else "") or None,
                order_index=i,
            ))
        db.session.commit()
        flash("تم حفظ سلم الدرجات.", "success")
        return redirect(url_for("results.scales_list"))
    return render_template("results/scale_form.html", scale=scale)


@bp.route("/scales/<int:scale_id>/delete", methods=["POST"], endpoint="scale_delete")
@login_required
@require_permission("results", "delete")
def scale_delete(scale_id):
    s = GradingScale.query.filter_by(id=scale_id, school_id=_sid()).first_or_404()
    db.session.delete(s); db.session.commit()
    flash("تم حذف سلم الدرجات.", "success")
    return redirect(url_for("results.scales_list"))


# ─── Ticket #16 — Rubrics ───────────────────────────────────────────

@bp.route("/rubrics", endpoint="rubrics_list")
@login_required
@require_permission("results", "view")
def rubrics_list():
    items = (
        Rubric.query.filter_by(school_id=_sid())
        .order_by(Rubric.created_at.desc()).all()
    )
    return render_template("results/rubrics_list.html", rubrics=items)


@bp.route("/rubrics/new", methods=["GET", "POST"], endpoint="rubric_new")
@login_required
@require_permission("results", "edit")
def rubric_new():
    subjects = Subject.query.filter_by(school_id=_sid()).order_by(Subject.name).all()
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        if not title:
            flash("عنوان الروبريك مطلوب.", "danger")
            return redirect(url_for("results.rubric_new"))
        r = Rubric(
            school_id=_sid(),
            created_by_id=getattr(current_user, "id", None),
            title=title,
            description=(request.form.get("description") or "").strip(),
            subject_id=request.form.get("subject_id", type=int) or None,
            is_template=True,
        )
        db.session.add(r); db.session.commit()
        return redirect(url_for("results.rubric_edit", rubric_id=r.id))
    return render_template("results/rubric_form.html", rubric=None, subjects=subjects)


@bp.route("/rubrics/<int:rubric_id>/edit", methods=["GET", "POST"], endpoint="rubric_edit")
@login_required
@require_permission("results", "edit")
def rubric_edit(rubric_id):
    r = Rubric.query.filter_by(id=rubric_id, school_id=_sid()).first_or_404()
    subjects = Subject.query.filter_by(school_id=_sid()).order_by(Subject.name).all()
    if request.method == "POST":
        r.title = (request.form.get("title") or r.title).strip()
        r.description = (request.form.get("description") or "").strip()
        r.subject_id = request.form.get("subject_id", type=int) or None
        # Rewrite criteria
        for c in list(r.criteria):
            db.session.delete(c)
        db.session.flush()
        titles = request.form.getlist("crit_title")
        descs = request.form.getlist("crit_desc")
        weights = request.form.getlist("crit_weight")
        maxes = request.form.getlist("crit_max")
        for i, t in enumerate(titles):
            t = (t or "").strip()
            if not t: continue
            db.session.add(RubricCriterion(
                rubric_id=r.id, title=t,
                description=(descs[i] if i < len(descs) else "") or None,
                weight=Decimal(weights[i] or "0") if i < len(weights) else Decimal(0),
                max_score=Decimal(maxes[i] or "100") if i < len(maxes) else Decimal(100),
                order_index=i,
            ))
        db.session.commit()
        flash("تم حفظ الروبريك.", "success")
        return redirect(url_for("results.rubrics_list"))
    return render_template("results/rubric_form.html", rubric=r, subjects=subjects)


@bp.route("/rubrics/<int:rubric_id>/delete", methods=["POST"], endpoint="rubric_delete")
@login_required
@require_permission("results", "delete")
def rubric_delete(rubric_id):
    r = Rubric.query.filter_by(id=rubric_id, school_id=_sid()).first_or_404()
    db.session.delete(r); db.session.commit()
    flash("تم حذف الروبريك.", "success")
    return redirect(url_for("results.rubrics_list"))


# ─── Ticket #18 — Transcript ────────────────────────────────────────

def _student_year_results(student_id):
    """YearResult rows for this student, ordered newest-first via the
    Enrollment.year_id join."""
    return (
        YearResult.query.filter_by(school_id=_sid())
        .join(Enrollment, Enrollment.id == YearResult.enrollment_id)
        .filter(Enrollment.student_id == student_id)
        .order_by(Enrollment.year_id.desc()).all()
    )


@bp.route("/transcript/<int:student_id>", endpoint="transcript_view")
@login_required
@require_permission("results", "view")
def transcript_view(student_id):
    student = Student.query.filter_by(id=student_id, school_id=_sid()).first_or_404()
    results = _student_year_results(student.id)
    snapshots = (
        TranscriptSnapshot.query.filter_by(student_id=student.id)
        .order_by(TranscriptSnapshot.issued_at.desc()).all()
    )
    return render_template(
        "results/transcript.html",
        student=student, results=results, snapshots=snapshots,
    )


@bp.route("/transcript/<int:student_id>/snapshot", methods=["POST"],
          endpoint="transcript_snapshot")
@login_required
@require_permission("results", "edit")
def transcript_snapshot(student_id):
    """Freeze a copy of every YearResult for this student into a JSON
    payload — used when the school issues an official transcript for
    transfer or an external body."""
    student = Student.query.filter_by(id=student_id, school_id=_sid()).first_or_404()
    results = _student_year_results(student.id)
    payload = {
        "student_id": student.id,
        "student_name": student.full_name,
        "years": [
            {
                "enrollment_id": r.enrollment_id,
                "year_id": r.enrollment.year_id if r.enrollment else None,
                "year_name": (r.enrollment.year.name
                              if r.enrollment and r.enrollment.year else None),
                "average": str(r.average) if r.average is not None else None,
                "status": r.status,
            }
            for r in results
        ],
    }
    snap = TranscriptSnapshot(
        school_id=_sid(), student_id=student.id,
        issued_by_user_id=getattr(current_user, "id", None),
        content=payload,
        serial_number="TR-" + uuid4().hex[:10].upper(),
        purpose=(request.form.get("purpose") or "أرشيف").strip(),
    )
    db.session.add(snap); db.session.commit()
    flash(f"تم إصدار كشف تراكمي بالرقم {snap.serial_number}.", "success")
    return redirect(url_for("results.transcript_view", student_id=student.id))
