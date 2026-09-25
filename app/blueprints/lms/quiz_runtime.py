"""Phase-2 quiz-runtime endpoints (tickets #10, #11, #13, #19).

  · POST /quizzes/attempts/<id>/tab-switch   — bump tab_switch_count.
  · POST /quizzes/attempts/<id>/flag         — toggle a flagged question.
  · POST /quizzes/attempts/<id>/autosave     — persist single answer.
  · GET  /quizzes/<qid>/live                 — teacher live monitor page.
  · GET  /quizzes/<qid>/live.json            — polling data source.

Kept separate so the `views.py` monolith doesn't grow further; each
endpoint is 200-safe and JSON-only where the caller is JS."""

from datetime import datetime, timezone
from decimal import Decimal

from flask import abort, jsonify, render_template, request
from flask_login import current_user, login_required

from . import bp
from ...extensions import csrf, db
from ...models import (
    Answer, Choice, Question, QuizAttempt, Student,
    lms_attempt_flagged_questions,
)
from ._helpers import _normalize_short_answer


def _own_attempt_or_403(attempt_id):
    attempt = QuizAttempt.query.get_or_404(attempt_id)
    # Only the student that owns it may write. Teachers can *view*
    # (see live monitor), but write-endpoints stay student-only.
    uid = getattr(current_user, "id", None)
    stu = None
    if uid and hasattr(Student, "user_id"):
        stu = Student.query.filter_by(user_id=uid).first()
    if not stu or attempt.student_id != stu.id:
        abort(403)
    if attempt.submitted_at is not None:
        abort(409)  # already submitted, no more writes
    return attempt


@bp.route("/quizzes/attempts/<int:attempt_id>/tab-switch",
          methods=["POST"], endpoint="attempt_tab_switch")
@csrf.exempt  # navigator.sendBeacon can't add X-CSRFToken header
@login_required
def attempt_tab_switch(attempt_id):
    """Ticket #10 — record one tab switch on the attempt.

    Called via `navigator.sendBeacon`, which fires reliably during
    `visibilitychange` (a normal fetch can be canceled by the page
    unload). Beacon POSTs carry the session cookie but can't add
    custom headers — CSRF is exempted here because the write is
    idempotent (bumps an integer) and the session cookie already
    binds the request to a specific student. Ownership is verified
    against `_own_attempt_or_403`."""
    attempt = _own_attempt_or_403(attempt_id)
    attempt.tab_switch_count = (attempt.tab_switch_count or 0) + 1
    db.session.commit()
    return jsonify({"count": attempt.tab_switch_count})


@bp.route("/quizzes/attempts/<int:attempt_id>/flag",
          methods=["POST"], endpoint="attempt_flag")
