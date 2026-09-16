from datetime import datetime

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import (
    AcademicYear, Assignment, Grade, Section, Subject, Teacher, Term, User,
)


def _sid():
    return current_user.school_id


def _get(model, oid):
    obj = model.query.filter_by(id=oid, school_id=_sid()).first()
    if not obj:
        abort(404)
    return obj


# ---------- T-4.1 Teachers ----------

@bp.route("")
@login_required
@require_permission("teachers", "view")
def teachers_list():
    teachers = (
        Teacher.query.filter_by(school_id=_sid())
        .order_by(Teacher.full_name)
        .all()
    )
    return render_template("teachers/list.html", teachers=teachers)


@bp.route("/new", methods=["GET", "POST"])
@login_required
@require_permission("teachers", "add")
def teacher_new():
    users = User.query.filter_by(school_id=_sid()).order_by(User.full_name).all()
    if request.method == "POST":
        if not request.form.get("full_name", "").strip():
            flash("الاسم الكامل حقل إلزامي.", "danger")
            return render_template("teachers/form.html", teacher=None, form=request.form, users=users)
        if not request.form.get("specialization", "").strip():
            flash("التخصص حقل إلزامي.", "danger")
            return render_template("teachers/form.html", teacher=None, form=request.form, users=users)

        teacher = Teacher(
            school_id=_sid(),
            full_name=request.form["full_name"].strip(),
            national_id=(request.form.get("national_id") or "").strip() or None,
            phone=(request.form.get("phone") or "").strip() or None,
            email=(request.form.get("email") or "").strip() or None,
            specialization=request.form["specialization"].strip(),
            hire_date=_parse_date(request.form.get("hire_date")),
            notes=(request.form.get("notes") or "").strip() or None,
            user_id=int(request.form["user_id"]) if request.form.get("user_id") else None,
        )
        db.session.add(teacher)
        db.session.commit()
        flash(f"تم إنشاء ملف المعلم {teacher.full_name}.", "success")
        return redirect(url_for("teachers.teacher_detail", teacher_id=teacher.id))
    return render_template("teachers/form.html", teacher=None, form={}, users=users)


@bp.route("/<int:teacher_id>")
@login_required
@require_permission("teachers", "view")
def teacher_detail(teacher_id):
    teacher = _get(Teacher, teacher_id)
    active_year = AcademicYear.query.filter_by(school_id=_sid(), status="active").first()
    assignments = []
    if active_year:
        assignments = (
            Assignment.query.filter_by(
                teacher_id=teacher.id, year_id=active_year.id, is_active=True
            )
            .all()
        )
    # Pool of subjects the teacher could be qualified in — same school
    # scope as the pickers elsewhere.
    all_subjects = (
        Subject.query.filter_by(school_id=_sid(), is_active=True)
        .order_by(Subject.name).all()
    )
    return render_template(
        "teachers/detail.html",
        teacher=teacher,
        assignments=assignments,
        active_year=active_year,
        all_subjects=all_subjects,
    )


@bp.route("/<int:teacher_id>/edit", methods=["GET", "POST"])
@login_required
@require_permission("teachers", "edit")
def teacher_edit(teacher_id):
    teacher = _get(Teacher, teacher_id)
    users = User.query.filter_by(school_id=_sid()).order_by(User.full_name).all()
    if request.method == "POST":
        teacher.full_name = request.form["full_name"].strip()
        teacher.national_id = (request.form.get("national_id") or "").strip() or None
        teacher.phone = (request.form.get("phone") or "").strip() or None
        teacher.email = (request.form.get("email") or "").strip() or None
        teacher.specialization = request.form["specialization"].strip()
        teacher.hire_date = _parse_date(request.form.get("hire_date"))
        teacher.notes = (request.form.get("notes") or "").strip() or None
        teacher.user_id = int(request.form["user_id"]) if request.form.get("user_id") else None
        db.session.commit()
        flash("تم تحديث بيانات المعلم.", "success")
        return redirect(url_for("teachers.teacher_detail", teacher_id=teacher.id))
    return render_template("teachers/form.html", teacher=teacher, form={}, users=users)


@bp.route("/<int:teacher_id>/specialization", methods=["POST"])
@login_required
@require_permission("teachers", "edit")
def teacher_specialization(teacher_id):
    """Ticket #14 pt 2 — rewrite the teacher_subjects M2M for this
    teacher. Called from teachers/detail.html qualification chips."""
    teacher = _get(Teacher, teacher_id)
    subject_ids = request.form.getlist("subject_ids", type=int)
    all_subjects = Subject.query.filter_by(school_id=_sid()).all()
    teacher.subjects = [s for s in all_subjects if s.id in subject_ids]
    db.session.commit()
    flash(
        f"تم تحديث المواد المؤهَّل {teacher.full_name} لتدريسها "
        f"({len(teacher.subjects)} مادة).",
        "success",
    )
    return redirect(url_for("teachers.teacher_detail", teacher_id=teacher.id))


