from datetime import datetime, date

from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import (
    AcademicYear, Grade, Invoice, Payment, Section, School, Student,
    Enrollment, TransferLog, User, YearResult,
)


def _sid():
    return current_user.school_id


def _active_year():
    return AcademicYear.query.filter_by(school_id=_sid(), status="active").first()


def _next_permanent_code() -> str:
    """
    Returns the next serial permanent code for this school.

    Uses MAX(existing suffix) + 1 rather than COUNT(*) + 1 so that deleting
    a student never causes a collision with an existing code on the next
    insert (unique constraint uq_student_school_code).
    """
    school = db.session.get(School, _sid())
    if school is None:
        raise ValueError("لا توجد مدرسة مرتبطة بالمستخدم الحالي")
    base = school.code or "SCH"
    prefix = f"{base}-"
    codes = (
        db.session.query(Student.permanent_code)
        .filter(Student.school_id == _sid(),
                Student.permanent_code.like(f"{prefix}%"))
        .all()
    )
    max_n = 0
    for (code,) in codes:
        try:
            max_n = max(max_n, int(code[len(prefix):]))
        except (ValueError, TypeError):
            pass
    return f"{prefix}{max_n + 1:05d}"


def _get(model, oid):
    obj = model.query.filter_by(id=oid, school_id=_sid()).first()
    if not obj:
        abort(404)
    return obj


# ---------- T-3.1: Permanent profile ----------

