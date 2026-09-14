from datetime import datetime
from decimal import Decimal

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import AcademicYear, Grade, Section, Term


def _sid():
    return current_user.school_id


# ---------- Academic Years (T-2.1) ----------

@bp.route("/years")
@login_required
@require_permission("academic_years", "view")
def years_list():
    years = (
        AcademicYear.query.filter_by(school_id=_sid())
        .order_by(AcademicYear.start_date.desc())
        .all()
    )
    return render_template("academic/years_list.html", years=years)


@bp.route("/years/new", methods=["GET", "POST"])
@login_required
@require_permission("academic_years", "add")
def year_new():
    if request.method == "POST":
        status = request.form.get("status", "active")
        if status == "active":
            existing = AcademicYear.query.filter_by(school_id=_sid(), status="active").first()
            if existing:
                flash(
                    f"يوجد سنة نشطة ({existing.name}). أغلقها أولاً قبل تفعيل سنة جديدة.",
                    "warning",
                )
                return render_template("academic/year_form.html", year=None)

        year = AcademicYear(
            school_id=_sid(),
            name=request.form["name"].strip(),
            start_date=datetime.strptime(request.form["start_date"], "%Y-%m-%d").date(),
            end_date=datetime.strptime(request.form["end_date"], "%Y-%m-%d").date(),
            status=status,
        )
        db.session.add(year)
        db.session.commit()
        flash("تم إنشاء السنة الدراسية.", "success")
        return redirect(url_for("academic.years_list"))
    return render_template("academic/year_form.html", year=None)


@bp.route("/years/<int:year_id>/close", methods=["POST"])
@login_required
@require_permission("academic_years", "edit")
def year_close(year_id):
    year = _get(AcademicYear, year_id)
    year.status = "closed"
    # Sprint 9 TC-7.1.2: freeze the pass rule so post-closure edits can't
    # retroactively change historic results.
    from ...models import PassRule
    PassRule.query.filter_by(school_id=_sid(), year_id=year.id).update(
        {"is_frozen": True}
    )
    db.session.commit()
    flash(
        "تم إغلاق السنة (أرشيف). لا يمكن تعديل بياناتها التشغيلية "
        "وتم تجميد قاعدة النجاح لهذه السنة.",
        "info",
    )
    return redirect(url_for("academic.years_list"))


# ---------- Terms (T-2.2) ----------

@bp.route("/years/<int:year_id>/terms")
@login_required
@require_permission("terms", "view")
def terms_list(year_id):
    year = _get(AcademicYear, year_id)
    total = sum((t.weight or Decimal(0)) for t in year.terms)
    return render_template("academic/terms_list.html", year=year, total_weight=total)


def _validate_term_dates_and_weight(year, form, editing_id=None):
    """Sprint 9 TC-2.2.5 + TC-2.2.6 — return (data, error_msg).

    Rejects: end<=start, dates overlapping another term in the same year,
    and cumulative weight > 100%.
    """
    try:
        start = datetime.strptime(form["start_date"], "%Y-%m-%d").date()
        end = datetime.strptime(form["end_date"], "%Y-%m-%d").date()
        weight = Decimal(form["weight"])
        order_index = int(form["order_index"])
        name = (form.get("name") or "").strip()
    except (KeyError, ValueError) as e:
        return None, f"بيانات غير صالحة: {e}"

    if not name:
        return None, "اسم الفترة الدراسية مطلوب."
    if end <= start:
        return None, "تاريخ النهاية يجب أن يكون بعد تاريخ البداية."

    # TC-2.2.5: date overlap check
    overlap_q = Term.query.filter_by(school_id=year.school_id, year_id=year.id).filter(
        Term.start_date <= end, Term.end_date >= start,
    )
    if editing_id is not None:
        overlap_q = overlap_q.filter(Term.id != editing_id)
    overlap = overlap_q.first()
    if overlap:
        return None, (
            f"تعارض تواريخ: الفترة الدراسية \"{overlap.name}\" "
            f"({overlap.start_date} → {overlap.end_date}) تتقاطع مع التواريخ المدخلة. "
            "اختر تواريخ لا تتداخل."
        )

    # TC-2.2.6: cumulative weight <= 100
    other_weight_q = db.session.query(
        func.coalesce(func.sum(Term.weight), 0)
    ).filter_by(school_id=year.school_id, year_id=year.id)
    if editing_id is not None:
        other_weight_q = other_weight_q.filter(Term.id != editing_id)
    other_weight = Decimal(other_weight_q.scalar() or 0)
    if other_weight + weight > Decimal(100):
        return None, (
            f"مجموع الأوزان سيتجاوز 100% "
            f"(المسجّل حاليًا {other_weight}% + الجديد {weight}% = {other_weight + weight}%). "
            "قلّل الوزن أو عدّل الفترات الأخرى أولًا."
        )

    return {
        "name": name, "order_index": order_index,
        "start_date": start, "end_date": end, "weight": weight,
    }, None


@bp.route("/years/<int:year_id>/terms/new", methods=["GET", "POST"])
@login_required
@require_permission("terms", "add")
def term_new(year_id):
    year = _get(AcademicYear, year_id)
    if year.status == "closed":
        flash("السنة مغلقة، لا يمكن تعديل الفترات الدراسية.", "danger")
        return redirect(url_for("academic.terms_list", year_id=year_id))
    if request.method == "POST":
        data, err = _validate_term_dates_and_weight(year, request.form)
        if err:
            flash(err, "danger")
            return render_template("academic/term_form.html", year=year, term=None, form=request.form)

        term = Term(school_id=_sid(), year_id=year.id, **data)
        db.session.add(term)
        db.session.commit()

        total = db.session.query(func.coalesce(func.sum(Term.weight), 0)).filter_by(year_id=year.id).scalar()
        if Decimal(total) == Decimal(100):
            flash("تم إضافة الفترة الدراسية. مجموع الأوزان = 100%.", "success")
        else:
            flash(
                f"تم إضافة الفترة الدراسية. مجموع الأوزان الحالي = {total}% "
                "— أضف بقية الفترات حتى يصل الإجمالي إلى 100%.",
                "warning",
            )
        return redirect(url_for("academic.terms_list", year_id=year.id))
    return render_template("academic/term_form.html", year=year, term=None)


