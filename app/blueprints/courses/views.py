"""Courses & Lessons — LMS core."""
import re
from urllib.parse import urlparse, parse_qs

from flask import render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError

from . import bp
from ...extensions import db
from ...models import (
    Course, CourseSection, Lesson, AcademicYear, Section, Subject, Teacher,
    Grade, Term, Unit, Assignment,
)


# ─── Embed URL normalizer ──────────────────────────────────────────────
#
# Users often paste the "share" URL for YouTube/Vimeo/Google Drive which
# does NOT work inside an iframe. This helper converts those to their
# embed variants so the player renders in one click.
#
def _embed_url(raw: str) -> str:
    """Return an iframe-safe embed URL. Falls back to the input untouched."""
    if not raw:
        return raw
    u = raw.strip()

    # YouTube — watch?v=xxx / youtu.be/xxx / shorts/xxx → /embed/xxx
    m = re.search(
        r'(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)([A-Za-z0-9_-]{6,})',
        u,
    )
    if m:
        vid = m.group(1)
        # keep timestamp t=/start= if present
        t = None
        try:
            q = parse_qs(urlparse(u).query)
            if "t" in q:
                t = q["t"][0]
            elif "start" in q:
                t = q["start"][0]
        except Exception:
            pass
        base = f"https://www.youtube.com/embed/{vid}"
        return f"{base}?start={t}" if t else base

    # Vimeo — vimeo.com/12345 → player.vimeo.com/video/12345
    m = re.search(r'vimeo\.com/(?:video/)?(\d+)', u)
    if m:
        return f"https://player.vimeo.com/video/{m.group(1)}"

    # Google Drive — /file/d/ID/view → /file/d/ID/preview
    m = re.search(r'drive\.google\.com/file/d/([A-Za-z0-9_-]+)', u)
    if m:
        return f"https://drive.google.com/file/d/{m.group(1)}/preview"

    return u


@bp.app_template_filter("embed_url")
def embed_url_filter(value):
    """Jinja: {{ lesson.media_url | embed_url }}."""
    return _embed_url(value or "")


# ─── Course CRUD ───────────────────────────────────────────────────────

@bp.route("/", endpoint="list_courses")
@login_required
def list_courses():
    """Ticket #12 part 2 — level 0 of the hierarchical browse.

    Renders the school's Grades as clickable cards; each card summarises
    how many courses currently live under that grade so the user has a
    quick pulse. The old flat course list is gone; a course card view
    remains available under /courses/grade/<gid>/term/<tid> after the
    user picks a grade and term.
    """
    sid = getattr(current_user, "school_id", None)
    grades = (
        Grade.query.filter_by(school_id=sid).order_by(Grade.order_index).all()
        if sid else Grade.query.order_by(Grade.name).all()
    )
    # Ticket #2 — Course now carries grade_id directly, no join needed.
    counts = {g.id: 0 for g in grades}
    if grades:
        base = db.session.query(Course.grade_id, db.func.count(Course.id))
        if sid:
            base = base.filter(Course.school_id == sid)
        for gid, n in base.group_by(Course.grade_id).all():
            if gid in counts:
                counts[gid] = n
    return render_template("courses/list.html", grades=grades, counts=counts)


@bp.route("/grade/<int:grade_id>", endpoint="grade_terms")
@login_required
def grade_terms(grade_id):
    """Level 1 — pick a term inside a grade. Open terms are highlighted."""
    sid = getattr(current_user, "school_id", None)
    grade = Grade.query.filter_by(id=grade_id, school_id=sid).first_or_404() \
        if sid else Grade.query.get_or_404(grade_id)
    # Terms in the active year (fallback: most recent year).
    year = (
        AcademicYear.query.filter_by(school_id=sid, status="active").first()
        or AcademicYear.query.filter_by(school_id=sid)
        .order_by(AcademicYear.start_date.desc()).first()
    ) if sid else AcademicYear.query.order_by(AcademicYear.start_date.desc()).first()
    terms = (
        Term.query.filter_by(school_id=sid, year_id=year.id)
        .order_by(Term.order_index).all()
        if year else []
    )
    return render_template(
        "courses/grade_terms.html", grade=grade, year=year, terms=terms,
    )


