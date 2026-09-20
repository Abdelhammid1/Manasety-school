"""Ticket #4 — school calendar routes.

Month view + day CRUD + bulk generators (weekly holidays, term
extents). Attaches to the academic blueprint so it lives under
/academic/calendar.
"""
from datetime import date, timedelta
from calendar import monthrange

from flask import (
    abort, flash, redirect, render_template, request, url_for,
)
from flask_login import current_user, login_required

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import AcademicYear, SchoolCalendarDay, Term


def _sid():
    return current_user.school_id


def _active_year():
    return (
        AcademicYear.query.filter_by(school_id=_sid(), status="active").first()
        or AcademicYear.query.filter_by(school_id=_sid())
        .order_by(AcademicYear.start_date.desc()).first()
    )


@bp.route("/calendar", endpoint="calendar_month")
@login_required
@require_permission("academic_years", "view")
def calendar_month():
    """Month-grid view of a specific academic year. `?month=YYYY-MM`
    selects the month; default is the current month."""
    year = _active_year()
    if not year:
        flash("لا توجد سنة دراسية معرَّفة.", "warning")
        return redirect(url_for("academic.years_list"))

    month_arg = (request.args.get("month") or "").strip()
    try:
        anchor = date.fromisoformat(month_arg + "-01") if month_arg else date.today().replace(day=1)
    except ValueError:
        anchor = date.today().replace(day=1)

    first = anchor.replace(day=1)
    _, last_day = monthrange(first.year, first.month)
    last = first.replace(day=last_day)
    prev_anchor = (first - timedelta(days=1)).replace(day=1)
    next_first = (last + timedelta(days=1))

    # Pull every calendar day in the month across all stages so we can
    # colour each cell — one row per (date, stage) pair.
    rows = (
        SchoolCalendarDay.query.filter(
            SchoolCalendarDay.school_id == _sid(),
            SchoolCalendarDay.academic_year_id == year.id,
            SchoolCalendarDay.date >= first,
            SchoolCalendarDay.date <= last,
        ).order_by(SchoolCalendarDay.date).all()
    )
    by_date = {}
    for r in rows:
        by_date.setdefault(r.date, []).append(r)

    # Build 6×7 grid starting from the Saturday on or before the 1st
    # (school week begins Sunday; header shows Saturday first). Overflow
    # days at the start/end come from adjacent months, marked greyed-out.
    weekday_of_first = first.weekday()          # Mon=0 … Sun=6
    days_before = (weekday_of_first + 2) % 7    # Sat→0, Sun→1, Mon→2, …
    grid_start = first - timedelta(days=days_before)
    cells = []
    for i in range(42):
        d = grid_start + timedelta(days=i)
        cells.append({
            "date": d,
            "in_month": d.month == first.month,
            "entries": by_date.get(d, []),
        })

    return render_template(
        "academic/calendar_month.html",
        year=year, anchor=first, cells=cells,
        prev_month=prev_anchor.isoformat()[:7],
        next_month=next_first.isoformat()[:7],
    )


@bp.route("/calendar/day", methods=["POST"], endpoint="calendar_day_add")
@login_required
@require_permission("academic_years", "edit")
def calendar_day_add():
    """Create one day entry. Idempotent-ish: refuses a duplicate on
    the unique (year, date, stage) triple."""
    year = _active_year()
    if not year:
        flash("لا توجد سنة دراسية.", "danger")
        return redirect(url_for("academic.calendar_month"))
    try:
        d = date.fromisoformat(request.form["date"])
    except (KeyError, ValueError):
        flash("تاريخ غير صالح.", "danger")
        return redirect(url_for("academic.calendar_month"))
    stage = (request.form.get("applies_to_stage") or "").strip() or None
    if SchoolCalendarDay.query.filter_by(
        school_id=_sid(), academic_year_id=year.id, date=d, applies_to_stage=stage
    ).first():
        flash("يوم مسجَّل بالفعل لهذا التاريخ.", "warning")
        return redirect(url_for("academic.calendar_month",
                                month=d.strftime("%Y-%m")))
    day = SchoolCalendarDay(
        school_id=_sid(), academic_year_id=year.id,
        date=d, day_type=(request.form.get("day_type") or "holiday").strip(),
        title=(request.form.get("title") or "").strip() or None,
        description=(request.form.get("description") or "").strip() or None,
        applies_to_stage=stage,
    )
    db.session.add(day); db.session.commit()
    flash(f"تم إضافة {day.title or day.day_type} — {d}.", "success")
    return redirect(url_for("academic.calendar_month", month=d.strftime("%Y-%m")))


@bp.route("/calendar/day/<int:day_id>/delete", methods=["POST"],
          endpoint="calendar_day_delete")
@login_required
@require_permission("academic_years", "delete")
def calendar_day_delete(day_id):
    day = SchoolCalendarDay.query.filter_by(id=day_id, school_id=_sid()).first_or_404()
    d = day.date
    db.session.delete(day); db.session.commit()
    flash("تم حذف اليوم.", "success")
    return redirect(url_for("academic.calendar_month", month=d.strftime("%Y-%m")))


@bp.route("/calendar/clear-weekends", methods=["POST"],
          endpoint="calendar_clear_weekends")
@login_required
@require_permission("academic_years", "delete")
def calendar_clear_weekends():
    """Bulk-delete every auto-generated weekend row for the active year.
    Manually-added holidays/events are preserved."""
    year = _active_year()
    if not year:
        flash("لا توجد سنة دراسية نشطة.", "danger")
        return redirect(url_for("academic.calendar_month"))
    n = SchoolCalendarDay.query.filter_by(
        school_id=_sid(), academic_year_id=year.id, day_type="weekend",
    ).delete(synchronize_session=False)
    db.session.commit()
    flash(f"تم حذف {n} يوم عطلة أسبوعية مُولَّد.", "success")
    return redirect(url_for("academic.calendar_month"))


@bp.route("/calendar/generate", methods=["POST"], endpoint="calendar_generate")
@login_required
@require_permission("academic_years", "edit")
def calendar_generate():
    """Bulk-fill weekly holidays across the whole active year, one
    click. Skips dates that already have a calendar entry to keep
    idempotency safe. weekday_ids come from the checkboxes in the
    generator card (0=Mon … 6=Sun)."""
    year = _active_year()
    if not year:
        flash("لا توجد سنة دراسية نشطة.", "danger")
        return redirect(url_for("academic.calendar_month"))
    weekdays = {int(x) for x in request.form.getlist("weekdays", type=int)}
    if not weekdays:
        flash("اختر أيام الإجازة الأسبوعية.", "warning")
        return redirect(url_for("academic.calendar_month"))
    label = (request.form.get("title") or "عطلة أسبوعية").strip()

    # Existing rows so we don't overwrite manual entries.
    existing = {(r.date, r.applies_to_stage) for r in
                SchoolCalendarDay.query.filter_by(
                    school_id=_sid(), academic_year_id=year.id,
                ).all()}

    d = year.start_date
    added = 0
    while d <= year.end_date:
        if d.weekday() in weekdays and (d, None) not in existing:
            db.session.add(SchoolCalendarDay(
                school_id=_sid(), academic_year_id=year.id,
                date=d, day_type="weekend", title=label,
            ))
            existing.add((d, None)); added += 1
        d += timedelta(days=1)
    db.session.commit()
    flash(f"تم توليد {added} يوم عطلة أسبوعية عبر السنة الدراسية.", "success")
    return redirect(url_for("academic.calendar_month"))