@bp.route("/terms/<int:term_id>/edit", methods=["GET", "POST"])
@login_required
@require_permission("terms", "edit")
def term_edit(term_id):
    """Sprint 9 TC-2.2.4 — edit an existing term with the same validation."""
    term = _get(Term, term_id)
    year = _get(AcademicYear, term.year_id)
    if year.status == "closed":
        flash("السنة مغلقة، لا يمكن تعديل الفترات الدراسية.", "danger")
        return redirect(url_for("academic.terms_list", year_id=year.id))
    if request.method == "POST":
        data, err = _validate_term_dates_and_weight(year, request.form, editing_id=term.id)
        if err:
            flash(err, "danger")
            return render_template("academic/term_form.html", year=year, term=term, form=request.form)
        for k, v in data.items():
            setattr(term, k, v)
        db.session.commit()
        flash("تم تعديل الفترة الدراسية.", "success")
        return redirect(url_for("academic.terms_list", year_id=year.id))
    return render_template("academic/term_form.html", year=year, term=term)


@bp.route("/terms/<int:term_id>/delete", methods=["POST"])
@login_required
@require_permission("terms", "delete")
def term_delete(term_id):
    term = _get(Term, term_id)
    year_id = term.year_id
    db.session.delete(term)
    db.session.commit()
    flash("تم حذف الفترة الدراسية.", "success")
    return redirect(url_for("academic.terms_list", year_id=year_id))


# ---------- Grades (T-2.3) ----------

@bp.route("/grades")
@login_required
@require_permission("grades", "view")
def grades_list():
    # Sprint 9 TC-2.4.2: count sections per grade only for the active year,
    # so opening a new year doesn't inherit last year's stale count.
    active_year = AcademicYear.query.filter_by(school_id=_sid(), status="active").first()
    grades = (
        Grade.query.filter_by(school_id=_sid())
        .order_by(Grade.order_index)
        .all()
    )
    section_counts = {}
    if active_year:
        rows = (
            db.session.query(Section.grade_id, func.count(Section.id))
            .filter(Section.school_id == _sid(), Section.year_id == active_year.id)
            .group_by(Section.grade_id).all()
        )
        section_counts = {gid: n for gid, n in rows}
    return render_template(
        "academic/grades_list.html",
        grades=grades, section_counts=section_counts, active_year=active_year,
    )


@bp.route("/grades/new", methods=["GET", "POST"])
@login_required
@require_permission("grades", "add")
def grade_new():
    if request.method == "POST":
        grade = Grade(
            school_id=_sid(),
            name=request.form["name"].strip(),
            order_index=int(request.form["order_index"]),
            stage=request.form.get("stage") or None,
        )
        db.session.add(grade)
        db.session.commit()
        flash("تم إضافة الصف.", "success")
        return redirect(url_for("academic.grades_list"))
    return render_template("academic/grade_form.html", grade=None)


@bp.route("/grades/<int:grade_id>/edit", methods=["GET", "POST"])
@login_required
@require_permission("grades", "edit")
def grade_edit(grade_id):
    grade = _get(Grade, grade_id)
    if request.method == "POST":
        grade.name = request.form["name"].strip()
        grade.order_index = int(request.form["order_index"])
        grade.stage = request.form.get("stage") or None
        db.session.commit()
        flash("تم تحديث الصف.", "success")
        return redirect(url_for("academic.grades_list"))
    return render_template("academic/grade_form.html", grade=grade)


# ---------- Sections (T-2.4) ----------

@bp.route("/sections")
@login_required
@require_permission("sections", "view")
def sections_list():
    year = AcademicYear.query.filter_by(school_id=_sid(), status="active").first()
    sections = []
    if year:
        sections = (
            Section.query.filter_by(school_id=_sid(), year_id=year.id)
            .join(Grade)
            .order_by(Grade.order_index, Section.name)
            .all()
        )
    return render_template("academic/sections_list.html", sections=sections, active_year=year)


@bp.route("/sections/new", methods=["GET", "POST"])
@login_required
@require_permission("sections", "add")
def section_new():
    year = AcademicYear.query.filter_by(school_id=_sid(), status="active").first()
    if not year:
        flash("يجب إنشاء سنة دراسية نشطة أولاً.", "warning")
        return redirect(url_for("academic.years_list"))
    grades = Grade.query.filter_by(school_id=_sid()).order_by(Grade.order_index).all()
    if request.method == "POST":
        section = Section(
            school_id=_sid(),
            year_id=year.id,
            grade_id=int(request.form["grade_id"]),
            name=request.form["name"].strip(),
            capacity=int(request.form.get("capacity") or 30),
        )
        db.session.add(section)
        db.session.commit()
        flash("تم إضافة الفصل.", "success")
        return redirect(url_for("academic.sections_list"))
    return render_template("academic/section_form.html", section=None, grades=grades, year=year)


# ---------- helpers ----------

def _get(model, oid):
    obj = model.query.filter_by(id=oid, school_id=_sid()).first()
    if not obj:
        abort(404)
    return obj
