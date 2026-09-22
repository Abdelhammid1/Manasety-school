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


def _upsert_guardian_link(student, name, phone, *, relationship, is_primary):
    """Ticket #1 — keep student.parent_*/mother_* fields in sync with
    real Guardian rows.

    Looks up an existing Guardian in this school by phone (same rule
    the Guardian tab uses), creates one if none matches. Then ensures
    an active StudentGuardian link exists — updating relationship/
    is_primary on an existing link if needed. No-op when both name and
    phone are empty.

    Returns the Guardian row (or None if nothing was written).
    """
    from ...models import Guardian, StudentGuardian
    name = (name or "").strip() or None
    phone = (phone or "").strip() or None
    if not name and not phone:
        return None
    sid = student.school_id

    guardian = None
    if phone:
        guardian = Guardian.query.filter_by(school_id=sid, phone=phone).first()
    if guardian is None and name:
        # Same-school same-name fallback so parents typed in twice with
        # no phone don't get duplicated. Matches backfill script's rule.
        guardian = Guardian.query.filter_by(school_id=sid, full_name=name).first()
    if guardian is None:
        if not name:
            # We won't create a phone-only Guardian without a name; the
            # form's parent_name field is what carries it. Fall through
            # silently to preserve backwards-compat for edits that only
            # supply a phone.
            return None
        guardian = Guardian(school_id=sid, full_name=name, phone=phone)
        db.session.add(guardian); db.session.flush()
    else:
        # Merge fresh info onto the existing Guardian (name upgrade,
        # phone fill-in) without stomping non-empty values.
        if name and not guardian.full_name:
            guardian.full_name = name
        if phone and not guardian.phone:
            guardian.phone = phone

    link = StudentGuardian.query.filter_by(
        student_id=student.id, guardian_id=guardian.id,
    ).first()
    if link is None:
        db.session.add(StudentGuardian(
            student_id=student.id, guardian_id=guardian.id,
            relationship=relationship, is_primary=is_primary,
            can_receive_notifications=True,
        ))
    else:
        # Only promote to primary if we're syncing the "father" record
        # and no other link is primary yet; never demote an existing
        # primary picked from the Guardians tab.
        if is_primary and not any(
            l.is_primary for l in student.guardian_links if l.id != link.id
        ):
            link.is_primary = True
        if relationship and not link.relationship:
            link.relationship = relationship
    return guardian