@bp.route("/grade/<int:grade_id>/term/<int:term_id>", endpoint="grade_term_subjects")
@login_required
def grade_term_subjects(grade_id, term_id):
    """Level 2 — subjects available in (grade × term), joined through
    both subject_grades AND subject_terms so a subject only shows here
    when it's flagged for both the grade AND the term."""
    sid = getattr(current_user, "school_id", None)
    grade = Grade.query.filter_by(id=grade_id, school_id=sid).first_or_404()
    term  = Term.query.filter_by(id=term_id,  school_id=sid).first_or_404()

    subjects = (
        Subject.query.filter_by(school_id=sid, is_active=True)
        .join(Subject.grades).filter(Grade.id == grade.id)
        .join(Subject.terms).filter(Term.id == term.id)
        .order_by(Subject.name).all()
    )

    # Ticket #2 — Course is scoped by (year, grade, subject, term) directly.
    # At most one row per subject-term-grade group; template still supports a
    # list but in practice each list has 0 or 1 entries.
    subject_courses = {}
    if subjects:
        year_id = term.year_id
        rows = (
            Course.query
            .filter(Course.school_id == sid,
                    Course.academic_year_id == year_id,
                    Course.grade_id == grade.id,
                    Course.subject_id.in_([s.id for s in subjects]),
                    # Term match — courses w/ NULL term (year-long) match too.
                    db.or_(Course.term_id == term.id, Course.term_id.is_(None)))
            .all()
        )
        for c in rows:
            subject_courses.setdefault(c.subject_id, []).append(c)

    return render_template(
        "courses/grade_term_subjects.html",
        grade=grade, term=term, subjects=subjects,
        subject_courses=subject_courses,
    )


@bp.route("/pick/grade/<int:grade_id>/subject/<int:subject_id>",
          endpoint="course_pick_section")
@login_required
def course_pick_section(grade_id, subject_id):
    """When a subject has courses in multiple sections of the same
    grade, this is the section picker. If only one, we redirect
    straight to the detail page."""
    sid = getattr(current_user, "school_id", None)
    grade = Grade.query.filter_by(id=grade_id, school_id=sid).first_or_404()
    subject = Subject.query.filter_by(id=subject_id, school_id=sid).first_or_404()
    # Ticket #2 — Course now scoped by (year, grade, subject, term). At most
    # one row per (grade, subject) per year; jump straight to it. Multiple
    # rows can only appear if term-per-course is used, and we still list them.
    courses = (
        Course.query.filter_by(
            school_id=sid, grade_id=grade_id, subject_id=subject_id,
        ).all()
    )
    if len(courses) == 1:
        return redirect(url_for("courses.detail", course_id=courses[0].id))
    return render_template(
        "courses/pick_section.html",
        grade=grade, subject=subject, courses=courses,
    )


@bp.route("/<int:course_id>", endpoint="detail")
@login_required
def detail(course_id):
    course = Course.query.get_or_404(course_id)
    # Ticket #2 — resolve teachers per-section via teacher.Assignment.
    # A course's teacher pool = the distinct set of teachers assigned to
    # (course.subject, section, course.year) for any of the course's sections.
    section_ids = [cs.section_id for cs in course.course_sections]
    teachers = []
    if section_ids:
        rows = (
            db.session.query(Teacher)
            .join(Assignment, Assignment.teacher_id == Teacher.id)
            .filter(
                Assignment.year_id == course.academic_year_id,
                Assignment.subject_id == course.subject_id,
                Assignment.section_id.in_(section_ids),
                Assignment.is_active.is_(True),
            )
            .distinct()
            .all()
        )
        teachers = rows
    return render_template("courses/detail.html",
                           course=course, lessons=course.lessons, teachers=teachers)


def _course_form_options():
    """Dropdown option data for the course new/edit form, all school-scoped.

    Ticket #2 — Course now belongs to (year, grade, subject, term); we
    no longer show sections or teachers on the create form. Sections
    are attached separately via CourseSection publications; teacher
    resolution happens at view time via teacher.Assignment.
    """
    sid = getattr(current_user, "school_id", None)

    years = (
        AcademicYear.query.filter_by(school_id=sid)
        .order_by(AcademicYear.start_date.desc()).all()
        if sid else AcademicYear.query.order_by(AcademicYear.start_date.desc()).all()
    )
    grades = (
        Grade.query.filter_by(school_id=sid).order_by(Grade.order_index).all()
        if sid else Grade.query.order_by(Grade.name).all()
    )
    subjects = (
        Subject.query.filter_by(school_id=sid).order_by(Subject.name).all()
        if sid else Subject.query.order_by(Subject.name).all()
    )
    terms = (
        Term.query.filter_by(school_id=sid).order_by(Term.year_id.desc(), Term.order_index).all()
        if sid else Term.query.order_by(Term.name).all()
    )
    return years, grades, subjects, terms


