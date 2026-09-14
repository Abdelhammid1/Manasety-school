"""LMS auxiliary hubs — assignments, quizzes, announcements landing pages."""
from flask import render_template
from flask_login import login_required, current_user

from . import bp
from ...models import CourseAssignment, Quiz, Announcement


def _school_scope(query, model):
    school_id = getattr(current_user, "school_id", None)
    if school_id and hasattr(model, "school_id"):
        return query.filter(model.school_id == school_id)
    return query


@bp.route("/assignments", endpoint="assignments_home")
@login_required
def assignments_home():
    items = CourseAssignment.query.order_by(CourseAssignment.due_at.asc().nullslast()).limit(100).all()
    return render_template("lms/assignments_home.html", items=items)


@bp.route("/quizzes", endpoint="quizzes_home")
@login_required
def quizzes_home():
    items = Quiz.query.order_by(Quiz.opens_at.asc().nullslast()).limit(100).all()
    return render_template("lms/quizzes_home.html", items=items)


@bp.route("/announcements", endpoint="announcements_home")
@login_required
def announcements_home():
    q = _school_scope(Announcement.query, Announcement)
    items = q.order_by(Announcement.is_pinned.desc(), Announcement.created_at.desc()).limit(100).all()
    return render_template("lms/announcements_home.html", items=items)