@bp.route("/<int:teacher_id>/toggle", methods=["POST"])
@login_required
@require_permission("teachers", "edit")
def teacher_toggle(teacher_id):
    teacher = _get(Teacher, teacher_id)
    teacher.is_active = not teacher.is_active
    db.session.commit()
    flash("تم تحديث حالة المعلم.", "success")
    return redirect(url_for("teachers.teachers_list"))


# ---------- T-4.2 Subjects ----------

@bp.route("/subjects")
@login_required
@require_permission("teachers", "view")
def subjects_list():
    from ...models import Course
    subjects = Subject.query.filter_by(school_id=_sid()).order_by(Subject.name).all()

    # Pre-compute per-subject FK usage so the delete button on each card can
    # disable itself when the delete would be refused. Two queries beat N+1
    # count() calls in the template. Both keys default to 0 so any subject
    # missing from the map still shows correctly.
    sids = [s.id for s in subjects]
    course_counts = {sid: 0 for sid in sids}
    assign_counts = {sid: 0 for sid in sids}
    if sids:
        for sid, cnt in (
            db.session.query(Course.subject_id, db.func.count(Course.id))
            .filter(Course.school_id == _sid(), Course.subject_id.in_(sids))
            .group_by(Course.subject_id).all()
        ):
            course_counts[sid] = cnt
        for sid, cnt in (
            db.session.query(Assignment.subject_id, db.func.count(Assignment.id))
            .filter(Assignment.school_id == _sid(), Assignment.subject_id.in_(sids))
            .group_by(Assignment.subject_id).all()
        ):
            assign_counts[sid] = cnt
    return render_template(
        "teachers/subjects_list.html",
        subjects=subjects,
        course_counts=course_counts,
        assign_counts=assign_counts,
    )


@bp.route("/subjects/<int:subject_id>/delete", methods=["POST"])
@login_required
@require_permission("teachers", "delete")
def subject_delete(subject_id):
    """Hard-delete a subject, but only when nothing points at it.

    Subjects are referenced by four sets of rows:
      · teaching-assignments (assignments.subject_id, NOT NULL)
      · LMS courses          (lms_courses.subject_id, NOT NULL)
      · bank questions       (lms_bank_questions.subject_id, NULL-able)
      · subject_grades / subject_terms  (association tables, cascade OK)

    A delete against a subject still bound to an active teaching-assignment
    or an existing course would either fail at the FK layer or silently
    strand orphan tags. We block the delete instead and tell the user
    what's in the way. Bank-question subject tags are nulled — they're a
    soft link that survives fine as "بدون مادة".
    """
    from ...models import BankQuestion
    subject = _get(Subject, subject_id)

    from ...models import Course
    n_courses = Course.query.filter_by(subject_id=subject.id, school_id=_sid()).count()
    n_assigns = Assignment.query.filter_by(subject_id=subject.id, school_id=_sid()).count()
    if n_courses or n_assigns:
        parts = []
        if n_courses: parts.append(f"{n_courses} مقرّر")
        if n_assigns: parts.append(f"{n_assigns} تخصيص تدريس")
        flash(
            f"لا يمكن حذف المادة ({subject.name}) — مرتبطة بـ "
            + " و".join(parts)
            + ". امسح أو أعِد ربط هذه السجلات أولاً.",
            "danger",
        )
        return redirect(url_for("teachers.subjects_list"))

    # Null-out the soft link on bank questions so the historical tags
    # survive as "بدون مادة" instead of pointing at a dead row.
    BankQuestion.query.filter_by(subject_id=subject.id).update(
        {BankQuestion.subject_id: None}
    )

    name = subject.name
    db.session.delete(subject)  # subject_grades + subject_terms cascade
    db.session.commit()
    flash(f"تم حذف المادة ({name}) نهائياً.", "success")
    return redirect(url_for("teachers.subjects_list"))


@bp.route("/subjects/<int:subject_id>/toggle", methods=["POST"])
@login_required
@require_permission("teachers", "edit")
def subject_toggle(subject_id):
    """Sprint 9 TC-4.2.2 — soft-disable a subject (hard delete would break
    historical GradeEntry rows)."""
    subject = _get(Subject, subject_id)
    subject.is_active = not subject.is_active
    db.session.commit()
    flash(
        f"تم {'تعطيل' if not subject.is_active else 'تفعيل'} المادة ({subject.name}).",
        "success",
    )
    return redirect(url_for("teachers.subjects_list"))


