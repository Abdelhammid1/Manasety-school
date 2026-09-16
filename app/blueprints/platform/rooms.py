"""Ticket #7 — Rooms CRUD."""
from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import Room


@bp.route("/rooms", endpoint="rooms_list")
@login_required
@require_permission("sections", "view")
def rooms_list():
    rooms = (
        Room.query.filter_by(school_id=current_user.school_id)
        .order_by(Room.room_type, Room.name).all()
    )
    return render_template("platform/rooms_list.html", rooms=rooms)


@bp.route("/rooms/new", methods=["POST"], endpoint="room_new")
@login_required
@require_permission("sections", "edit")
def room_new():
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("اسم القاعة مطلوب.", "danger")
        return redirect(url_for("platform.rooms_list"))
    r = Room(
        school_id=current_user.school_id, name=name,
        code=(request.form.get("code") or "").strip() or None,
        capacity=request.form.get("capacity", type=int),
        room_type=(request.form.get("room_type") or "classroom").strip(),
    )
    db.session.add(r); db.session.commit()
    flash(f"تم إضافة القاعة ({r.name}).", "success")
    return redirect(url_for("platform.rooms_list"))


@bp.route("/rooms/<int:room_id>/toggle", methods=["POST"], endpoint="room_toggle")
@login_required
@require_permission("sections", "edit")
def room_toggle(room_id):
    r = Room.query.filter_by(id=room_id, school_id=current_user.school_id).first_or_404()
    r.is_active = not r.is_active
    db.session.commit()
    flash("تم تحديث حالة القاعة.", "success")
    return redirect(url_for("platform.rooms_list"))


@bp.route("/rooms/<int:room_id>/delete", methods=["POST"], endpoint="room_delete")
@login_required
@require_permission("sections", "delete")
def room_delete(room_id):
    r = Room.query.filter_by(id=room_id, school_id=current_user.school_id).first_or_404()
    db.session.delete(r); db.session.commit()
    flash("تم حذف القاعة.", "success")
    return redirect(url_for("platform.rooms_list"))
