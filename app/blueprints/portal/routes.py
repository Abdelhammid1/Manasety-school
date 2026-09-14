from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import (
    AcademicYear, Assignment, Material, ScheduleSlot, Day, Period,
    Section, Subject, Teacher,
)


def _sid():
    return current_user.school_id


def _active_year():
    return AcademicYear.query.filter_by(school_id=_sid(), status="active").first()


def _teacher_for_current_user():
    return Teacher.query.filter_by(school_id=_sid(), user_id=current_user.id).first()


@bp.route("")
@login_required
@require_permission("portal", "view")
def home():
    teacher = _teacher_for_current_user()
    year = _active_year()
    if not teacher:
        return render_template("portal/not_linked.html")

    days = []
    periods = []
    grid = {}
    sections = []
    if year:
        days = Day.query.filter_by(school_id=_sid(), is_active=True).order_by(Day.order_index).all()
        periods = Period.query.filter_by(school_id=_sid()).order_by(Period.order_index).all()
        slots = ScheduleSlot.query.filter_by(
            school_id=_sid(), year_id=year.id, teacher_id=teacher.id
        ).all()
        grid = {(s.day_id, s.period_id): s for s in slots}

        assignments = Assignment.query.filter_by(
            teacher_id=teacher.id, year_id=year.id, is_active=True
        ).all()
        seen = {}
        for a in assignments:
            if a.section_id not in seen:
                seen[a.section_id] = {"section": a.section, "subjects": []}
            seen[a.section_id]["subjects"].append(a.subject)
        sections = list(seen.values())

    return render_template(
        "portal/home.html",
        teacher=teacher, year=year, days=days, periods=periods, grid=grid,
        sections=sections,
    )


@bp.route("/materials")
@login_required
@require_permission("portal", "view")
def materials():
    teacher = _teacher_for_current_user()
    if not teacher:
        return render_template("portal/not_linked.html")
    items = Material.query.filter_by(school_id=_sid(), teacher_id=teacher.id).order_by(Material.created_at.desc()).all()
    return render_template("portal/materials.html", materials=items, teacher=teacher)


@bp.route("/materials/new", methods=["GET", "POST"])
@login_required
@require_permission("portal", "edit")
def material_new():
    teacher = _teacher_for_current_user()
    if not teacher:
        return render_template("portal/not_linked.html")
    year = _active_year()
    if not year:
        flash("لا توجد سنة دراسية نشطة.", "warning")
        return redirect(url_for("portal.materials"))

    assignments = (
        Assignment.query.filter_by(
            teacher_id=teacher.id, year_id=year.id, is_active=True
        ).all()
    )
    # de-dup (section, subject) pairs for the dropdown
    pairs = []
    seen = set()
    for a in assignments:
        key = (a.section_id, a.subject_id)
        if key in seen: continue
        seen.add(key)
        pairs.append({
            "section_id": a.section_id, "subject_id": a.subject_id,
            "label": f"{a.section.grade.name} / {a.section.name} — {a.subject.name}",
        })

    if request.method == "POST":
        pair = request.form.get("pair", "").split("|")
        if len(pair) != 2:
            flash("اختر الفصل والمادة.", "danger")
            return redirect(url_for("portal.material_new"))
        section_id, subject_id = int(pair[0]), int(pair[1])
        if not any(p["section_id"] == section_id and p["subject_id"] == subject_id for p in pairs):
            abort(403)
        kind = request.form.get("kind", "link")
        if kind not in ("file", "video", "link"):
            abort(400)
        m = Material(
            school_id=_sid(), teacher_id=teacher.id, year_id=year.id,
            section_id=section_id, subject_id=subject_id,
            title=request.form["title"].strip(),
            description=(request.form.get("description") or "").strip() or None,
            kind=kind,
            external_url=(request.form.get("external_url") or "").strip() or None,
        )
        db.session.add(m)
        db.session.commit()
        flash("تم رفع المحتوى ويظهر الآن للطلاب وأولياء أمورهم.", "success")
        return redirect(url_for("portal.materials"))
    return render_template("portal/material_form.html", pairs=pairs, teacher=teacher)
