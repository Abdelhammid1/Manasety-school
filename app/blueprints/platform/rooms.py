"""Ticket #7 — Rooms CRUD + room-centric weekly booking view."""
from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import (
    AcademicYear, Assignment, Day, Period, Room, ScheduleSlot, Section,
)


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

    # Ticket B5 — refuse to delete a Room that's still referenced by
    # any ScheduleSlot. Matches the pattern used by section_delete,
    # grade_delete, term_delete throughout the project.
    from ...models import ScheduleSlot
    n_slots = ScheduleSlot.query.filter_by(room_id=r.id).count()
    if n_slots:
        flash(
            f"لا يمكن حذف القاعة ({r.name}) — محجوزة في {n_slots} حصة. "
            "ألغِ الحجوزات أولاً أو عطّل القاعة بدل حذفها.",
            "danger",
        )
        return redirect(url_for("platform.rooms_list"))

    db.session.delete(r); db.session.commit()
    flash("تم حذف القاعة.", "success")
    return redirect(url_for("platform.rooms_list"))


# ─── Room detail: weekly booking grid + inline slot creator ────────────
#
# Ticket #7 (additional) — a room-centric view of the schedule. Rows are
# periods, columns are days; each cell shows the booking (section +
# subject + teacher) for that timeslot, or an empty-cell form that lets
# the admin book a section straight from here.
#
# Booking here goes through the same conflict checks as the section
# schedule editor — teacher can't be double-booked, room already checked
# because we're editing an existing (year, day, period, room) tuple that
# is unique per definition of "occupied cell".

def _current_year():
    return AcademicYear.query.filter_by(
        school_id=current_user.school_id, status="active",
    ).first()


@bp.route("/rooms/<int:room_id>", endpoint="room_detail")
@login_required
@require_permission("sections", "view")
def room_detail(room_id):
    sid = current_user.school_id
    room = Room.query.filter_by(id=room_id, school_id=sid).first_or_404()
    year = _current_year()
    days = Day.query.filter_by(school_id=sid, is_active=True).order_by(Day.order_index).all()
    periods = Period.query.filter_by(school_id=sid).order_by(Period.order_index).all()

    slots = []
    grid = {}
    assignments = []
    if year:
        slots = ScheduleSlot.query.filter_by(
            school_id=sid, year_id=year.id, room_id=room.id,
        ).all()
        grid = {(s.day_id, s.period_id): s for s in slots}
        # Every active (section × subject × teacher) triple for this year —
        # the admin picks one from a combined dropdown to book a cell.
        assignments = (
            Assignment.query.filter_by(
                school_id=sid, year_id=year.id, is_active=True,
            )
            .join(Section, Section.id == Assignment.section_id)
            .order_by(Section.grade_id, Section.name).all()
        )

    return render_template(
        "platform/room_detail.html",
        room=room, year=year, days=days, periods=periods,
        grid=grid, assignments=assignments,
    )


@bp.route("/rooms/<int:room_id>/slot", methods=["POST"], endpoint="room_slot_save")
@login_required
@require_permission("schedule", "edit")
def room_slot_save(room_id):
    """Book a cell on this room from the room-detail page. Payload is
    a single `assignment_id` (bundling section/subject/teacher) plus
    day + period. Runs the same conflict checks as `schedule.slot_save`.
    """
    sid = current_user.school_id
    room = Room.query.filter_by(id=room_id, school_id=sid).first_or_404()
    year = _current_year()
    if not year:
        flash("لا توجد سنة دراسية نشطة.", "danger")
        return redirect(url_for("platform.room_detail", room_id=room.id))

    day_id = request.form.get("day_id", type=int)
    period_id = request.form.get("period_id", type=int)
    assignment_id = request.form.get("assignment_id", type=int)
    a = Assignment.query.filter_by(id=assignment_id, school_id=sid).first() \
        if assignment_id else None
    if not (day_id and period_id and a):
        flash("بيانات ناقصة — اختر الشعبة/المادة/المعلم.", "danger")
        return redirect(url_for("platform.room_detail", room_id=room.id))

    # Teacher conflict (same teacher, same (day, period), different section).
    teacher_conflict = (
        ScheduleSlot.query.filter_by(
            year_id=year.id, day_id=day_id, period_id=period_id,
            teacher_id=a.teacher_id,
        )
        .filter(ScheduleSlot.section_id != a.section_id)
        .first()
    )
    if teacher_conflict:
        other = f"{teacher_conflict.section.grade.name} / {teacher_conflict.section.name}"
        flash(
            f"تعارض معلم: {a.teacher.full_name} مسنَد لـ ({other}) في نفس اليوم والحصة.",
            "danger",
        )
        return redirect(url_for("platform.room_detail", room_id=room.id))

    # Room already-booked check for THIS room (safety — the cell is
    # rendered as "empty" only when this returns None).
    room_conflict = ScheduleSlot.query.filter_by(
        year_id=year.id, day_id=day_id, period_id=period_id, room_id=room.id,
    ).first()
    if room_conflict:
        flash("هذه الخانة محجوزة بالفعل على هذه القاعة.", "danger")
        return redirect(url_for("platform.room_detail", room_id=room.id))

    # Upsert the section's own slot for (day, period) — if the section
    # already has a slot here with a *different* subject/teacher, we
    # refuse rather than silently overwrite.
    existing = ScheduleSlot.query.filter_by(
        year_id=year.id, section_id=a.section_id, day_id=day_id, period_id=period_id,
    ).first()
    if existing and (existing.subject_id != a.subject_id or existing.teacher_id != a.teacher_id):
        flash(
            "الشعبة عندها حصة مختلفة في نفس التوقيت — عدّلها من جدول الشعبة أولاً.",
            "danger",
        )
        return redirect(url_for("platform.room_detail", room_id=room.id))
    if existing:
        existing.room_id = room.id
    else:
        db.session.add(ScheduleSlot(
            school_id=sid, year_id=year.id, section_id=a.section_id,
            day_id=day_id, period_id=period_id,
            subject_id=a.subject_id, teacher_id=a.teacher_id, room_id=room.id,
        ))
    db.session.commit()
    flash("تم حجز الخانة على هذه القاعة.", "success")
    return redirect(url_for("platform.room_detail", room_id=room.id))


@bp.route("/rooms/<int:room_id>/slot/<int:slot_id>/unbook",
          methods=["POST"], endpoint="room_slot_unbook")
@login_required
@require_permission("schedule", "edit")
def room_slot_unbook(room_id, slot_id):
    """Detach the room from a slot without deleting the section's slot.
    The section still has its subject/teacher for that timeslot — just
    without a room allocation."""
    sid = current_user.school_id
    slot = ScheduleSlot.query.filter_by(
        id=slot_id, school_id=sid, room_id=room_id,
    ).first_or_404()
    slot.room_id = None
    db.session.commit()
    flash("تم إلغاء ربط الحصة بهذه القاعة.", "success")
    return redirect(url_for("platform.room_detail", room_id=room_id))
