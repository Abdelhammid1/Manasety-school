"""Ticket #16 grading — score a Submission against its Assignment's
Rubric. Uses RubricScore rows already in the schema (submission_id set).
"""
from decimal import Decimal
from datetime import datetime, timezone

from flask import (
    abort, flash, redirect, render_template, request, url_for,
)
from flask_login import current_user, login_required

from . import bp
from ...extensions import db
from ...models import (
    CourseAssignment, Submission, Rubric, RubricCriterion, RubricScore, Student,
)


@bp.route("/submissions/<int:submission_id>/rubric-grade", methods=["GET", "POST"],
          endpoint="submission_rubric_grade")
@login_required
def submission_rubric_grade(submission_id):
    """Grade a Submission against every RubricCriterion. Weights are
    honoured — the final Submission.score is the weighted sum of each
    criterion's (score / max) × weight × assignment.max_score / 100.
    """
    sub = Submission.query.get_or_404(submission_id)
    a = sub.assignment
    if a is None or a.rubric_id is None:
        flash("هذا الواجب لا يستخدم روبريك — استخدم شاشة التصحيح العادية.", "warning")
        return redirect(url_for("lms.assignment_detail", aid=a.id if a else 0))
    rubric = Rubric.query.get(a.rubric_id)
    if rubric is None:
        abort(404)

    existing = {r.criterion_id: r for r in sub.rubric_scores} \
        if hasattr(sub, "rubric_scores") else {
            r.criterion_id: r
            for r in RubricScore.query.filter_by(submission_id=sub.id).all()
        }

    if request.method == "POST":
        total_weight = Decimal(0)
        weighted = Decimal(0)
        _now = datetime.now(timezone.utc)
        for c in rubric.criteria:
            score_raw = request.form.get(f"score_{c.id}")
            comment = (request.form.get(f"comment_{c.id}") or "").strip() or None
            if score_raw is None or score_raw == "":
                continue
            try:
                score = Decimal(score_raw)
            except Exception:
                continue
            row = existing.get(c.id)
            if row is None:
                row = RubricScore(criterion_id=c.id, submission_id=sub.id)
                db.session.add(row)
            row.score = score
            row.comment = comment
            row.graded_by_id = getattr(current_user, "id", None)
            row.graded_at = _now
            # Accumulate weighted total.
            if c.max_score and c.weight:
                weighted += (score / Decimal(str(c.max_score))) * Decimal(str(c.weight))
                total_weight += Decimal(str(c.weight))

        # Final score = weighted / total_weight × assignment.max_score.
        if total_weight > 0:
            final = (weighted / total_weight) * Decimal(str(a.max_score or 100))
            sub.score = final.quantize(Decimal("0.01"))
        sub.feedback = (request.form.get("feedback") or "").strip()
        sub.graded_by_id = getattr(current_user, "id", None)
        sub.graded_at = _now
        db.session.commit()
        flash(f"تم التصحيح — الدرجة النهائية: {sub.score}.", "success")
        return redirect(url_for("lms.assignment_detail", aid=a.id))

    student = Student.query.get(sub.student_id)
    return render_template(
        "lms/submission_rubric_grade.html",
        submission=sub, student=student, assignment=a,
        rubric=rubric, existing=existing,
    )
