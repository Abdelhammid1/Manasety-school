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


@bp.route("/years/<int:year_id>/edit", methods=["GET", "POST"], endpoint="year_edit")
@login_required
@require_permission("academic_years", "edit")
def year_edit(year_id):
    """Edit an existing academic year. The template shows a confirm modal
    warning that changes may affect linked reports and records."""
    year = _get(AcademicYear, year_id)
    if request.method == "POST":
        # If activating this year, close any other active one first.
        new_status = request.form.get("status", year.status)
        if new_status == "active" and year.status != "active":
            other = AcademicYear.query.filter_by(school_id=_sid(), status="active").first()
            if other and other.id != year.id:
                flash(
                    f"يوجد سنة نشطة ({other.name}). أغلقها أولاً قبل تفعيل هذه السنة.",
                    "warning",
                )
                return render_template("academic/year_form.html", year=year)
        year.name = request.form["name"].strip()
        year.start_date = datetime.strptime(request.form["start_date"], "%Y-%m-%d").date()
        year.end_date = datetime.strptime(request.form["end_date"], "%Y-%m-%d").date()
        year.status = new_status
        db.session.commit()
        flash("تم حفظ التعديلات على السنة الدراسية.", "success")
        return redirect(url_for("academic.years_list"))
    return render_template("academic/year_form.html", year=year)


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

    # Ticket #12 part 1 — accept status_mode + manual_status.
    #   status_mode defaults to "auto"; anything else must be "manual".
    #   manual_status is required (and validated) only in manual mode;
    #   we don't null it out when the mode is auto so that flipping back
    #   to manual restores the previous choice cleanly.
    status_mode = (form.get("status_mode") or "auto").strip().lower()
    if status_mode not in ("auto", "manual"):
        status_mode = "auto"
    manual_status = (form.get("manual_status") or "").strip().lower() or None
    if status_mode == "manual" and manual_status not in ("open", "closed"):
        return None, "اختر حالة (مفتوحة أو مقفلة) للتحكم اليدوي."

    return {
        "name": name, "order_index": order_index,
        "start_date": start, "end_date": end, "weight": weight,
        "status_mode": status_mode,
        "manual_status": manual_status,
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
    """Hard-delete a term, but only when nothing points at it.

    Terms are referenced NOT NULL by AssessmentComponent.term_id, and via
    that by GradeEntry.component_id. A raw delete would either 500 with
    IntegrityError or wipe live grading data. We refuse the delete and
    tell the user what's in the way, mirroring subject_delete and
    grade_delete.
    """
    from ...models import AssessmentComponent, GradeEntry
    from ...models.teacher import subject_terms
    term = _get(Term, term_id)
    year_id = term.year_id

    n_components = AssessmentComponent.query.filter_by(term_id=term.id).count()
    if n_components:
        n_entries = (
            GradeEntry.query.join(AssessmentComponent,
                                  GradeEntry.component_id == AssessmentComponent.id)
            .filter(AssessmentComponent.term_id == term.id)
            .count()
        )
        flash(
            f"لا يمكن حذف الفترة ({term.name}) — مرتبطة بـ "
            f"{n_components} مكوّن تقييم و {n_entries} درجة مرصودة. "
            "احذف المكوّنات أو انقلها لفترة أخرى أولاً.",
            "danger",
        )
        return redirect(url_for("academic.terms_list", year_id=year_id))

    # Clear the soft subject_terms M2M rows tied to this term so the
    # cascade doesn't leave orphan association rows.
    db.session.execute(
        subject_terms.delete().where(subject_terms.c.term_id == term.id)
    )
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


@bp.route("/grades/<int:grade_id>", methods=["GET"], endpoint="grade_detail")
@login_required
@require_permission("grades", "view")
def grade_detail(grade_id):
    """Grade detail — list all sections belonging to this grade (any year)."""
    grade = _get(Grade, grade_id)
    active_year = AcademicYear.query.filter_by(school_id=_sid(), status="active").first()
    sections = (
        Section.query.filter_by(school_id=_sid(), grade_id=grade.id)
        .join(AcademicYear, AcademicYear.id == Section.year_id)
        .order_by(AcademicYear.start_date.desc(), Section.name)
        .all()
    )
    return render_template(
        "academic/grade_detail.html",
        grade=grade, sections=sections, active_year=active_year,
    )


@bp.route("/grades/<int:grade_id>/delete", methods=["POST"], endpoint="grade_delete")
@login_required
@require_permission("grades", "delete")
def grade_delete(grade_id):
    """Delete a grade — refuses if any Section refers to it, in any year."""
    grade = _get(Grade, grade_id)
    linked_sections = Section.query.filter_by(school_id=_sid(), grade_id=grade.id).count()
    if linked_sections:
        flash(
            f"لا يمكن حذف الصف «{grade.name}» — يحتوي على {linked_sections} فصلاً. "
            "احذف الفصول أولاً أو انقل الطلاب إلى صف آخر.",
            "danger",
        )
        return redirect(url_for("academic.grades_list"))
    db.session.delete(grade)
    db.session.commit()
    flash(f"تم حذف الصف «{grade.name}».", "success")
    return redirect(url_for("academic.grades_list"))


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


@bp.route("/sections/<int:section_id>", methods=["GET"], endpoint="section_detail")
@login_required
@require_permission("sections", "view")
def section_detail(section_id):
    """Section detail — every active student in this section as clickable rows."""
    from ...models import Student, Enrollment
    section = _get(Section, section_id)
    enrollments = (
        Enrollment.query.filter_by(school_id=_sid(), section_id=section.id, status="active")
        .join(Student).order_by(Student.full_name).all()
    )
    return render_template(
        "academic/section_detail.html",
        section=section, enrollments=enrollments,
    )


@bp.route("/sections/new", methods=["GET", "POST"])
@login_required
@require_permission("sections", "add")
def section_new():
    """Create a section. FK columns (year_id, grade_id) are NOT NULL so
    both dependencies must exist before the form is renderable; without
    the flash-and-redirect an empty grades list rendered an empty <select>
    and a POST 500'd on int(request.form["grade_id"])."""
    year = AcademicYear.query.filter_by(school_id=_sid(), status="active").first()
    if not year:
        flash("يجب إنشاء سنة دراسية نشطة أولاً.", "warning")
        return redirect(url_for("academic.years_list"))
    grades = Grade.query.filter_by(school_id=_sid()).order_by(Grade.order_index).all()
    if not grades:
        flash("يجب إنشاء صف دراسي واحد على الأقل قبل إضافة فصل.", "warning")
        return redirect(url_for("academic.grades_list"))
    if request.method == "POST":
        grade_id = request.form.get("grade_id", type=int)
        name = (request.form.get("name") or "").strip()
        if not name or grade_id not in [g.id for g in grades]:
            flash("اسم الفصل والصف مطلوبان.", "danger")
            return render_template("academic/section_form.html", section=None, grades=grades, year=year)
        section = Section(
            school_id=_sid(),
            year_id=year.id,
            grade_id=grade_id,
            name=name,
            capacity=int(request.form.get("capacity") or 30),
        )
        db.session.add(section)
        db.session.commit()
        flash("تم إضافة الفصل.", "success")
        return redirect(url_for("academic.sections_list"))
    return render_template("academic/section_form.html", section=None, grades=grades, year=year)


@bp.route("/sections/<int:section_id>/edit", methods=["GET", "POST"])
@login_required
@require_permission("sections", "edit")
def section_edit(section_id):
    """Edit a section. year_id + grade_id are structural — changing them
    would rewrite every enrollment, so we lock them here and only allow
    name and capacity edits. If the user wants to move students to a
    different grade, promotion/transfer flows handle that."""
    section = _get(Section, section_id)
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        cap  = request.form.get("capacity", type=int) or section.capacity
        if not name:
            flash("اسم الفصل مطلوب.", "danger")
            return render_template("academic/section_form.html", section=section, grades=[section.grade], year=section.year)
        if cap < section.current_count:
            flash(
                f"لا يمكن ضبط السعة على {cap} — يوجد {section.current_count} طالب مسجّل بالفعل.",
                "danger",
            )
            return render_template("academic/section_form.html", section=section, grades=[section.grade], year=section.year)
        section.name = name
        section.capacity = cap
        db.session.commit()
        flash("تم تعديل الفصل.", "success")
        return redirect(url_for("academic.section_detail", section_id=section.id))
    return render_template(
        "academic/section_form.html",
        section=section, grades=[section.grade], year=section.year,
    )


@bp.route("/sections/<int:section_id>/delete", methods=["POST"])
@login_required
@require_permission("sections", "delete")
def section_delete(section_id):
    """Delete a section. Refuses if students are enrolled or any course
    has been created for it — these hold live records (attendance,
    grades, submissions) that can't survive a section deletion."""
    from ...models import Course, Enrollment
    section = _get(Section, section_id)
    n_enroll = Enrollment.query.filter_by(section_id=section.id).count()
    n_course = Course.query.filter_by(section_id=section.id).count()
    if n_enroll or n_course:
        parts = []
        if n_enroll: parts.append(f"{n_enroll} تسجيل طالب")
        if n_course: parts.append(f"{n_course} مقرّر")
        flash(
            f"لا يمكن حذف الفصل ({section.name}) — مرتبط بـ " + " و".join(parts) + ". "
            "انقل الطلاب أو احذف المقرّرات أولاً.",
            "danger",
        )
        return redirect(url_for("academic.sections_list"))
    db.session.delete(section)
    db.session.commit()
    flash("تم حذف الفصل نهائياً.", "success")
    return redirect(url_for("academic.sections_list"))


# ---------- helpers ----------

def _get(model, oid):
    obj = model.query.filter_by(id=oid, school_id=_sid()).first()
    if not obj:
        abort(404)
    return obj
