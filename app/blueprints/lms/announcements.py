"""Announcements module — feed, composer, pin/unpin, delete.

Split out of `views.py` for ticket P1-18. Every route keeps the same
endpoint name so `url_for('lms.…')` continues to resolve."""

from flask import (
    abort, flash, redirect, render_template, request, url_for,
)
from flask_login import login_required, current_user

from . import bp
from ...extensions import db
from ...models import Announcement, Section


def _can_compose_announcement():
    if not current_user.is_authenticated:
        return False
    if getattr(getattr(current_user, "role", None), "name", None) in ("admin", "teacher"):
        return True
    try:
        return bool(current_user.can("portal", "add"))
    except Exception:
        return False


def _load_own_announcement(aid):
    """Fetch an announcement the current user is allowed to modify.
    Admin can touch any of the school's announcements; the author can
    touch theirs."""
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
    """Section discovery for the 'my_section' feed filter."""
    from ...models import Assignment as TeachingAssignment, Enrollment, Student
    role_name = getattr(getattr(current_user, "role", None), "name", None)
    ids = set()
    if role_name == "teacher":
        from ...models import Teacher
        t = Teacher.query.filter_by(user_id=current_user.id).first()
        if t:
            for a in TeachingAssignment.query.filter_by(teacher_id=t.id, is_active=True).all():
                ids.add(a.section_id)
    elif role_name == "parent":
        children = Student.query.filter_by(parent_user_id=current_user.id).all()
        if children:
            for e in Enrollment.query.filter(
                Enrollment.student_id.in_([c.id for c in children]),
                Enrollment.status == "active",
            ).all():
                ids.add(e.section_id)
    return list(ids)


def _school_scope(query, model):
    school_id = getattr(current_user, "school_id", None)
    if school_id and hasattr(model, "school_id"):
        return query.filter(model.school_id == school_id)
    return query


@bp.route("/announcements", methods=["GET"], endpoint="announcements_home")
@login_required
def announcements_home():
    sid = getattr(current_user, "school_id", None)
    q = _school_scope(Announcement.query, Announcement)

    scope = (request.args.get("scope") or "all").strip()
    if scope == "pinned":
        q = q.filter(Announcement.is_pinned.is_(True))
    elif scope == "my_section":
        section_ids = _linked_section_ids()
        if section_ids:
            q = q.filter(Announcement.section_id.in_(section_ids))

    items = q.order_by(
        Announcement.is_pinned.desc(),
        Announcement.created_at.desc(),
    ).limit(100).all()

    sections = []
    if sid:
        sections = Section.query.filter_by(school_id=sid).limit(200).all()

    return render_template(
        "lms/announcements_home.html",
        items=items, scope=scope, sections=sections,
        can_compose=_can_compose_announcement(),
    )


@bp.route("/announcements/new", methods=["POST"], endpoint="announcement_new")
@login_required
def announcement_new():
    """Composer target — school- or section-scoped announcement.

    Ticket P0-1: gated on `_can_compose_announcement` so students and
    parents can't POST-forge school-wide announcements."""
    if not _can_compose_announcement():
        abort(403)
    sid = current_user.school_id
    title = (request.form.get("title") or "").strip()
    body = (request.form.get("body") or "").strip()
    audience = (request.form.get("audience") or "school").strip()
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
