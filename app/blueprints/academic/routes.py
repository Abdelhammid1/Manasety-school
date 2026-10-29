from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from . import bp
from . import validation as v
from ..utils import require_permission
from ...extensions import db
from ...models import AcademicYear, Grade, Section, Term


def _sid() -> int:
    # SAAS-005 — central tenant source of truth. One function
    # here so no blueprint reads current_user.school_id directly.
    from ...services.tenancy import current_school_id
    return current_school_id()


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
    prior_years = (
        AcademicYear.query.filter_by(school_id=_sid())
        .order_by(AcademicYear.start_date.desc()).all()
    )

    def form_page(form=None):
        return render_template("academic/year_form.html", year=None, prior_years=prior_years,
                               values=v.values(None, form, YEAR_FIELDS))

    if request.method == "POST":
        try:
            data = _year_data(request.form)
        except v.Invalid as e:
            flash(str(e), "danger")
            return form_page(request.form)
        if data["status"] == "active":
            existing = AcademicYear.query.filter_by(school_id=_sid(), status="active").first()
            if existing:
                flash(
                    f"يوجد سنة نشطة ({v.iso(existing.name)}). أغلقها أولاً قبل تفعيل سنة جديدة.",
                    "warning",
                )
                return form_page(request.form)

        year = AcademicYear(school_id=_sid(), **data)
        db.session.add(year)
        db.session.flush()

        # Ticket A7 — optional rollover from a prior year. Copies
        # Section rows only (not enrollments or courses — those need
        # a fresh cycle per school policy).
        from_year_id = request.form.get("rollover_from", type=int)
        copied_msg = None
        if from_year_id:
            source = AcademicYear.query.filter_by(
                id=from_year_id, school_id=_sid()).first()
            if source:
                copied = _rollover_sections(source, year)
                copied_msg = f"تم نسخ {copied} فصل من {v.iso(source.name)}."

        err = v.commit("السنة الدراسية")
        if err:
            flash(err, "danger")
            return form_page(request.form)
        if copied_msg:
            flash(copied_msg, "info")
        flash("تم إنشاء السنة الدراسية.", "success")
        return redirect(url_for("academic.years_list"))
    return form_page()


YEAR_FIELDS = ("name", "start_date", "end_date", "status")


def _year_data(form, editing=None) -> dict:
    """The year's fields, or v.Invalid with the first problem."""
    name = v.text(form, "name", "اسم السنة الدراسية", max_len=64)
    start = v.day(form, "start_date", "تاريخ البداية")
    end = v.day(form, "end_date", "تاريخ النهاية")
    if end <= start:
        raise v.Invalid("تاريخ النهاية يجب أن يكون بعد تاريخ البداية.")
    status = (form.get("status") or (editing.status if editing else "active")).strip()
    if status not in ("active", "closed"):
        raise v.Invalid("حالة السنة غير صحيحة — اختر نشطة أو مغلقة.")
    other = v.clash(AcademicYear, exclude_id=getattr(editing, "id", None), school_id=_sid(), name=name)
    if other:
        raise v.Invalid(f"السنة الدراسية \"{v.iso(name)}\" موجودة بالفعل{v.deleted_note(other)}.")
    return {"name": name, "start_date": start, "end_date": end, "status": status}


def _rollover_sections(source_year, target_year):
    """Ticket A7 — copy every Section from `source_year` into
    `target_year`, keeping (name, capacity, grade_id). Skips names
    that already exist in the target so re-running is safe."""
    existing_names = {
        s.name for s in Section.query.filter_by(
            school_id=_sid(), year_id=target_year.id).all()
    }
    sources = Section.query.filter_by(
        school_id=_sid(), year_id=source_year.id).all()
    added = 0
    for s in sources:
        if s.name in existing_names:
            continue
        db.session.add(Section(
            school_id=_sid(), year_id=target_year.id,
            grade_id=s.grade_id, name=s.name,
            capacity=s.capacity,
        ))
        added += 1
    return added