def _grade_and_term_options():
    """Options for subject form dropdowns.

    Grades are school-scoped and ordered. Terms are joined to their parent
    year (already scoped by year.school_id) and ordered by year (newest
    first) then term order — so the picker shows the current-year terms up
    top with the year name inline, and historical terms below.
    """
    grades = (
        Grade.query.filter_by(school_id=_sid())
        .order_by(Grade.order_index).all()
    )
    terms = (
        Term.query.filter_by(school_id=_sid())
        .join(AcademicYear, AcademicYear.id == Term.year_id)
        .order_by(AcademicYear.start_date.desc(), Term.order_index).all()
    )
    return grades, terms


@bp.route("/subjects/new", methods=["GET", "POST"])
@login_required
@require_permission("teachers", "add")
def subject_new():
    grades, terms = _grade_and_term_options()
    if request.method == "POST":
        subject = Subject(
            school_id=_sid(),
            name=request.form["name"].strip(),
            code=(request.form.get("code") or "").strip() or None,
        )
        gids = request.form.getlist("grade_ids", type=int)
        tids = request.form.getlist("term_ids",  type=int)
        subject.grades = [g for g in grades if g.id in gids]
        subject.terms  = [t for t in terms  if t.id in tids]
        db.session.add(subject)
        db.session.commit()
        flash(f"تم إضافة المادة {subject.name}.", "success")
        return redirect(url_for("teachers.subjects_list"))
    return render_template(
        "teachers/subject_form.html",
        subject=None, grades=grades, terms=terms,
    )


@bp.route("/subjects/<int:subject_id>/edit", methods=["GET", "POST"])
@login_required
@require_permission("teachers", "edit")
def subject_edit(subject_id):
    subject = _get(Subject, subject_id)
    grades, terms = _grade_and_term_options()
    if request.method == "POST":
        subject.name = request.form["name"].strip()
        subject.code = (request.form.get("code") or "").strip() or None
        gids = request.form.getlist("grade_ids", type=int)
        tids = request.form.getlist("term_ids",  type=int)
        subject.grades = [g for g in grades if g.id in gids]
        subject.terms  = [t for t in terms  if t.id in tids]
        db.session.commit()
        flash("تم تحديث المادة.", "success")
        return redirect(url_for("teachers.subjects_list"))
    return render_template(
        "teachers/subject_form.html",
        subject=subject, grades=grades, terms=terms,
    )


# ---------- T-4.3 Assignments ----------

@bp.route("/assignments")
@login_required
@require_permission("teachers", "view")
def assignments_list():
    year = AcademicYear.query.filter_by(school_id=_sid(), status="active").first()
    sections = []
    if year:
        sections = (
            Section.query.filter_by(school_id=_sid(), year_id=year.id)
            .join(Grade)
            .order_by(Grade.order_index, Section.name)
            .all()
        )
    return render_template(
        "teachers/assignments_list.html", year=year, sections=sections
    )