def _sync_student_guardians(student):
    """Ticket #1 wiring — call after any student write that touched
    parent_*/mother_* fields. Bridges the legacy flat fields with the
    Guardian entity so the two never drift apart."""
    _upsert_guardian_link(
        student, student.parent_name, student.parent_phone,
        relationship="أب", is_primary=True,
    )
    _upsert_guardian_link(
        student, student.mother_name, student.mother_phone,
        relationship="أم", is_primary=False,
    )


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

    # Ticket #14 — scope the list by the user's UserScope. When the
    # user has grade/section scopes, join through their active
    # Enrollment and filter by those. Users with no UserScope pass
    # through unchanged.
    from ...services.scopes import apply_scope, _user_scopes
    scopes = _user_scopes(current_user)
    if scopes and not any(s.scope_type == "all_school" for s in scopes):
        query = query.join(Enrollment, Enrollment.student_id == Student.id) \
                     .filter(Enrollment.status == "active")
        query = apply_scope(query, current_user,
                            section_field=Enrollment.section_id,
                            grade_field=Enrollment.grade_id)

    students = query.order_by(Student.full_name).limit(500).all()
    return render_template(
        "students/list.html", students=students, q=q,
        active_year=year, section_ctx=section_ctx,
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
@require_permission("students", "add")
def student_new():
    from ...models import Guardian, StudentGuardian
    guardians_pool = (
        Guardian.query.filter_by(school_id=_sid())
        .order_by(Guardian.full_name).all()
    )
    render_kwargs = dict(
        parent_users=_parent_users(),
        guardians_pool=guardians_pool,
    )

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
                return render_template("students/form.html", student=None, form=request.form, dup=dup, **render_kwargs)

        try:
            dob = _parse_date(request.form.get("dob"))
        except ValueError:
            flash("تاريخ الميلاد غير صالح — استخدم صيغة YYYY-MM-DD.", "danger")
            return render_template("students/form.html", student=None, form=request.form, dup=None, **render_kwargs)

        parent_name = (request.form.get("parent_name") or "").strip() or None
        parent_phone = (request.form.get("parent_phone") or "").strip() or None
        parent_email = (request.form.get("parent_email") or "").strip() or None

        # Ticket #7 — Guardian picker with three modes:
        #   • guardian_mode=existing → link the picked Guardian
        #   • guardian_mode=new_with_account → create Guardian + User inline
        #   • guardian_mode=new (default) → create Guardian only, no account
        guardian_mode = (request.form.get("guardian_mode") or "new").strip()
        existing_guardian_id = request.form.get("existing_guardian_id", type=int)

        try:
            student = Student(
                school_id=_sid(),
                permanent_code=_next_permanent_code(),
                full_name=request.form["full_name"].strip(),
                national_id=nid,
                dob=dob,
                gender=request.form.get("gender") or None,
                parent_name=parent_name,
                parent_phone=parent_phone,
                parent_email=parent_email,
                parent_user_id=int(request.form["parent_user_id"]) if request.form.get("parent_user_id") else None,
                mother_name=(request.form.get("mother_name") or "").strip() or None,
                mother_phone=(request.form.get("mother_phone") or "").strip() or None,
                address=(request.form.get("address") or "").strip() or None,
                notes=(request.form.get("notes") or "").strip() or None,
            )
            db.session.add(student)
            db.session.flush()

            # Ticket #7 — link an existing Guardian if the admin picked one;
            # otherwise fall through to the legacy sync path.
            if guardian_mode == "existing" and existing_guardian_id:
                g = Guardian.query.filter_by(
                    id=existing_guardian_id, school_id=_sid(),
                ).first()
                if g:
                    db.session.add(StudentGuardian(
                        student_id=student.id, guardian_id=g.id,
                        relationship="أب", is_primary=True,
                        can_receive_notifications=True,
                    ))
                    if g.user_id and not student.parent_user_id:
                        student.parent_user_id = g.user_id
            else:
                # Ticket #1 — bridge the legacy parent_* fields to Guardian.
                _sync_student_guardians(student)

                # Ticket #7 — if requested, create a login for the just-
                # created guardian right after we synced the row.
                if (guardian_mode == "new_with_account"
                        and parent_name and student.guardian_links):
                    primary_guardian = next(
                        (l.guardian for l in student.guardian_links
                         if l.is_primary), None,
                    ) or student.guardian_links[0].guardian
                    if primary_guardian and not primary_guardian.user_id:
                        from ...services.user_provisioning import provision_user
                        new_user, err = provision_user(
                            school_id=_sid(), kind="parent",
                            full_name=primary_guardian.full_name,
                            username=request.form.get("guardian_account_username"),
                            password=request.form.get("guardian_account_password"),
                            email=parent_email, phone=parent_phone,
                        )
                        if err:
                            db.session.rollback()
                            flash(err, "danger")
                            return render_template("students/form.html", student=None, form=request.form, dup=None, **render_kwargs)
                        primary_guardian.user_id = new_user.id
                        student.parent_user_id = new_user.id

            # Ticket #7 — inline student account (parent-app / student portal).
            if request.form.get("create_student_account"):
                from ...services.user_provisioning import provision_user
                new_user, err = provision_user(
                    school_id=_sid(), kind="student",
                    full_name=student.full_name,
                    username=request.form.get("student_account_username"),
                    password=request.form.get("student_account_password"),
                    email=None, phone=None,
                )
                if err:
                    db.session.rollback()
                    flash(err, "danger")
                    return render_template("students/form.html", student=None, form=request.form, dup=None, **render_kwargs)
                # Ticket (2026-09-21) — link the new User back to the
                # Student row via `student.user_id` so the student
                # mobile app can look up its own profile on login.
                student.user_id = new_user.id

            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception("student create failed: form=%r", dict(request.form))
            flash(
                "تعذّر حفظ ملف الطالب. راجع البيانات المدخلة، وإذا استمرت المشكلة تواصل مع الدعم الفني (تم تسجيل الخطأ).",
                "danger",
            )
            return render_template("students/form.html", student=None, form=request.form, dup=None, **render_kwargs)

        flash(f"تم إنشاء ملف الطالب — كود دائم: {student.permanent_code}", "success")
        return redirect(url_for("students.student_detail", student_id=student.id))
    return render_template("students/form.html", student=None, form={}, dup=None, **render_kwargs)


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
    # Ticket C — pass the CTA-trigger through as a plain int so the
    # template doesn't need Jinja's int filter.
    new_enrollment_id = request.args.get("new_enrollment_id", type=int) or 0
    return render_template(
        "students/detail.html",
        student=student,
        active_year=year,
        has_active_enrollment=has_active_enrollment,
        invoices=invoices, fin_totals=fin_totals,
        new_enrollment_id=new_enrollment_id,
    )


# ─── Ticket 1 — Guardians on the student page ─────────────────────────

@bp.route("/<int:student_id>/guardians/add", methods=["POST"])
@login_required
@require_permission("students", "edit")
def guardian_add(student_id):
    """Attach an existing Guardian by phone/national_id lookup, or create
    a fresh one if no match. Idempotent: refuses to duplicate the
    student↔guardian link."""
    from ...models import Guardian, StudentGuardian
    student = _get(Student, student_id)
    sid = current_user.school_id

    lookup_phone = (request.form.get("phone") or "").strip()
    lookup_nid   = (request.form.get("national_id") or "").strip()
    full_name    = (request.form.get("full_name") or "").strip()
    relationship = (request.form.get("relationship") or "أب").strip()

    guardian = None
    if lookup_nid:
        guardian = Guardian.query.filter_by(school_id=sid, national_id=lookup_nid).first()
    if guardian is None and lookup_phone:
        guardian = Guardian.query.filter_by(school_id=sid, phone=lookup_phone).first()

    if guardian is None:
        if not full_name:
            flash("اسم ولي الأمر مطلوب لإنشاء صف جديد.", "danger")
            return redirect(url_for("students.student_detail", student_id=student.id))
        guardian = Guardian(
            school_id=sid, full_name=full_name,
            phone=lookup_phone or None,
            national_id=lookup_nid or None,
            email=(request.form.get("email") or "").strip() or None,
            occupation=(request.form.get("occupation") or "").strip() or None,
        )
        db.session.add(guardian); db.session.flush()

    existing = StudentGuardian.query.filter_by(
        student_id=student.id, guardian_id=guardian.id,
    ).first()
    if existing:
        flash(f"{guardian.full_name} مرتبط بالفعل بالطالب.", "warning")
        return redirect(url_for("students.student_detail", student_id=student.id))

    db.session.add(StudentGuardian(
        student_id=student.id, guardian_id=guardian.id,
        relationship=relationship,
        is_primary=bool(request.form.get("is_primary")),
        is_emergency_contact=bool(request.form.get("is_emergency_contact")),
        can_pickup_student=bool(request.form.get("can_pickup_student")),
        can_view_academic_data=bool(request.form.get("can_view_academic_data")),
        can_view_financial_data=bool(request.form.get("can_view_financial_data")),
        can_receive_notifications=bool(request.form.get("can_receive_notifications", "1")),
    ))

    # Ticket "ربط حساب ولي الأمر" — inline account creation. The
    # guardian modal now carries a "إنشاء حساب دخول" checkbox +
    # username/password fields. If ticked, we spin a fresh User with
    # role='parent', link it to the Guardian, and stamp
    # Student.parent_user_id so the parent portal + parent app can
    # sign in immediately without a separate admin trip.
    if request.form.get("create_login_account"):
        from ...models import User
        from werkzeug.security import generate_password_hash
        raw_username = (request.form.get("login_username") or "").strip()
        raw_password = (request.form.get("login_password") or "").strip()
        if len(raw_password) < 8:
            flash("كلمة المرور مطلوبة (٨ أحرف على الأقل) لإنشاء حساب الدخول.", "warning")
        else:
            username = raw_username or (guardian.phone or "") \
                       or f"parent_{guardian.id}"
            if User.query.filter_by(username=username).first():
                flash(f"اسم المستخدم «{username}» مستخدم بالفعل — يرجى اختيار اسم آخر.",
                      "warning")
            else:
                new_user = User(
                    username=username,
                    full_name=guardian.full_name,
                    email=guardian.email or None,
                    school_id=sid, role="parent", is_active=True,
                )
                new_user.password_hash = generate_password_hash(raw_password)
                db.session.add(new_user); db.session.flush()
                if hasattr(guardian, "user_id"):
                    guardian.user_id = new_user.id
                if student.parent_user_id is None:
                    student.parent_user_id = new_user.id
                flash(f"تم إنشاء حساب دخول لولي الأمر — اسم المستخدم: {username}",
                      "success")

    db.session.commit()
    flash(f"تم ربط ولي الأمر {guardian.full_name} بالطالب.", "success")
    return redirect(url_for("students.student_detail", student_id=student.id))


@bp.route("/guardian-links/<int:link_id>/update", methods=["POST"])
@login_required
@require_permission("students", "edit")
def guardian_link_update(link_id):
    from ...models import StudentGuardian
    link = StudentGuardian.query.get_or_404(link_id)
    link.relationship = (request.form.get("relationship") or link.relationship or "").strip() or None
    link.is_primary = bool(request.form.get("is_primary"))
    link.is_emergency_contact = bool(request.form.get("is_emergency_contact"))
    link.can_pickup_student = bool(request.form.get("can_pickup_student"))
    link.can_view_academic_data = bool(request.form.get("can_view_academic_data"))
    link.can_view_financial_data = bool(request.form.get("can_view_financial_data"))
    link.can_receive_notifications = bool(request.form.get("can_receive_notifications"))
    db.session.commit()
    flash("تم تحديث صلاحيات ولي الأمر.", "success")
    return redirect(url_for("students.student_detail", student_id=link.student_id))


@bp.route("/guardian-links/<int:link_id>/delete", methods=["POST"])
@login_required
@require_permission("students", "edit")
def guardian_link_delete(link_id):
    from ...models import StudentGuardian
    link = StudentGuardian.query.get_or_404(link_id)
    sid = link.student_id
    db.session.delete(link); db.session.commit()
    flash("تم إلغاء ربط ولي الأمر بالطالب.", "success")
    return redirect(url_for("students.student_detail", student_id=sid))


@bp.route("/guardians")
@login_required
@require_permission("students", "view")
def guardians_list():
    """School-wide guardian directory. Each row shows the guardian +
    their linked students so admins can see brothers/sisters together."""
    from ...models import Guardian
    q = Guardian.query.filter_by(school_id=current_user.school_id)
    search = (request.args.get("q") or "").strip()
    if search:
        q = q.filter(db.or_(
            Guardian.full_name.ilike(f"%{search}%"),
            Guardian.phone.ilike(f"%{search}%"),
            Guardian.national_id.ilike(f"%{search}%"),
        ))
    items = q.order_by(Guardian.full_name).limit(300).all()
    return render_template("students/guardians_list.html", guardians=items, search=search)


@bp.route("/guardians/new", methods=["GET", "POST"], endpoint="guardian_new")
@login_required
@require_permission("students", "add")
def guardian_new():
    """Ticket #8 — standalone Guardian creation from the guardians tab.
    Optional inline User account + optional link to one or more students."""
    from ...models import Guardian, StudentGuardian
    students_pool = (
        Student.query.filter_by(school_id=_sid())
        .order_by(Student.full_name).limit(1000).all()
    )
    if request.method == "POST":
        full_name = (request.form.get("full_name") or "").strip()
        if not full_name:
            flash("اسم ولي الأمر مطلوب.", "danger")
            return render_template("students/guardian_form.html",
                                   form=request.form, students=students_pool)
        phone = (request.form.get("phone") or "").strip() or None
        national_id = (request.form.get("national_id") or "").strip() or None
        email = (request.form.get("email") or "").strip() or None

        guardian = Guardian(
            school_id=_sid(),
            full_name=full_name,
            phone=phone, national_id=national_id, email=email,
            occupation=(request.form.get("occupation") or "").strip() or None,
            address=(request.form.get("address") or "").strip() or None,
        )
        db.session.add(guardian); db.session.flush()

        if request.form.get("create_account"):
            from ...services.user_provisioning import provision_user
            new_user, err = provision_user(
                school_id=_sid(), kind="parent", full_name=full_name,
                username=request.form.get("account_username"),
                password=request.form.get("account_password"),
                email=email, phone=phone,
            )
            if err:
                db.session.rollback()
                flash(err, "danger")
                return render_template("students/guardian_form.html",
                                       form=request.form, students=students_pool)
            guardian.user_id = new_user.id

        # Ticket #8 — link one or more students in the same step.
        picked_student_ids = request.form.getlist("student_ids", type=int)
        primary_student_id = request.form.get("primary_student_id", type=int)
        for stu_id in picked_student_ids:
            stu = Student.query.filter_by(id=stu_id, school_id=_sid()).first()
            if not stu:
                continue
            db.session.add(StudentGuardian(
                student_id=stu.id, guardian_id=guardian.id,
                relationship=(request.form.get("relationship") or "أب").strip(),
                is_primary=(stu.id == primary_student_id),
                can_receive_notifications=True,
            ))
            if guardian.user_id and not stu.parent_user_id:
                stu.parent_user_id = guardian.user_id

        db.session.commit()
        flash(f"تم إضافة ولي الأمر {guardian.full_name}.", "success")
        return redirect(url_for("students.guardians_list"))

    return render_template("students/guardian_form.html",
                           form={}, students=students_pool)


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
        # Ticket #1 — same guardian sync as student_new.
        _sync_student_guardians(student)
        db.session.commit()
        flash("تم تحديث ملف الطالب.", "success")
        return redirect(url_for("students.student_detail", student_id=student.id))
    from ...models import Guardian
    return render_template(
        "students/form.html", student=student, form={}, dup=None,
        parent_users=_parent_users(),
        guardians_pool=Guardian.query.filter_by(school_id=_sid())
            .order_by(Guardian.full_name).all(),
    )


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
        # Ticket C — land on the student detail page and surface an
        # explicit "Create invoice now" CTA scoped to this enrollment.
        # The flag is read by students/detail.html; the invoice_new
        # route reads ?enrollment_id=… to pre-select the dropdown.
        flash(
            f"تم قيد الطالب {student.full_name} في {section.grade.name} / {section.name}. "
            "تقدر تنشئ فاتورة الرسوم لسنة القيد دلوقتي.",
            "success",
        )
        return redirect(url_for(
            "students.student_detail",
            student_id=student.id, new_enrollment_id=enrollment.id,
        ))

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
