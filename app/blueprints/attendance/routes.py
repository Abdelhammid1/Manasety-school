from datetime import datetime, date, timedelta

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import (
    AcademicYear, Assignment, Attendance, Enrollment, Grade, NotificationLog,
    Section, Student, Teacher,
)
from ...services.notifications import send_notification


def _sid():
    return current_user.school_id


def _active_year():
    return AcademicYear.query.filter_by(school_id=_sid(), status="active").first()


def _get(model, oid):
    obj = model.query.filter_by(id=oid, school_id=_sid()).first()
    if not obj:
        abort(404)
    return obj


def _teacher_for_current_user():
    """Return the Teacher row for the logged-in user, or None if they aren't
    a teacher (admins, staff without a Teacher profile)."""
    return Teacher.query.filter_by(school_id=_sid(), user_id=current_user.id).first()


def _teacher_can_touch_section(teacher, section):
    """Sprint 9 (TC-6.1.3): check the teacher has an active Assignment covering
    the target section in that section's year."""
    return Assignment.query.filter_by(
        teacher_id=teacher.id, section_id=section.id,
        year_id=section.year_id, is_active=True,
    ).first() is not None


def _is_admin():
    """Sprint 10 hotfix — non-admin users must always be scope-checked, even if
    they don't have a linked Teacher record. This closes the gap where a User
    with role=teacher but no Teacher row was treated like an admin."""
    role_name = getattr(current_user.role, "name", None) if current_user.role else None
    return role_name == "admin"


# ---------- T-6.1 / T-6.2 Daily marking + notifications ----------

@bp.route("")
@login_required
@require_permission("attendance", "view")
def index():
    year = _active_year()
    sections = []
    if year:
        q = (
            Section.query.filter_by(school_id=_sid(), year_id=year.id)
            .join(Grade)
        )
        # Sprint 9 TC-6.1.3 (hardened Sprint 10): admins see all sections.
        # Anyone else (teacher role, misconfigured account, etc.) is filtered
        # to their assigned sections — empty list if no assignments.
        if _is_admin():
            sections = q.order_by(Grade.order_index, Section.name).all()
        else:
            teacher = _teacher_for_current_user()
            if not teacher:
                sections = []  # non-admin without Teacher record → nothing
            else:
                assigned_ids = {
                    a.section_id for a in Assignment.query.filter_by(
                        teacher_id=teacher.id, year_id=year.id, is_active=True,
                    ).all()
                }
                if not assigned_ids:
                    sections = []
                else:
                    q = q.filter(Section.id.in_(assigned_ids))
                    sections = q.order_by(Grade.order_index, Section.name).all()
    return render_template("attendance/index.html", year=year, sections=sections)


