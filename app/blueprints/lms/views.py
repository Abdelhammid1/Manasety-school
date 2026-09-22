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
    abort, current_app, flash, redirect, render_template, request, url_for,
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
    """Best-effort resolution of the logged-in user → Student row.

    The SIS schema doesn't force a user_id column on Student, so we look up
    the first Student in the school as a dev fallback. Real deployments should
    link Student.parent_user_id + a student.user_id column."""
    uid = getattr(current_user, "id", None)
    if not uid:
        return None
    # Prefer any Student explicitly linked by an id-matching parent (rare) or
    # username-matching permanent code. Fall back to the school's first
    # active enrollment so the demo student can browse in dev.
    if hasattr(Student, "user_id"):
        s = Student.query.filter_by(user_id=uid).first()
        if s:
            return s
    return Student.query.filter_by(school_id=current_user.school_id).first()


def _school_scope(query, model):
    school_id = getattr(current_user, "school_id", None)
    if school_id and hasattr(model, "school_id"):
        return query.filter(model.school_id == school_id)
    return query


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
        pool = BankQuestion.query.filter(
            BankQuestion.school_id == current_user.school_id,
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


# ─── Performance reports (ticket #16 pt 4) ────────────────────────────
#
# Aggregate mastery from AssignmentAnswer + Answer (quiz-side) by
# (subject → unit → lesson). Two views: per-student for parents / the
# teacher, and per-section for the teacher to spot classroom-wide weak
# points.

def _mastery_by_unit(rows):
    """Given an iterable of (unit_id, unit_title, correct_bool,
    awarded_points, max_points) tuples, return a list of dicts
    grouped by unit with percent correct + weight rendered for the UI.
    """
    buckets = {}
    for uid, utitle, is_correct, awarded, max_pts in rows:
        b = buckets.setdefault(uid, {
            "unit_id": uid, "unit_title": utitle,
            "answered": 0, "correct": 0, "max_pts": Decimal(0), "awarded": Decimal(0),
        })
        b["answered"] += 1
        if is_correct: b["correct"] += 1
        b["max_pts"] += Decimal(str(max_pts or 0))
        b["awarded"] += Decimal(str(awarded or 0))
    out = []
    for b in buckets.values():
        pct = int(round((b["correct"] * 100) / b["answered"])) if b["answered"] else 0
        b["percent"] = pct
        b["label"] = "قوة" if pct >= 80 else ("متوسط" if pct >= 60 else "ضعف")
        out.append(b)
    out.sort(key=lambda x: x["percent"], reverse=True)
    return out


@bp.route("/reports/student/<int:student_id>", endpoint="report_student")
@login_required
def report_student(student_id):
    """Per-student mastery per subject × unit."""
    student = Student.query.get_or_404(student_id)

    # Assignment-side answers
    aa_rows = (
        db.session.query(
            Course.subject_id, Subject.name,
            Unit.id, Unit.title,
            AssignmentAnswer.is_correct,
            AssignmentAnswer.awarded_points,
            AssignmentQuestion.points,
        )
        .join(AssignmentQuestion, AssignmentQuestion.id == AssignmentAnswer.question_id)
        .join(CourseAssignment, CourseAssignment.id == AssignmentQuestion.assignment_id)
        .join(Course, Course.id == CourseAssignment.course_id)
        .join(Subject, Subject.id == Course.subject_id)
        .join(Submission, Submission.id == AssignmentAnswer.submission_id)
        .outerjoin(Unit, Unit.id == BankQuestion.unit_id) if False else None
    )
    # Simpler pull without the complex Unit join — walk in Python so
    # we can carry BankQuestion.unit_id/lesson_id on the source_bank_id
    # link. Small enough per student.
    subjects_data = {}
    q = (
        AssignmentAnswer.query
        .join(Submission, Submission.id == AssignmentAnswer.submission_id)
        .filter(Submission.student_id == student.id)
        .all()
    )
    for a in q:
        aq = AssignmentQuestion.query.get(a.question_id)
        if not aq: continue
        ca = aq.assignment
        course = ca.course if ca else None
        subject = course.subject if course else None
        if not subject: continue
        bank = BankQuestion.query.get(aq.source_bank_id) if aq.source_bank_id else None
        unit = bank.unit if bank else None
        u_id = unit.id if unit else 0
        u_title = unit.title if unit else "بدون وحدة"

        subjects_data.setdefault(subject.id, {
            "subject_id": subject.id, "subject_name": subject.name, "rows": [],
        })["rows"].append((u_id, u_title, bool(a.is_correct),
                           a.awarded_points or 0, aq.points or 0))

    # Quiz answers, same shape.
    qa = (
        Answer.query
        .join(QuizAttempt, QuizAttempt.id == Answer.attempt_id)
        .filter(QuizAttempt.student_id == student.id)
        .all()
    )
    for a in qa:
        qq = Question.query.get(a.question_id)
        if not qq: continue
        quiz = qq.quiz
        course = quiz.course if quiz else None
        subject = course.subject if course else None
        if not subject: continue
        bank = BankQuestion.query.get(qq.source_bank_id) if getattr(qq, 'source_bank_id', None) else None
        unit = bank.unit if bank else None
        u_id = unit.id if unit else 0
        u_title = unit.title if unit else "بدون وحدة"
        subjects_data.setdefault(subject.id, {
            "subject_id": subject.id, "subject_name": subject.name, "rows": [],
        })["rows"].append((u_id, u_title, bool(a.is_correct),
                           a.awarded_points or 0, qq.points or 0))

    # Aggregate per subject.
    result = []
    for sd in subjects_data.values():
        units = _mastery_by_unit(sd["rows"])
        overall_pct = int(round(sum(u["percent"] for u in units) / len(units))) if units else 0
        result.append({
            "subject_id": sd["subject_id"], "subject_name": sd["subject_name"],
            "units": units, "overall": overall_pct,
            "answered_total": sum(u["answered"] for u in units),
        })
    result.sort(key=lambda x: x["overall"], reverse=True)
    return render_template("lms/report_student.html", student=student, subjects=result)


@bp.route("/reports/section/<int:section_id>", endpoint="report_section")
@login_required
def report_section(section_id):
    """Per-section mastery per subject × unit. Same shape as the
    student report but aggregates across every enrolled student's
    answers."""
    section = Section.query.get_or_404(section_id)
    from ...models import Enrollment
    students = (
        Student.query.join(Enrollment, Enrollment.student_id == Student.id)
        .filter(Enrollment.section_id == section.id, Enrollment.status == "active").all()
    )
    # Rows collected across everyone in the section.
    subjects_data = {}
    for stu in students:
        for a in (AssignmentAnswer.query.join(
                Submission, Submission.id == AssignmentAnswer.submission_id
             ).filter(Submission.student_id == stu.id).all()):
            aq = AssignmentQuestion.query.get(a.question_id)
            if not aq: continue
            ca = aq.assignment; course = ca.course if ca else None
            subject = course.subject if course else None
            if not subject: continue
            bank = BankQuestion.query.get(aq.source_bank_id) if aq.source_bank_id else None
            unit = bank.unit if bank else None
            u_id = unit.id if unit else 0; u_title = unit.title if unit else "بدون وحدة"
            subjects_data.setdefault(subject.id, {
                "subject_id": subject.id, "subject_name": subject.name, "rows": [],
            })["rows"].append((u_id, u_title, bool(a.is_correct), a.awarded_points or 0, aq.points or 0))
        for a in (Answer.query.join(
                QuizAttempt, QuizAttempt.id == Answer.attempt_id
             ).filter(QuizAttempt.student_id == stu.id).all()):
            qq = Question.query.get(a.question_id)
            if not qq: continue
            quiz = qq.quiz; course = quiz.course if quiz else None
            subject = course.subject if course else None
            if not subject: continue
            bank = BankQuestion.query.get(qq.source_bank_id) if getattr(qq, 'source_bank_id', None) else None
            unit = bank.unit if bank else None
            u_id = unit.id if unit else 0; u_title = unit.title if unit else "بدون وحدة"
            subjects_data.setdefault(subject.id, {
                "subject_id": subject.id, "subject_name": subject.name, "rows": [],
            })["rows"].append((u_id, u_title, bool(a.is_correct), a.awarded_points or 0, qq.points or 0))

    result = []
    for sd in subjects_data.values():
        units = _mastery_by_unit(sd["rows"])
        overall_pct = int(round(sum(u["percent"] for u in units) / len(units))) if units else 0
        result.append({
            "subject_id": sd["subject_id"], "subject_name": sd["subject_name"],
            "units": units, "overall": overall_pct,
            "answered_total": sum(u["answered"] for u in units),
        })
    result.sort(key=lambda x: x["overall"], reverse=True)
    return render_template(
        "lms/report_section.html",
        section=section, students=students, subjects=result,
    )


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

def _bank_query():
    """Bank rows scoped to the current user's school + optional filters.

    The `source` querystring picks which bank tab is showing:
      · `source=school` (default) → the school's own curriculum bank
      · `source=nafis`            → the ETEC نافس bank
    """
    q = BankQuestion.query.filter_by(school_id=current_user.school_id)
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
    return subjects, grades, years, terms, courses, units, lessons


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

    q = BankQuestion.query.filter_by(school_id=sid, source=source)
    if subject_id: q = q.filter(BankQuestion.subject_id == subject_id)

    total = q.count()
    state_rows = q.with_entities(
        BankQuestion.review_state, db.func.count(BankQuestion.id),
    ).group_by(BankQuestion.review_state).all()
    states = {s: n for s, n in state_rows}
    stats = {
        "total":     total,
        "approved":  states.get("approved", 0),
        "pending":   states.get("pending", 0),
        "draft":     states.get("draft", 0),
        "no_answer": states.get("no_answer", 0),
        "duplicate": states.get("duplicate", 0),
        "rejected":  states.get("rejected", 0),
        "coverage_pct": (states.get("approved", 0) * 100 // total) if total else 0,
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

    # By-subject roll-up.
    by_subject_map = {}
    for r in templates:
        key = r.subject_id or 0
        row = by_subject_map.setdefault(key, {
            "subject_id": r.subject_id,
            "subject_name": (Subject.query.get(r.subject_id).name
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


@bp.route("/bank", endpoint="bank_home")
@login_required
def bank_home():
    """Bank browser — two tabs (School / NAFIS), same page, same filters."""
    items = _bank_query().limit(200).all()
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
    subjects, grades, years, terms, courses, units, lessons = _bank_form_extras()
    return render_template(
        "lms/bank_form.html", item=None,
        subjects=subjects, grades=grades, years=years, terms=terms,
        courses=courses, units=units, lessons=lessons,
    )


@bp.route("/bank/<int:bid>/edit", methods=["GET", "POST"], endpoint="bank_edit")
@login_required
def bank_edit(bid):
    item = BankQuestion.query.filter_by(id=bid, school_id=current_user.school_id).first_or_404()
    if request.method == "POST":
        return _bank_save(item)
    subjects, grades, years, terms, courses, units, lessons = _bank_form_extras(item)
    return render_template(
        "lms/bank_form.html", item=item,
        subjects=subjects, grades=grades, years=years, terms=terms,
        courses=courses, units=units, lessons=lessons,
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
    item.tags = (request.form.get("tags") or "").strip()
    item.subject_id       = request.form.get("subject_id", type=int) or None
    item.grade_id         = request.form.get("grade_id",   type=int) or None
    item.academic_year_id = request.form.get("year_id",    type=int) or None
    item.term_id          = request.form.get("term_id",    type=int) or None
    item.unit_id          = request.form.get("unit_id",    type=int) or None
    item.lesson_id        = request.form.get("lesson_id",  type=int) or None
    db.session.flush()

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
        pool = BankQuestion.query.filter(
            BankQuestion.school_id == current_user.school_id,
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
    subjects, grades, years = _bank_filter_options()
    already = {q.source_bank_id for q in quiz.questions if q.source_bank_id}
    return render_template(
        "lms/bank_picker.html",
        quiz=quiz, items=items, already=already,
        subjects=subjects, grades=grades, years=years,
        selected={
            "subject_id": request.args.get("subject_id", type=int),
            "grade_id":   request.args.get("grade_id",   type=int),
            "year_id":    request.args.get("year_id",    type=int),
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
                ans.text_answer = ",".join(str(x) for x in sorted(picked))
                ans.is_correct = picked == correct and bool(correct)
            elif q.kind == "short":
                text = (request.form.get(f"q{q.id}_text") or "").strip()
                ans.text_answer = text
                ans.is_correct = (
                    text.casefold() == (q.correct_short or "").strip().casefold()
                    and bool(q.correct_short)
                )
            elif q.kind == "essay":
                ans.text_answer = (request.form.get(f"q{q.id}_text") or "").strip()
                ans.is_correct = None  # requires manual grading
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
        attempt = QuizAttempt(
            quiz_id=quiz.id, student_id=student.id, started_at=now,
        )
        db.session.add(attempt)
        db.session.commit()

    # Deadline for this attempt = max(quiz.closes_at, started_at+duration).
    from datetime import timedelta
    hard_stop = attempt.started_at + timedelta(minutes=quiz.duration_minutes or 30)
    if quiz.closes_at:
        hard_stop = min(hard_stop, quiz.closes_at)

    return render_template(
        "lms/quiz_take.html",
        quiz=quiz, attempt=attempt, questions=quiz.questions,
        hard_stop_iso=hard_stop.isoformat() + "Z",
        now=now,
    )


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

        # multi: any subset of correct choices — all-or-nothing
        elif q.kind == "multi":
            selected = {int(v) for v in raw_multi if v.isdigit()}
            correct_ids = {c.id for c in q.choices if c.is_correct}
            ans.choice_id = None
            ans.text_answer = ",".join(str(s) for s in sorted(selected))
            ok = selected == correct_ids and bool(correct_ids)
            ans.is_correct = ok
            ans.awarded_points = q.points if ok else Decimal("0")
            total_awarded += (ans.awarded_points or Decimal("0"))

        # short: exact-match (case-insensitive) against correct_short
        elif q.kind == "short":
            ans.choice_id = None
            ans.text_answer = raw_text
            expected = (q.correct_short or "").strip().lower()
            ok = bool(expected) and raw_text.lower() == expected
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
        # Teachers/admins can review any attempt within their school.
        role = getattr(getattr(current_user, "role", None), "name", None)
        if role not in ("admin", "teacher"):
            abort(403)
    ans_map = {a.question_id: a for a in attempt.answers}
    total_max = sum((q.points or Decimal(0)) for q in attempt.quiz.questions)
    return render_template(
        "lms/quiz_result.html",
        attempt=attempt, quiz=attempt.quiz, questions=attempt.quiz.questions,
        answers=ans_map, total_max=total_max,
    )


# --- Announcements: feed + composer + pin/unpin + delete -----------------

@bp.route("/announcements", methods=["GET"], endpoint="announcements_home")
@login_required
def announcements_home():
    sid = getattr(current_user, "school_id", None)
    q = _school_scope(Announcement.query, Announcement)

    scope = (request.args.get("scope") or "all").strip()
    if scope == "pinned":
        q = q.filter(Announcement.is_pinned.is_(True))
    elif scope == "my_section":
        # if user has a linked teacher/student, filter to their section(s)
        section_ids = _linked_section_ids()
        if section_ids:
            q = q.filter(Announcement.section_id.in_(section_ids))

    items = q.order_by(
        Announcement.is_pinned.desc(),
        Announcement.created_at.desc(),
    ).limit(100).all()

    # Sections the current user can address as audience for the composer
    sections = []
    if sid:
        sections = Section.query.filter_by(school_id=sid).limit(200).all()

    can_compose = bool(
        current_user.is_authenticated and (
            current_user.can("portal", "add")
            or getattr(getattr(current_user, "role", None), "name", None) in ("admin", "teacher")
        )
    )
    return render_template(
        "lms/announcements_home.html",
        items=items, scope=scope, sections=sections,
        can_compose=can_compose,
    )


@bp.route("/announcements/new", methods=["POST"], endpoint="announcement_new")
@login_required
def announcement_new():
    """Composer target — creates a school- or section-scoped announcement."""
    sid = current_user.school_id
    title = (request.form.get("title") or "").strip()
    body = (request.form.get("body") or "").strip()
    audience = (request.form.get("audience") or "school").strip()  # school | section
    section_id = request.form.get("section_id") or None
    is_pinned = bool(request.form.get("is_pinned"))

    if not title:
        flash("العنوان مطلوب.", "danger")
        return redirect(url_for("lms.announcements_home"))
    if audience == "section" and not section_id:
        flash("اختر الفصل المستهدف.", "danger")
        return redirect(url_for("lms.announcements_home"))

    a = Announcement(
        school_id=sid,
        section_id=int(section_id) if audience == "section" else None,
        author_id=current_user.id,
        title=title, body=body, is_pinned=is_pinned,
    )
    db.session.add(a)
    db.session.commit()
    flash("تم نشر الإعلان.", "success")
    return redirect(url_for("lms.announcements_home"))


@bp.route("/announcements/<int:aid>/pin", methods=["POST"], endpoint="announcement_pin")
@login_required
def announcement_pin(aid):
    a = _load_own_announcement(aid)
    a.is_pinned = not a.is_pinned
    db.session.commit()
    flash("تم تحديث حالة التثبيت.", "success")
    return redirect(url_for("lms.announcements_home"))


@bp.route("/announcements/<int:aid>/delete", methods=["POST"], endpoint="announcement_delete")
@login_required
def announcement_delete(aid):
    a = _load_own_announcement(aid)
    db.session.delete(a)
    db.session.commit()
    flash("تم حذف الإعلان.", "success")
    return redirect(url_for("lms.announcements_home"))


# --- helpers -------------------------------------------------------------

def _load_own_announcement(aid):
    """Fetch an announcement that the current user is allowed to modify.
    Admin can touch any of the school's announcements; author can touch theirs.
    """
    a = Announcement.query.filter_by(
        id=aid, school_id=current_user.school_id
    ).first()
    if not a:
        abort(404)
    role_name = getattr(getattr(current_user, "role", None), "name", None)
    if role_name != "admin" and a.author_id != current_user.id:
        abort(403)
    return a


def _linked_section_ids():
    """Best-effort section discovery for 'my_section' filter — parents get
    their children's sections; teachers get their teaching sections; students
    get their own section."""
    from ...models import Assignment as TeachingAssignment, Enrollment, Student
    sid = current_user.school_id
    role_name = getattr(getattr(current_user, "role", None), "name", None)
    ids = set()
    if role_name == "teacher":
        # teacher: teaching-assignment.section_id
        from ...models import Teacher
        t = Teacher.query.filter_by(user_id=current_user.id).first()
        if t:
            for a in TeachingAssignment.query.filter_by(teacher_id=t.id, is_active=True).all():
                ids.add(a.section_id)
    elif role_name == "parent":
        # parent: their children's active enrollments
        children = Student.query.filter_by(parent_user_id=current_user.id).all()
        if children:
            for e in Enrollment.query.filter(
                Enrollment.student_id.in_([c.id for c in children]),
                Enrollment.status == "active",
            ).all():
                ids.add(e.section_id)
    return list(ids)
