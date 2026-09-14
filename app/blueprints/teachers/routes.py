from datetime import datetime

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import (
    AcademicYear, Assignment, Grade, Section, Subject, Teacher, User,
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
    return render_template(
        "teachers/detail.html",
        teacher=teacher,
        assignments=assignments,
        active_year=active_year,
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
    subjects = Subject.query.filter_by(school_id=_sid()).order_by(Subject.name).all()
    return render_template("teachers/subjects_list.html", subjects=subjects)


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


@bp.route("/subjects/new", methods=["GET", "POST"])
@login_required
@require_permission("teachers", "add")
def subject_new():
    grades = Grade.query.filter_by(school_id=_sid()).order_by(Grade.order_index).all()
    if request.method == "POST":
        subject = Subject(
            school_id=_sid(),
            name=request.form["name"].strip(),
            code=(request.form.get("code") or "").strip() or None,
        )
        gids = request.form.getlist("grade_ids", type=int)
        subject.grades = [g for g in grades if g.id in gids]
        db.session.add(subject)
        db.session.commit()
        flash(f"تم إضافة المادة {subject.name}.", "success")
        return redirect(url_for("teachers.subjects_list"))
    return render_template("teachers/subject_form.html", subject=None, grades=grades)


@bp.route("/subjects/<int:subject_id>/edit", methods=["GET", "POST"])
@login_required
@require_permission("teachers", "edit")
def subject_edit(subject_id):
    subject = _get(Subject, subject_id)
    grades = Grade.query.filter_by(school_id=_sid()).order_by(Grade.order_index).all()
    if request.method == "POST":
        subject.name = request.form["name"].strip()
        subject.code = (request.form.get("code") or "").strip() or None
        gids = request.form.getlist("grade_ids", type=int)
        subject.grades = [g for g in grades if g.id in gids]
        db.session.commit()
        flash("تم تحديث المادة.", "success")
        return redirect(url_for("teachers.subjects_list"))
    return render_template("teachers/subject_form.html", subject=subject, grades=grades)


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
    section = _get(Section, section_id)
    year = section.year
    teachers = (
        Teacher.query.filter_by(school_id=_sid(), is_active=True)
        .order_by(Teacher.full_name)
        .all()
    )
    subjects = (
        Subject.query.filter_by(school_id=_sid())
        .join(Subject.grades)
        .filter(Grade.id == section.grade_id)
        .all()
    )

    if request.method == "POST":
        subject_id = int(request.form["subject_id"])
        teacher_id = int(request.form["teacher_id"])
        weekly_periods = max(1, int(request.form.get("weekly_periods") or 1))
        confirmed = request.form.get("confirm_coteach") == "1"

        existing = Assignment.query.filter_by(
            year_id=year.id, section_id=section.id, subject_id=subject_id,
            is_active=True,
        ).all()
        already_same = any(a.teacher_id == teacher_id for a in existing)
        if already_same:
            flash("هذا المعلم مسنَد بالفعل لهذه المادة والفصل.", "warning")
            return redirect(url_for("teachers.section_assignments", section_id=section.id))

        if existing and not confirmed:
            others = "، ".join(a.teacher.full_name for a in existing)
            flash(
                f"تنبيه (تدريس مشترك): المادة مسنَدة سابقًا إلى ({others}). "
                "أكّد لإضافة معلم آخر.",
                "warning",
            )
            return render_template(
                "teachers/assignment_confirm.html",
                section=section, subject_id=subject_id, teacher_id=teacher_id,
                weekly_periods=weekly_periods,
                teachers=teachers, subjects=subjects, others=others,
            )

        a = Assignment(
            school_id=_sid(), year_id=year.id, section_id=section.id,
            subject_id=subject_id, teacher_id=teacher_id,
            weekly_periods=weekly_periods,
        )
        db.session.add(a)
        db.session.commit()
        flash("تم الإسناد بنجاح.", "success")
        return redirect(url_for("teachers.section_assignments", section_id=section.id))

    assignments = (
        Assignment.query.filter_by(
            year_id=year.id, section_id=section.id, is_active=True
        )
        .order_by(Assignment.id)
        .all()
    )
    return render_template(
        "teachers/section_assignments.html",
        section=section, year=year, teachers=teachers, subjects=subjects,
        assignments=assignments,
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
