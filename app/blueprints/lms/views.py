"""LMS hubs — assignments, quizzes, announcements landing pages + CRUD.

Real backend for the composer, pin toggle, and delete on the announcement feed
so the Stitch design isn't just a static shell."""
from datetime import datetime

from flask import (
    abort, flash, redirect, render_template, request, url_for,
)
from flask_login import login_required, current_user

from . import bp
from ...extensions import db
from ...models import (
    Announcement, CourseAssignment, Quiz, Section,
)


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