@bp.route("/new", methods=["GET", "POST"], endpoint="new")
@login_required
def new():
    """Create a Course.

    Ticket #2 — Course belongs to (year, grade, subject, term). The
    form asks for grade + subject + optional term. Sections are
    attached separately in a follow-up "publish" step.
    """
    years, grades, subjects, terms = _course_form_options()
    ctx = dict(years=years, grades=grades, subjects=subjects, terms=terms)

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        year_id    = request.form.get("academic_year_id", type=int)
        grade_id   = request.form.get("grade_id",         type=int)
        subject_id = request.form.get("subject_id",       type=int)
        term_id    = request.form.get("term_id",          type=int) or None

        errors = []
        if not title:               errors.append("عنوان المقرّر مطلوب.")
        if not years:               errors.append("لا توجد سنوات دراسية — أضف واحدة من إدارة السنوات.")
        if not grades:              errors.append("لا توجد صفوف — أضف صفاً من إدارة الصفوف.")
        if not subjects:            errors.append("لا توجد مواد — أضف مادة من إدارة المواد.")
        if not year_id    or year_id    not in [y.id for y in years]:    errors.append("اختر سنة دراسية صحيحة.")
        if not grade_id   or grade_id   not in [g.id for g in grades]:   errors.append("اختر صفاً صحيحاً.")
        if not subject_id or subject_id not in [s.id for s in subjects]: errors.append("اختر مادة صحيحة.")
        if term_id and term_id not in [t.id for t in terms]:
            errors.append("اختر ترماً صحيحاً أو اتركه فارغاً للسنة كاملة.")
        if errors:
            for e in errors: flash(e, "danger")
            return render_template("courses/new.html", **ctx)

        c = Course(
            school_id=current_user.school_id,
            academic_year_id=year_id,
            grade_id=grade_id,
            subject_id=subject_id,
            term_id=term_id,
            title=title,
            description=(request.form.get("description") or "").strip(),
            is_published=bool(request.form.get("is_published")),
        )
        db.session.add(c)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash(
                "يوجد مقرّر بنفس (السنة + الصف + المادة + الترم) بالفعل — "
                "افتحه بدلاً من إنشاء جديد.",
                "danger",
            )
            return render_template("courses/new.html", **ctx)

        flash("تم إنشاء المقرّر بنجاح.", "success")
        return redirect(url_for("courses.detail", course_id=c.id))
    return render_template("courses/new.html", **ctx)


@bp.route("/<int:course_id>/delete", methods=["POST"], endpoint="delete")
@login_required
def course_delete(course_id):
    """Hard-delete a Course + its cascaded lessons/assignments/quizzes.

    The Course row is what pins the (year, section, subject) unique
    triple; without delete, a mistyped course blocks any future course
    for the same triple forever. Cascade on Course covers Lesson,
    CourseAssignment, Quiz (defined in lms.py); Submissions, Answers,
    Attempts hang off those and go with them.
    """
    course = Course.query.filter_by(
        id=course_id, school_id=current_user.school_id
    ).first_or_404()
    title = course.title
    db.session.delete(course)
    db.session.commit()
    flash(f"تم حذف المقرّر ({title}) نهائياً.", "success")
    return redirect(url_for("courses.list_courses"))


# ─── Lesson CRUD ───────────────────────────────────────────────────────

def _get_lesson_or_404(lesson_id):
    return Lesson.query.get_or_404(lesson_id)


@bp.route("/<int:course_id>/lessons/new", methods=["GET", "POST"], endpoint="lesson_new")
@login_required
def lesson_new(course_id):
    course = Course.query.get_or_404(course_id)
    if request.method == "POST":
        last = max((l.order_index for l in course.lessons), default=0)
        lesson = Lesson(
            course_id=course.id,
            unit_id=request.form.get("unit_id", type=int) or None,
            order_index=last + 1,
            title=request.form["title"].strip(),
            kind=request.form.get("kind", "text"),
            body=request.form.get("body", ""),
            media_url=_embed_url(request.form.get("media_url", "")),
            duration_minutes=int(request.form.get("duration_minutes") or 0),
            is_published=bool(request.form.get("is_published", "1")),
        )
        db.session.add(lesson)
        db.session.commit()
        flash("تمت إضافة الدرس. اضغط عليه لعرضه.", "success")
        return redirect(url_for("courses.detail", course_id=course.id))
    return render_template("courses/lesson_new.html", course=course, lesson=None)


