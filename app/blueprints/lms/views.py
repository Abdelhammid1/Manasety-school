"""LMS hubs — assignments, quizzes, announcements + full submission + quiz-take
+ auto-grader. No static demo data — every list, form, and result comes from
real DB rows scoped to the current user's school (and, where applicable, their
Student record)."""
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal


def _tz_safe_now(reference=None):
    """Return a `now` datetime whose tz-awareness matches `reference`.

    Postgres columns declared as DateTime(timezone=True) come back as
    tz-aware; SQLite gives us naive datetimes. Comparing the two raises
    'can't compare offset-naive and offset-aware datetimes', which is the
    crash the assignment_detail 500 traces back to on the prod server.
    This helper picks the right flavor of 'now' for a given column value.
    """
    now = datetime.now(timezone.utc)
    if reference is None or reference.tzinfo is not None:
        return now
    return now.replace(tzinfo=None)


def _past_due(due_at):
    """True iff a due-date has passed, safe against tz mismatch."""
    if due_at is None:
        return False
    return _tz_safe_now(due_at) > due_at

from flask import (
    abort, current_app, flash, jsonify, redirect, render_template, request, url_for,
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from . import bp
from ...extensions import db
from ...models import (
    Announcement, Course, CourseAssignment, Quiz, Question, Choice,
    QuizAttempt, Answer, Section, Student, Submission,
    BankQuestion, BankChoice,
    AssignmentQuestion, AssignmentChoice, AssignmentAnswer,
    AssignmentTemplate, AssignmentTemplateQuestion, AssignmentTemplateChoice,
    AssessmentTemplate, AssessmentTemplateItem,
    Subject, Grade, AcademicYear, Term, Unit, Lesson,
)


ALLOWED_SUBMISSION_EXT = {"pdf", "doc", "docx", "png", "jpg", "jpeg", "zip", "txt"}


def _current_student():
    """Resolve the logged-in user → Student row via an EXPLICIT link.

    The old dev-fallback (return the school's first Student when no
    link exists) leaked one student's timeline into every unlinked
    account — bug #16. Return None instead and let callers show a
    "account is not linked to a student" message."""
    uid = getattr(current_user, "id", None)
    if not uid:
        return None
    if hasattr(Student, "user_id"):
        s = Student.query.filter_by(user_id=uid).first()
        if s:
            return s
    return None


def _school_scope(query, model):
    school_id = getattr(current_user, "school_id", None)
    if school_id and hasattr(model, "school_id"):
        return query.filter(model.school_id == school_id)
    return query


# ─── Short-answer normalization (ticket P1-11) ─────────────────────────
# Compare student answers and answer keys after collapsing whitespace,
# unifying Arabic ↔ Latin digits, dropping tashkeel, folding case, and
# stripping common punctuation. So "١٥" == "15" == "15." == " 15 ".
_ARABIC_DIGIT_MAP = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_TASHKEEL = "".join(chr(c) for c in range(0x064B, 0x0653)) + "ٰۭۖ"
_TASHKEEL_MAP = {ord(ch): None for ch in _TASHKEEL}
_STRIP_PUNCT = ".,،؛?؟!:;\"'()[]{}<>«»…-_/\\"
_STRIP_PUNCT_MAP = {ord(ch): " " for ch in _STRIP_PUNCT}


def _normalize_short_answer(text) -> str:
    if text is None:
        return ""
    s = str(text)
    s = s.translate(_ARABIC_DIGIT_MAP)
    s = s.translate(_TASHKEEL_MAP)
    s = s.translate(_STRIP_PUNCT_MAP)
    # Collapse whitespace + lowercase + strip.
    s = " ".join(s.split()).strip().casefold()
    # Unify a few common Arabic letter variants that carry no semantic
    # difference in short-answer form.
    s = s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    s = s.replace("ى", "ي").replace("ة", "ه")
    return s


@bp.route("/assignments", endpoint="assignments_home")
@login_required
def assignments_home():
    items = (
        CourseAssignment.query
        .order_by(CourseAssignment.due_at.asc().nullslast())
        .limit(100).all()
    )
    return render_template("lms/assignments_home.html", items=items)


@bp.route("/quizzes", endpoint="quizzes_home")
@login_required
def quizzes_home():
    items = (
        Quiz.query.order_by(Quiz.opens_at.asc().nullslast()).limit(100).all()
    )
    return render_template("lms/quizzes_home.html", items=items)


# ─── Assignment CRUD (teacher-side) ───────────────────────────────────────
#
# Course is the anchor for both assignments and quizzes — every URL is scoped
# under /courses/<cid> so the composer knows where to write.

def _parse_dt(s):
    """Accept 'YYYY-MM-DDTHH:MM' from a datetime-local input; return None on empty."""
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def _rubrics_for_subject(subject_id):
    from ...models import Rubric
    if not subject_id:
        return Rubric.query.filter_by(school_id=current_user.school_id).order_by(Rubric.title).all()
    return (
        Rubric.query.filter_by(school_id=current_user.school_id)
        .filter((Rubric.subject_id == subject_id) | (Rubric.subject_id.is_(None)))
        .order_by(Rubric.title).all()
    )


@bp.route("/courses/<int:cid>/assignments/new", methods=["GET", "POST"], endpoint="assignment_new")
@login_required
def assignment_new(cid):
    course = Course.query.get_or_404(cid)
    rubrics = _rubrics_for_subject(course.subject_id)
    if request.method == "POST":
        a = CourseAssignment(
            course_id=course.id,
            title=(request.form.get("title") or "").strip(),
            instructions=(request.form.get("instructions") or "").strip(),
            max_score=Decimal(request.form.get("max_score") or "100"),
            due_at=_parse_dt(request.form.get("due_at")),
            allow_late=bool(request.form.get("allow_late")),
            is_published=bool(request.form.get("is_published")),
            rubric_id=request.form.get("rubric_id", type=int) or None,
        )
        if not a.title:
            flash("عنوان الواجب مطلوب.", "danger")
            return render_template("lms/assignment_form.html", assignment=None, course=course, rubrics=rubrics)
        db.session.add(a); db.session.commit()
        flash("تم إنشاء الواجب.", "success")
        return redirect(url_for("courses.detail", course_id=course.id))
    return render_template("lms/assignment_form.html", assignment=None, course=course, rubrics=rubrics)


@bp.route("/assignments/<int:aid>/edit", methods=["GET", "POST"], endpoint="assignment_edit")
@login_required
def assignment_edit(aid):
    a = CourseAssignment.query.get_or_404(aid)
    course = a.course
    rubrics = _rubrics_for_subject(course.subject_id if course else None)
    if request.method == "POST":
        a.title = (request.form.get("title") or "").strip()
        a.instructions = (request.form.get("instructions") or "").strip()
        a.max_score = Decimal(request.form.get("max_score") or "100")
        a.due_at = _parse_dt(request.form.get("due_at"))
        a.allow_late = bool(request.form.get("allow_late"))
        a.is_published = bool(request.form.get("is_published"))
        a.rubric_id = request.form.get("rubric_id", type=int) or None
        db.session.commit()
        flash("تم حفظ الواجب.", "success")
        return redirect(url_for("courses.detail", course_id=course.id))
    return render_template("lms/assignment_form.html", assignment=a, course=course, rubrics=rubrics)


# ─── Smart-assignment composer (ticket #16 pt 3) ──────────────────────
#
# Mirrors the quiz_questions / quiz_pick_from_bank routes so an
# assignment can carry MCQ / TF / short / essay questions the same way
# a quiz does. When an assignment has zero questions it stays as the
# legacy free-form (upload/text) homework.

@bp.route("/assignments/<int:aid>/questions", endpoint="assignment_questions")
@login_required
def assignment_questions(aid):
    a = CourseAssignment.query.get_or_404(aid)
    return render_template("lms/assignment_questions.html", assignment=a)


@bp.route("/assignments/<int:aid>/questions/add", methods=["POST"],
          endpoint="assignment_question_add")
@login_required
def assignment_question_add(aid):
    a = CourseAssignment.query.get_or_404(aid)
    last = max((q.order_index for q in a.questions), default=0)
    kind = request.form.get("kind", "mcq")
    q = AssignmentQuestion(
        assignment_id=a.id, order_index=last + 1, kind=kind,
        prompt=(request.form.get("prompt") or "").strip(),
        points=Decimal(request.form.get("points") or "1"),
        correct_short=(request.form.get("correct_short") or "").strip(),
    )
    db.session.add(q); db.session.flush()
    if kind == "mcq":
        for i, label in enumerate(["الخيار أ", "الخيار ب", "الخيار ج", "الخيار د"], start=1):
            db.session.add(AssignmentChoice(question_id=q.id, order_index=i,
                                            label=label, is_correct=(i == 1)))
    elif kind == "tf":
        db.session.add(AssignmentChoice(question_id=q.id, order_index=1, label="صح", is_correct=True))
        db.session.add(AssignmentChoice(question_id=q.id, order_index=2, label="خطأ", is_correct=False))
    db.session.commit()
    flash("تمت إضافة السؤال — عدّل الخيارات إن لزم.", "success")
    return redirect(url_for("lms.assignment_questions", aid=a.id))


@bp.route("/assignment-questions/<int:qid>/update", methods=["POST"],
          endpoint="assignment_question_update")
@login_required
def assignment_question_update(qid):
    q = AssignmentQuestion.query.get_or_404(qid)
    if q.is_locked:
        flash(
            "لا يمكن تعديل السؤال بعد إجابة الطلاب عليه.",
            "danger",
        )
        return redirect(url_for("lms.assignment_questions", aid=q.assignment_id))
    q.prompt = (request.form.get("prompt") or "").strip()
    q.points = Decimal(request.form.get("points") or "1")
    q.correct_short = (request.form.get("correct_short") or "").strip()
    correct_ids = set(int(x) for x in request.form.getlist("correct_choices") if x.isdigit())
    for c in q.choices:
        c.label = (request.form.get(f"choice_label[{c.id}]") or c.label).strip()
        c.is_correct = c.id in correct_ids
    db.session.commit()
    flash("تم حفظ السؤال.", "success")
    return redirect(url_for("lms.assignment_questions", aid=q.assignment_id))


@bp.route("/assignment-questions/<int:qid>/delete", methods=["POST"],
          endpoint="assignment_question_delete")
@login_required
def assignment_question_delete(qid):
    q = AssignmentQuestion.query.get_or_404(qid)
    aid = q.assignment_id
    db.session.delete(q); db.session.commit()
    flash("تم حذف السؤال.", "success")
    return redirect(url_for("lms.assignment_questions", aid=aid))


@bp.route("/assignments/<int:aid>/pick", methods=["GET", "POST"],
          endpoint="assignment_pick_from_bank")
@login_required
def assignment_pick_from_bank(aid):
    """Same UX as quiz_pick_from_bank — clone selected BankQuestions
    into AssignmentQuestion + AssignmentChoice rows for this assignment.
    Duplicate-safe on source_bank_id."""
    a = CourseAssignment.query.get_or_404(aid)

    if request.method == "POST":
        picked_ids = [int(x) for x in request.form.getlist("bank_ids") if x.isdigit()]
        if not picked_ids:
            flash("لم يتم اختيار أي سؤال.", "warning")
            return redirect(url_for("lms.assignment_pick_from_bank", aid=a.id))

        existing_sources = {q.source_bank_id for q in a.questions if q.source_bank_id}
        # Defense-in-depth for ticket P0-3: filter approved + non-archived
        # here too, not just on the GET picker. A teacher posting a stale
        # id from an earlier tab would otherwise sneak a rejected row into
        # the assignment.
        pool = BankQuestion.query.filter(
            BankQuestion.school_id == current_user.school_id,
            BankQuestion.review_state == "approved",
            BankQuestion.is_archived == False,  # noqa: E712
            BankQuestion.id.in_(picked_ids),
        ).all()

        last = max((q.order_index for q in a.questions), default=0)
        added = 0; skipped = 0
        for bq in pool:
            if bq.id in existing_sources:
                skipped += 1
                continue
            last += 1
            aq = AssignmentQuestion(
                assignment_id=a.id, order_index=last,
                kind=bq.kind, prompt=bq.prompt,
                points=bq.points or Decimal("1"),
                correct_short=bq.correct_short or "",
                source_bank_id=bq.id,
            )
            db.session.add(aq); db.session.flush()
            for bc in bq.choices:
                db.session.add(AssignmentChoice(
                    question_id=aq.id, order_index=bc.order_index,
                    label=bc.label, is_correct=bc.is_correct,
                ))
            added += 1
        db.session.commit()
        msg = f"تمت إضافة {added} سؤال إلى الواجب."
        if skipped:
            msg += f" (تم تجاهل {skipped} سؤال موجود مسبقاً.)"
        flash(msg, "success" if added else "warning")
        return redirect(url_for("lms.assignment_questions", aid=a.id))

    items = _bank_query().limit(300).all()
    subjects, grades, years, terms = _bank_filter_options()
    already = {q.source_bank_id for q in a.questions if q.source_bank_id}
    return render_template(
        "lms/assignment_bank_picker.html",
        assignment=a, items=items, already=already,
        subjects=subjects, grades=grades, years=years, terms=terms,
        selected={
            "subject_id": request.args.get("subject_id", type=int),
            "grade_id":   request.args.get("grade_id",   type=int),
            "year_id":    request.args.get("year_id",    type=int),
            "term_id":    request.args.get("term_id",    type=int),
            "unit_id":    request.args.get("unit_id",    type=int),
            "lesson_id":  request.args.get("lesson_id",  type=int),
            "difficulty": request.args.get("difficulty", ""),
            "kind":       request.args.get("kind", ""),
            "tag":        (request.args.get("tag") or "").strip(),
            "q":          (request.args.get("q")   or "").strip(),
        },
    )


# Performance reports were split into ./reports.py (ticket P1-18).


# ─── Assignment templates (ticket #16 pt 5) ───────────────────────────

@bp.route("/templates", endpoint="template_home")
@login_required
def template_home():
    """Assignment-templates library — school-scoped list with filters."""
    sid = current_user.school_id
    q = AssignmentTemplate.query.filter_by(school_id=sid)
    subj = request.args.get("subject_id", type=int)
    grade = request.args.get("grade_id", type=int)
    search = (request.args.get("q") or "").strip()
    if subj:   q = q.filter(AssignmentTemplate.subject_id == subj)
    if grade:  q = q.filter(AssignmentTemplate.grade_id == grade)
    if search: q = q.filter(AssignmentTemplate.title.ilike(f"%{search}%"))
    items = q.order_by(AssignmentTemplate.updated_at.desc()).limit(200).all()
    subjects = Subject.query.filter_by(school_id=sid).order_by(Subject.name).all()
    grades   = Grade.query.filter_by(school_id=sid).order_by(Grade.order_index).all()
    return render_template(
        "lms/template_list.html",
        items=items, subjects=subjects, grades=grades,
        selected={"subject_id": subj, "grade_id": grade, "q": search},
    )


@bp.route("/templates/<int:tid>/delete", methods=["POST"], endpoint="template_delete")
@login_required
def template_delete(tid):
    """Hard-delete a template. Cascades to template_questions + choices.
    CourseAssignments cloned from this template are UNAFFECTED —
    source_template_id is set to NULL by the schema's ON DELETE SET NULL."""
    tmpl = AssignmentTemplate.query.filter_by(
        id=tid, school_id=current_user.school_id
    ).first_or_404()
    title = tmpl.title
    db.session.delete(tmpl); db.session.commit()
    flash(f"تم حذف قالب الواجب ({title}) من المكتبة.", "success")
    return redirect(url_for("lms.template_home"))


@bp.route("/assignments/<int:aid>/save-as-template", methods=["POST"],
          endpoint="assignment_save_as_template")
@login_required
def assignment_save_as_template(aid):
    """Snapshot a live CourseAssignment (title + instructions + max_score
    + allow_late + every AssignmentQuestion + Choice) into a fresh
    AssignmentTemplate row so the teacher can re-clone it into other
    courses later. Copy semantics — later edits to either side do not
    cross-contaminate."""
    a = CourseAssignment.query.get_or_404(aid)
    course = a.course
    # Ticket #2 — Course now stores grade_id directly.
    grade_id = course.grade_id if course else None
    tmpl = AssignmentTemplate(
        school_id=current_user.school_id,
        created_by_id=getattr(current_user, "id", None),
        subject_id=course.subject_id if course else None,
        grade_id=grade_id,
        title=a.title,
        instructions=a.instructions or "",
        max_score=a.max_score,
        allow_late=a.allow_late,
    )
    db.session.add(tmpl); db.session.flush()
    for q in a.questions:
        tq = AssignmentTemplateQuestion(
            template_id=tmpl.id,
            order_index=q.order_index,
            kind=q.kind, prompt=q.prompt,
            points=q.points, correct_short=q.correct_short,
            source_bank_id=q.source_bank_id,
        )
        db.session.add(tq); db.session.flush()
        for c in q.choices:
            db.session.add(AssignmentTemplateChoice(
                question_id=tq.id, order_index=c.order_index,
                label=c.label, is_correct=c.is_correct,
            ))
    db.session.commit()
    flash(f"تم حفظ نسخة من الواجب ({a.title}) في مكتبة القوالب.", "success")
    return redirect(url_for("lms.template_home"))


@bp.route("/courses/<int:cid>/assignments/from-template", methods=["GET", "POST"],
          endpoint="assignment_from_template")
@login_required
def assignment_from_template(cid):
    """GET  — template picker page scoped to the target course.
    POST — clone the chosen template into a fresh CourseAssignment
           on this course. Increment the template's usage_count."""
    course = Course.query.get_or_404(cid)
    sid = current_user.school_id

    if request.method == "POST":
        tid = request.form.get("template_id", type=int)
        tmpl = AssignmentTemplate.query.filter_by(id=tid, school_id=sid).first()
        if not tmpl:
            flash("قالب الواجب غير موجود.", "danger")
            return redirect(url_for("lms.assignment_from_template", cid=course.id))

        a = CourseAssignment(
            course_id=course.id,
            title=tmpl.title,
            instructions=tmpl.instructions or "",
            max_score=tmpl.max_score or Decimal("100"),
            allow_late=tmpl.allow_late,
            is_published=False,   # start as draft so the teacher can review
            source_template_id=tmpl.id,
        )
        db.session.add(a); db.session.flush()
        for tq in tmpl.questions:
            aq = AssignmentQuestion(
                assignment_id=a.id,
                order_index=tq.order_index,
                kind=tq.kind, prompt=tq.prompt,
                points=tq.points, correct_short=tq.correct_short,
                source_bank_id=tq.source_bank_id,
            )
            db.session.add(aq); db.session.flush()
            for tc in tq.choices:
                db.session.add(AssignmentChoice(
                    question_id=aq.id, order_index=tc.order_index,
                    label=tc.label, is_correct=tc.is_correct,
                ))
        tmpl.usage_count = (tmpl.usage_count or 0) + 1
        db.session.commit()
        flash(f"تم إنشاء الواجب من القالب — عدّله ثم انشره.", "success")
        return redirect(url_for("lms.assignment_edit", aid=a.id))

    items = (
        AssignmentTemplate.query.filter_by(school_id=sid)
        .order_by(AssignmentTemplate.updated_at.desc()).all()
    )
    return render_template(
        "lms/template_picker.html",
        course=course, items=items,
    )


@bp.route("/assignments/<int:aid>/delete", methods=["POST"], endpoint="assignment_delete")
@login_required
def assignment_delete(aid):
    a = CourseAssignment.query.get_or_404(aid)
    course_id = a.course_id
    db.session.delete(a); db.session.commit()
    flash("تم حذف الواجب.", "success")
    return redirect(url_for("courses.detail", course_id=course_id))


# ─── Quiz CRUD (teacher-side) ─────────────────────────────────────────────

@bp.route("/courses/<int:cid>/quizzes/new", methods=["GET", "POST"], endpoint="quiz_new")
@login_required
def quiz_new(cid):
    course = Course.query.get_or_404(cid)
    if request.method == "POST":
        q = Quiz(
            course_id=course.id,
            title=(request.form.get("title") or "").strip(),
            description=(request.form.get("description") or "").strip(),
            duration_minutes=int(request.form.get("duration_minutes") or 30),
            opens_at=_parse_dt(request.form.get("opens_at")),
            closes_at=_parse_dt(request.form.get("closes_at")),
            max_attempts=int(request.form.get("max_attempts") or 1),
            shuffle_questions=bool(request.form.get("shuffle_questions")),
            shuffle_choices=bool(request.form.get("shuffle_choices")),
            allow_partial_credit=bool(request.form.get("allow_partial_credit")),
            is_published=bool(request.form.get("is_published")),
        )
        if not q.title:
            flash("عنوان الاختبار مطلوب.", "danger")
            return render_template("lms/quiz_form.html", quiz=None, course=course)
        db.session.add(q); db.session.commit()
        flash("تم إنشاء الاختبار — أضف الأسئلة الآن.", "success")
        return redirect(url_for("lms.quiz_questions", qid=q.id))
    return render_template("lms/quiz_form.html", quiz=None, course=course)


@bp.route("/quizzes/<int:qid>/edit", methods=["GET", "POST"], endpoint="quiz_edit")
@login_required
def quiz_edit(qid):
    q = Quiz.query.get_or_404(qid)
    course = q.course
    if request.method == "POST":
        q.title = (request.form.get("title") or "").strip()
        q.description = (request.form.get("description") or "").strip()
        q.duration_minutes = int(request.form.get("duration_minutes") or 30)
        q.opens_at = _parse_dt(request.form.get("opens_at"))
        q.closes_at = _parse_dt(request.form.get("closes_at"))
        q.max_attempts = int(request.form.get("max_attempts") or 1)
        q.shuffle_questions = bool(request.form.get("shuffle_questions"))
        q.shuffle_choices = bool(request.form.get("shuffle_choices"))
        q.allow_partial_credit = bool(request.form.get("allow_partial_credit"))
        q.is_published = bool(request.form.get("is_published"))
        db.session.commit()
        flash("تم حفظ الاختبار.", "success")
        return redirect(url_for("lms.quiz_questions", qid=q.id))
    return render_template("lms/quiz_form.html", quiz=q, course=course)


@bp.route("/quizzes/<int:qid>/delete", methods=["POST"], endpoint="quiz_delete")
@login_required
def quiz_delete(qid):
    q = Quiz.query.get_or_404(qid)
    course_id = q.course_id
    db.session.delete(q); db.session.commit()
    flash("تم حذف الاختبار.", "success")
    return redirect(url_for("courses.detail", course_id=course_id))


# --- Question composer ---------------------------------------------------

@bp.route("/quizzes/<int:qid>/questions", methods=["GET"], endpoint="quiz_questions")
@login_required
def quiz_questions(qid):
    quiz = Quiz.query.get_or_404(qid)
    return render_template("lms/quiz_questions.html", quiz=quiz)


@bp.route("/quizzes/<int:qid>/questions/add", methods=["POST"], endpoint="quiz_question_add")
@login_required
def quiz_question_add(qid):
    quiz = Quiz.query.get_or_404(qid)
    last = max((qq.order_index for qq in quiz.questions), default=0)
    kind = request.form.get("kind", "mcq")
    q = Question(
        quiz_id=quiz.id, order_index=last + 1, kind=kind,
        prompt=(request.form.get("prompt") or "").strip(),
        points=Decimal(request.form.get("points") or "1"),
        correct_short=(request.form.get("correct_short") or "").strip(),
    )
    db.session.add(q); db.session.flush()

    # Auto-populate default choices for mcq/tf so the teacher only has to
    # mark which is correct next.
    if kind == "mcq":
        for i, label in enumerate(["الخيار أ", "الخيار ب", "الخيار ج", "الخيار د"], start=1):
            db.session.add(Choice(question_id=q.id, order_index=i, label=label, is_correct=(i == 1)))
    elif kind == "tf":
        db.session.add(Choice(question_id=q.id, order_index=1, label="صح", is_correct=True))
        db.session.add(Choice(question_id=q.id, order_index=2, label="خطأ", is_correct=False))
    db.session.commit()
    flash("تمت إضافة السؤال — عدّل الخيارات إن لزم.", "success")
    return redirect(url_for("lms.quiz_questions", qid=quiz.id))


@bp.route("/questions/<int:qid>/update", methods=["POST"], endpoint="quiz_question_update")
@login_required
def quiz_question_update(qid):
    q = Question.query.get_or_404(qid)
    # Ticket #19 — refuse silent edits once a student has answered.
    # The teacher can bump version (creating a fresh version so old
    # attempts still refer to their original text). Here we just refuse
    # the direct edit; a follow-up commit adds the versioning UI proper.
    if q.is_locked:
        flash(
            "لا يمكن تعديل السؤال بعد إجابة الطلاب عليه. "
            "أنشئ نسخة معدَّلة بدلاً من التعديل المباشر.",
            "danger",
        )
        return redirect(url_for("lms.quiz_questions", qid=q.quiz_id))
    q.prompt = (request.form.get("prompt") or "").strip()
    q.points = Decimal(request.form.get("points") or "1")
    q.correct_short = (request.form.get("correct_short") or "").strip()
    # Update choices — labels come in as choice_label[<choice_id>] and
    # correct choice ids come in as correct_choices (a list of ids).
    correct_ids = set(int(x) for x in request.form.getlist("correct_choices") if x.isdigit())
    for c in q.choices:
        c.label = (request.form.get(f"choice_label[{c.id}]") or c.label).strip()
        c.is_correct = c.id in correct_ids
    db.session.commit()
    flash("تم حفظ السؤال.", "success")
    return redirect(url_for("lms.quiz_questions", qid=q.quiz_id))


@bp.route("/questions/<int:qid>/delete", methods=["POST"], endpoint="quiz_question_delete")
@login_required
def quiz_question_delete(qid):
    q = Question.query.get_or_404(qid)
    quiz_id = q.quiz_id
    db.session.delete(q); db.session.commit()
    flash("تم حذف السؤال.", "success")
    return redirect(url_for("lms.quiz_questions", qid=quiz_id))


@bp.route("/questions/<int:qid>/version", methods=["POST"],
          endpoint="quiz_question_new_version")
@login_required
def quiz_question_new_version(qid):
    """Ticket #19 — clone a locked Question into a new row on the same
    Quiz (with version = old.version + 1, is_locked = False, appended
    to the end). The teacher edits the clone; the original stays intact
    so previous QuizAttempts still key on their answered version."""
    q = Question.query.get_or_404(qid)
    last = max((qq.order_index for qq in q.quiz.questions), default=0)
    clone = Question(
        quiz_id=q.quiz_id, order_index=last + 1,
        kind=q.kind, prompt=q.prompt, points=q.points,
        correct_short=q.correct_short,
        source_bank_id=q.source_bank_id,
        version=(q.version or 1) + 1, is_locked=False, locked_at=None,
    )
    db.session.add(clone); db.session.flush()
    for c in q.choices:
        db.session.add(Choice(
            question_id=clone.id, order_index=c.order_index,
            label=c.label, is_correct=c.is_correct,
        ))
    db.session.commit()
    flash(f"تم إنشاء نسخة جديدة (الإصدار {clone.version}). عدّلها ثم احذف الأصل لو حاب.", "success")
    return redirect(url_for("lms.quiz_questions", qid=q.quiz_id))


@bp.route("/assignment-questions/<int:qid>/version", methods=["POST"],
          endpoint="assignment_question_new_version")
@login_required
def assignment_question_new_version(qid):
    q = AssignmentQuestion.query.get_or_404(qid)
    last = max((qq.order_index for qq in q.assignment.questions), default=0)
    clone = AssignmentQuestion(
        assignment_id=q.assignment_id, order_index=last + 1,
        kind=q.kind, prompt=q.prompt, points=q.points,
        correct_short=q.correct_short,
        source_bank_id=q.source_bank_id,
        version=(q.version or 1) + 1, is_locked=False,
    )
    db.session.add(clone); db.session.flush()
    for c in q.choices:
        db.session.add(AssignmentChoice(
            question_id=clone.id, order_index=c.order_index,
            label=c.label, is_correct=c.is_correct,
        ))
    db.session.commit()
    flash(f"تم إنشاء نسخة جديدة (الإصدار {clone.version}).", "success")
    return redirect(url_for("lms.assignment_questions", aid=q.assignment_id))


# ─── Question Bank ────────────────────────────────────────────────────────
#
# The school's reusable question pool. Teachers write questions once (tagged
# with subject / grade / year / difficulty) and pick from the bank when
# composing quizzes — the picker COPIES the question + its choices into
# `lms_questions` + `lms_choices` and keeps a `source_bank_id` back-pointer.

def _sync_bank_tags(item, tags_raw: str):
    """Rebuild `item.tag_rows` from a comma-separated string.

    Existing BankTag rows are reused case-insensitively per school.
    Missing rows are created on the fly. The FK cascade on
    `lms_bank_question_tags` handles the assoc table; we only touch the
    parent side so SA does the assoc bookkeeping."""
    from ...models import BankTag
    sid = current_user.school_id
    seen_norm = set()
    picks = []
    for raw in (tags_raw or "").split(","):
        name = raw.strip()
        if not name:
            continue
        norm = name.casefold()
        if norm in seen_norm:
            continue
        seen_norm.add(norm)
        picks.append(name)
    if not picks:
        item.tag_rows = []
        return
    existing = (
        BankTag.query.filter(
            BankTag.school_id == sid,
            db.func.lower(BankTag.name).in_([p.casefold() for p in picks]),
        ).all()
    )
    by_norm = {t.name.casefold(): t for t in existing}
    rows = []
    for name in picks:
        norm = name.casefold()
        tag = by_norm.get(norm)
        if not tag:
            tag = BankTag(school_id=sid, name=name)
            db.session.add(tag)
            db.session.flush()
            by_norm[norm] = tag
        rows.append(tag)
    item.tag_rows = rows


def _stratified_sample(pool, k):
    """Draw `k` items from `pool` spread across `unit_id` buckets.

    Instead of a straight `random.sample` — which can trivially pull
    every question from one unit — this splits the pool by
    `BankQuestion.unit_id`, allocates picks per unit proportionally to
    each unit's pool size (min 1 whenever the unit has questions), and
    tops up the last few picks randomly if rounding leaves quota. When
    the pool has fewer distinct units than `k`, each unit contributes
    what it has and the rest fill from the leftover pool at random."""
    import random as _random
    if k <= 0 or not pool:
        return []
    if k >= len(pool):
        return list(pool)

    buckets = {}
    for bq in pool:
        buckets.setdefault(bq.unit_id, []).append(bq)

    n_units = len(buckets)
    picks = []
    if n_units <= 1:
        return _random.sample(pool, k)

    # Proportional allocation with a floor of 1 per non-empty unit.
    base = max(1, k // n_units)
    for uid, items in buckets.items():
        take = min(base, len(items))
        if take:
            picks.extend(_random.sample(items, take))
    # Fill the remainder with random picks from anything left over.
    picked_ids = {q.id for q in picks}
    remainder = [q for q in pool if q.id not in picked_ids]
    need = k - len(picks)
    if need > 0 and remainder:
        picks.extend(_random.sample(remainder, min(need, len(remainder))))
    # If we somehow overshot (floors added up past k), trim randomly.
    if len(picks) > k:
        picks = _random.sample(picks, k)
    return picks


def _bank_query(*, include_all_states=False, include_archived=False):
    """Bank rows scoped to the current user's school + optional filters.

    The `source` querystring picks which bank tab is showing:
      · `source=school` (default) → the school's own curriculum bank
      · `source=nafis`            → the ETEC نافس bank

    By default rows are approved + not archived — that's what every
    picker (quiz/assignment/template) must show. Only the admin dashboard
    (qbank_dashboard) sets `include_all_states=True`/`include_archived=True`
    so admins can see the full pool.
    """
    q = BankQuestion.query.filter_by(school_id=current_user.school_id)
    if not include_all_states:
        q = q.filter(BankQuestion.review_state == "approved")
    if not include_archived:
        q = q.filter(BankQuestion.is_archived == False)  # noqa: E712
    subj = request.args.get("subject_id", type=int)
    grade = request.args.get("grade_id", type=int)
    year  = request.args.get("year_id",  type=int)
    diff  = request.args.get("difficulty")
    kind  = request.args.get("kind")
    tag   = (request.args.get("tag") or "").strip()
    search = (request.args.get("q") or "").strip()
    term  = request.args.get("term_id",   type=int)
    unit  = request.args.get("unit_id",   type=int)
    lesson = request.args.get("lesson_id", type=int)
    source = (request.args.get("source") or "school").strip()
    if source not in ("school", "nafis"):
        source = "school"
    q = q.filter(BankQuestion.source == source)

    # Nafis-only extras — only meaningful when source=nafis.
    if source == "nafis":
        level = (request.args.get("nafis_level") or "").strip()
        if level in ("g3", "g6", "g9"):
            q = q.filter(BankQuestion.nafis_level == level)
        outcome_id = request.args.get("outcome_id", type=int)
        if outcome_id:
            q = q.filter(BankQuestion.outcome_id == outcome_id)

    if subj:  q = q.filter(BankQuestion.subject_id == subj)
    if grade: q = q.filter(BankQuestion.grade_id == grade)
    if year:  q = q.filter(BankQuestion.academic_year_id == year)
    if term:  q = q.filter(BankQuestion.term_id == term)
    if unit:  q = q.filter(BankQuestion.unit_id == unit)
    if lesson: q = q.filter(BankQuestion.lesson_id == lesson)
    if diff:  q = q.filter(BankQuestion.difficulty == diff)
    if kind:  q = q.filter(BankQuestion.kind == kind)
    if tag:   q = q.filter(BankQuestion.tags.ilike(f"%{tag}%"))
    if search:
        q = q.filter(BankQuestion.prompt.ilike(f"%{search}%"))
    return q.order_by(BankQuestion.updated_at.desc())


def _bank_filter_options():
    """Dropdown data for bank filters, all scoped to the current school.
    Includes terms (across all years) and courses+units so the form can
    cascade subject → course → unit → lesson."""
    sid = current_user.school_id
    subjects = Subject.query.filter_by(school_id=sid).order_by(Subject.name).all()
    grades   = Grade.query.filter_by(school_id=sid).order_by(Grade.order_index).all()
    years    = (
        AcademicYear.query.filter_by(school_id=sid)
        .order_by(AcademicYear.start_date.desc()).all()
    )
    terms    = (
        Term.query.filter_by(school_id=sid)
        .join(AcademicYear, AcademicYear.id == Term.year_id)
        .order_by(AcademicYear.start_date.desc(), Term.order_index).all()
    )
    return subjects, grades, years, terms


def _bank_form_extras(item=None):
    """Extra data the bank form needs: courses/units/lessons for the
    cascading picker. Returns (subjects, grades, years, terms, courses,
    units, lessons_by_unit) — the last three preloaded for the item's
    current subject when editing, empty otherwise (JS fetches on demand
    later)."""
    subjects, grades, years, terms = _bank_filter_options()
    sid = current_user.school_id
    # Courses for the whole school — the form will scope to the picked
    # subject client-side. Server data payload is small (a few dozen
    # rows), so no need for an XHR endpoint yet.
    courses = (
        Course.query.filter_by(school_id=sid)
        .order_by(Course.title).all()
    )
    # Every unit + lesson in the school. Same argument as courses.
    units = (
        Unit.query.join(Course, Course.id == Unit.course_id)
        .filter(Course.school_id == sid)
        .order_by(Unit.course_id, Unit.order_index).all()
    )
    lessons = (
        Lesson.query.join(Course, Course.id == Lesson.course_id)
        .filter(Course.school_id == sid)
        .order_by(Lesson.course_id, Lesson.order_index).all()
    )
    # Qdrat-parity — 2-level skill taxonomy for the form. `axes` are
    # top-level buckets; `indicators` carry axis_id so the picker can
    # cascade axis → indicator client-side.
    from ...models import Axis, Indicator
    axes = (
        Axis.query.filter_by(school_id=sid)
        .order_by(Axis.order_index, Axis.name).all()
    )
    indicators = (
        Indicator.query.filter_by(school_id=sid)
        .order_by(Indicator.axis_id, Indicator.order_index).all()
    )
    return (subjects, grades, years, terms, courses, units, lessons,
            axes, indicators)


@bp.route("/bank/dashboard", endpoint="qbank_dashboard")
@login_required
def qbank_dashboard():
    """Analytics-heavy landing page for the school's question bank.

    Same shape as /api/admin/question_bank/dashboard, but server-side
    rendered as the Stitch `lms_1` design so the page paints in one
    request (no client-side JS needed).
    """
    sid = current_user.school_id
    source = (request.args.get("source") or "school").strip()
    if source not in ("school", "nafis"):
        source = "school"

    subject_id = request.args.get("subject_id", type=int)
    state      = (request.args.get("review_state") or "").strip() or None
    difficulty = (request.args.get("difficulty") or "").strip() or None
    show_archive = request.args.get("archive") == "1"

    q = BankQuestion.query.filter_by(school_id=sid, source=source)
    q = q.filter(BankQuestion.is_archived == show_archive)
    if subject_id: q = q.filter(BankQuestion.subject_id == subject_id)

    total = q.count()
    state_rows = q.with_entities(
        BankQuestion.review_state, db.func.count(BankQuestion.id),
    ).group_by(BankQuestion.review_state).all()
    states = {s: n for s, n in state_rows}
    # Housekeeping counts (qdrat-parity #7): archived rows and rows
    # missing a subject or axis tag — both are surfaced as CTAs on the
    # dashboard so admins have a clear entry into cleanup.
    archived_count = BankQuestion.query.filter_by(
        school_id=sid, source=source, is_archived=True).count()
    unclassified_count = BankQuestion.query.filter(
        BankQuestion.school_id == sid,
        BankQuestion.source == source,
        BankQuestion.is_archived == False,
        db.or_(BankQuestion.subject_id.is_(None),
               BankQuestion.axis_id.is_(None)),
    ).count()
    stats = {
        "total":     total,
        "approved":  states.get("approved", 0),
        "pending":   states.get("pending", 0),
        "draft":     states.get("draft", 0),
        "no_answer": states.get("no_answer", 0),
        "duplicate": states.get("duplicate", 0),
        "rejected":  states.get("rejected", 0),
        "coverage_pct": (states.get("approved", 0) * 100 // total) if total else 0,
        "archived":     archived_count,
        "unclassified": unclassified_count,
    }

    diff_rows = q.with_entities(
        BankQuestion.difficulty, db.func.count(BankQuestion.id),
    ).group_by(BankQuestion.difficulty).all()
    difficulty_totals = {d: n for d, n in diff_rows}
    difficulty_out = {
        "easy":      difficulty_totals.get("easy", 0),
        "medium":    difficulty_totals.get("medium", 0),
        "hard":      difficulty_totals.get("hard", 0),
        "very_hard": difficulty_totals.get("very_hard", 0),
    }

    subj_rows = q.with_entities(
        BankQuestion.subject_id, db.func.count(BankQuestion.id),
    ).group_by(BankQuestion.subject_id).order_by(
        db.func.count(BankQuestion.id).desc()
    ).all()
    by_subject = []
    for s_id, n in subj_rows:
        s = Subject.query.get(s_id) if s_id else None
        by_subject.append({
            "subject_id": s_id,
            "subject_name": s.name if s else "بدون تصنيف",
            "count": n,
        })
    subject_count = len([r for r in by_subject if r["subject_id"]])
    avg_per_subject = (total / subject_count) if subject_count else 0

    # Question list — filtered slice, 30 rows, newest first.
    lq = q
    if state:      lq = lq.filter(BankQuestion.review_state == state)
    if difficulty: lq = lq.filter(BankQuestion.difficulty == difficulty)
    items = lq.order_by(BankQuestion.created_at.desc()).limit(30).all()

    subjects = Subject.query.filter_by(school_id=sid).order_by(Subject.name).all()
    return render_template(
        "lms/qbank_dashboard.html",
        stats=stats,
        difficulty=difficulty_out,
        by_subject=by_subject,
        subject_count=subject_count,
        avg_per_subject=avg_per_subject,
        items=items,
        subjects=subjects,
        show_archive=show_archive,
        selected={
            "source": source,
            "subject_id": subject_id,
            "review_state": state or "",
            "difficulty": difficulty or "",
        },
    )


@bp.route("/assessment-templates", endpoint="templates_gallery")
@login_required
def templates_gallery():
    """AssessmentTemplate gallery — grouped by subject (Stitch lms_3)."""
    sid = current_user.school_id
    subject_id = request.args.get("subject_id", type=int)
    kind       = (request.args.get("kind") or "").strip() or None
    state      = (request.args.get("state") or "published").strip()
    query_str  = (request.args.get("q") or "").strip()

    q = AssessmentTemplate.query.filter_by(school_id=sid)
    if subject_id: q = q.filter(AssessmentTemplate.subject_id == subject_id)
    if kind:       q = q.filter(AssessmentTemplate.kind == kind)
    if state:      q = q.filter(AssessmentTemplate.state == state)
    if query_str:
        q = q.filter(AssessmentTemplate.title.ilike(f"%{query_str}%") |
                     AssessmentTemplate.code.ilike(f"%{query_str}%"))
    templates = q.order_by(AssessmentTemplate.updated_at.desc()).all()

    # By-subject roll-up. One query for every subject referenced,
    # then a lookup instead of a `.get()` per template (ticket P2-20).
    subj_ids = {r.subject_id for r in templates if r.subject_id}
    subj_name_by_id = {
        s.id: s.name for s in (
            Subject.query.filter(Subject.id.in_(subj_ids)).all()
            if subj_ids else []
        )
    }
    by_subject_map = {}
    for r in templates:
        key = r.subject_id or 0
        row = by_subject_map.setdefault(key, {
            "subject_id": r.subject_id,
            "subject_name": (subj_name_by_id.get(r.subject_id, "بدون تصنيف")
                             if r.subject_id else "بدون تصنيف"),
            "total": 0, "assignment_count": 0, "exam_count": 0,
        })
        row["total"] += 1
        if r.kind == "assignment": row["assignment_count"] += 1
        if r.kind == "exam":       row["exam_count"]       += 1
    by_subject = sorted(by_subject_map.values(), key=lambda r: -r["total"])

    # Global KPIs (not filtered).
    all_q = AssessmentTemplate.query.filter_by(school_id=sid)
    all_total = all_q.count()
    published = all_q.filter_by(state="published").count()
    archived  = all_q.filter_by(state="archived").count()
    assignments = all_q.filter_by(kind="assignment").count()
    exams = all_q.filter_by(kind="exam").count()
    from datetime import datetime as _dt, timedelta as _td
    today = _dt.utcnow().date()
    month_start = today.replace(day=1)
    today_count = all_q.filter(db.func.date(AssessmentTemplate.created_at) == today).count()
    month_count = all_q.filter(AssessmentTemplate.created_at >= month_start).count()
    authors = db.session.query(AssessmentTemplate.created_by_id).filter_by(
        school_id=sid).distinct().count()

    subjects = Subject.query.filter_by(school_id=sid).order_by(Subject.name).all()
    return render_template(
        "lms/templates_gallery.html",
        by_subject=by_subject,
        templates=templates,
        subjects=subjects,
        stats={
            "total": all_total,
            "published": published,
            "archived": archived,
            "assignments": assignments,
            "exams": exams,
            "today": today_count,
            "month": month_count,
            "authors": authors,
        },
        selected={
            "subject_id": subject_id,
            "kind": kind or "",
            "state": state,
            "q": query_str,
        },
    )


@bp.route("/assessment-templates/new", methods=["GET", "POST"], endpoint="template_new")
@login_required
def template_new():
    """Create a template (Stitch lms_5 shell — form implemented next)."""
    if request.method == "POST":
        data = request.form
        title = (data.get("title") or "").strip()
        if not title:
            return redirect(url_for("lms.template_new"))
        import_code = (data.get("import_from_code") or "").strip()
        source_tmpl = None
        if import_code:
            source_tmpl = AssessmentTemplate.query.filter_by(
                school_id=current_user.school_id, code=import_code).first()
        t = AssessmentTemplate(
            school_id=current_user.school_id,
            created_by_id=current_user.id,
            title=title,
            code=(data.get("code") or "").strip() or None,
            description=(data.get("description") or "").strip(),
            subject_id=data.get("subject_id") or None,
            grade_id=data.get("grade_id") or None,
            kind=data.get("kind") or "assignment",
            state="published",
        )
        db.session.add(t)
        db.session.flush()
        if source_tmpl:
            for it in source_tmpl.items:
                db.session.add(AssessmentTemplateItem(
                    template_id=t.id,
                    bank_question_id=it.bank_question_id,
                    order_index=it.order_index,
                    points_override=it.points_override,
                ))
        db.session.commit()
        return redirect(url_for("lms.templates_gallery"))
    subjects = Subject.query.filter_by(school_id=current_user.school_id).order_by(Subject.name).all()
    return render_template("lms/template_new.html", subjects=subjects)


@bp.route("/assessment-templates/<int:tid>/edit", methods=["GET", "POST"], endpoint="template_edit")
@login_required
def template_edit(tid):
    t = AssessmentTemplate.query.filter_by(
        id=tid, school_id=current_user.school_id).first_or_404()
    if request.method == "POST":
        data = request.form
        t.title       = (data.get("title") or t.title).strip()
        t.code        = (data.get("code") or "").strip() or None
        t.description = (data.get("description") or "").strip()
        t.subject_id  = data.get("subject_id") or None
        t.grade_id    = data.get("grade_id") or None
        t.kind        = data.get("kind") or t.kind
        t.state       = data.get("state") or t.state
        db.session.commit()
        return redirect(url_for("lms.templates_gallery"))
    subjects = Subject.query.filter_by(school_id=current_user.school_id).order_by(Subject.name).all()
    return render_template("lms/template_new.html", template=t, subjects=subjects)


# ─── Template Detail + Question Picker (Stitch lms_6) ──────────────────
@bp.route("/assessment-templates/<int:tid>", endpoint="template_detail")
@login_required
def template_detail(tid):
    """Stitch lms_6 — a template's items list plus an inline picker
    that pulls from the school bank. GET-only; the write paths live at
    lms.template_items_attach / template_item_delete / template_items_save."""
    sid = current_user.school_id
    t = AssessmentTemplate.query.filter_by(
        id=tid, school_id=sid).first_or_404()

    items = (
        AssessmentTemplateItem.query
        .filter_by(template_id=t.id)
        .order_by(AssessmentTemplateItem.order_index).all()
    )
    attached_ids = {it.bank_question_id for it in items}

    diff_totals = {"easy": 0, "medium": 0, "hard": 0, "very_hard": 0}
    total_points = 0.0
    for it in items:
        bq = it.bank_question
        if not bq:
            continue
        diff_totals[bq.difficulty] = diff_totals.get(bq.difficulty, 0) + 1
        pts = it.points_override if it.points_override is not None else bq.points
        total_points += float(pts or 0)

    # Picker — approved school-source rows, with optional filters from query.
    filters = {
        "q":          (request.args.get("q") or "").strip(),
        "subject_id": request.args.get("subject_id", type=int),
        "difficulty": (request.args.get("difficulty") or "").strip(),
        "kind":       (request.args.get("kind") or "").strip(),
    }
    pool = BankQuestion.query.filter(
        BankQuestion.school_id == sid,
        BankQuestion.source == "school",
        BankQuestion.review_state == "approved",
    )
    if filters["subject_id"]:
        pool = pool.filter(BankQuestion.subject_id == filters["subject_id"])
    if filters["difficulty"]:
        pool = pool.filter(BankQuestion.difficulty == filters["difficulty"])
    if filters["kind"]:
        pool = pool.filter(BankQuestion.kind == filters["kind"])
    if filters["q"]:
        pool = pool.filter(BankQuestion.prompt.ilike(f"%{filters['q']}%"))
    picker_items = pool.order_by(BankQuestion.id.desc()).limit(30).all()
    picker_total = BankQuestion.query.filter_by(
        school_id=sid, source="school", review_state="approved").count()

    subjects = (
        Subject.query.filter_by(school_id=sid)
        .order_by(Subject.name).all()
    )
    return render_template(
        "lms/template_detail.html",
        template=t, items=items,
        attached_ids=attached_ids,
        stats={
            "total": len(items),
            "points": total_points,
            "difficulty": diff_totals,
        },
        picker={"rows": picker_items, "total": picker_total},
        filters=filters, subjects=subjects,
    )


@bp.route("/assessment-templates/<int:tid>/items/attach",
          methods=["POST"], endpoint="template_items_attach")
@login_required
def template_items_attach(tid):
    """Attach a batch of bank-question ids to a template. Silently
    skips rows already attached (the uq_asstmpl_q constraint would
    otherwise 500 the batch on the first duplicate)."""
    sid = current_user.school_id
    t = AssessmentTemplate.query.filter_by(
        id=tid, school_id=sid).first_or_404()
    picked = [int(x) for x in request.form.getlist("bank_ids") if x.isdigit()]
    if not picked:
        flash("لم يتم اختيار أي سؤال.", "warning")
        return redirect(url_for("lms.template_detail", tid=t.id))
    existing = {
        it.bank_question_id for it in
        AssessmentTemplateItem.query.filter_by(template_id=t.id).all()
    }
    next_order = 1 + (
        db.session.query(db.func.max(AssessmentTemplateItem.order_index))
        .filter_by(template_id=t.id).scalar() or 0
    )
    added = 0
    for bid in picked:
        if bid in existing:
            continue
        # Same defense-in-depth as the quiz/assignment pickers — only
        # approved, non-archived bank rows can be attached to a template.
        bq = BankQuestion.query.filter_by(
            id=bid, school_id=sid,
            review_state="approved", is_archived=False,
        ).first()
        if not bq:
            continue
        db.session.add(AssessmentTemplateItem(
            template_id=t.id, bank_question_id=bq.id,
            order_index=next_order,
        ))
        next_order += 1
        added += 1
    db.session.commit()
    flash(f"تم إضافة {added} سؤال إلى النموذج.", "success")
    return redirect(url_for("lms.template_detail", tid=t.id))


@bp.route("/assessment-templates/<int:tid>/items/<int:iid>/delete",
          methods=["POST"], endpoint="template_item_delete")
@login_required
def template_item_delete(tid, iid):
    sid = current_user.school_id
    t = AssessmentTemplate.query.filter_by(
        id=tid, school_id=sid).first_or_404()
    it = AssessmentTemplateItem.query.filter_by(
        id=iid, template_id=t.id).first_or_404()
    db.session.delete(it)
    db.session.commit()
    flash("تم حذف السؤال من النموذج.", "success")
    return redirect(url_for("lms.template_detail", tid=t.id))


@bp.route("/assessment-templates/<int:tid>/items/save",
          methods=["POST"], endpoint="template_items_save")
@login_required
def template_items_save(tid):
    """Bulk-save `points_override` and `order_index` for every item.
    Fields are keyed by item id: `points_<iid>` and `order_<iid>`."""
    sid = current_user.school_id
    t = AssessmentTemplate.query.filter_by(
        id=tid, school_id=sid).first_or_404()
    for it in AssessmentTemplateItem.query.filter_by(template_id=t.id).all():
        raw_pts = request.form.get(f"points_{it.id}")
        if raw_pts is not None and raw_pts.strip() != "":
            try:
                it.points_override = Decimal(raw_pts)
            except Exception:
                pass
        raw_order = request.form.get(f"order_{it.id}", type=int)
        if raw_order is not None:
            it.order_index = raw_order
    db.session.commit()
    flash("تم حفظ التغييرات.", "success")
    return redirect(url_for("lms.template_detail", tid=t.id))


@bp.route("/assessment-templates/<int:tid>/use", methods=["GET", "POST"],
          endpoint="template_use")
@login_required
def template_use(tid):
    """Spawn a real Quiz from an AssessmentTemplate. Copies every
    attached BankQuestion into fresh Question + Choice rows so the
    resulting quiz is independent of later template edits."""
    from ...models import Section, AcademicYear, Choice as _Choice
    sid = current_user.school_id
    t = AssessmentTemplate.query.filter_by(
        id=tid, school_id=sid).first_or_404()
    items = (
        AssessmentTemplateItem.query
        .filter_by(template_id=t.id)
        .order_by(AssessmentTemplateItem.order_index).all()
    )

    if request.method == "POST":
        if not items:
            flash("النموذج فارغ — أضف أسئلة أولاً.", "warning")
            return redirect(url_for("lms.template_detail", tid=t.id))
        title = (request.form.get("title") or "").strip() or t.title
        section_id = request.form.get("section_id", type=int)
        section = Section.query.filter_by(id=section_id, school_id=sid).first()
        if not section:
            flash("الشعبة غير موجودة.", "danger")
            return redirect(url_for("lms.template_use", tid=t.id))

        year = AcademicYear.query.filter_by(
            school_id=sid, status="active").first() or AcademicYear.query.filter_by(
            school_id=sid).order_by(AcademicYear.id.desc()).first()
        subject_id = t.subject_id or (items[0].bank_question.subject_id if items[0].bank_question else None)

        course = Course.query.filter_by(
            school_id=sid,
            academic_year_id=year.id if year else None,
            grade_id=section.grade_id,
            subject_id=subject_id,
        ).first()
        if not course:
            course = Course(
                school_id=sid,
                academic_year_id=year.id if year else None,
                grade_id=section.grade_id,
                subject_id=subject_id,
                title=f"{title} (من نموذج)",
                is_published=True,
            )
            db.session.add(course)
            db.session.flush()

        # Branch on template kind: 'exam' → Quiz + Question + Choice
        # (auto-graded, timed), 'assignment' → CourseAssignment +
        # AssignmentQuestion + AssignmentChoice (due-date, allow_late).
        if t.kind == "assignment":
            total_points = sum(
                float((it.points_override if it.points_override is not None
                       else (it.bank_question.points if it.bank_question else 1)) or 1)
                for it in items
            )
            asg = CourseAssignment(
                course_id=course.id,
                title=title,
                instructions=t.description or "",
                max_score=Decimal(str(total_points)) if total_points else Decimal("100"),
                due_at=_parse_dt(request.form.get("due_at")),
                allow_late=bool(request.form.get("allow_late")),
                is_published=bool(request.form.get("publish")),
            )
            db.session.add(asg)
            db.session.flush()
            for idx, it in enumerate(items, start=1):
                bq = it.bank_question
                if not bq:
                    continue
                aq = AssignmentQuestion(
                    assignment_id=asg.id,
                    order_index=idx,
                    kind=bq.kind,
                    prompt=bq.prompt,
                    points=(it.points_override if it.points_override is not None else bq.points) or 1,
                    correct_short=bq.correct_short or "",
                    source_bank_id=bq.id,
                )
                db.session.add(aq)
                db.session.flush()
                for i, bc in enumerate(bq.choices or []):
                    db.session.add(AssignmentChoice(
                        question_id=aq.id, order_index=i,
                        label=bc.label, is_correct=bool(bc.is_correct),
                    ))
            db.session.commit()
            flash(f"تم توليد الواجب «{asg.title}» من النموذج.", "success")
            return redirect(url_for("lms.assignments_home"))

        quiz = Quiz(
            course_id=course.id,
            title=title,
            description=t.description or "",
            duration_minutes=request.form.get("duration_minutes", type=int) or 60,
            opens_at=_parse_dt(request.form.get("opens_at")),
            closes_at=_parse_dt(request.form.get("closes_at")),
            shuffle_questions=bool(request.form.get("shuffle_questions")),
            shuffle_choices=bool(request.form.get("shuffle_choices")),
            allow_partial_credit=bool(request.form.get("allow_partial_credit")),
            is_published=bool(request.form.get("publish")),
        )
        db.session.add(quiz)
        db.session.flush()

        for idx, it in enumerate(items, start=1):
            bq = it.bank_question
            if not bq:
                continue
            q = Question(
                quiz_id=quiz.id,
                order_index=idx,
                kind=bq.kind,
                prompt=bq.prompt,
                points=(it.points_override if it.points_override is not None else bq.points) or 1,
                correct_short=bq.correct_short or "",
                source_bank_id=bq.id,
            )
            db.session.add(q)
            db.session.flush()
            for i, bc in enumerate(bq.choices or []):
                db.session.add(_Choice(
                    question_id=q.id, order_index=i,
                    label=bc.label, is_correct=bool(bc.is_correct),
                ))
        db.session.commit()
        flash(f"تم توليد الاختبار «{quiz.title}» من النموذج.", "success")
        return redirect(url_for("lms.quizzes_home"))

    sections = (
        Section.query.filter_by(school_id=sid)
        .order_by(Section.grade_id, Section.name).all()
    )
    return render_template("lms/template_use.html",
                           template=t, items=items, sections=sections)


# ─── Blueprint Exam Generator (Stitch lms_4) ────────────────────────────
@bp.route("/exams/blueprint/new", methods=["GET", "POST"],
          endpoint="blueprint_exam_new")
@login_required
def blueprint_exam_new():
    """Render the exam-blueprint composer. POST handled by
    lms.blueprint_exam_create — kept as a separate endpoint so the form
    can be reused (edit, retry) without re-rendering on success."""
    sid = current_user.school_id
    subjects = Subject.query.filter_by(school_id=sid).order_by(Subject.name).all()
    # Available approved-question counts per subject.
    avail = dict(
        db.session.query(
            BankQuestion.subject_id, db.func.count(BankQuestion.id)
        ).filter(
            BankQuestion.school_id == sid,
            BankQuestion.review_state == "approved",
            BankQuestion.source == "school",
        ).group_by(BankQuestion.subject_id).all()
    )
    subject_rows = [
        {"subject_id": s.id, "subject_name": s.name, "available": avail.get(s.id, 0)}
        for s in subjects
    ]
    from ...models import Section
    sections = (
        Section.query.filter_by(school_id=sid)
        .order_by(Section.grade_id, Section.name).all()
    )
    return render_template(
        "lms/blueprint_exam.html",
        subject_rows=subject_rows,
        sections=sections,
    )


@bp.route("/exams/blueprint/create", methods=["POST"],
          endpoint="blueprint_exam_create")
@login_required
def blueprint_exam_create():
    """POST target for the Blueprint form. Builds a Quiz + Questions
    (with copied choices, unlike the JWT API twin) by drawing N approved
    bank questions per subject."""
    import random as _random
    from ...models import Section, AcademicYear
    sid = current_user.school_id
    form = request.form
    title = (form.get("title") or "").strip()
    section_id = form.get("section_id", type=int)
    duration = form.get("duration_minutes", type=int) or 60
    shuffle_q = bool(form.get("shuffle_questions"))
    shuffle_c = bool(form.get("shuffle_choices"))
    if not (title and section_id):
        flash("العنوان والشعبة مطلوبان", "error")
        return redirect(url_for("lms.blueprint_exam_new"))

    section = Section.query.filter_by(id=section_id, school_id=sid).first()
    if not section:
        flash("الشعبة غير موجودة", "error")
        return redirect(url_for("lms.blueprint_exam_new"))
    year = AcademicYear.query.filter_by(
        school_id=sid, status="active").first() or AcademicYear.query.filter_by(
        school_id=sid).order_by(AcademicYear.id.desc()).first()

    # Collect per-subject picks from the form.
    sources = []
    for key, val in form.items():
        if not key.startswith("subject_count_"):
            continue
        try:
            subj_id = int(key.rsplit("_", 1)[-1])
            count = int(val or 0)
        except (TypeError, ValueError):
            continue
        if count <= 0:
            continue
        diff = (form.get(f"subject_difficulty_{subj_id}") or "").strip() or None
        sources.append({"subject_id": subj_id, "count": count, "difficulty": diff})
    if not sources:
        flash("حدد عدد الأسئلة لمادة واحدة على الأقل", "error")
        return redirect(url_for("lms.blueprint_exam_new"))

    # Resolve/create a Course for the first source subject on this
    # grade+year — matches the API twin's convention.
    first = sources[0]
    course = Course.query.filter_by(
        school_id=sid,
        academic_year_id=year.id if year else None,
        grade_id=section.grade_id,
        subject_id=first["subject_id"],
    ).first()
    if not course:
        course = Course(
            school_id=sid,
            academic_year_id=year.id if year else None,
            grade_id=section.grade_id,
            subject_id=first["subject_id"],
            title=f"{title} (Blueprint)",
            is_published=True,
        )
        db.session.add(course)
        db.session.flush()

    quiz = Quiz(
        course_id=course.id,
        title=title,
        description=(form.get("description") or "").strip(),
        duration_minutes=duration,
        shuffle_questions=shuffle_q,
        shuffle_choices=shuffle_c,
        is_published=False,
    )
    db.session.add(quiz)
    db.session.flush()

    from ...models import Choice as _Choice
    order = 0
    total = 0
    for src in sources:
        pool = BankQuestion.query.filter(
            BankQuestion.school_id == sid,
            BankQuestion.source == "school",
            BankQuestion.review_state == "approved",
            BankQuestion.is_archived == False,  # noqa: E712
            BankQuestion.subject_id == src["subject_id"],
        )
        if src["difficulty"]:
            pool = pool.filter(BankQuestion.difficulty == src["difficulty"])
        pool_list = pool.all()
        if not pool_list:
            continue
        picks = _stratified_sample(pool_list, src["count"])
        for bq in picks:
            order += 1
            q = Question(
                quiz_id=quiz.id, order_index=order,
                kind=bq.kind, prompt=bq.prompt,
                points=bq.points or 1,
                correct_short=bq.correct_short or "",
                source_bank_id=bq.id,
            )
            db.session.add(q)
            db.session.flush()
            bchoices = list(bq.choices) if hasattr(bq, "choices") else []
            if not bchoices:
                # Fall back to an explicit query — the relationship may
                # not be declared on BankQuestion in every schema build.
                from ...models import BankChoice
                bchoices = BankChoice.query.filter_by(question_id=bq.id).order_by(
                    BankChoice.order_index).all()
            if shuffle_c:
                _random.shuffle(bchoices)
            for i, bc in enumerate(bchoices):
                db.session.add(_Choice(
                    question_id=q.id,
                    order_index=i,
                    label=bc.label,
                    is_correct=bool(bc.is_correct),
                ))
            total += 1
    db.session.commit()
    flash(f"تم توليد الاختبار «{quiz.title}» بـ {total} سؤال", "success")
    return redirect(url_for("lms.quizzes_home"))


@bp.route("/bank", endpoint="bank_home")
@login_required
def bank_home():
    """Bank browser — two tabs (School / NAFIS), same page, same filters.

    Teachers editing the bank must be able to see rows in every state
    (draft / pending / rejected / duplicate / archived), so this route
    bypasses the approved+active filter that the pickers apply."""
    q = _bank_query(include_all_states=True, include_archived=True)
    review = (request.args.get("review_state") or "").strip()
    if review:
        q = q.filter(BankQuestion.review_state == review)
    show_archived = request.args.get("archived") == "1"
    q = q.filter(BankQuestion.is_archived == (True if show_archived else False))
    items = q.limit(200).all()
    subjects, grades, years, terms = _bank_filter_options()

    # Tab counters — a single scoped query per bank so the tab shows
    # the actual population, not just the filtered slice.
    school_total = BankQuestion.query.filter_by(
        school_id=current_user.school_id, source="school",
    ).count()
    nafis_total = BankQuestion.query.filter_by(
        school_id=current_user.school_id, source="nafis",
    ).count()

    source = (request.args.get("source") or "school").strip()
    if source not in ("school", "nafis"):
        source = "school"

    return render_template(
        "lms/bank_list.html",
        items=items,
        source=source,
        school_total=school_total,
        nafis_total=nafis_total,
        total=(school_total if source == "school" else nafis_total),
        subjects=subjects, grades=grades, years=years, terms=terms,
        selected={
            "source":     source,
            "subject_id": request.args.get("subject_id", type=int),
            "grade_id":   request.args.get("grade_id",   type=int),
            "year_id":    request.args.get("year_id",    type=int),
            "term_id":    request.args.get("term_id",    type=int),
            "unit_id":    request.args.get("unit_id",    type=int),
            "lesson_id":  request.args.get("lesson_id",  type=int),
            "difficulty": request.args.get("difficulty", ""),
            "kind":       request.args.get("kind", ""),
            "tag":        (request.args.get("tag") or "").strip(),
            "q":          (request.args.get("q")   or "").strip(),
            "nafis_level":(request.args.get("nafis_level") or "").strip(),
            "outcome_id": request.args.get("outcome_id", type=int),
        },
    )


@bp.route("/bank/new", methods=["GET", "POST"], endpoint="bank_new")
@login_required
def bank_new():
    if request.method == "POST":
        return _bank_save(None)
    (subjects, grades, years, terms, courses, units, lessons,
     axes, indicators) = _bank_form_extras()
    return render_template(
        "lms/bank_form.html", item=None,
        subjects=subjects, grades=grades, years=years, terms=terms,
        courses=courses, units=units, lessons=lessons,
        axes=axes, indicators=indicators,
    )


@bp.route("/bank/smart/new", methods=["GET", "POST"], endpoint="bank_smart_new")
@login_required
def bank_smart_new():
    """Stitch lms_2 authoring form — 5-section smart-question editor.
    Reuses `_bank_save` so the write path stays identical to the
    classic form."""
    if request.method == "POST":
        return _bank_save(None)
    (subjects, grades, years, terms, _courses, units, lessons,
     axes, indicators) = _bank_form_extras()
    return render_template(
        "lms/bank_smart.html",
        subjects=subjects, grades=grades, years=years, terms=terms,
        units=units, lessons=lessons,
        axes=axes, indicators=indicators,
    )


@bp.route("/bank/<int:bid>/edit", methods=["GET", "POST"], endpoint="bank_edit")
@login_required
def bank_edit(bid):
    item = BankQuestion.query.filter_by(id=bid, school_id=current_user.school_id).first_or_404()
    if request.method == "POST":
        return _bank_save(item)
    (subjects, grades, years, terms, courses, units, lessons,
     axes, indicators) = _bank_form_extras(item)
    return render_template(
        "lms/bank_form.html", item=item,
        subjects=subjects, grades=grades, years=years, terms=terms,
        courses=courses, units=units, lessons=lessons,
        axes=axes, indicators=indicators,
    )


def _bank_save(item):
    """Shared create/update path — writes the BankQuestion + its BankChoices."""
    kind = request.form.get("kind", "mcq")
    prompt = (request.form.get("prompt") or "").strip()
    if not prompt:
        flash("نص السؤال مطلوب.", "danger")
        return redirect(request.url)

    is_new = item is None
    if is_new:
        item = BankQuestion(school_id=current_user.school_id,
                            created_by_id=getattr(current_user, "id", None))
        db.session.add(item)

    item.kind = kind
    item.prompt = prompt
    item.points = Decimal(request.form.get("points") or "1")
    item.correct_short = (request.form.get("correct_short") or "").strip()
    item.difficulty = request.form.get("difficulty") or "medium"
    # Tags — dual-write: (a) legacy comma-string on `item.tags` for
    # backward compat, and (b) normalized rows on the M:N tag table.
    # `_sync_bank_tags` de-dupes by casefold and creates missing tags
    # scoped to the current school. (Ticket P1-8)
    tags_raw = (request.form.get("tags") or "").strip()
    item.tags = tags_raw
    _sync_bank_tags(item, tags_raw)
    item.subject_id       = request.form.get("subject_id", type=int) or None
    item.grade_id         = request.form.get("grade_id",   type=int) or None
    item.academic_year_id = request.form.get("year_id",    type=int) or None
    item.term_id          = request.form.get("term_id",    type=int) or None
    item.unit_id          = request.form.get("unit_id",    type=int) or None
    item.lesson_id        = request.form.get("lesson_id",  type=int) or None
    # Qdrat-parity pt2 — axis + indicator (2-level skill taxonomy),
    # printable code + anti-piracy UUID (auto-fill on first save).
    item.axis_id       = request.form.get("axis_id",      type=int) or None
    item.indicator_id  = request.form.get("indicator_id", type=int) or None
    item.passage_id    = request.form.get("passage_id",   type=int) or None
    posted_code = (request.form.get("code") or "").strip()
    if posted_code:
        item.code = posted_code
    db.session.flush()
    if is_new:
        import uuid as _uuid
        if not item.uuid:
            item.uuid = str(_uuid.uuid4())
        if not item.code:
            # School prefix + year fragment + row id → "S1-Y26-Q42"
            from datetime import datetime as _dt
            item.code = f"S{item.school_id}-Y{_dt.utcnow().year % 100:02d}-Q{item.id}"

    # Rewrite choices from the form. For mcq/multi/tf we accept parallel
    # choice_label[] and correct_choice[] arrays — index-aligned. For a
    # brand-new mcq/tf with no explicit choices, seed the defaults.
    labels = request.form.getlist("choice_label")
    correct_flags = set(request.form.getlist("choice_correct"))  # values are indices as strings

    # Wipe & rewrite (cascade removes old BankChoice rows).
    for c in list(item.choices):
        db.session.delete(c)
    db.session.flush()

    if kind in ("mcq", "multi", "tf"):
        if not labels:
            if kind == "tf":
                labels = ["صح", "خطأ"]
                correct_flags = {"0"}
            else:
                labels = ["الخيار أ", "الخيار ب", "الخيار ج", "الخيار د"]
                correct_flags = correct_flags or {"0"}
        for i, label in enumerate(labels):
            label = (label or "").strip()
            if not label:
                continue
            db.session.add(BankChoice(
                question_id=item.id, order_index=i + 1, label=label,
                is_correct=(str(i) in correct_flags),
            ))

    db.session.commit()
    flash("تم حفظ السؤال في البنك." if is_new else "تم تعديل السؤال.", "success")
    return redirect(url_for("lms.bank_home"))


@bp.route("/bank/<int:bid>/delete", methods=["POST"], endpoint="bank_delete")
@login_required
def bank_delete(bid):
    item = BankQuestion.query.filter_by(id=bid, school_id=current_user.school_id).first_or_404()
    db.session.delete(item); db.session.commit()
    flash("تم حذف السؤال من البنك.", "success")
    return redirect(url_for("lms.bank_home"))


BANK_STATE_LABEL = {
    "approved":  ("تم اعتماد السؤال.",   "success"),
    "pending":   ("تم إرساله للمراجعة.", "info"),
    "rejected":  ("تم رفض السؤال.",     "warning"),
    "draft":     ("تم إرجاعه لمسودة.",  "info"),
    "no_answer": ("تم وسمه (بدون إجابة).", "warning"),
    "duplicate": ("تم وسمه (متشابه).",  "warning"),
}


@bp.route("/bank/<int:bid>/archive", methods=["POST"], endpoint="bank_archive")
@login_required
def bank_archive(bid):
    """Qdrat-parity #5 — soft-hide a bank question (النشطة ↔ الأرشيف)."""
    item = BankQuestion.query.filter_by(
        id=bid, school_id=current_user.school_id).first_or_404()
    item.is_archived = not item.is_archived
    db.session.commit()
    flash("تم أرشفة السؤال." if item.is_archived else "تم استعادة السؤال.", "success")
    return redirect(request.referrer or url_for("lms.qbank_dashboard"))


@bp.route("/assessment-templates/<int:tid>/items/<int:iid>/toggle-hidden",
          methods=["POST"], endpoint="template_item_toggle_hidden")
@login_required
def template_item_toggle_hidden(tid, iid):
    """Qdrat-parity #8 — soft-hide an item inside a specific template."""
    sid = current_user.school_id
    t = AssessmentTemplate.query.filter_by(
        id=tid, school_id=sid).first_or_404()
    it = AssessmentTemplateItem.query.filter_by(
        id=iid, template_id=t.id).first_or_404()
    it.is_hidden = not it.is_hidden
    db.session.commit()
    flash("تم إخفاء السؤال من النموذج." if it.is_hidden else "تم إظهار السؤال.", "success")
    return redirect(url_for("lms.template_detail", tid=t.id))


@bp.route("/assessment-templates/<int:tid>/ai/generate",
          methods=["POST"], endpoint="template_ai_generate")
@login_required
def template_ai_generate(tid):
    """Qdrat-beat #1 — use DeepSeek to generate N more questions like
    the ones already attached to this template, then land them straight
    into the bank in `pending` review state and attach them here.
    Requires DEEPSEEK_API_KEY in the environment; otherwise 400s with
    a friendly flash."""
    from ...services import deepseek
    sid = current_user.school_id
    t = AssessmentTemplate.query.filter_by(
        id=tid, school_id=sid).first_or_404()

    if not deepseek.is_configured():
        flash("لم يتم تهيئة مفتاح DeepSeek — اطلب من مدير النظام إضافة DEEPSEEK_API_KEY.",
              "warning")
        return redirect(url_for("lms.template_detail", tid=t.id))

    count = max(1, min(10, request.form.get("count", type=int) or 5))
    items = AssessmentTemplateItem.query.filter_by(template_id=t.id).all()
    examples = []
    for it in items[:6]:
        bq = it.bank_question
        if not bq:
            continue
        examples.append({
            "prompt":     bq.prompt,
            "kind":       bq.kind,
            "difficulty": bq.difficulty,
            "points":     float(bq.points or 1),
            "choices": [{"label": c.label, "is_correct": c.is_correct}
                        for c in (bq.choices or [])],
        })
    if not examples:
        flash("أضف على الأقل سؤالاً واحداً للنموذج قبل التوليد.", "warning")
        return redirect(url_for("lms.template_detail", tid=t.id))

    try:
        generated = deepseek.generate_similar_questions(
            examples, count=count,
            subject=t.subject.name if t.subject else None,
        )
    except deepseek.AIError as e:
        current_app.logger.warning("DeepSeek error: %s", e)
        flash(f"تعذّر التوليد الآن: {e}", "danger")
        return redirect(url_for("lms.template_detail", tid=t.id))

    # Land each generated row into the bank in `pending` state so the
    # admin has to accept it — we're never inserting raw AI output as
    # approved content into the exam pool.
    import uuid as _uuid
    from datetime import datetime as _dt
    next_order = 1 + (
        db.session.query(db.func.max(AssessmentTemplateItem.order_index))
        .filter_by(template_id=t.id).scalar() or 0
    )
    added = 0
    for gq in generated:
        prompt = (gq.get("prompt") or "").strip()
        if not prompt:
            continue
        bq = BankQuestion(
            school_id=sid,
            created_by_id=getattr(current_user, "id", None),
            subject_id=t.subject_id,
            grade_id=t.grade_id,
            kind=gq.get("kind") or "mcq",
            prompt=prompt,
            points=Decimal(str(gq.get("points") or 1)),
            difficulty=gq.get("difficulty") or "medium",
            review_state="pending",
            source="school",
            uuid=str(_uuid.uuid4()),
        )
        db.session.add(bq)
        db.session.flush()
        bq.code = f"S{sid}-Y{_dt.utcnow().year % 100:02d}-AI{bq.id}"
        for i, c in enumerate(gq.get("choices") or []):
            db.session.add(BankChoice(
                question_id=bq.id, order_index=i + 1,
                label=(c.get("label") or "").strip(),
                is_correct=bool(c.get("is_correct")),
            ))
        db.session.add(AssessmentTemplateItem(
            template_id=t.id, bank_question_id=bq.id,
            order_index=next_order,
        ))
        next_order += 1
        added += 1
    db.session.commit()
    flash(f"تم توليد {added} سؤالاً بالذكاء الاصطناعي — بحاجة إلى مراجعتك في البنك.",
          "success")
    return redirect(url_for("lms.template_detail", tid=t.id))


@bp.route("/bank/ai-review", methods=["POST"], endpoint="bank_ai_review")
@login_required
def bank_ai_review():
    """Qdrat-beat #3 — batch AI review of the school's `pending` bank
    rows. DeepSeek flags each as ok / duplicate / ambiguous / no_answer,
    and we auto-move duplicates and no-answer rows into their matching
    review_state so the admin only sees the actionable rest."""
    from ...services import deepseek
    sid = current_user.school_id
    if not deepseek.is_configured():
        flash("لم يتم تهيئة مفتاح DeepSeek.", "warning")
        return redirect(url_for("lms.qbank_dashboard"))

    pending = BankQuestion.query.filter_by(
        school_id=sid, source="school", review_state="pending",
    ).limit(30).all()
    if not pending:
        flash("لا أسئلة قيد المراجعة حالياً.", "info")
        return redirect(url_for("lms.qbank_dashboard"))

    payload = [{"id": q.id, "prompt": q.prompt} for q in pending]
    try:
        findings = deepseek.review_pending_questions(payload)
    except deepseek.AIError as e:
        flash(f"تعذّرت المراجعة الآن: {e}", "danger")
        return redirect(url_for("lms.qbank_dashboard"))

    by_id = {q.id: q for q in pending}
    changed = 0
    for f in findings:
        q = by_id.get(int(f.get("id", 0)))
        if not q:
            continue
        target = (f.get("suggested_state") or "").strip()
        if target in {"duplicate", "no_answer", "approved", "rejected"}:
            q.review_state = target
            q.review_notes = (f.get("note") or "")[:500]
            changed += 1
    db.session.commit()
    flash(f"راجع الذكاء الاصطناعي {len(findings)} سؤالاً — تم نقل {changed} إلى حالتها الصحيحة.",
          "success")
    return redirect(url_for("lms.qbank_dashboard"))


@bp.route("/quizzes/<int:qid>/analysis", endpoint="quiz_analysis")
@login_required
def quiz_analysis(qid):
    """Teacher-facing post-exam analysis. Aggregates per-question correct
    percentages across every submitted attempt, then (if DeepSeek is
    configured) asks the LLM for weak topics + remediation. Renders the
    Stitch lms_11 card."""
    from ...services import deepseek
    from ...models import Answer as _Ans
    quiz = Quiz.query.get_or_404(qid)
    if quiz.course.school_id != current_user.school_id:
        abort(403)

    attempts = QuizAttempt.query.filter(
        QuizAttempt.quiz_id == quiz.id,
        QuizAttempt.submitted_at.isnot(None),
    ).all()
    student_count = len({a.student_id for a in attempts})

    # Per-question stats + per-choice distribution (P1-13).
    # `bad_key_alert=True` when a plurality of students picked a choice
    # the teacher didn't mark correct — strong signal the answer key is
    # wrong. `topic` (P1-14) comes from the source BankQuestion.unit /
    # lesson when available, not text-slicing the prompt.
    q_stats = []
    for q in quiz.questions:
        answered = _Ans.query.join(QuizAttempt).filter(
            QuizAttempt.quiz_id == quiz.id,
            QuizAttempt.submitted_at.isnot(None),
            _Ans.question_id == q.id,
        ).all()
        n = len(answered)
        correct = sum(1 for a in answered if a.is_correct)
        pct = int(round(correct / n * 100)) if n else 0

        choice_dist = []
        bad_key_alert = False
        if q.kind in ("mcq", "tf") and q.choices:
            tallies = {c.id: 0 for c in q.choices}
            for a in answered:
                if a.choice_id in tallies:
                    tallies[a.choice_id] += 1
            for c in q.choices:
                cnt = tallies.get(c.id, 0)
                choice_dist.append({
                    "label":      c.label,
                    "count":      cnt,
                    "pct":        int(round(cnt / n * 100)) if n else 0,
                    "is_correct": bool(c.is_correct),
                })
            # Bad-key alert: any non-correct choice got >60% + more
            # than the correct one — key is almost certainly wrong.
            top_wrong = max(
                (d for d in choice_dist if not d["is_correct"]),
                key=lambda d: d["pct"], default=None,
            )
            top_right = max(
                (d for d in choice_dist if d["is_correct"]),
                key=lambda d: d["pct"], default=None,
            )
            if (top_wrong and top_right
                    and top_wrong["pct"] >= 60
                    and top_wrong["pct"] > top_right["pct"]):
                bad_key_alert = True

        topic = (q.prompt.split("؟")[0][:40] if q.prompt else "")
        bank = (BankQuestion.query.get(q.source_bank_id)
                if getattr(q, "source_bank_id", None) else None)
        if bank:
            if bank.unit and bank.lesson:
                topic = f"{bank.unit.title} — {bank.lesson.title}"
            elif bank.unit:
                topic = bank.unit.title
            elif bank.lesson:
                topic = bank.lesson.title

        q_stats.append({
            "prompt":         q.prompt[:120],
            "correct_pct":    pct,
            "topic":          topic,
            "attempts":       n,
            "choice_dist":    choice_dist,
            "bad_key_alert":  bad_key_alert,
        })
    # Compute score bands.
    scores = [float(a.score or 0) for a in attempts if a.score is not None]
    total_max = sum(float(q.points or 0) for q in quiz.questions) or 1
    pct_scores = [s / total_max * 100 for s in scores]
    kpi = {
        "avg":  int(round(sum(pct_scores)/len(pct_scores))) if pct_scores else 0,
        "max":  int(round(max(pct_scores))) if pct_scores else 0,
        "min":  int(round(min(pct_scores))) if pct_scores else 0,
        "students_at_risk": sum(1 for p in pct_scores if p < 50),
    }
    weak_qs = sorted([qs for qs in q_stats if qs["attempts"] > 0],
                     key=lambda x: x["correct_pct"])[:4]

    ai = None
    ai_error = None
    if deepseek.is_configured() and q_stats:
        try:
            ai = deepseek.summarize_exam_results(quiz.title, q_stats)
        except deepseek.AIError as e:
            ai_error = str(e)

    bad_key_qs = [qs for qs in q_stats if qs["bad_key_alert"]]

    return render_template("lms/quiz_analysis.html",
                           quiz=quiz, kpi=kpi, weak_qs=weak_qs,
                           q_stats=q_stats, bad_key_qs=bad_key_qs,
                           student_count=student_count, ai=ai, ai_error=ai_error)


# Passages were split into ./passages.py (ticket P1-18).


@bp.route("/bank/<int:bid>/rewrite", endpoint="bank_rewrite_panel")
@login_required
def bank_rewrite_panel(bid):
    """Renders the Stitch lms_8 AI rewriter drawer as a full page."""
    sid = current_user.school_id
    q = BankQuestion.query.filter_by(id=bid, school_id=sid).first_or_404()
    return render_template("lms/bank_rewrite.html", question=q)


@bp.route("/bank/<int:bid>/ai-rewrite",
          methods=["POST"], endpoint="bank_ai_rewrite")
@login_required
def bank_ai_rewrite(bid):
    """Return the AI-rewritten version of a bank question as JSON — the
    drawer decides whether to save-as-copy or replace-in-place."""
    from ...services import deepseek
    sid = current_user.school_id
    q = BankQuestion.query.filter_by(id=bid, school_id=sid).first_or_404()
    if not deepseek.is_configured():
        return jsonify({"error": "لم يتم تهيئة مفتاح DeepSeek."}), 400
    body = request.get_json(silent=True) or request.form
    directive = (body.get("directive") or "").strip() or "أعد صياغة السؤال بشكل أوضح."
    src = {
        "prompt": q.prompt, "kind": q.kind,
        "difficulty": q.difficulty,
        "points": float(q.points or 1),
        "correct_short": q.correct_short or "",
        "choices": [{"label": c.label, "is_correct": c.is_correct}
                    for c in (q.choices or [])],
    }
    try:
        rewritten = deepseek.rewrite_question(src, directive)
        return jsonify({"original": src, "rewritten": rewritten})
    except deepseek.AIError as e:
        return jsonify({"error": str(e)}), 502


@bp.route("/bank/<int:bid>/ai-rewrite/save",
          methods=["POST"], endpoint="bank_ai_rewrite_save")
@login_required
def bank_ai_rewrite_save(bid):
    """Persist an AI-rewritten question. mode=copy → new BankQuestion in
    `pending`; mode=replace → mutate the original + bump version."""
    sid = current_user.school_id
    q = BankQuestion.query.filter_by(id=bid, school_id=sid).first_or_404()
    mode = (request.form.get("mode") or "copy").strip()
    prompt = (request.form.get("prompt") or "").strip()
    if not prompt:
        flash("لا يوجد نص لحفظه.", "danger")
        return redirect(url_for("lms.bank_edit", bid=q.id))
    kind = request.form.get("kind") or q.kind
    labels = request.form.getlist("choice_label")
    correct_flags = set(request.form.getlist("choice_correct"))

    def _rewrite_choices(target):
        for c in list(target.choices):
            db.session.delete(c)
        db.session.flush()
        for i, label in enumerate(labels):
            if not (label or "").strip():
                continue
            db.session.add(BankChoice(
                question_id=target.id, order_index=i + 1,
                label=label.strip(),
                is_correct=(str(i) in correct_flags),
            ))

    if mode == "replace":
        q.prompt = prompt
        q.kind = kind
        db.session.flush()
        _rewrite_choices(q)
        db.session.commit()
        flash("تم استبدال السؤال بالنسخة المعدّلة.", "success")
        return redirect(url_for("lms.bank_edit", bid=q.id))

    import uuid as _uuid
    from datetime import datetime as _dt
    new_q = BankQuestion(
        school_id=sid,
        created_by_id=getattr(current_user, "id", None),
        subject_id=q.subject_id, grade_id=q.grade_id,
        kind=kind, prompt=prompt,
        points=q.points, correct_short=q.correct_short or "",
        difficulty=q.difficulty, review_state="pending",
        source="school", uuid=str(_uuid.uuid4()),
    )
    db.session.add(new_q); db.session.flush()
    new_q.code = f"S{sid}-Y{_dt.utcnow().year % 100:02d}-AI{new_q.id}"
    _rewrite_choices(new_q)
    db.session.commit()
    flash("تم حفظ نسخة جديدة بحالة قيد المراجعة.", "success")
    return redirect(url_for("lms.bank_edit", bid=new_q.id))


@bp.route("/submissions/<int:sid>/grade", endpoint="submission_grade_panel")
@login_required
def submission_grade_panel(sid):
    """Renders the Stitch lms_10 AI grading sidebar as a full page."""
    from ...models import Submission
    school_sid = current_user.school_id
    sub = Submission.query.get_or_404(sid)
    if sub.assignment.course.school_id != school_sid:
        abort(403)
    return render_template("lms/submission_grade.html", submission=sub)


@bp.route("/submissions/<int:sid>/grade/save",
          methods=["POST"], endpoint="submission_grade_save")
@login_required
def submission_grade_save(sid):
    """Save teacher grades. Two modes:
      · Free-form  → single `score` + `feedback`.
      · Rubric     → per-criterion `criterion_<id>` scores (+ optional
                     `criterion_note_<id>`), rolled up into a weighted
                     total using each RubricCriterion.weight."""
    from ...models import Submission, RubricScore, RubricCriterion
    school_sid = current_user.school_id
    sub = Submission.query.get_or_404(sid)
    if sub.assignment.course.school_id != school_sid:
        abort(403)

    rubric = sub.assignment.rubric if hasattr(sub.assignment, "rubric") else None
    if rubric and rubric.criteria:
        # Rubric grading — replace prior RubricScore rows for this
        # submission and roll up to sub.score using criterion weights
        # (falling back to a straight avg when weights sum to zero).
        RubricScore.query.filter_by(submission_id=sub.id).delete()
        db.session.flush()
        weighted_sum = Decimal(0)
        weight_total = Decimal(0)
        raw_sum      = Decimal(0)
        raw_max      = Decimal(0)
        for c in rubric.criteria:
            raw = request.form.get(f"criterion_{c.id}")
            if raw is None or str(raw).strip() == "":
                continue
            try:
                score = Decimal(str(raw))
            except Exception:
                continue
            note = (request.form.get(f"criterion_note_{c.id}") or "").strip()
            db.session.add(RubricScore(
                criterion_id=c.id, submission_id=sub.id,
                score=score, comment=note,
                graded_by_id=getattr(current_user, "id", None),
            ))
            w    = Decimal(str(c.weight or 0))
            mx   = Decimal(str(c.max_score or 100)) or Decimal(1)
            raw_sum += score
            raw_max += mx
            if w > 0:
                weighted_sum += (score / mx) * w
                weight_total += w
        max_score = Decimal(str(sub.assignment.max_score or 100))
        if weight_total > 0:
            sub.score = (weighted_sum / weight_total) * max_score
        elif raw_max > 0:
            sub.score = (raw_sum / raw_max) * max_score
        else:
            sub.score = Decimal(0)
    else:
        try:
            sub.score = Decimal(request.form.get("score") or "0")
        except Exception:
            sub.score = None

    sub.feedback = (request.form.get("feedback") or "").strip()
    sub.graded_by_id = getattr(current_user, "id", None)
    sub.graded_at = datetime.now(timezone.utc)
    db.session.commit()
    flash("تم اعتماد التصحيح وإرساله للطالب.", "success")
    return redirect(url_for("lms.assignments_home"))


@bp.route("/submissions/<int:sid>/ai-grade",
          methods=["POST"], endpoint="submission_ai_grade")
@login_required
def submission_ai_grade(sid):
    """AI-grade a free-form Submission (essay/short). Returns suggested
    {score, feedback, key_points} as JSON. Actual save is a follow-up
    POST to `submission_ai_grade_save`."""
    from ...services import deepseek
    from ...models import Submission
    school_sid = current_user.school_id
    sub = Submission.query.get_or_404(sid)
    if sub.assignment.course.school_id != school_sid:
        abort(403)
    if not deepseek.is_configured():
        return jsonify({"error": "لم يتم تهيئة مفتاح DeepSeek."}), 400
    prompt = sub.assignment.title
    # Prefer the real Rubric object when the assignment is linked to one
    # — the AI grader gets the actual criteria (title, description,
    # weight, max_score) as structured data, not the free-form
    # instructions string.
    rubric_obj = sub.assignment.rubric
    if rubric_obj and rubric_obj.criteria:
        rubric_payload = {
            "title": rubric_obj.title,
            "description": rubric_obj.description or "",
            "criteria": [
                {
                    "id": c.id,
                    "title": c.title,
                    "description": c.description or "",
                    "weight": float(c.weight or 0),
                    "max_score": float(c.max_score or 100),
                }
                for c in rubric_obj.criteria
            ],
        }
    else:
        rubric_payload = sub.assignment.instructions or ""
    student_answer = (sub.body or "").strip() or "—"
    max_points = float(sub.assignment.max_score or 100)
    try:
        data = deepseek.grade_free_form_answer(
            prompt, student_answer, max_points, rubric_payload,
        )
        return jsonify(data)
    except deepseek.AIError as e:
        return jsonify({"error": str(e)}), 502


@bp.route("/exams/blueprint/ai-suggest",
          methods=["POST"], endpoint="blueprint_ai_suggest")
@login_required
def blueprint_ai_suggest():
    """Qdrat-beat #2 — ask DeepSeek for an easy/medium/hard/very_hard
    split for a given (subject, grade, total). Returns JSON so the
    Blueprint form can populate its sliders client-side."""
    from ...services import deepseek
    if not deepseek.is_configured():
        return jsonify({"error": "DEEPSEEK_API_KEY not configured"}), 400
    body = request.get_json(silent=True) or request.form
    subject = (body.get("subject") or "").strip() or "عام"
    grade   = (body.get("grade") or "").strip() or "الابتدائي"
    total   = int(body.get("total") or 20)
    try:
        mix = deepseek.suggest_blueprint_mix(subject, grade, total)
        return jsonify(mix)
    except deepseek.AIError as e:
        return jsonify({"error": str(e)}), 502


@bp.route("/assessment-templates/<int:tid>/print", endpoint="template_print")
@login_required
def template_print(tid):
    """Qdrat-parity #4 — print-friendly render of every attached question.
    ?mode=continuous → questions flow; ?mode=per-page → page-break per Q."""
    sid = current_user.school_id
    t = AssessmentTemplate.query.filter_by(
        id=tid, school_id=sid).first_or_404()
    items = [
        it for it in AssessmentTemplateItem.query.filter_by(template_id=t.id)
        .order_by(AssessmentTemplateItem.order_index).all()
        if not it.is_hidden
    ]
    mode = "per-page" if (request.args.get("mode") == "per-page") else "continuous"
    return render_template("lms/template_print.html",
                           template=t, items=items, mode=mode)


@bp.route("/bank/<int:bid>/state", methods=["POST"], endpoint="bank_set_state")
@login_required
def bank_set_state(bid):
    """Move a bank question through the Qdrat-parity review workflow.
    The classic /bank UI just shows the current state; this endpoint is
    what the Stitch qbank_dashboard uses to actually drive transitions
    from the row's inline action buttons."""
    item = BankQuestion.query.filter_by(
        id=bid, school_id=current_user.school_id).first_or_404()
    new_state = (request.form.get("state") or "").strip()
    if new_state not in BANK_STATE_LABEL:
        abort(400)
    item.review_state = new_state
    note = (request.form.get("note") or "").strip()
    if note:
        item.review_notes = note
    db.session.commit()
    msg, category = BANK_STATE_LABEL[new_state]
    flash(msg, category)
    return redirect(request.referrer or url_for("lms.qbank_dashboard"))


# --- Picker: pull questions from the bank into a specific quiz -----------

@bp.route("/quizzes/<int:qid>/pick", methods=["GET", "POST"], endpoint="quiz_pick_from_bank")
@login_required
def quiz_pick_from_bank(qid):
    """GET: filterable list of bank rows with checkboxes.
    POST: for each ticked bank id, clone the BankQuestion + its BankChoices
    into fresh Question + Choice rows attached to this quiz.

    Cloning (not referencing) is deliberate — a bank edit later must NOT
    silently change an in-flight quiz, and a bank deletion must not remove
    questions students already saw. `Question.source_bank_id` keeps the
    audit trail. Duplicate picks are skipped so the teacher can safely
    re-run the picker.
    """
    quiz = Quiz.query.get_or_404(qid)

    if request.method == "POST":
        picked_ids = [int(x) for x in request.form.getlist("bank_ids") if x.isdigit()]
        if not picked_ids:
            flash("لم يتم اختيار أي سؤال.", "warning")
            return redirect(url_for("lms.quiz_pick_from_bank", qid=quiz.id))

        # skip anything already cloned into this quiz
        existing_sources = {
            q.source_bank_id for q in quiz.questions if q.source_bank_id
        }
        # Defense-in-depth for ticket P0-3 — mirror the picker's
        # approved+non-archived filter on the POST side so a stale
        # bank_id can't sneak a rejected row into the live quiz.
        pool = BankQuestion.query.filter(
            BankQuestion.school_id == current_user.school_id,
            BankQuestion.review_state == "approved",
            BankQuestion.is_archived == False,  # noqa: E712
            BankQuestion.id.in_(picked_ids),
        ).all()

        last = max((qq.order_index for qq in quiz.questions), default=0)
        added = 0
        skipped = 0
        for bq in pool:
            if bq.id in existing_sources:
                skipped += 1
                continue
            last += 1
            q = Question(
                quiz_id=quiz.id,
                order_index=last,
                kind=bq.kind,
                prompt=bq.prompt,
                points=bq.points or Decimal("1"),
                correct_short=bq.correct_short or "",
                source_bank_id=bq.id,
            )
            db.session.add(q); db.session.flush()
            for bc in bq.choices:
                db.session.add(Choice(
                    question_id=q.id,
                    order_index=bc.order_index,
                    label=bc.label,
                    is_correct=bc.is_correct,
                ))
            added += 1

        db.session.commit()
        msg = f"تمت إضافة {added} سؤال."
        if skipped:
            msg += f" (تم تجاهل {skipped} سؤال موجود مسبقاً في هذا الاختبار.)"
        flash(msg, "success" if added else "warning")
        return redirect(url_for("lms.quiz_questions", qid=quiz.id))

    # GET
    items = _bank_query().limit(300).all()
    subjects, grades, years, terms = _bank_filter_options()
    already = {q.source_bank_id for q in quiz.questions if q.source_bank_id}
    return render_template(
        "lms/bank_picker.html",
        quiz=quiz, items=items, already=already,
        subjects=subjects, grades=grades, years=years, terms=terms,
        selected={
            "subject_id": request.args.get("subject_id", type=int),
            "grade_id":   request.args.get("grade_id",   type=int),
            "year_id":    request.args.get("year_id",    type=int),
            "term_id":    request.args.get("term_id",    type=int),
            "unit_id":    request.args.get("unit_id",    type=int),
            "lesson_id":  request.args.get("lesson_id",  type=int),
            "difficulty": request.args.get("difficulty", ""),
            "kind":       request.args.get("kind", ""),
            "tag":        (request.args.get("tag") or "").strip(),
            "q":          (request.args.get("q")   or "").strip(),
        },
    )


# ─── Assignment submission (existing student flow, unchanged) ─────────────

@bp.route("/assignments/<int:aid>", methods=["GET"], endpoint="assignment_detail")
@login_required
def assignment_detail(aid):
    """Assignment detail + submission form (student view)."""
    a = CourseAssignment.query.get_or_404(aid)
    student = _current_student()
    submission = None
    if student:
        submission = Submission.query.filter_by(
            assignment_id=a.id, student_id=student.id
        ).first()
    return render_template(
        "lms/assignment_detail.html",
        assignment=a, student=student, submission=submission,
        now=_tz_safe_now(a.due_at),
        past_due=_past_due(a.due_at),
    )


@bp.route("/assignments/<int:aid>/submit", methods=["POST"], endpoint="assignment_submit")
@login_required
def assignment_submit(aid):
    """Accept a student's submission (body text + optional file upload).
    Deadline is enforced: if past due AND allow_late is False → 400.
    """
    a = CourseAssignment.query.get_or_404(aid)
    student = _current_student()
    if not student:
        flash("لا يمكن التسليم — الحساب غير مرتبط بطالب.", "danger")
        return redirect(url_for("lms.assignment_detail", aid=a.id))

    now = _tz_safe_now(a.due_at)
    if a.due_at and now > a.due_at and not a.allow_late:
        flash("انتهى موعد التسليم ولا يُسمح بالتسليم المتأخر.", "danger")
        return redirect(url_for("lms.assignment_detail", aid=a.id))

    submission = Submission.query.filter_by(
        assignment_id=a.id, student_id=student.id
    ).first()
    if submission is None:
        submission = Submission(assignment_id=a.id, student_id=student.id)
        db.session.add(submission)

    submission.body = (request.form.get("body") or "").strip()

    # Optional file upload — capped by app.config['MAX_CONTENT_LENGTH'] and
    # by our whitelist. Saved under app/static/uploads/submissions/<aid>/.
    file = request.files.get("attachment")
    if file and file.filename:
        ext = file.filename.rsplit(".", 1)[-1].lower()
        if ext not in ALLOWED_SUBMISSION_EXT:
            flash(f"صيغة الملف .{ext} غير مدعومة.", "danger")
            return redirect(url_for("lms.assignment_detail", aid=a.id))
        safe = secure_filename(file.filename)
        unique = f"{uuid.uuid4().hex[:12]}_{safe}"
        subdir = os.path.join(current_app.static_folder, "uploads", "submissions", str(a.id))
        os.makedirs(subdir, exist_ok=True)
        path = os.path.join(subdir, unique)
        file.save(path)
        submission.file_url = url_for("static", filename=f"uploads/submissions/{a.id}/{unique}")

    # Ticket #19 — lock all AssignmentQuestion rows on first answer.
    if a.questions:
        _now = datetime.now(timezone.utc)
        for q in a.questions:
            if not q.is_locked:
                q.is_locked = True
                q.locked_at = _now
    # Ticket #16 pt 3 — persist + auto-grade quiz-style answers when the
    # assignment carries AssignmentQuestion rows. Mirrors quiz_submit:
    # mcq/multi/tf → auto scored via choice.is_correct; short → normalized
    # string match; essay → left ungraded for the teacher.
    if a.questions:
        db.session.flush()  # ensure submission.id exists
        # Wipe previous answers so an edit-submit doesn't leave stale rows.
        for existing in list(submission.answers):
            db.session.delete(existing)
        db.session.flush()

        auto_total = Decimal(0)
        for q in a.questions:
            ans = AssignmentAnswer(submission_id=submission.id, question_id=q.id)
            if q.kind in ("mcq", "tf"):
                cid = request.form.get(f"q{q.id}_choice", type=int)
                ans.choice_id = cid
                choice = next((c for c in q.choices if c.id == cid), None)
                ans.is_correct = bool(choice and choice.is_correct)
            elif q.kind == "multi":
                picked = set(int(x) for x in request.form.getlist(f"q{q.id}_choices") if x.isdigit())
                correct = {c.id for c in q.choices if c.is_correct}
                all_ids = {c.id for c in q.choices}
                ans.text_answer = ",".join(str(x) for x in sorted(picked))
                ans.is_correct = picked == correct and bool(correct)
                # Assignment-side partial credit mirrors quiz behaviour
                # when the parent assignment's rubric-less quiz-style
                # answers include a partial-credit intent. For now we
                # apply the same ratio unconditionally to `multi` on
                # assignments — it matches the ticket #10 acceptance
                # criteria and matches the pedagogy call.
                if correct:
                    good = len(picked & correct)
                    bad  = len(picked & (all_ids - correct))
                    net  = max(0, good - bad)
                    ratio = Decimal(net) / Decimal(len(correct))
                    ans.awarded_points = (q.points or Decimal(0)) * ratio
                else:
                    ans.awarded_points = Decimal(0)
            elif q.kind == "short":
                text = (request.form.get(f"q{q.id}_text") or "").strip()
                ans.text_answer = text
                ans.is_correct = (
                    _normalize_short_answer(text)
                    == _normalize_short_answer(q.correct_short or "")
                    and bool(q.correct_short)
                )
            elif q.kind == "essay":
                ans.text_answer = (request.form.get(f"q{q.id}_text") or "").strip()
                ans.is_correct = None  # requires manual grading
            if q.kind != "multi":
                ans.awarded_points = (q.points or Decimal(0)) if ans.is_correct else Decimal(0)
            if q.kind != "essay":
                auto_total += ans.awarded_points
            db.session.add(ans)

        # Score is provisional until the teacher grades any essay
        # questions. If there are no essays we can set the final score
        # directly; otherwise leave submission.score NULL so the teacher
        # UI knows it needs review.
        has_essay = any(q.kind == "essay" for q in a.questions)
        if not has_essay:
            submission.score = auto_total

    submission.submitted_at = now

    # Ticket #3 — sync into GradeEntry when the assignment is fully
    # graded (no essay pending) and linked to an auto-syncing
    # AssessmentComponent.
    if a.questions and submission.score is not None:
        try:
            from ...services.lms_sync import sync_assignment_submission
            sync_assignment_submission(submission)
        except Exception:
            current_app.logger.exception("lms_sync assignment failure")

    db.session.commit()
    flash("تم تسليم الواجب بنجاح.", "success")
    return redirect(url_for("lms.assignment_detail", aid=a.id))


# ─── Quiz taking + auto-grader ────────────────────────────────────────────

@bp.route("/quizzes/<int:qid>/take", methods=["GET"], endpoint="quiz_take")
@login_required
def quiz_take(qid):
    """Start-or-continue a quiz attempt. Creates a QuizAttempt if the student
    hasn't started yet and the quiz has not exceeded max_attempts. Renders
    the timed quiz-taking UI."""
    quiz = Quiz.query.get_or_404(qid)
    student = _current_student()
    if not student:
        flash("لا يمكن بدء الاختبار — الحساب غير مرتبط بطالب.", "danger")
        return redirect(url_for("lms.quizzes_home"))

    now = _tz_safe_now(quiz.opens_at or quiz.closes_at)
    if quiz.opens_at and now < quiz.opens_at:
        flash("الاختبار لم يُفتح بعد.", "warning")
        return redirect(url_for("lms.quizzes_home"))
    if quiz.closes_at and now > quiz.closes_at:
        flash("الاختبار مُغلَق.", "warning")
        return redirect(url_for("lms.quizzes_home"))

    # Reuse the latest in-progress attempt if any; otherwise create.
    attempt = (
        QuizAttempt.query
        .filter_by(quiz_id=quiz.id, student_id=student.id)
        .order_by(QuizAttempt.started_at.desc())
        .first()
    )
    if attempt and attempt.submitted_at is None:
        pass  # continue
    else:
        # count completed attempts against the cap
        done = QuizAttempt.query.filter(
            QuizAttempt.quiz_id == quiz.id,
            QuizAttempt.student_id == student.id,
            QuizAttempt.submitted_at.isnot(None),
        ).count()
        if done >= (quiz.max_attempts or 1):
            flash("تجاوزت الحد الأقصى للمحاولات على هذا الاختبار.", "warning")
            return redirect(url_for("lms.quizzes_home"))
        import random as _random
        attempt = QuizAttempt(
            quiz_id=quiz.id, student_id=student.id, started_at=now,
            shuffle_seed=_random.randint(1, 2_000_000_000),
        )
        db.session.add(attempt)
        db.session.commit()

    # Deadline for this attempt = max(quiz.closes_at, started_at+duration).
    from datetime import timedelta
    hard_stop = attempt.started_at + timedelta(minutes=quiz.duration_minutes or 30)
    if quiz.closes_at:
        hard_stop = min(hard_stop, quiz.closes_at)

    questions, ordered_choices = _shuffled_view(quiz, attempt)

    return render_template(
        "lms/quiz_take.html",
        quiz=quiz, attempt=attempt, questions=questions,
        ordered_choices=ordered_choices,
        hard_stop_iso=hard_stop.isoformat() + "Z",
        now=now,
    )


def _shuffled_view(quiz, attempt):
    """Return (questions_in_display_order, {q.id: [choices_in_order]}).

    The permutation is derived from `attempt.shuffle_seed` so the same
    student refreshing the page keeps the same order, while two
    different students (different seeds) see different orders. When the
    quiz has both shuffle flags off this collapses to the natural
    order, so callers can render it unconditionally."""
    import random as _random
    seed = attempt.shuffle_seed or attempt.id or 0
    qs = list(quiz.questions)
    if quiz.shuffle_questions and seed:
        rng = _random.Random(seed)
        rng.shuffle(qs)
    ordered_choices = {}
    for q in qs:
        chs = list(q.choices) if getattr(q, "choices", None) else []
        # tf questions keep their natural (true/false) order — shuffling
        # a two-item T/F is UX noise, not a real anti-cheat.
        if quiz.shuffle_choices and seed and q.kind in ("mcq", "multi"):
            rng = _random.Random(seed * 100003 + (q.id or 0))
            rng.shuffle(chs)
        ordered_choices[q.id] = chs
    return qs, ordered_choices


@bp.route("/quizzes/<int:qid>/submit", methods=["POST"], endpoint="quiz_submit")
@login_required
def quiz_submit(qid):
    """Save the student's answers, auto-grade objective questions (mcq/tf/short),
    leave essay ungraded for the teacher, and stamp the attempt.
    """
    quiz = Quiz.query.get_or_404(qid)
    student = _current_student()
    if not student:
        abort(400)

    attempt_id = int(request.form.get("attempt_id") or 0)
    attempt = QuizAttempt.query.get_or_404(attempt_id)
    if attempt.quiz_id != quiz.id or attempt.student_id != student.id:
        abort(403)
    if attempt.submitted_at is not None:
        flash("سبق تسليم هذه المحاولة.", "warning")
        return redirect(url_for("lms.quizzes_home"))

    total_awarded = Decimal("0")
    autograded_all = True

    # Ticket #19 — on first answer, lock the question so any subsequent
    # teacher edit has to bump the version instead of silently rewriting
    # a prompt students already saw.
    _now = datetime.now(timezone.utc)
    for q in quiz.questions:
        if not q.is_locked:
            q.is_locked = True
            q.locked_at = _now
        # Fetch or create the Answer row for this attempt+question.
        ans = Answer.query.filter_by(
            attempt_id=attempt.id, question_id=q.id
        ).first()
        if ans is None:
            ans = Answer(attempt_id=attempt.id, question_id=q.id)
            db.session.add(ans)

        raw_choice = request.form.get(f"q_{q.id}")
        raw_multi = request.form.getlist(f"q_{q.id}[]")
        raw_text = (request.form.get(f"q_{q.id}_text") or "").strip()

        # mcq / tf: single choice_id
        if q.kind in ("mcq", "tf"):
            ans.choice_id = int(raw_choice) if raw_choice else None
            ans.text_answer = ""
            if ans.choice_id:
                choice = Choice.query.get(ans.choice_id)
                if choice and choice.question_id == q.id:
                    ans.is_correct = bool(choice.is_correct)
                    ans.awarded_points = q.points if ans.is_correct else Decimal("0")
                else:
                    ans.is_correct = False
                    ans.awarded_points = Decimal("0")
            else:
                ans.is_correct = False
                ans.awarded_points = Decimal("0")
            total_awarded += (ans.awarded_points or Decimal("0"))

        # multi: any subset of correct choices. All-or-nothing by
        # default; when the quiz has `allow_partial_credit=True`, we
        # award a proportional slice using the classic "correct picks
        # minus wrong picks, floored at zero, divided by |correct|"
        # rubric — matches how most testbanks handle multi.
        elif q.kind == "multi":
            selected = {int(v) for v in raw_multi if v.isdigit()}
            correct_ids = {c.id for c in q.choices if c.is_correct}
            all_ids = {c.id for c in q.choices}
            ans.choice_id = None
            ans.text_answer = ",".join(str(s) for s in sorted(selected))
            if quiz.allow_partial_credit and correct_ids:
                good = len(selected & correct_ids)
                bad  = len(selected & (all_ids - correct_ids))
                net  = max(0, good - bad)
                ratio = Decimal(net) / Decimal(len(correct_ids))
                pts = (q.points or Decimal("0")) * ratio
                ans.is_correct = (selected == correct_ids)
                ans.awarded_points = pts
            else:
                ok = selected == correct_ids and bool(correct_ids)
                ans.is_correct = ok
                ans.awarded_points = q.points if ok else Decimal("0")
            total_awarded += (ans.awarded_points or Decimal("0"))

        # short: normalized-text match — strip whitespace, drop
        # tashkeel, unify Arabic ↔ Latin digits and lose punctuation
        # before compare. (P1-11)
        elif q.kind == "short":
            ans.choice_id = None
            ans.text_answer = raw_text
            expected = _normalize_short_answer(q.correct_short or "")
            got      = _normalize_short_answer(raw_text)
            ok = bool(expected) and got == expected
            ans.is_correct = ok
            ans.awarded_points = q.points if ok else Decimal("0")
            total_awarded += (ans.awarded_points or Decimal("0"))

        # essay: hold for teacher review
        else:
            ans.choice_id = None
            ans.text_answer = raw_text
            ans.is_correct = None
            ans.awarded_points = None
            autograded_all = False

    attempt.submitted_at = _tz_safe_now(attempt.started_at)
    attempt.score = total_awarded
    attempt.auto_graded = autograded_all

    # Ticket #3 — mirror the score into GradeEntry when the quiz is
    # linked to an auto-syncing AssessmentComponent. Only fires when
    # the attempt is fully auto-graded — an essay awaiting a teacher
    # would leave the SIS side inconsistent otherwise.
    if autograded_all:
        try:
            from ...services.lms_sync import sync_quiz_attempt
            sync_quiz_attempt(attempt)
        except Exception:
            # Sync must never block the student's submission.
            current_app.logger.exception("lms_sync quiz failure")

    db.session.commit()

    flash(
        f"تم تسليم الاختبار. النتيجة الحالية: {total_awarded}"
        + (" (بانتظار تصحيح المعلم للأسئلة المقالية)" if not autograded_all else ""),
        "success",
    )
    return redirect(url_for("lms.quiz_result", attempt_id=attempt.id))


@bp.route("/quizzes/result/<int:attempt_id>", methods=["GET"], endpoint="quiz_result")
@login_required
def quiz_result(attempt_id):
    """Post-submission review: per-question status + total + teacher feedback."""
    attempt = QuizAttempt.query.get_or_404(attempt_id)
    student = _current_student()
    if not student or attempt.student_id != student.id:
        # Teachers/admins can review any attempt within their school;
        # a parent can review one of their own children's attempts.
        role = getattr(getattr(current_user, "role", None), "name", None)
        if role in ("admin", "teacher"):
            pass  # authorized
        elif role == "parent":
            owner = Student.query.get(attempt.student_id)
            if not owner or owner.parent_user_id != current_user.id:
                abort(403)
        else:
            abort(403)
    ans_map = {a.question_id: a for a in attempt.answers}
    total_max = sum((q.points or Decimal(0)) for q in attempt.quiz.questions)
    return render_template(
        "lms/quiz_result.html",
        attempt=attempt, quiz=attempt.quiz, questions=attempt.quiz.questions,
        answers=ans_map, total_max=total_max,
    )


# Announcements were split into ./announcements.py (ticket P1-18).
