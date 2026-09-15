"""Courses & Lessons — LMS core."""
import re
from urllib.parse import urlparse, parse_qs

from flask import render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user

from . import bp
from ...extensions import db
from ...models import (
    Course, Lesson, AcademicYear, Section, Subject, Teacher, Grade,
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
    school_id = getattr(current_user, "school_id", None)
    q = Course.query
    if school_id:
        q = q.filter_by(school_id=school_id)
    courses = q.order_by(Course.created_at.desc()).all()
    return render_template("courses/list.html", courses=courses)


@bp.route("/<int:course_id>", endpoint="detail")
@login_required
def detail(course_id):
    course = Course.query.get_or_404(course_id)
    return render_template("courses/detail.html", course=course, lessons=course.lessons)


def _course_form_options():
    """Dropdown option data for the course new/edit form, all school-scoped.

    We want the user to pick meaningful names — never a raw id. So we
    pull the school's academic years (newest first), sections joined to
    their grade (so the label is "الصف — الفصل"), subjects, and teachers.
    """
    sid = getattr(current_user, "school_id", None)

    years = (
        AcademicYear.query.filter_by(school_id=sid)
        .order_by(AcademicYear.start_date.desc()).all()
        if sid else AcademicYear.query.order_by(AcademicYear.start_date.desc()).all()
    )
    sections = (
        Section.query.filter_by(school_id=sid)
        .join(Grade, Grade.id == Section.grade_id)
        .order_by(Grade.order_index, Section.name).all()
        if sid else Section.query.order_by(Section.name).all()
    )
    subjects = (
        Subject.query.filter_by(school_id=sid).order_by(Subject.name).all()
        if sid else Subject.query.order_by(Subject.name).all()
    )
    teachers = (
        Teacher.query.filter_by(school_id=sid, is_active=True)
        .order_by(Teacher.full_name).all()
        if sid else Teacher.query.order_by(Teacher.full_name).all()
    )
    return years, sections, subjects, teachers


@bp.route("/new", methods=["GET", "POST"], endpoint="new")
@login_required
def new():
    years, sections, subjects, teachers = _course_form_options()
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        if not title:
            flash("عنوان المقرّر مطلوب.", "danger")
            return render_template(
                "courses/new.html", years=years, sections=sections,
                subjects=subjects, teachers=teachers,
            )
        c = Course(
            school_id=getattr(current_user, "school_id", 1),
            academic_year_id=request.form.get("academic_year_id", type=int) or (years[0].id if years else 1),
            section_id=request.form.get("section_id", type=int) or (sections[0].id if sections else 1),
            subject_id=request.form.get("subject_id", type=int) or (subjects[0].id if subjects else 1),
            teacher_id=request.form.get("teacher_id", type=int) or None,
            title=title,
            description=(request.form.get("description") or "").strip(),
            is_published=bool(request.form.get("is_published")),
        )
        db.session.add(c)
        db.session.commit()
        flash("تم إنشاء المقرّر بنجاح.", "success")
        return redirect(url_for("courses.detail", course_id=c.id))
    return render_template(
        "courses/new.html",
        years=years, sections=sections, subjects=subjects, teachers=teachers,
    )


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
        lesson.kind = request.form.get("kind", "text")
        lesson.body = request.form.get("body", "")
        lesson.media_url = _embed_url(request.form.get("media_url", ""))
        lesson.duration_minutes = int(request.form.get("duration_minutes") or 0)
        lesson.is_published = bool(request.form.get("is_published"))
        db.session.commit()
        flash("تم حفظ تعديلات الدرس.", "success")
        return redirect(url_for("courses.detail", course_id=course.id))
    return render_template("courses/lesson_new.html", course=course, lesson=lesson)


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
