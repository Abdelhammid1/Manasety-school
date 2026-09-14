from collections import defaultdict
from datetime import datetime, time

from flask import abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import (
    AcademicYear, Assignment, Day, Grade, Period, ScheduleSlot,
    Section, Subject, Teacher,
)


def _sid():
    return current_user.school_id


def _active_year():
    return AcademicYear.query.filter_by(school_id=_sid(), status="active").first()


def _get(model, oid):
    obj = model.query.filter_by(id=oid, school_id=_sid()).first()
    if not obj:
        abort(404)
    return obj


# ---------- T-5.1 Time template (days + periods) ----------

@bp.route("/settings", methods=["GET"])
@login_required
@require_permission("schedule", "view")
def settings():
    days = Day.query.filter_by(school_id=_sid()).order_by(Day.order_index).all()
    periods = Period.query.filter_by(school_id=_sid()).order_by(Period.order_index).all()
    return render_template("schedule/settings.html", days=days, periods=periods)


@bp.route("/days/new", methods=["POST"])
@login_required
@require_permission("schedule", "edit")
def day_new():
    day = Day(
        school_id=_sid(),
        name=request.form["name"].strip(),
        order_index=int(request.form["order_index"]),
    )
    db.session.add(day)
    db.session.commit()
    flash(f"تمت إضافة اليوم {day.name}.", "success")
    return redirect(url_for("schedule.settings"))


@bp.route("/days/<int:day_id>/delete", methods=["POST"])
@login_required
@require_permission("schedule", "delete")
def day_delete(day_id):
    day = _get(Day, day_id)
    if ScheduleSlot.query.filter_by(day_id=day.id).first():
        flash("لا يمكن حذف يوم مرتبط بحصص.", "danger")
    else:
        db.session.delete(day)
        db.session.commit()
        flash("تم حذف اليوم.", "success")
    return redirect(url_for("schedule.settings"))


@bp.route("/periods/new", methods=["POST"])
@login_required
@require_permission("schedule", "edit")
def period_new():
    period = Period(
        school_id=_sid(),
        name=request.form["name"].strip(),
        order_index=int(request.form["order_index"]),
        start_time=time.fromisoformat(request.form["start_time"]),
        end_time=time.fromisoformat(request.form["end_time"]),
        is_break=bool(request.form.get("is_break")),
    )
    db.session.add(period)
    db.session.commit()
    flash(f"تمت إضافة {period.name}.", "success")
    return redirect(url_for("schedule.settings"))


@bp.route("/periods/<int:period_id>/delete", methods=["POST"])
@login_required
@require_permission("schedule", "delete")
def period_delete(period_id):
    p = _get(Period, period_id)
    if ScheduleSlot.query.filter_by(period_id=p.id).first():
        flash("لا يمكن حذف حصة مرتبطة بجدول.", "danger")
    else:
        db.session.delete(p)
        db.session.commit()
        flash("تم حذف الحصة.", "success")
    return redirect(url_for("schedule.settings"))


# ---------- T-5.2 / T-5.4 Section schedule ----------

@bp.route("")
@login_required
@require_permission("schedule", "view")
def index():
    year = _active_year()
    sections = []
    teachers = []
    if year:
        sections = (
            Section.query.filter_by(school_id=_sid(), year_id=year.id)
            .join(Grade)
            .order_by(Grade.order_index, Section.name)
            .all()
        )
    teachers = (
        Teacher.query.filter_by(school_id=_sid(), is_active=True)
        .order_by(Teacher.full_name)
        .all()
    )
    return render_template(
        "schedule/index.html", year=year, sections=sections, teachers=teachers
    )