@bp.route("")
@login_required
@require_permission("students", "view")
def students_list():
    q = (request.args.get("q") or "").strip()
    section_id = request.args.get("section_id", type=int)
    year = _active_year()
    query = Student.query.filter_by(school_id=_sid())

    section_ctx = None
    if section_id:
        # Sprint 9 Improvement F.1 — link from a section directly to its students.
        section_ctx = _get(Section, section_id)
        query = query.join(Enrollment).filter(
            Enrollment.section_id == section_id,
            Enrollment.status == "active",
        )

    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(Student.full_name.ilike(like), Student.permanent_code.ilike(like))
        )
    students = query.order_by(Student.full_name).limit(500).all()
    return render_template(
        "students/list.html", students=students, q=q,
        active_year=year, section_ctx=section_ctx,
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
@require_permission("students", "add")
def student_new():
    if request.method == "POST":
        nid = (request.form.get("national_id") or "").strip() or None
        if nid:
            dup = Student.query.filter_by(school_id=_sid(), national_id=nid).first()
            if dup and request.form.get("confirm_dup") != "1":
                flash(
                    f"تنبيه: يوجد طالب آخر بنفس رقم الهوية ({dup.full_name} — {dup.permanent_code}). "
                    "أكّد الحفظ إذا كنت متأكدًا.",
                    "warning",
                )
                return render_template("students/form.html", student=None, form=request.form, dup=dup, parent_users=_parent_users())

        try:
            dob = _parse_date(request.form.get("dob"))
        except ValueError:
            flash("تاريخ الميلاد غير صالح — استخدم صيغة YYYY-MM-DD.", "danger")
            return render_template("students/form.html", student=None, form=request.form, dup=None, parent_users=_parent_users())

        try:
            student = Student(
                school_id=_sid(),
                permanent_code=_next_permanent_code(),
                full_name=request.form["full_name"].strip(),
                national_id=nid,
                dob=dob,
                gender=request.form.get("gender") or None,
                parent_name=(request.form.get("parent_name") or "").strip() or None,
                parent_phone=(request.form.get("parent_phone") or "").strip() or None,
                parent_email=(request.form.get("parent_email") or "").strip() or None,
                parent_user_id=int(request.form["parent_user_id"]) if request.form.get("parent_user_id") else None,
                mother_name=(request.form.get("mother_name") or "").strip() or None,
                mother_phone=(request.form.get("mother_phone") or "").strip() or None,
                address=(request.form.get("address") or "").strip() or None,
                notes=(request.form.get("notes") or "").strip() or None,
            )
            db.session.add(student)
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception("student create failed: form=%r", dict(request.form))
            flash(
                "تعذّر حفظ ملف الطالب. راجع البيانات المدخلة، وإذا استمرت المشكلة تواصل مع الدعم الفني (تم تسجيل الخطأ).",
                "danger",
            )
            return render_template("students/form.html", student=None, form=request.form, dup=None, parent_users=_parent_users())

        flash(f"تم إنشاء ملف الطالب — كود دائم: {student.permanent_code}", "success")
        return redirect(url_for("students.student_detail", student_id=student.id))
    return render_template("students/form.html", student=None, form={}, dup=None, parent_users=_parent_users())


@bp.route("/<int:student_id>")
@login_required
@require_permission("students", "view")
def student_detail(student_id):
    student = _get(Student, student_id)
    year = _active_year()
    has_active_enrollment = any(
        e.year_id == (year.id if year else None) and e.status == "active"
        for e in student.enrollments
    )
    # Sprint 9 Improvement F.2 — surface all fees/payments in one place.
    eids = [e.id for e in student.enrollments]
    invoices = []
    fin_totals = {"invoiced": 0.0, "paid": 0.0, "remaining": 0.0}
    if eids:
        invoices = (
            Invoice.query.filter(Invoice.enrollment_id.in_(eids))
            .order_by(Invoice.issue_date.desc()).all()
        )
        for inv in invoices:
            fin_totals["invoiced"] += float(inv.total_amount)
            fin_totals["paid"] += float(inv.paid_amount)
            fin_totals["remaining"] += float(inv.remaining)
    return render_template(
        "students/detail.html",
        student=student,
        active_year=year,
        has_active_enrollment=has_active_enrollment,
        invoices=invoices, fin_totals=fin_totals,
    )


@bp.route("/<int:student_id>/edit", methods=["GET", "POST"])
@login_required
@require_permission("students", "edit")
def student_edit(student_id):
    student = _get(Student, student_id)
    if request.method == "POST":
        student.full_name = request.form["full_name"].strip()
        student.national_id = (request.form.get("national_id") or "").strip() or None
        student.dob = _parse_date(request.form.get("dob"))
        student.gender = request.form.get("gender") or None
        student.parent_name = (request.form.get("parent_name") or "").strip() or None
        student.parent_phone = (request.form.get("parent_phone") or "").strip() or None
        student.parent_email = (request.form.get("parent_email") or "").strip() or None
        student.parent_user_id = int(request.form["parent_user_id"]) if request.form.get("parent_user_id") else None
        student.mother_name = (request.form.get("mother_name") or "").strip() or None
        student.mother_phone = (request.form.get("mother_phone") or "").strip() or None
        student.address = (request.form.get("address") or "").strip() or None
        student.notes = (request.form.get("notes") or "").strip() or None
        db.session.commit()
        flash("تم تحديث ملف الطالب.", "success")
        return redirect(url_for("students.student_detail", student_id=student.id))
    return render_template("students/form.html", student=student, form={}, dup=None, parent_users=_parent_users())


def _parent_users():
    return User.query.filter_by(school_id=_sid(), is_active=True).order_by(User.full_name).all()


# ---------- T-3.2: Enroll in active year ----------

@bp.route("/<int:student_id>/enroll", methods=["GET", "POST"])
@login_required
@require_permission("students", "add")
def enroll(student_id):
    student = _get(Student, student_id)
    year = _active_year()
    if not year:
        flash("لا توجد سنة نشطة. أنشئ سنة دراسية أولاً.", "warning")
        return redirect(url_for("academic.years_list"))

    existing = Enrollment.query.filter_by(student_id=student.id, year_id=year.id).first()
    if existing and existing.status == "active":
        flash(f"الطالب مقيّد بالفعل في السنة {year.name}.", "warning")
        return redirect(url_for("students.student_detail", student_id=student.id))

    grades = Grade.query.filter_by(school_id=_sid()).order_by(Grade.order_index).all()
    sections = (
        Section.query.filter_by(school_id=_sid(), year_id=year.id)
        .join(Grade)
        .order_by(Grade.order_index, Section.name)
        .all()
    )

    if request.method == "POST":
        section = _get(Section, int(request.form["section_id"]))
        if section.year_id != year.id:
            abort(400)
        if section.is_full:
            flash(
                f"الفصل ({section.grade.name} / {section.name}) ممتلئ "
                f"({section.current_count}/{section.capacity}). اختر فصلاً آخر.",
                "danger",
            )
            return render_template(
                "students/enroll.html", student=student, year=year, sections=sections, grades=grades
            )

        enrollment = Enrollment(
            school_id=_sid(),
            student_id=student.id,
            year_id=year.id,
            grade_id=section.grade_id,
            section_id=section.id,
            status="active",
            enrolled_at=date.today(),
        )
        db.session.add(enrollment)
        db.session.commit()
        flash(
            f"تم قيد الطالب {student.full_name} في {section.grade.name} / {section.name}.",
            "success",
        )
        return redirect(url_for("students.student_detail", student_id=student.id))

    return render_template(
        "students/enroll.html", student=student, year=year, sections=sections, grades=grades
    )


# ---------- T-3.3: Horizontal transfer ----------

@bp.route("/enrollment/<int:enrollment_id>/transfer", methods=["GET", "POST"])
@login_required
@require_permission("students", "edit")
def transfer(enrollment_id):
    enrollment = _get(Enrollment, enrollment_id)
    if enrollment.status != "active":
        flash("لا يمكن نقل قيد غير نشط.", "danger")
        return redirect(url_for("students.student_detail", student_id=enrollment.student_id))

    siblings = (
        Section.query.filter_by(
            school_id=_sid(), year_id=enrollment.year_id, grade_id=enrollment.grade_id
        )
        .filter(Section.id != enrollment.section_id)
        .order_by(Section.name)
        .all()
    )

    if request.method == "POST":
        to_section = _get(Section, int(request.form["to_section_id"]))
        if to_section.grade_id != enrollment.grade_id or to_section.year_id != enrollment.year_id:
            abort(400)
        if to_section.is_full:
            flash(
                f"الفصل المستهدف ({to_section.name}) ممتلئ "
                f"({to_section.current_count}/{to_section.capacity}). تم منع النقل.",
                "danger",
            )
            return render_template(
                "students/transfer.html", enrollment=enrollment, siblings=siblings
            )

        log = TransferLog(
            school_id=_sid(),
            enrollment_id=enrollment.id,
            from_section_id=enrollment.section_id,
            to_section_id=to_section.id,
            transfer_date=date.today(),
            performed_by_user_id=current_user.id,
            notes=(request.form.get("notes") or "").strip() or None,
        )
        enrollment.section_id = to_section.id
        db.session.add(log)
        db.session.commit()
        flash(
            f"تم نقل الطالب إلى الفصل {to_section.name}. تم توثيق تاريخ النقل.",
            "success",
        )
        return redirect(url_for("students.student_detail", student_id=enrollment.student_id))

    return render_template("students/transfer.html", enrollment=enrollment, siblings=siblings)


# ---------- T-3.5: Status change (withdraw/transfer-out) ----------

@bp.route("/enrollment/<int:enrollment_id>/status", methods=["GET", "POST"])
@login_required
@require_permission("students", "edit")
def status_change(enrollment_id):
    enrollment = _get(Enrollment, enrollment_id)
    if request.method == "POST":
        new_status = request.form["status"]
        if new_status not in {"active", "withdrawn", "transferred"}:
            abort(400)
        enrollment.status = new_status
        enrollment.status_changed_at = date.today()
        enrollment.status_reason = (request.form.get("reason") or "").strip() or None
        db.session.commit()
        flash("تم تحديث حالة قيد الطالب.", "success")
        return redirect(url_for("students.student_detail", student_id=enrollment.student_id))
    return render_template("students/status.html", enrollment=enrollment)


# ---------- T-3.4 / Sprint 8 Ticket 4: Auto pass/fail-driven promotion ----------

@bp.route("/promotion", methods=["GET", "POST"])
@login_required
@require_permission("students", "edit")
def promotion():
    """Promote each active enrollment according to its approved YearResult.

    Behavior:
      - Pass students → new enrollment in the next grade / target section.
      - Fail students → new enrollment in the same grade / target section.
      - Students without an approved YearResult are surfaced in an
        'incomplete' bucket and skipped (user must approve results first).

    The whole operation runs in a single DB transaction — on any error the
    entire batch is rolled back.
    """
    years = (
        AcademicYear.query.filter_by(school_id=_sid())
        .order_by(AcademicYear.start_date.desc())
        .all()
    )
    grades = Grade.query.filter_by(school_id=_sid()).order_by(Grade.order_index).all()
    target_year = _active_year()

    # Accept these either from query string (GET picker) or form body (POST from same page).
    from_year_id = (
        request.args.get("from_year_id", type=int)
        or request.form.get("from_year_id", type=int)
    )
    grade_id = (
        request.args.get("grade_id", type=int)
        or request.form.get("grade_id", type=int)
    )

    passes = []                # [(enrollment, YearResult)]
    fails = []                 # [(enrollment, YearResult)]
    incomplete_no_yr = []      # [enrollment] (no YearResult yet)
    incomplete_status = []     # [(enrollment, YearResult)] (status='incomplete')
    next_grade = None
    next_grade_sections = []   # target sections in the NEXT grade
    same_grade_sections = []   # target sections in the SAME grade

    if from_year_id and grade_id:
        from_year = _get(AcademicYear, from_year_id)
        current_grade = _get(Grade, grade_id)
        next_grade = (
            Grade.query.filter_by(school_id=_sid())
            .filter(Grade.order_index > current_grade.order_index)
            .order_by(Grade.order_index)
            .first()
        )

        active_enrollments = (
            Enrollment.query.filter_by(
                school_id=_sid(), year_id=from_year.id,
                grade_id=grade_id, status="active",
            )
            .join(Student)
            .order_by(Student.full_name)
            .all()
        )

        # Pull all YearResult rows for these enrollments in one query
        eids = [e.id for e in active_enrollments]
        yrs_by_eid = {
            yr.enrollment_id: yr
            for yr in YearResult.query.filter(YearResult.enrollment_id.in_(eids)).all()
        }

        # Split by status
        for e in active_enrollments:
            yr = yrs_by_eid.get(e.id)
            if yr is None:
                incomplete_no_yr.append(e)
            elif yr.status == "pass":
                passes.append((e, yr))
            elif yr.status == "fail":
                fails.append((e, yr))
            else:
                incomplete_status.append((e, yr))

        if target_year:
            if next_grade:
                next_grade_sections = (
                    Section.query.filter_by(
                        school_id=_sid(), year_id=target_year.id,
                        grade_id=next_grade.id,
                    )
                    .order_by(Section.name)
                    .all()
                )
            same_grade_sections = (
                Section.query.filter_by(
                    school_id=_sid(), year_id=target_year.id,
                    grade_id=current_grade.id,
                )
                .order_by(Section.name)
                .all()
            )

    if request.method == "POST":
        if not target_year:
            flash("لا توجد سنة نشطة لاستقبال الترقية.", "danger")
            return redirect(url_for("students.promotion"))

        promote_section_id = request.form.get("promote_section_id", type=int)
        retain_section_id = request.form.get("retain_section_id", type=int)

        # Feasibility: need a target section for whichever bucket has students
        if passes and not promote_section_id:
            flash("اختر الفصل المستهدف للطلاب الناجحين قبل التنفيذ.", "danger")
            return redirect(
                url_for("students.promotion", from_year_id=from_year_id, grade_id=grade_id)
            )
        if fails and not retain_section_id:
            flash("اختر الفصل المستهدف للطلاب الراسبين قبل التنفيذ.", "danger")
            return redirect(
                url_for("students.promotion", from_year_id=from_year_id, grade_id=grade_id)
            )
        if passes and not next_grade:
            flash("لا يوجد صف أعلى — تعذّر ترقية الناجحين. راجع الصفوف.", "danger")
            return redirect(
                url_for("students.promotion", from_year_id=from_year_id, grade_id=grade_id)
            )

        promote_section = (
            db.session.get(Section, promote_section_id) if promote_section_id else None
        )
        retain_section = (
            db.session.get(Section, retain_section_id) if retain_section_id else None
        )

        # Validate the sections match the expected grades + belong to target_year
        if promote_section and (
            promote_section.year_id != target_year.id
            or (next_grade and promote_section.grade_id != next_grade.id)
        ):
            flash("الفصل المستهدف للناجحين غير صالح.", "danger")
            return redirect(
                url_for("students.promotion", from_year_id=from_year_id, grade_id=grade_id)
            )
        if retain_section and (
            retain_section.year_id != target_year.id
            or retain_section.grade_id != grade_id
        ):
            flash("الفصل المستهدف للراسبين غير صالح.", "danger")
            return redirect(
                url_for("students.promotion", from_year_id=from_year_id, grade_id=grade_id)
            )

        promoted_n = 0
        retained_n = 0
        skipped_already_enrolled = 0
        skipped_capacity = 0

        try:
            # Single transaction — commit at the end, rollback on any error
            for e, yr in passes:
                already = Enrollment.query.filter_by(
                    student_id=e.student_id, year_id=target_year.id
                ).first()
                if already:
                    skipped_already_enrolled += 1
                    continue
                if promote_section.is_full:
                    skipped_capacity += 1
                    continue
                e.final_result = "pass"
                e.status = "promoted_out"
                db.session.add(Enrollment(
                    school_id=_sid(),
                    student_id=e.student_id,
                    year_id=target_year.id,
                    grade_id=next_grade.id,
                    section_id=promote_section.id,
                    status="active",
                    enrolled_at=date.today(),
                ))
                promoted_n += 1

            for e, yr in fails:
                already = Enrollment.query.filter_by(
                    student_id=e.student_id, year_id=target_year.id
                ).first()
                if already:
                    skipped_already_enrolled += 1
                    continue
                if retain_section.is_full:
                    skipped_capacity += 1
                    continue
                e.final_result = "fail"
                e.status = "promoted_out"
                db.session.add(Enrollment(
                    school_id=_sid(),
                    student_id=e.student_id,
                    year_id=target_year.id,
                    grade_id=e.grade_id,
                    section_id=retain_section.id,
                    status="active",
                    enrolled_at=date.today(),
                ))
                retained_n += 1

            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception("promotion transaction failed")
            flash(
                f"فشلت عملية الترقية وتمّ إلغاء كل التغييرات: {exc}",
                "danger",
            )
            return redirect(
                url_for("students.promotion", from_year_id=from_year_id, grade_id=grade_id)
            )

        msg = (
            f"تمّ اعتماد الترقية: {promoted_n} ناجح تمّت ترقيتهم • "
            f"{retained_n} راسب أُبقوا في نفس الصف"
        )
        if skipped_already_enrolled or skipped_capacity:
            msg += (
                f" • تخطّي {skipped_already_enrolled + skipped_capacity} "
                f"(قيد مُسبق أو فصل ممتلئ)"
            )
        flash(msg + ".", "success")
        return redirect(
            url_for("students.promotion", from_year_id=from_year_id, grade_id=grade_id)
        )

    return render_template(
        "students/promotion.html",
        years=years,
        grades=grades,
        from_year_id=from_year_id,
        grade_id=grade_id,
        target_year=target_year,
        next_grade=next_grade,
        passes=passes,
        fails=fails,
        incomplete_no_yr=incomplete_no_yr,
        incomplete_status=incomplete_status,
        next_grade_sections=next_grade_sections,
        same_grade_sections=same_grade_sections,
    )


# ---------- helpers ----------

def _parse_date(s):
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d").date()
