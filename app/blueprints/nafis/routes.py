"""NAFIS blueprint — phase 1 routes.

Screens:
  · /nafis/outcomes            — learning-outcomes catalog browser
  · /nafis/cycles              — list of testing rounds
  · /nafis/cycles/new          — create a testing round
  · /nafis/cycles/<id>         — one cycle detail (+ results placeholder)
  · /nafis/cycles/<id>/edit    — edit a cycle
  · /nafis/cycles/<id>/delete  — POST-delete a cycle
"""
from datetime import date, datetime

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import (
    AcademicYear, LearningOutcome, NafisCycle,
    NAFIS_LEVELS, NAFIS_SUBJECTS, NAFIS_CYCLE_STATUS,
)


SUBJECT_LABELS = {
    "reading": "القراءة",
    "math":    "الرياضيات",
    "science": "العلوم",
}
LEVEL_LABELS = {
    "g3": "الثالث الابتدائي",
    "g6": "السادس الابتدائي",
    "g9": "الثالث المتوسط",
}
STATUS_LABELS = {
    "upcoming":          "قادمة",
    "active":            "جارية",
    "completed":         "مُنجزة (بدون نتائج)",
    "results_published": "النتائج منشورة",
}


def _sid() -> int:
    return current_user.school_id


def _parse_date(raw: str | None):
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


# ─── Outcomes catalog ────────────────────────────────────────────────

@bp.route("/outcomes", endpoint="outcomes_home")
@login_required
@require_permission("results", "view")
def outcomes_home():
    """Browser for the ETEC learning-outcomes tree.

    Filters via querystring:
      ?subject=reading|math|science   (default: reading)
      ?level=g3|g6|g9                 (default: g3)
    """
    subject = (request.args.get("subject") or "reading").strip()
    if subject not in NAFIS_SUBJECTS:
        subject = "reading"
    level = (request.args.get("level") or "g3").strip()
    if level not in NAFIS_LEVELS:
        level = "g3"
    # Science has no g3 — auto-bump if the picker sent us an invalid pair.
    if subject == "science" and level == "g3":
        level = "g6"

    # Broad outcomes for the header band.
    broad = (
        LearningOutcome.query
        .filter_by(school_id=None, subject=subject, level=level,
                   kind="broad_outcome")
        .order_by(LearningOutcome.seq).all()
    )

    # Domains → sub-domains → standards → indicators. Pull the whole
    # tree in one query and re-nest in Python — cheap for ~150 rows.
    tree_rows = (
        LearningOutcome.query
        .filter_by(school_id=None, subject=subject, level=level)
        .filter(LearningOutcome.kind.in_(
            ("domain", "subdomain", "standard", "indicator")))
        .order_by(LearningOutcome.id).all()
    )
    by_id  = {r.id: r for r in tree_rows}
    kids   = {}
    roots  = []
    for r in tree_rows:
        if r.parent_id and r.parent_id in by_id:
            kids.setdefault(r.parent_id, []).append(r)
        elif r.kind == "domain":
            roots.append(r)

    return render_template(
        "nafis/outcomes.html",
        subject=subject, level=level,
        subject_labels=SUBJECT_LABELS, level_labels=LEVEL_LABELS,
        subjects=NAFIS_SUBJECTS, levels=NAFIS_LEVELS,
        broad=broad, roots=roots, kids=kids,
        total_standards=sum(1 for r in tree_rows if r.kind == "standard"),
        total_indicators=sum(1 for r in tree_rows if r.kind == "indicator"),
    )


# ─── Cycles CRUD ─────────────────────────────────────────────────────

@bp.route("/cycles", endpoint="cycles_list")
@login_required
@require_permission("results", "view")
def cycles_list():
    cycles = (
        NafisCycle.query.filter_by(school_id=_sid())
        .order_by(NafisCycle.start_date.desc().nullslast(), NafisCycle.id.desc())
        .all()
    )
    return render_template(
        "nafis/cycles_list.html",
        cycles=cycles,
        status_labels=STATUS_LABELS,
        level_labels=LEVEL_LABELS,
    )