@bp.route("/section/<int:section_id>", methods=["GET", "POST"])
@login_required
@require_permission("schedule", "view")
def section_schedule(section_id):
    section = _get(Section, section_id)
    year = section.year
    days = Day.query.filter_by(school_id=_sid(), is_active=True).order_by(Day.order_index).all()
    periods = (
        Period.query.filter_by(school_id=_sid()).order_by(Period.order_index).all()
    )
    slots = ScheduleSlot.query.filter_by(
        school_id=_sid(), year_id=year.id, section_id=section.id
    ).all()
    grid = {(s.day_id, s.period_id): s for s in slots}

    assignments = (
        Assignment.query.filter_by(
            year_id=year.id, section_id=section.id, is_active=True
        ).all()
    )
    return render_template(
        "schedule/section.html",
        section=section, year=year, days=days, periods=periods,
        grid=grid, assignments=assignments,
    )


@bp.route("/section/<int:section_id>/slot", methods=["POST"])
@login_required
@require_permission("schedule", "edit")
def slot_save(section_id):
    section = _get(Section, section_id)
    year = section.year
    day_id = int(request.form["day_id"])
    period_id = int(request.form["period_id"])
    subject_id = int(request.form["subject_id"])
    teacher_id = int(request.form["teacher_id"])

    # Conflict check: same teacher at same (day, period) in a different section
    conflict = (
        ScheduleSlot.query.filter_by(
            year_id=year.id, day_id=day_id, period_id=period_id, teacher_id=teacher_id,
        )
        .filter(ScheduleSlot.section_id != section.id)
        .first()
    )
    if conflict:
        teacher_name = conflict.teacher.full_name
        other_section = f"{conflict.section.grade.name} / {conflict.section.name}"
        flash(
            f"تعارض: المعلم ({teacher_name}) مسنَد بالفعل لفصل آخر ({other_section}) في نفس اليوم والحصة. تم منع الإسناد.",
            "danger",
        )
        return redirect(url_for("schedule.section_schedule", section_id=section.id))

    slot = ScheduleSlot.query.filter_by(
        year_id=year.id, section_id=section.id, day_id=day_id, period_id=period_id
    ).first()
    if slot:
        slot.subject_id = subject_id
        slot.teacher_id = teacher_id
    else:
        slot = ScheduleSlot(
            school_id=_sid(), year_id=year.id, section_id=section.id,
            day_id=day_id, period_id=period_id,
            subject_id=subject_id, teacher_id=teacher_id,
        )
        db.session.add(slot)
    db.session.commit()
    flash("تم حفظ الحصة.", "success")
    return redirect(url_for("schedule.section_schedule", section_id=section.id))


@bp.route("/section/<int:section_id>/slot/<int:slot_id>/delete", methods=["POST"])
@login_required
@require_permission("schedule", "delete")
def slot_delete(section_id, slot_id):
    section = _get(Section, section_id)
    slot = ScheduleSlot.query.filter_by(id=slot_id, section_id=section.id).first()
    if slot:
        db.session.delete(slot)
        db.session.commit()
        flash("تم حذف الحصة.", "success")
    return redirect(url_for("schedule.section_schedule", section_id=section.id))


# ---------- T-5.5 Auto-schedule generator (Sprint 8, Ticket 1) ----------