@bp.route("/lessons/<int:lesson_id>/edit", methods=["GET", "POST"], endpoint="lesson_edit")
@login_required
def lesson_edit(lesson_id):
    """Edit a lesson. Same form template as lesson_new — driven by `lesson` context."""
    lesson = _get_lesson_or_404(lesson_id)
    course = lesson.course
    if request.method == "POST":
        lesson.title = request.form["title"].strip()
        lesson.unit_id = request.form.get("unit_id", type=int) or None
        lesson.kind = request.form.get("kind", "text")
        lesson.body = request.form.get("body", "")
        lesson.media_url = _embed_url(request.form.get("media_url", ""))
        lesson.duration_minutes = int(request.form.get("duration_minutes") or 0)
        lesson.is_published = bool(request.form.get("is_published"))
        db.session.commit()
        flash("تم حفظ تعديلات الدرس.", "success")
        return redirect(url_for("courses.detail", course_id=course.id))
    return render_template("courses/lesson_new.html", course=course, lesson=lesson)


# ─── Unit CRUD (ticket #16 part 1) ────────────────────────────────────

@bp.route("/<int:course_id>/units/new", methods=["POST"], endpoint="unit_new")
@login_required
def unit_new(course_id):
    """Create a Unit within a Course. Minimal form — title only from a
    modal on the course detail page. Description + reorder come later
    via unit_edit."""
    course = Course.query.get_or_404(course_id)
    title = (request.form.get("title") or "").strip()
    if not title:
        flash("عنوان الوحدة مطلوب.", "danger")
        return redirect(url_for("courses.detail", course_id=course.id))
    last = max((u.order_index for u in course.units), default=0)
    unit = Unit(
        course_id=course.id, title=title,
        description=(request.form.get("description") or "").strip(),
        order_index=last + 1,
    )
    db.session.add(unit); db.session.commit()
    flash(f"تمت إضافة الوحدة ({unit.title}).", "success")
    return redirect(url_for("courses.detail", course_id=course.id))


@bp.route("/units/<int:unit_id>/edit", methods=["POST"], endpoint="unit_edit")
@login_required
def unit_edit(unit_id):
    """Update the unit's title/description. POST-only — no separate form
    page; inline edit on the course detail page."""
    unit = Unit.query.get_or_404(unit_id)
    title = (request.form.get("title") or "").strip()
    if not title:
        flash("عنوان الوحدة مطلوب.", "danger")
        return redirect(url_for("courses.detail", course_id=unit.course_id))
    unit.title = title
    unit.description = (request.form.get("description") or "").strip()
    db.session.commit()
    flash("تم تعديل الوحدة.", "success")
    return redirect(url_for("courses.detail", course_id=unit.course_id))


@bp.route("/units/<int:unit_id>/delete", methods=["POST"], endpoint="unit_delete")
@login_required
def unit_delete(unit_id):
    """Hard-delete a unit. Its lessons stay — Lesson.unit_id is set to
    NULL via the schema's ON DELETE SET NULL, so lessons fall back into
    the \"no unit\" bucket for later re-tagging."""
    unit = Unit.query.get_or_404(unit_id)
    course_id = unit.course_id
    db.session.delete(unit); db.session.commit()
    flash("تم حذف الوحدة. الدروس داخلها انتقلت لبند \"بدون وحدة\".", "success")
    return redirect(url_for("courses.detail", course_id=course_id))


@bp.route("/lessons/<int:lesson_id>/delete", methods=["POST"], endpoint="lesson_delete")
@login_required
def lesson_delete(lesson_id):
    lesson = _get_lesson_or_404(lesson_id)
    course_id = lesson.course_id
    db.session.delete(lesson)
    db.session.commit()
    flash("تم حذف الدرس.", "success")
    return redirect(url_for("courses.detail", course_id=course_id))


@bp.route("/lessons/<int:lesson_id>", endpoint="lesson_view")
@login_required
def lesson_view(lesson_id):
    lesson = _get_lesson_or_404(lesson_id)
    return render_template("courses/lesson_view.html", lesson=lesson, course=lesson.course)