@bp.route("/assignments/section/<int:section_id>", methods=["GET", "POST"])
@login_required
@require_permission("teachers", "edit")
def section_assignments(section_id):
    """Ticket #14 — assignments are now term-scoped.

    The screen picks a term (?term_id=X, or the currently-open term of
    the section's year as default). Subjects list is filtered to those
    flagged for that term AND that grade; the teacher dropdown is
    filtered to teachers qualified for the picked subject via the
    teacher_subjects M2M — with an \"إظهار كل المعلمين\" override for
    coverage / emergency assignments.
    """
    section = _get(Section, section_id)
    year = section.year
    # ── Term picker ────────────────────────────────────────────────
    year_terms = (
        Term.query.filter_by(school_id=_sid(), year_id=year.id)
        .order_by(Term.order_index).all()
    )
    requested = request.args.get("term_id", type=int)
    term = None
    if requested:
        term = next((t for t in year_terms if t.id == requested), None)
    if term is None:
        # Default: the currently open term, else the first, else None.
        term = next((t for t in year_terms if t.is_open), None) or (year_terms[0] if year_terms else None)

    # ── Subjects filtered by grade × term ─────────────────────────
    subjects_q = (
        Subject.query.filter_by(school_id=_sid(), is_active=True)
        .join(Subject.grades).filter(Grade.id == section.grade_id)
    )
    if term is not None:
        subjects_q = subjects_q.join(Subject.terms).filter(Term.id == term.id)
    subjects = subjects_q.order_by(Subject.name).all()

    # ── Teachers ──────────────────────────────────────────────────
    all_teachers = (
        Teacher.query.filter_by(school_id=_sid(), is_active=True)
        .order_by(Teacher.full_name).all()
    )
    # For the initial GET render we pass ALL teachers; the client-side
    # JS filters them by the currently-selected subject. Server-side
    # validation on POST does the authoritative check.

    if request.method == "POST":
        subject_id = request.form.get("subject_id", type=int)
        teacher_id = request.form.get("teacher_id", type=int)
        weekly_periods = max(1, int(request.form.get("weekly_periods") or 1))
        confirmed = request.form.get("confirm_coteach") == "1"
        override_specialization = request.form.get("show_all") == "1"

        if not subject_id or not teacher_id:
            flash("اختر المادة والمعلم.", "danger")
            return redirect(url_for("teachers.section_assignments",
                                    section_id=section.id, term_id=term.id if term else None))

        teacher = Teacher.query.filter_by(id=teacher_id, school_id=_sid()).first()
        subject = Subject.query.filter_by(id=subject_id, school_id=_sid()).first()
        if teacher is None or subject is None:
            flash("بيانات غير صالحة.", "danger")
            return redirect(url_for("teachers.section_assignments",
                                    section_id=section.id, term_id=term.id if term else None))

        # Specialization check — refuse silently unless override is set.
        # Empty teacher.subjects is treated as \"generalist\" (no
        # specialization declared yet) and is allowed to teach anything.
        if teacher.subjects and subject not in teacher.subjects and not override_specialization:
            flash(
                f"المعلم ({teacher.full_name}) غير مؤهَّل لتدريس ({subject.name}). "
                "فعّل \"إظهار كل المعلمين\" في الفورم إذا كان هذا إسناداً استثنائيًا.",
                "danger",
            )
            return redirect(url_for("teachers.section_assignments",
                                    section_id=section.id, term_id=term.id if term else None))

        existing = Assignment.query.filter_by(
            year_id=year.id,
            term_id=term.id if term else None,
            section_id=section.id,
            subject_id=subject_id,
            is_active=True,
        ).all()
        already_same = any(a.teacher_id == teacher_id for a in existing)
        if already_same:
            flash("هذا المعلم مسنَد بالفعل لهذه المادة والفصل والفترة.", "warning")
            return redirect(url_for("teachers.section_assignments",
                                    section_id=section.id, term_id=term.id if term else None))

        if existing and not confirmed:
            others = "، ".join(a.teacher.full_name for a in existing)
            flash(
                f"تنبيه (تدريس مشترك): المادة مسنَدة سابقًا إلى ({others}) في هذه الفترة. "
                "أكّد لإضافة معلم آخر.",
                "warning",
            )
            return render_template(
                "teachers/assignment_confirm.html",
                section=section, subject_id=subject_id, teacher_id=teacher_id,
                weekly_periods=weekly_periods,
                teachers=all_teachers, subjects=subjects, others=others,
                term=term,
            )

        a = Assignment(
            school_id=_sid(), year_id=year.id,
            term_id=term.id if term else None,
            section_id=section.id,
            subject_id=subject_id, teacher_id=teacher_id,
            weekly_periods=weekly_periods,
        )
        db.session.add(a)
        db.session.commit()
        flash("تم الإسناد بنجاح.", "success")
        return redirect(url_for("teachers.section_assignments",
                                section_id=section.id, term_id=term.id if term else None))

    # Assignments for this section, scoped to the selected term (with the
    # legacy whole-year assignments — term_id NULL — always folded in so
    # the historical data stays visible until re-tagged).
    assignments_q = Assignment.query.filter_by(
        year_id=year.id, section_id=section.id, is_active=True,
    )
    if term is not None:
        assignments_q = assignments_q.filter(
            (Assignment.term_id == term.id) | (Assignment.term_id.is_(None))
        )
    assignments = assignments_q.order_by(Assignment.id).all()

    # Build a {subject_id: [teacher_id, ...]} map so the JS filter can
    # show only qualified teachers when a subject is picked.
    teacher_subject_map = {
        s.id: [t.id for t in all_teachers if s in t.subjects] for s in subjects
    }
    return render_template(
        "teachers/section_assignments.html",
        section=section, year=year, term=term, year_terms=year_terms,
        teachers=all_teachers, subjects=subjects,
        assignments=assignments,
        teacher_subject_map=teacher_subject_map,
    )


@bp.route("/assignments/<int:assignment_id>/remove", methods=["POST"])
@login_required
@require_permission("teachers", "delete")
def assignment_remove(assignment_id):
    a = _get(Assignment, assignment_id)
    section_id = a.section_id
    a.is_active = False
    db.session.commit()
    flash("تم إلغاء الإسناد.", "success")
    return redirect(url_for("teachers.section_assignments", section_id=section_id))


@bp.route("/assignments/<int:assignment_id>/update", methods=["POST"])
@login_required
@require_permission("teachers", "edit")
def assignment_update(assignment_id):
    a = _get(Assignment, assignment_id)
    a.weekly_periods = max(1, int(request.form.get("weekly_periods") or 1))
    db.session.commit()
    flash("تم تحديث عدد الحصص الأسبوعية.", "success")
    return redirect(url_for("teachers.section_assignments", section_id=a.section_id))


def _parse_date(s):
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d").date()