@bp.route("/years/<hid:year_id>/edit", methods=["GET", "POST"], endpoint="year_edit")
@login_required
@require_permission("academic_years", "edit")
def year_edit(year_id):
    """Edit an existing academic year. The template shows a confirm modal
    warning that changes may affect linked reports and records."""
    year = _get(AcademicYear, year_id)

    def form_page(form=None):
        return render_template("academic/year_form.html", year=year,
                               values=v.values(year, form, YEAR_FIELDS))

    if request.method == "POST":
        try:
            data = _year_data(request.form, editing=year)
        except v.Invalid as e:
            flash(str(e), "danger")
            return form_page(request.form)
        # If activating this year, close any other active one first.
        if data["status"] == "active" and year.status != "active":
            other = AcademicYear.query.filter_by(school_id=_sid(), status="active").first()
            if other and other.id != year.id:
                flash(
                    f"يوجد سنة نشطة ({v.iso(other.name)}). أغلقها أولاً قبل تفعيل هذه السنة.",
                    "warning",
                )
                return form_page(request.form)
        for k, val in data.items():
            setattr(year, k, val)
        err = v.commit("السنة الدراسية")
        if err:
            flash(err, "danger")
            return form_page(request.form)
        flash("تم حفظ التعديلات على السنة الدراسية.", "success")
        return redirect(url_for("academic.years_list"))
    return form_page()


@bp.route("/years/<hid:year_id>/close", methods=["GET", "POST"])
@login_required
@require_permission("academic_years", "edit")
def year_close(year_id):
    """Ticket "Additional 11" — close the fiscal year AND freeze the
    pass rule at the same time. The finance service posts the
    retained-earnings journal; the pass rule freeze is the SIS side.

    Ticket B (2026-09-21) — GET renders a preview page showing the
    computed revenue/expense/net numbers and a confirm button that
    POSTs the actual close. Prior behavior (POST-only) 405'd anyone
    who navigated to /academic/years/<id>/close in the URL bar; the
    "معاينة الإقفال" button on the years list now also lands here.
    """
    from ...models import PassRule
    from ...services.ledger import close_fiscal_year, LedgerError
    # Ticket "معاينة الاقفال مش بتفتح" — the raw abort(404) that _get
    # falls back to was rendering the generic 404 page even when the
    # cause was simply "year id belongs to another school". Give a
    # friendlier flash + redirect so admins that mis-typed the URL
    # land on the years list instead of hitting a dead end.
    # SAAS-018: same message + a link to the years list, but as a real
    # 404 (a foreign id must not look like a successful redirect).
    year = AcademicYear.query.filter_by(id=year_id, school_id=_sid()).first()
    if year is None:
        return render_template(
            "errors/error.html", code=404, title="السنة الدراسية غير موجودة",
            msg="السنة الدراسية غير موجودة أو غير مسموح لك بالوصول لها.",
            back_url=url_for("academic.years_list"), back_label="قائمة السنوات الدراسية",
        ), 404

    # GET (or an explicit dry_run POST) → preview screen.
    is_preview = request.method == "GET" or request.form.get("dry_run") == "1"
    if is_preview:
        try:
            preview = close_fiscal_year(_sid(), year, dry_run=True)
        except LedgerError as e:
            flash(str(e), "danger")
            return redirect(url_for("academic.years_list"))
        return render_template(
            "academic/year_close_preview.html", year=year, preview=preview,
        )

    # POST without dry_run → actually close.
    try:
        preview = close_fiscal_year(_sid(), year, dry_run=False)
    except LedgerError as e:
        db.session.rollback()
        flash(str(e), "danger")
        return redirect(url_for("academic.year_close", year_id=year.id))

    PassRule.query.filter_by(school_id=_sid(), year_id=year.id).update({"is_frozen": True})
    db.session.commit()
    flash(
        f"تم إقفال السنة {v.iso(year.name)} — صافي الربح/الخسارة: "
        f"{preview['net_income']:.2f} رُحّل إلى حساب الأرباح المرحّلة.",
        "success",
    )
    return redirect(url_for("academic.years_list"))


# ---------- Terms (T-2.2) ----------

@bp.route("/years/<hid:year_id>/terms")
@login_required
@require_permission("terms", "view")
def terms_list(year_id):
    year = _get(AcademicYear, year_id)
    total = sum((t.weight or Decimal(0)) for t in year.terms)
    return render_template("academic/terms_list.html", year=year, total_weight=total)


