"""Courses & Lessons — LMS core."""
from flask import render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user

from . import bp
from ...extensions import db
from ...models import Course, Lesson


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


@bp.route("/new", methods=["GET", "POST"], endpoint="new")
@login_required
def new():
    if request.method == "POST":
        c = Course(
            school_id=getattr(current_user, "school_id", 1),
            academic_year_id=int(request.form.get("academic_year_id", 1)),
            section_id=int(request.form.get("section_id", 1)),
            subject_id=int(request.form.get("subject_id", 1)),
            teacher_id=int(request.form["teacher_id"]) if request.form.get("teacher_id") else None,
            title=request.form["title"].strip(),
            description=request.form.get("description", "").strip(),
        )
        db.session.add(c)
        db.session.commit()
        flash("تم إنشاء المادة بنجاح.", "success")
        return redirect(url_for("courses.detail", course_id=c.id))
    return render_template("courses/new.html")


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
            media_url=request.form.get("media_url", "").strip(),
            duration_minutes=int(request.form.get("duration_minutes") or 0),
        )
        db.session.add(lesson)
        db.session.commit()
        flash("تمت إضافة الدرس.", "success")
        return redirect(url_for("courses.detail", course_id=course.id))
    return render_template("courses/lesson_new.html", course=course)


@bp.route("/lessons/<int:lesson_id>", endpoint="lesson_view")
@login_required
def lesson_view(lesson_id):
    lesson = Lesson.query.get_or_404(lesson_id)
    return render_template("courses/lesson_view.html", lesson=lesson, course=lesson.course)
