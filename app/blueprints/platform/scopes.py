"""Ticket #14 — UserScope management + helper."""
from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import User, UserScope, Grade, Section


@bp.route("/scopes/<int:user_id>", methods=["GET", "POST"], endpoint="user_scopes")
@login_required
@require_permission("users", "edit")
def user_scopes(user_id):
    """One page per user — replaces the user's UserScope rows on save."""
    u = User.query.filter_by(id=user_id, school_id=current_user.school_id).first_or_404()
    grades = Grade.query.filter_by(school_id=u.school_id).order_by(Grade.order_index).all()
    sections = Section.query.filter_by(school_id=u.school_id).order_by(Section.name).all()

    if request.method == "POST":
        # Wipe & rewrite.
        UserScope.query.filter_by(user_id=u.id).delete()
        scope_type = (request.form.get("scope_type") or "all_school").strip()
        if scope_type == "all_school":
            db.session.add(UserScope(school_id=u.school_id, user_id=u.id,
                                     scope_type="all_school"))
        elif scope_type == "stage":
            stage = (request.form.get("stage") or "").strip() or None
            db.session.add(UserScope(school_id=u.school_id, user_id=u.id,
                                     scope_type="stage", stage_value=stage))
        elif scope_type == "grade":
            for gid in request.form.getlist("grade_ids", type=int):
                db.session.add(UserScope(school_id=u.school_id, user_id=u.id,
                                         scope_type="grade", scope_value=gid))
        elif scope_type == "section":
            for sid in request.form.getlist("section_ids", type=int):
                db.session.add(UserScope(school_id=u.school_id, user_id=u.id,
                                         scope_type="section", scope_value=sid))
        elif scope_type == "own_assignments":
            db.session.add(UserScope(school_id=u.school_id, user_id=u.id,
                                     scope_type="own_assignments"))
        db.session.commit()
        flash(f"تم حفظ نطاق {u.full_name}.", "success")
        return redirect(url_for("platform.user_scopes", user_id=u.id))

    current = UserScope.query.filter_by(user_id=u.id).all()
    return render_template(
        "platform/user_scopes.html",
        user=u, grades=grades, sections=sections, current=current,
    )