TERM_FIELDS = ("name", "order_index", "start_date", "end_date", "weight", "status_mode", "manual_status")


def _validate_term_dates_and_weight(year, form, editing_id=None):
    """Sprint 9 TC-2.2.5 + TC-2.2.6 — return (data, error_msg).

    Rejects, each with its own message: a missing / bad field, end <=
    start, dates overlapping another term of the year, an order already
    used in the year, and a cumulative weight over 100%. Under 100% is
    allowed while the year's terms are being added (the list shows the
    running total) — the current rule, kept.
    """
    try:
        name = v.text(form, "name", "اسم الفترة الدراسية", max_len=64)
        order_index = v.whole(form, "order_index", "ترتيب الفترة")
        start = v.day(form, "start_date", "تاريخ البداية")
        end = v.day(form, "end_date", "تاريخ النهاية")
        weight = v.percent(form, "weight")
    except v.Invalid as e:
        return None, str(e)
    if end <= start:
        return None, "تاريخ النهاية يجب أن يكون بعد تاريخ البداية."

    # the order is unique in the year (uq_term_year_order — deleted terms too)
    taken = v.clash(Term, exclude_id=editing_id, year_id=year.id, order_index=order_index)
    if taken:
        return None, (f"ترتيب الفترة ({order_index}) مستخدم بالفعل في فترة \"{taken.name}\"{v.deleted_note(taken)}، "
                      "اختر ترتيبًا آخر.")

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
            f"({v.iso(overlap.start_date)} → {v.iso(overlap.end_date)}) تتقاطع مع التواريخ المدخلة. "
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
            f"مجموع أوزان الفترات لا يجب أن يتجاوز 100% "
            f"(الحالي بعد التعديل: {_pct(other_weight + weight)}% — "
            f"الفترات الأخرى {_pct(other_weight)}% + هذه الفترة {_pct(weight)}%). "
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


def _pct(x) -> str:
    """60.00 → 60, 12.50 → 12.5"""
    d = Decimal(x).normalize()
    return format(d, "f")


@bp.route("/years/<hid:year_id>/terms/new", methods=["GET", "POST"])
@login_required
@require_permission("terms", "add")
def term_new(year_id):
    year = _get(AcademicYear, year_id)
    if year.status == "closed":
        flash("السنة مغلقة، لا يمكن تعديل الفترات الدراسية.", "danger")
        return redirect(url_for("academic.terms_list", year_id=year_id))

    def form_page(form=None):
        return render_template("academic/term_form.html", year=year, term=None,
                               values=v.values(None, form, TERM_FIELDS))

    if request.method == "POST":
        data, err = _validate_term_dates_and_weight(year, request.form)
        if err:
            flash(err, "danger")
            return form_page(request.form)

        term = Term(school_id=_sid(), year_id=year.id, **data)
        db.session.add(term)
        err = v.commit("الفترة الدراسية")
        if err:
            flash(err, "danger")
            return form_page(request.form)

        total = db.session.query(func.coalesce(func.sum(Term.weight), 0)).filter_by(year_id=year.id).scalar()
        if Decimal(total) == Decimal(100):
            flash("تم إضافة الفترة الدراسية. مجموع الأوزان = 100%.", "success")
        else:
            flash(
                f"تم إضافة الفترة الدراسية. مجموع الأوزان الحالي = {_pct(total)}% "
                "— أضف بقية الفترات حتى يصل الإجمالي إلى 100%.",
                "warning",
            )
        return redirect(url_for("academic.terms_list", year_id=year.id))
    return form_page()


