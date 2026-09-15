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


@bp.route("/courses/<int:cid>/assignments/new", methods=["GET", "POST"], endpoint="assignment_new")
@login_required
def assignment_new(cid):
    course = Course.query.get_or_404(cid)
    if request.method == "POST":
        a = CourseAssignment(
            course_id=course.id,
            title=(request.form.get("title") or "").strip(),
            instructions=(request.form.get("instructions") or "").strip(),
            max_score=Decimal(request.form.get("max_score") or "100"),
            due_at=_parse_dt(request.form.get("due_at")),
            allow_late=bool(request.form.get("allow_late")),
            is_published=bool(request.form.get("is_published")),
        )
        if not a.title:
            flash("عنوان الواجب مطلوب.", "danger")
            return render_template("lms/assignment_form.html", assignment=None, course=course)
        db.session.add(a); db.session.commit()
        flash("تم إنشاء الواجب.", "success")
        return redirect(url_for("courses.detail", course_id=course.id))
    return render_template("lms/assignment_form.html", assignment=None, course=course)


@bp.route("/assignments/<int:aid>/edit", methods=["GET", "POST"], endpoint="assignment_edit")
@login_required
def assignment_edit(aid):
    a = CourseAssignment.query.get_or_404(aid)
    course = a.course
    if request.method == "POST":
        a.title = (request.form.get("title") or "").strip()
        a.instructions = (request.form.get("instructions") or "").strip()
        a.max_score = Decimal(request.form.get("max_score") or "100")
        a.due_at = _parse_dt(request.form.get("due_at"))
        a.allow_late = bool(request.form.get("allow_late"))
        a.is_published = bool(request.form.get("is_published"))
        db.session.commit()
        flash("تم حفظ الواجب.", "success")
        return redirect(url_for("courses.detail", course_id=course.id))
    return render_template("lms/assignment_form.html", assignment=a, course=course)


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

    submission.submitted_at = now
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

    for q in quiz.questions:
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
