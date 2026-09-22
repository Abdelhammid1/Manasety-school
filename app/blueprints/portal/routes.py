from flask import abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import (
    AcademicYear, Assignment, Material, ScheduleSlot, Day, Period,
    Section, Subject, Teacher, Student, PickupCall,
)
from ...services import pickup as pickup_svc


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


# ── نداء — parent pickup call ───────────────────────────────────────
def _parent_children():
    """Every Student linked to the current user as a parent."""
    return Student.query.filter_by(parent_user_id=current_user.id).all()


@bp.route("/pickup")
@login_required
def pickup_home():
    """Parent-facing pickup page — big نداء button + active-call list."""
    kids = _parent_children()
    active_calls = (
        PickupCall.query
        .filter_by(parent_user_id=current_user.id, released_at=None)
        .all()
    )
    return render_template("portal/pickup.html",
                           children=kids, active=active_calls)


@bp.route("/pickup/call", methods=["POST"])
@login_required
def pickup_call():
    student_id = request.form.get("student_id", type=int)
    gate = (request.form.get("gate") or "").strip() or "البوابة الرئيسية"
    note = (request.form.get("note") or "").strip()
    student = Student.query.filter_by(
        id=student_id, parent_user_id=current_user.id).first_or_404()
    call = pickup_svc.create_call(current_user, student, gate=gate, note=note)
    flash(f"تم إرسال النداء — بانتظار خروج {student.full_name}.", "success")
    return redirect(url_for("portal.pickup_home"))


@bp.route("/pickup/<int:cid>/release", methods=["POST"])
@login_required
def pickup_release(cid):
    call = PickupCall.query.get_or_404(cid)
    if call.parent_user_id != current_user.id:
        # Teachers and admins can also close a call.
        if not getattr(current_user, "is_superuser", False):
            abort(403)
    pickup_svc.release_call(call, current_user)
    flash("تم إغلاق النداء.", "success")
    return redirect(request.referrer or url_for("portal.pickup_home"))


@bp.route("/pickup/active.json")
@login_required
def pickup_active_json():
    """Lightweight polling endpoint used by student + teacher banners."""
    uid = current_user.id
    calls = (
        PickupCall.query
        .filter(PickupCall.released_at.is_(None))
        .filter(db.or_(
            PickupCall.teacher_user_id == uid,
            PickupCall.student_id.in_(
                db.session.query(Student.id).filter(Student.user_id == uid)
            ),
        ))
        .order_by(PickupCall.called_at.desc()).all()
    )
    return jsonify({
        "calls": [{
            "id": c.id,
            "student": c.student.full_name if c.student else "",
            "parent": (c.parent.username if c.parent else "ولي الأمر"),
            "gate": c.gate or "",
            "note": c.note or "",
            "waited_min": c.waited_minutes,
            "role": "teacher" if c.teacher_user_id == uid else "student",
        } for c in calls],
    })


@bp.route("/pickup/<int:cid>/ack", methods=["POST"])
@login_required
def pickup_ack(cid):
    """Teacher or student marks the call as seen."""
    call = PickupCall.query.get_or_404(cid)
    uid = current_user.id
    if call.teacher_user_id == uid:
        pickup_svc.mark_seen_by_teacher(call)
    elif call.student and call.student.user_id == uid:
        pickup_svc.mark_seen_by_student(call)
    else:
        abort(403)
    return jsonify({"ok": True})