@bp.route("/section/<int:section_id>/mark", methods=["GET", "POST"])
@login_required
@require_permission("attendance", "edit")
def mark(section_id):
    section = _get(Section, section_id)

    # Sprint 9 TC-6.1.3 (hardened Sprint 10): non-admins must be assigned to
    # the section. A User with role=teacher but no Teacher record is denied
    # (was previously bypassing the check).
    if not _is_admin():
        teacher = _teacher_for_current_user()
        if not teacher or not _teacher_can_touch_section(teacher, section):
            flash(
                "لا تملك صلاحية تسجيل الحضور لهذا الفصل — يمكنك تسجيل الحضور فقط للفصول المسندة إليك.",
                "danger",
            )
            return redirect(url_for("attendance.index"))

    year = section.year
    on_date = _parse_date(request.values.get("date")) or date.today()

    enrollments = (
        Enrollment.query.filter_by(
            school_id=_sid(), year_id=year.id, section_id=section.id, status="active",
        )
        .join(Student).order_by(Student.full_name)
        .all()
    )
    existing = {
        a.enrollment_id: a
        for a in Attendance.query.filter(
            Attendance.enrollment_id.in_([e.id for e in enrollments]),
            Attendance.date == on_date,
        ).all()
    }

    if request.method == "POST":
        updates = 0
        creates = 0
        absent_notifs = 0
        for e in enrollments:
            status = request.form.get(f"status_{e.id}")
            if status not in ("present", "absent", "late"):
                continue
            note = (request.form.get(f"note_{e.id}") or "").strip() or None

            record = existing.get(e.id)
            prev_status = record.status if record else None
            if record:
                record.status = status
                record.notes = note
                record.recorded_by_user_id = current_user.id
                record.recorded_at = datetime.utcnow()
                updates += 1
            else:
                record = Attendance(
                    school_id=_sid(),
                    enrollment_id=e.id,
                    date=on_date,
                    status=status,
                    notes=note,
                    recorded_by_user_id=current_user.id,
                )
                db.session.add(record)
                creates += 1
            db.session.flush()

            # T-6.2: Notify parent on transition into 'absent'
            if status == "absent" and prev_status != "absent":
                student = e.student
                phone = (student.parent_phone or "").strip()
                if phone:
                    send_notification(
                        school_id=_sid(),
                        kind="absence",
                        payload={
                            "student": student.full_name,
                            "permanent_code": student.permanent_code,
                            "date": on_date.isoformat(),
                            "section": f"{section.grade.name} / {section.name}",
                            "message": (
                                f"تنبيه غياب: ابنكم {student.full_name} غائب "
                                f"بتاريخ {on_date.isoformat()} "
                                f"عن الفصل ({section.grade.name} / {section.name})."
                            ),
                        },
                        target_phone=phone,
                        student_id=student.id,  # Sprint 11: parent-scoping FK
                        related_kind="attendance",
                        related_id=record.id,
                    )
                    absent_notifs += 1

        db.session.commit()
        msg = f"تم الحفظ: {creates} سجل جديد، {updates} سجل محدّث."
        if absent_notifs:
            msg += f" أُرسل {absent_notifs} إشعار غياب لأولياء الأمور."
        flash(msg, "success")
        return redirect(url_for("attendance.mark", section_id=section.id, date=on_date.isoformat()))

    return render_template(
        "attendance/mark.html",
        section=section, year=year, on_date=on_date,
        enrollments=enrollments, existing=existing,
    )


# ---------- T-6.3 Reports ----------

@bp.route("/reports/section/<int:section_id>")
@login_required
@require_permission("attendance", "view")
def section_report(section_id):
    section = _get(Section, section_id)
    end = _parse_date(request.args.get("end")) or date.today()
    start = _parse_date(request.args.get("start")) or (end - timedelta(days=30))

    enrollments = (
        Enrollment.query.filter_by(
            school_id=_sid(), year_id=section.year_id, section_id=section.id, status="active",
        ).join(Student).order_by(Student.full_name).all()
    )

    counts = {}
    for status in ("present", "absent", "late"):
        rows = (
            db.session.query(Attendance.enrollment_id, func.count(Attendance.id))
            .filter(Attendance.status == status,
                    Attendance.date >= start, Attendance.date <= end,
                    Attendance.enrollment_id.in_([e.id for e in enrollments]))
            .group_by(Attendance.enrollment_id).all()
        )
        for eid, c in rows:
            counts.setdefault(eid, {})[status] = c

    summaries = []
    for e in enrollments:
        c = counts.get(e.id, {})
        p, a, l = c.get("present", 0), c.get("absent", 0), c.get("late", 0)
        total = p + a + l
        rate = (p / total * 100) if total else 0
        summaries.append({
            "enrollment": e, "present": p, "absent": a, "late": l,
            "total": total, "rate": round(rate, 1),
        })

    return render_template(
        "attendance/section_report.html",
        section=section, start=start, end=end, summaries=summaries,
    )


@bp.route("/reports/student/<int:student_id>")
@login_required
@require_permission("attendance", "view")
def student_report(student_id):
    student = _get(Student, student_id)
    end = _parse_date(request.args.get("end")) or date.today()
    start = _parse_date(request.args.get("start")) or (end - timedelta(days=60))

    enrollments = [e for e in student.enrollments if e.status == "active"]
    records = []
    p = a = l = 0
    if enrollments:
        eids = [e.id for e in enrollments]
        records = (
            Attendance.query.filter(
                Attendance.enrollment_id.in_(eids),
                Attendance.date >= start, Attendance.date <= end,
            ).order_by(Attendance.date.desc()).all()
        )
        for r in records:
            if r.status == "present": p += 1
            elif r.status == "absent": a += 1
            elif r.status == "late": l += 1
    total = p + a + l
    rate = round(p / total * 100, 1) if total else 0
    return render_template(
        "attendance/student_report.html",
        student=student, start=start, end=end, records=records,
        present=p, absent=a, late=l, total=total, rate=rate,
    )


def _parse_date(s):
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d").date()