@bp.route("/terms/<hid:term_id>/edit", methods=["GET", "POST"])
@login_required
@require_permission("terms", "edit")
def term_edit(term_id):
    """Sprint 9 TC-2.2.4 — edit an existing term with the same validation."""
    term = _get(Term, term_id)
    year = _get(AcademicYear, term.year_id)
    if year.status == "closed":
        flash("السنة مغلقة، لا يمكن تعديل الفترات الدراسية.", "danger")
        return redirect(url_for("academic.terms_list", year_id=year.id))

    def form_page(form=None):
        return render_template("academic/term_form.html", year=year, term=term,
                               values=v.values(term, form, TERM_FIELDS))

    if request.method == "POST":
        data, err = _validate_term_dates_and_weight(year, request.form, editing_id=term.id)
        if err:
            flash(err, "danger")
            return form_page(request.form)
        for key, val in data.items():
            setattr(term, key, val)
        err = v.commit("الفترة الدراسية")
        if err:
            flash(err, "danger")
            return form_page(request.form)
        flash("تم تعديل الفترة الدراسية.", "success")
        return redirect(url_for("academic.terms_list", year_id=year.id))
    return form_page()


@bp.route("/terms/<hid:term_id>/delete", methods=["POST"])
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


GRADE_FIELDS = ("name", "order_index", "stage")


def _grade_data(form, editing=None) -> dict:
    """The grade's fields, or v.Invalid. Name and order are unique in the
    school (uq_grade_school_name / uq_grade_school_order — deleted grades
    too); an existing grade keeps an order saved before the >= 1 rule."""
    name = v.text(form, "name", "اسم الصف", max_len=64)
    order_index = v.whole(form, "order_index", "ترتيب الصف",
                          keep=editing.order_index if editing else None)
    exclude = getattr(editing, "id", None)
    other = v.clash(Grade, exclude_id=exclude, school_id=_sid(), name=name)
    if other:
        raise v.Invalid(f"اسم الصف \"{name}\" موجود بالفعل{v.deleted_note(other)}.")
    other = v.clash(Grade, exclude_id=exclude, school_id=_sid(), order_index=order_index)
    if other:
        raise v.Invalid(f"ترتيب الصف ({order_index}) مستخدم بالفعل في صف \"{other.name}\"{v.deleted_note(other)}، "
                        "اختر ترتيبًا آخر.")
    return {"name": name, "order_index": order_index, "stage": (form.get("stage") or "").strip() or None}


@bp.route("/grades/new", methods=["GET", "POST"])
@login_required
@require_permission("grades", "add")
def grade_new():
    def form_page(form=None):
        return render_template("academic/grade_form.html", grade=None,
                               values=v.values(None, form, GRADE_FIELDS))

    if request.method == "POST":
        try:
            data = _grade_data(request.form)
        except v.Invalid as e:
            flash(str(e), "danger")
            return form_page(request.form)
        db.session.add(Grade(school_id=_sid(), **data))
        err = v.commit("الصف")
        if err:
            flash(err, "danger")
            return form_page(request.form)
        flash("تم إضافة الصف.", "success")
        return redirect(url_for("academic.grades_list"))
    return form_page()


@bp.route("/grades/<hid:grade_id>/edit", methods=["GET", "POST"])
@login_required
@require_permission("grades", "edit")
def grade_edit(grade_id):
    grade = _get(Grade, grade_id)

    def form_page(form=None):
        return render_template("academic/grade_form.html", grade=grade,
                               values=v.values(grade, form, GRADE_FIELDS))

    if request.method == "POST":
        try:
            data = _grade_data(request.form, editing=grade)
        except v.Invalid as e:
            flash(str(e), "danger")
            return form_page(request.form)
        for key, val in data.items():
            setattr(grade, key, val)
        err = v.commit("الصف")
        if err:
            flash(err, "danger")
            return form_page(request.form)
        flash("تم تحديث الصف.", "success")
        return redirect(url_for("academic.grades_list"))
    return form_page()


@bp.route("/grades/<hid:grade_id>", methods=["GET"], endpoint="grade_detail")
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


@bp.route("/grades/<hid:grade_id>/delete", methods=["POST"], endpoint="grade_delete")
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
        q = (
            Section.query.filter_by(school_id=_sid(), year_id=year.id)
            .join(Grade)
        )
        # Ticket #14 — scope-aware filtering.
        from ...services.scopes import apply_scope
        q = apply_scope(q, current_user,
                        section_field=Section.id,
                        grade_field=Section.grade_id,
                        stage_field=Grade.stage)
        sections = q.order_by(Grade.order_index, Section.name).all()
    return render_template("academic/sections_list.html", sections=sections, active_year=year)