@login_required
def attempt_flag(attempt_id):
    """Ticket #11 — toggle a flagged question on this attempt.

    Accepts `question_id` as either JSON body field or form field."""
    attempt = _own_attempt_or_403(attempt_id)
    body = request.get_json(silent=True) or request.form
    try:
        qid = int(body.get("question_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "question_id required"}), 400
    q = Question.query.get_or_404(qid)
    if q.quiz_id != attempt.quiz_id:
        abort(400)
    # Toggle by walking the M:N table directly (avoids a second query).
    existing = db.session.execute(
        lms_attempt_flagged_questions.select().where(
            (lms_attempt_flagged_questions.c.attempt_id == attempt.id) &
            (lms_attempt_flagged_questions.c.question_id == q.id)
        )
    ).first()
    if existing:
        db.session.execute(
            lms_attempt_flagged_questions.delete().where(
                (lms_attempt_flagged_questions.c.attempt_id == attempt.id) &
                (lms_attempt_flagged_questions.c.question_id == q.id)
            )
        )
        flagged = False
    else:
        db.session.execute(
            lms_attempt_flagged_questions.insert().values(
                attempt_id=attempt.id, question_id=q.id,
            )
        )
        flagged = True
    db.session.commit()
    return jsonify({"flagged": flagged})


@bp.route("/quizzes/attempts/<int:attempt_id>/autosave",
          methods=["POST"], endpoint="attempt_autosave")
@login_required
def attempt_autosave(attempt_id):
    """Ticket #13 — persist a single answer without finalizing the attempt.

    Body accepts either form-data or JSON with fields
        question_id: int
        choice_id:   int  (mcq/tf)
        choice_ids:  comma-separated ints (multi)
        text:        str  (short/essay)
    The response is minimal: {saved: true}."""
    attempt = _own_attempt_or_403(attempt_id)
    body = request.get_json(silent=True) or request.form
    try:
        qid = int(body.get("question_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "question_id required"}), 400
    q = Question.query.get_or_404(qid)
    if q.quiz_id != attempt.quiz_id:
        abort(400)

    ans = Answer.query.filter_by(
        attempt_id=attempt.id, question_id=q.id
    ).first()
    if ans is None:
        ans = Answer(attempt_id=attempt.id, question_id=q.id)
        db.session.add(ans)

    if q.kind in ("mcq", "tf"):
        raw = body.get("choice_id")
        ans.choice_id = int(raw) if raw not in (None, "", "None") else None
        ans.text_answer = ""
    elif q.kind == "multi":
        raw = body.get("choice_ids") or ""
        if isinstance(raw, (list, tuple)):
            picked = [str(x) for x in raw if str(x).isdigit()]
        else:
            picked = [x for x in str(raw).split(",") if x.strip().isdigit()]
        ans.choice_id = None
        ans.text_answer = ",".join(sorted(picked))
    else:
        ans.choice_id = None
        ans.text_answer = (body.get("text") or "").strip()

    # Draft answers stay ungraded (`is_correct=None`); quiz_submit will
    # do the final grading pass on the whole set.
    ans.is_correct = None
    ans.awarded_points = None
    db.session.commit()
    return jsonify({"saved": True})


# ── Ticket #19 — Live monitor ───────────────────────────────────────
@bp.route("/quizzes/<int:qid>/live", endpoint="quiz_live_monitor")
@login_required
def quiz_live_monitor(qid):
    role = getattr(getattr(current_user, "role", None), "name", None)
    if role not in ("admin", "teacher"):
        abort(403)
    from ...models import Quiz
    quiz = Quiz.query.get_or_404(qid)
    if quiz.course.school_id != current_user.school_id:
        abort(403)
    return render_template("lms/quiz_live_monitor.html", quiz=quiz)


@bp.route("/quizzes/<int:qid>/live.json", endpoint="quiz_live_monitor_json")
@login_required
def quiz_live_monitor_json(qid):
    role = getattr(getattr(current_user, "role", None), "name", None)
    if role not in ("admin", "teacher"):
        abort(403)
    from ...models import Quiz
    quiz = Quiz.query.get_or_404(qid)
    if quiz.course.school_id != current_user.school_id:
        abort(403)

    attempts = (
        QuizAttempt.query.filter_by(quiz_id=quiz.id)
        .order_by(QuizAttempt.started_at.desc()).limit(200).all()
    )
    total_qs = len(quiz.questions)
    rows = []
    for a in attempts:
        answered = Answer.query.filter(
            Answer.attempt_id == a.id,
            (Answer.choice_id.isnot(None)) | (Answer.text_answer != ""),
        ).count()
        stu = Student.query.get(a.student_id)
        rows.append({
            "attempt_id":  a.id,
            "student":     (stu.full_name if stu else f"طالب #{a.student_id}"),
            "started_at":  a.started_at.isoformat() if a.started_at else None,
            "submitted":   a.submitted_at is not None,
            "progress":    (int(answered / total_qs * 100) if total_qs else 0),
            "answered":    answered,
            "total_qs":    total_qs,
            "tab_switches": a.tab_switch_count or 0,
        })
    return jsonify({"rows": rows, "total_qs": total_qs})