@bp.route("/cycles/new", methods=["GET", "POST"], endpoint="cycle_new")
@login_required
@require_permission("results", "add")
def cycle_new():
    if request.method == "POST":
        name_ar = (request.form.get("name_ar") or "").strip()
        if not name_ar:
            flash("اسم الدورة مطلوب.", "danger")
            return redirect(url_for("nafis.cycle_new"))
        levels = [x for x in request.form.getlist("levels") if x in NAFIS_LEVELS]
        if not levels:
            levels = list(NAFIS_LEVELS)

        cyc = NafisCycle(
            school_id=_sid(),
            academic_year_id=request.form.get("academic_year_id", type=int) or None,
            name_ar=name_ar,
            hijri_year=(request.form.get("hijri_year") or "").strip() or None,
            gregorian_year=request.form.get("gregorian_year", type=int) or None,
            start_date=_parse_date(request.form.get("start_date")),
            end_date=_parse_date(request.form.get("end_date")),
            levels=",".join(levels),
            status=(request.form.get("status") or "upcoming").strip(),
            notes=(request.form.get("notes") or "").strip() or None,
        )
        try:
            db.session.add(cyc); db.session.commit()
        except Exception:
            db.session.rollback()
            flash("اسم الدورة مستخدم بالفعل في هذه المدرسة.", "danger")
            return redirect(url_for("nafis.cycle_new"))
        flash(f"تم إنشاء الدورة ({cyc.name_ar}).", "success")
        return redirect(url_for("nafis.cycle_detail", cycle_id=cyc.id))

    years = AcademicYear.query.filter_by(school_id=_sid()).order_by(
        AcademicYear.start_date.desc()).all()
    return render_template(
        "nafis/cycle_form.html", cycle=None, years=years,
        level_labels=LEVEL_LABELS, status_labels=STATUS_LABELS,
        today=date.today(),
    )


def _get_cycle(cycle_id):
    cyc = NafisCycle.query.filter_by(id=cycle_id, school_id=_sid()).first()
    if not cyc:
        abort(404)
    return cyc


@bp.route("/cycles/<int:cycle_id>", endpoint="cycle_detail")
@login_required
@require_permission("results", "view")
def cycle_detail(cycle_id):
    cyc = _get_cycle(cycle_id)
    # Result stats — empty until phase 2's importer lands.
    results_by_level = {lvl: {"total": 0, "students": set()} for lvl in cyc.target_levels}
    for r in cyc.results:
        b = results_by_level.setdefault(r.level, {"total": 0, "students": set()})
        b["total"] += 1
        b["students"].add(r.student_id)
    return render_template(
        "nafis/cycle_detail.html", cyc=cyc,
        results_by_level=results_by_level,
        subject_labels=SUBJECT_LABELS,
        level_labels=LEVEL_LABELS,
        status_labels=STATUS_LABELS,
    )


@bp.route("/cycles/<int:cycle_id>/edit", methods=["GET", "POST"],
          endpoint="cycle_edit")
@login_required
@require_permission("results", "edit")
def cycle_edit(cycle_id):
    cyc = _get_cycle(cycle_id)
    if request.method == "POST":
        name_ar = (request.form.get("name_ar") or "").strip()
        if not name_ar:
            flash("اسم الدورة مطلوب.", "danger")
            return redirect(url_for("nafis.cycle_edit", cycle_id=cyc.id))
        levels = [x for x in request.form.getlist("levels") if x in NAFIS_LEVELS]
        if not levels:
            levels = list(NAFIS_LEVELS)
        cyc.name_ar = name_ar
        cyc.academic_year_id = request.form.get("academic_year_id", type=int) or None
        cyc.hijri_year = (request.form.get("hijri_year") or "").strip() or None
        cyc.gregorian_year = request.form.get("gregorian_year", type=int) or None
        cyc.start_date = _parse_date(request.form.get("start_date"))
        cyc.end_date = _parse_date(request.form.get("end_date"))
        cyc.levels = ",".join(levels)
        cyc.status = (request.form.get("status") or cyc.status).strip()
        cyc.notes = (request.form.get("notes") or "").strip() or None
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash("تعارض في البيانات — راجع الحقول.", "danger")
            return redirect(url_for("nafis.cycle_edit", cycle_id=cyc.id))
        flash("تم حفظ التعديلات.", "success")
        return redirect(url_for("nafis.cycle_detail", cycle_id=cyc.id))

    years = AcademicYear.query.filter_by(school_id=_sid()).order_by(
        AcademicYear.start_date.desc()).all()
    return render_template(
        "nafis/cycle_form.html", cycle=cyc, years=years,
        level_labels=LEVEL_LABELS, status_labels=STATUS_LABELS,
        today=date.today(),
    )


@bp.route("/cycles/<int:cycle_id>/delete", methods=["POST"],
          endpoint="cycle_delete")
@login_required
@require_permission("results", "delete")
def cycle_delete(cycle_id):
    cyc = _get_cycle(cycle_id)
    name = cyc.name_ar
    db.session.delete(cyc); db.session.commit()
    flash(f"تم حذف الدورة ({name}).", "success")
    return redirect(url_for("nafis.cycles_list"))


# ─── Gaps placeholder (phase 2) ──────────────────────────────────────

@bp.route("/gaps", endpoint="gaps_home")
@login_required
@require_permission("results", "view")
def gaps_home():
    """Phase-2 placeholder — the real dashboard lights up once the
    NAFIS Excel importer lands and StudentGap rows start writing."""
    return render_template("nafis/gaps_placeholder.html")