def _auto_generate(year):
    """Greedy backtracking scheduler.

    Places `weekly_periods` slots for each active Assignment such that:
      1. no (section, day, period) is double-booked, and
      2. no (teacher, day, period) is double-booked.

    Returns (ok: bool, message: str, placements_count: int).
    On success the DB is updated (existing slots for the year are deleted first).
    """
    sid = year.school_id
    days = (
        Day.query.filter_by(school_id=sid, is_active=True)
        .order_by(Day.order_index).all()
    )
    periods = (
        Period.query.filter_by(school_id=sid, is_break=False)
        .order_by(Period.order_index).all()
    )
    if not days or not periods:
        return False, "لا توجد أيام أو حصص معرّفة. أضفها من إعدادات الجدول أولًا.", 0

    assignments = Assignment.query.filter_by(
        school_id=sid, year_id=year.id, is_active=True
    ).all()
    if not assignments:
        return False, "لا يوجد إسنادات نشطة لتوليد جدول منها.", 0

    total_cells = len(days) * len(periods)

    # Aggregate load per section / teacher for feasibility + heuristic
    section_load = defaultdict(int)
    teacher_load = defaultdict(int)
    for a in assignments:
        section_load[a.section_id] += a.weekly_periods
        teacher_load[a.teacher_id] += a.weekly_periods

    for section_id, load in section_load.items():
        if load > total_cells:
            s = Section.query.get(section_id)
            return (
                False,
                f"الفصل ({s.grade.name} / {s.name}) يحتاج {load} حصة أسبوعيًا "
                f"لكن الجدول يوفّر {total_cells} خانة فقط. راجع عدد الحصص أو الإسنادات.",
                0,
            )
    for teacher_id, load in teacher_load.items():
        if load > total_cells:
            t = Teacher.query.get(teacher_id)
            return (
                False,
                f"المعلم ({t.full_name}) عليه {load} حصة أسبوعيًا "
                f"لكن الجدول يوفّر {total_cells} خانة فقط.",
                0,
            )

    # Expand assignments into individual placements
    placements = []
    for a in assignments:
        placements.extend([a] * a.weekly_periods)

    # Most-constrained-first heuristic:
    #  teachers with the highest load are hardest to place → do them first.
    placements.sort(key=lambda a: (-teacher_load[a.teacher_id], -section_load[a.section_id]))

    cells = [(d.id, p.id) for d in days for p in periods]

    used_section = defaultdict(set)
    used_teacher = defaultdict(set)
    result = []

    def backtrack(idx):
        if idx >= len(placements):
            return True
        a = placements[idx]
        for cell in cells:
            if cell in used_section[a.section_id]:
                continue
            if cell in used_teacher[a.teacher_id]:
                continue
            used_section[a.section_id].add(cell)
            used_teacher[a.teacher_id].add(cell)
            result.append((a, cell[0], cell[1]))
            if backtrack(idx + 1):
                return True
            result.pop()
            used_section[a.section_id].discard(cell)
            used_teacher[a.teacher_id].discard(cell)
        return False

    if not backtrack(0):
        return (
            False,
            "تعذّر توليد جدول متكامل بدون تعارض. جرّب تقليل عدد الحصص "
            "أو أضف أيامًا/حصصًا في إعدادات الجدول.",
            0,
        )

    # Replace existing slots for this year
    ScheduleSlot.query.filter_by(school_id=sid, year_id=year.id).delete()
    for a, day_id, period_id in result:
        db.session.add(ScheduleSlot(
            school_id=sid, year_id=year.id, section_id=a.section_id,
            day_id=day_id, period_id=period_id,
            subject_id=a.subject_id, teacher_id=a.teacher_id,
        ))
    db.session.commit()
    return True, f"تم توليد {len(result)} حصة. يمكنك تعديل أي حصة يدويًا الآن.", len(result)


@bp.route("/auto_generate", methods=["POST"])
@login_required
@require_permission("schedule", "edit")
def auto_generate():
    year = _active_year()
    if not year:
        flash("لا توجد سنة دراسية نشطة.", "danger")
        return redirect(url_for("schedule.index"))
    ok, msg, _ = _auto_generate(year)
    flash(msg, "success" if ok else "danger")
    return redirect(url_for("schedule.index"))


# ---------- T-5.4 Teacher schedule view ----------

@bp.route("/teacher/<int:teacher_id>")
@login_required
@require_permission("schedule", "view")
def teacher_schedule(teacher_id):
    teacher = _get(Teacher, teacher_id)
    year = _active_year()
    days = Day.query.filter_by(school_id=_sid(), is_active=True).order_by(Day.order_index).all()
    periods = Period.query.filter_by(school_id=_sid()).order_by(Period.order_index).all()
    grid = {}
    if year:
        slots = ScheduleSlot.query.filter_by(
            school_id=_sid(), year_id=year.id, teacher_id=teacher.id
        ).all()
        grid = {(s.day_id, s.period_id): s for s in slots}
    return render_template(
        "schedule/teacher.html",
        teacher=teacher, year=year, days=days, periods=periods, grid=grid,
    )