@bp.route("/sections/<hid:section_id>", methods=["GET"], endpoint="section_detail")
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
    from ...services.guardians import shown_guardians
    # BUG-007 follow-up — the courses published to this section, linkable
    # from here too (same rules and routes as the course page). Editors
    # only: a view-only role would get 403 opening those course pages.
    can_link = current_user.can("lms", "edit")
    course_links, linkable_courses = [], []
    if can_link:
        from ..courses.views import section_courses
        course_links, linkable_courses = section_courses(section)
    return render_template(
        "academic/section_detail.html",
        section=section, enrollments=enrollments,
        guardian_of=shown_guardians(_sid(), [e.student_id for e in enrollments]),
        course_links=course_links, linkable_courses=linkable_courses,
        can_link=can_link,
    )


SECTION_FIELDS = ("name", "grade_id", "capacity")


def _section_data(form, year, grade, editing=None) -> dict:
    """Name and capacity, or v.Invalid. A name is unique in its grade for
    the year (uq_section_year_grade_name — deleted sections too)."""
    name = v.text(form, "name", "اسم الفصل", max_len=64)
    raw_cap = (form.get("capacity") or "").strip()
    if not raw_cap:
        # as before: a new section gets the form's default, an edit keeps its capacity
        capacity = 30 if editing is None else editing.capacity
    else:
        capacity = v.whole(form, "capacity", "سعة الفصل",
                           keep=editing.capacity if editing else None)
    other = v.clash(Section, exclude_id=getattr(editing, "id", None),
                    year_id=year.id, grade_id=grade.id, name=name)
    if other:
        raise v.Invalid(f"يوجد فصل بنفس الاسم \"{name}\" في هذا الصف لهذه السنة الدراسية{v.deleted_note(other)}.")
    if editing is not None and capacity < editing.current_count:
        raise v.Invalid(f"لا يمكن ضبط السعة على {capacity} — يوجد {editing.current_count} طالب مسجّل بالفعل.")
    return {"name": name, "capacity": capacity}


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

    def form_page(form=None):
        return render_template("academic/section_form.html", section=None, grades=grades, year=year,
                               values=v.values(None, form, SECTION_FIELDS))

    if request.method == "POST":
        grade_id = request.form.get("grade_id", type=int)
        grade = next((g for g in grades if g.id == grade_id), None)
        try:
            if grade is None:
                raise v.Invalid("الصف المختار غير موجود، برجاء إعادة الاختيار.")
            data = _section_data(request.form, year, grade)
        except v.Invalid as e:
            flash(str(e), "danger")
            return form_page(request.form)
        db.session.add(Section(school_id=_sid(), year_id=year.id, grade_id=grade.id, **data))
        err = v.commit("الفصل")
        if err:
            flash(err, "danger")
            return form_page(request.form)
        flash("تم إضافة الفصل.", "success")
        return redirect(url_for("academic.sections_list"))
    return form_page()


@bp.route("/sections/<hid:section_id>/edit", methods=["GET", "POST"])
@login_required
@require_permission("sections", "edit")
def section_edit(section_id):
    """Edit a section. year_id + grade_id are structural — changing them
    would rewrite every enrollment, so we lock them here and only allow
    name and capacity edits. If the user wants to move students to a
    different grade, promotion/transfer flows handle that."""
    section = _get(Section, section_id)

    def form_page(form=None):
        return render_template("academic/section_form.html", section=section, grades=[section.grade],
                               year=section.year, values=v.values(section, form, SECTION_FIELDS))

    if request.method == "POST":
        try:
            data = _section_data(request.form, section.year, section.grade, editing=section)
        except v.Invalid as e:
            flash(str(e), "danger")
            return form_page(request.form)
        for key, val in data.items():
            setattr(section, key, val)
        err = v.commit("الفصل")
        if err:
            flash(err, "danger")
            return form_page(request.form)
        flash("تم تعديل الفصل.", "success")
        return redirect(url_for("academic.section_detail", section_id=section.id))
    return form_page()


@bp.route("/sections/<hid:section_id>/delete", methods=["POST"])
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
