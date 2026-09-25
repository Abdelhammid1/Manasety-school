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


def _save_excuse_file(record, enrollment_id):
    """Ticket T8 — persist an uploaded excuse document alongside the
    attendance row. Stored under `static/uploads/attendance/<eid>/`.

    Silently skips when no file is uploaded or the file is empty.
    Overwrites `record.excuse_document` when a new file is uploaded on
    a re-save."""
    import os
    from flask import current_app, url_for
    from werkzeug.utils import secure_filename
    f = request.files.get(f"excuse_file_{enrollment_id}")
    if not f or not f.filename:
        return
    ext = f.filename.rsplit(".", 1)[-1].lower()
    if ext not in {"pdf", "png", "jpg", "jpeg", "webp"}:
        return
    import uuid as _uuid
    safe = secure_filename(f.filename)
    unique = f"{_uuid.uuid4().hex[:12]}_{safe}"
    subdir = os.path.join(
        current_app.static_folder, "uploads", "attendance", str(enrollment_id)
    )
    os.makedirs(subdir, exist_ok=True)
    path = os.path.join(subdir, unique)
    f.save(path)
    record.excuse_document = url_for(
        "static", filename=f"uploads/attendance/{enrollment_id}/{unique}"
    )


def _notify_absence(*, student, section, on_date, record):
    """Ticket T2 — dispatch one absence notification per guardian on
    `student.guardian_links` that has `can_receive_notifications=True`
    and a phone number set.

    Ticket T9 — also push a copy to any DeviceToken row registered by
    the student's own app (app='student'), so the student's phone
    surfaces the notice too, not just the parents'.

    Falls back to the legacy `student.parent_phone` when the student
    has no guardian links at all — that's the migration bridge for
    old rows imported before the Guardian model existed.

    Returns the count of notifications actually sent."""
    payload = {
        "student": student.full_name,
        "permanent_code": student.permanent_code,
        "date": on_date.isoformat(),
        "section": f"{section.grade.name} / {section.name}",
        "message": (
            f"تنبيه غياب: ابنكم {student.full_name} غائب "
            f"بتاريخ {on_date.isoformat()} "
            f"عن الفصل ({section.grade.name} / {section.name})."
        ),
    }
    sent = 0
    links = list(getattr(student, "guardian_links", None) or [])
    if links:
        for link in links:
            if not getattr(link, "can_receive_notifications", False):
                continue
            g = getattr(link, "guardian", None)
            phone = (getattr(g, "phone", "") or "").strip()
            if not phone:
                continue
            send_notification(
                school_id=_sid(), kind="absence", payload=payload,
                target_phone=phone,
                student_id=student.id,
                related_kind="attendance", related_id=record.id,
            )
            sent += 1
    else:
        # Fallback: legacy flat-field row.
        phone = (getattr(student, "parent_phone", "") or "").strip()
        if phone:
            send_notification(
                school_id=_sid(), kind="absence", payload=payload,
                target_phone=phone,
                student_id=student.id,
                related_kind="attendance", related_id=record.id,
            )
            sent += 1

    # Ticket T9 — queue a per-student self-notification when the
    # student's app has a device registered. The FCM pusher (built on
    # top of DeviceToken.app='student') picks up unpushed rows by
    # kind+student_id. Only enqueued when there's actually a device
    # token so we don't spam the log with never-pushed rows.
    if getattr(student, "user_id", None):
        from ...models import DeviceToken
        has_device = DeviceToken.query.filter_by(
            school_id=_sid(), user_id=student.user_id, app="student",
        ).first()
        if has_device is not None:
            student_payload = dict(payload,
                message=(
                    f"تنبيه: تم رصد غيابك يوم {on_date.isoformat()} "
                    f"في {section.grade.name} / {section.name}."
                ),
                target_app="student",
                target_user_id=student.user_id,
            )
            send_notification(
                school_id=_sid(), kind="absence", payload=student_payload,
                target_phone=None,
                student_id=student.id,
                related_kind="attendance", related_id=record.id,
            )
            sent += 1
    return sent


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
            # Ticket #14 — scope-aware filtering for admins on
            # non-all_school UserScope rows.
            from ...services.scopes import apply_scope
            q = apply_scope(q, current_user,
                            section_field=Section.id, grade_field=Section.grade_id,
                            stage_field=Grade.stage)
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

    # Ticket #4 — refuse attendance entries on non-teaching calendar
    # days. If the school defines the date as holiday/weekend/etc, the
    # POST is blocked with a flash so recorded numbers stay clean.
    from ...models import SchoolCalendarDay
    cal_entry = SchoolCalendarDay.query.filter_by(
        school_id=_sid(), academic_year_id=year.id, date=on_date,
    ).first()
    is_non_teaching = cal_entry is not None and not cal_entry.is_teaching

    enrollments = (
        Enrollment.query.filter_by(
            school_id=_sid(), year_id=year.id, section_id=section.id, status="active",
        )
        .join(Student).order_by(Student.full_name)
        .all()
    )
    # Ticket #8 — attendance mode from School settings decides whether
    # we render the day-grid (per-period) or the flat list.
    from ...models import Period, School
    school_row = db.session.get(School, _sid())
    mode = (school_row.attendance_mode if school_row else None) or "daily"
    periods = []
    if mode in ("per_period", "both"):
        periods = (
            Period.query.filter_by(school_id=_sid(), is_break=False)
            .order_by(Period.order_index).all()
        )
    all_records = Attendance.query.filter(
        Attendance.enrollment_id.in_([e.id for e in enrollments]),
        Attendance.date == on_date,
    ).all()
    # Daily rows use period_id=NULL; per-period rows key on (enrollment, period).
    existing = {a.enrollment_id: a for a in all_records if a.period_id is None}
    existing_by_period = {
        (a.enrollment_id, a.period_id): a for a in all_records if a.period_id is not None
    }

    if request.method == "POST":
        if is_non_teaching:
            flash(
                f"لا يمكن تسجيل حضور في {on_date} — يوم {cal_entry.title or cal_entry.day_type} "
                "حسب التقويم الدراسي. عدّل التقويم أولاً لو محتاج ترصد الحضور فيه.",
                "danger",
            )
            return redirect(url_for("attendance.mark", section_id=section.id, date=on_date))
        updates = 0
        creates = 0
        absent_notifs = 0
        for e in enrollments:
            status = request.form.get(f"status_{e.id}")
            # Ticket T7b — accept `left_early` (already defined in
            # ATTENDANCE_STATUSES). Ticket T8 — read excuse_reason /
            # excuse_document when the teacher marks `excused`.
            if status not in ("present", "absent", "late", "excused", "left_early"):
                continue
            note = (request.form.get(f"note_{e.id}") or "").strip() or None
            excuse_reason = None
            if status == "excused":
                excuse_reason = (
                    request.form.get(f"excuse_reason_{e.id}") or ""
                ).strip() or None

            record = existing.get(e.id)
            prev_status = record.status if record else None
            if record:
                record.status = status
                record.notes = note
                if status == "excused":
                    record.excuse_reason = excuse_reason
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
                    excuse_reason=excuse_reason,
                    recorded_by_user_id=current_user.id,
                )
                db.session.add(record)
                creates += 1
            db.session.flush()

            # Ticket T8 — optional excuse document file upload.
            if status == "excused":
                _save_excuse_file(record, e.id)

            # T2 — Notify every guardian with can_receive_notifications
            # on transition into 'absent'. Falls back to the legacy
            # student.parent_phone only when the student has zero
            # guardian_links (old imports that never went through the
            # new admission form / _sync_student_guardians).
            if status == "absent" and prev_status != "absent":
                student = e.student
                absent_notifs += _notify_absence(
                    student=student, section=section,
                    on_date=on_date, record=record,
                )

        # Ticket #8 — per-period cells. Form fields look like
        # perstatus_<enrollment_id>_<period_id>=<status>.
        if mode in ("per_period", "both") and periods:
            for e in enrollments:
                for p in periods:
                    field = f"perstatus_{e.id}_{p.id}"
                    st = request.form.get(field)
                    if st not in ("present", "absent", "late", "excused", "left_early"):
                        continue
                    row = existing_by_period.get((e.id, p.id))
                    if row is None:
                        row = Attendance(
                            school_id=_sid(),
                            enrollment_id=e.id, date=on_date,
                            period_id=p.id,
                            status=st,
                            recorded_by_user_id=current_user.id,
                        )
                        db.session.add(row); creates += 1
                    else:
                        row.status = st
                        row.recorded_by_user_id = current_user.id
                        row.recorded_at = datetime.utcnow()
                        updates += 1

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
        # Ticket #8
        mode=mode, periods=periods, existing_by_period=existing_by_period,
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

    # Ticket T3 — pull the full row set and derive per-day status
    # (see `_derive_day_status`). This kills double-counting when the
    # school runs in `both` mode.
    counts = _day_status_counts(
        eids=[e.id for e in enrollments],
        start=start, end=end,
    )

    summaries = []
    for e in enrollments:
        c = counts.get(e.id, {})
        p = c.get("present", 0); a = c.get("absent", 0)
        l = c.get("late", 0);    partial = c.get("partial", 0)
        excused    = c.get("excused", 0)
        left_early = c.get("left_early", 0)
        total = p + a + l + partial + excused + left_early
        rate = (p / total * 100) if total else 0
        summaries.append({
            "enrollment": e, "present": p, "absent": a, "late": l,
            "partial": partial, "excused": excused, "left_early": left_early,
            "total": total, "rate": round(rate, 1),
        })

    return render_template(
        "attendance/section_report.html",
        section=section, start=start, end=end, summaries=summaries,
    )


def _derive_day_status(day_records):
    """Ticket T3 — collapse a single (enrollment, date) tuple's rows
    to one status.

    Rules (in priority order):
      · Any daily row (period_id IS NULL) present alongside no
        per-period rows → use the daily row's status verbatim.
      · Per-period rows only:
          - all `absent`             → 'absent'
          - all `present` or mixed present+excused → 'present'
          - any `absent` mixed with any present    → 'partial'
          - any `late` and no absent               → 'late'
      · When both daily and per-period rows are present for the
        same date, the per-period breakdown wins (it's the finer
        signal). Prevents double-counting in `both` mode.
    """
    if not day_records:
        return None
    period_rows = [r for r in day_records if r.period_id is not None]
    daily_rows  = [r for r in day_records if r.period_id is None]
    if not period_rows:
        # Simple daily-only case.
        return daily_rows[0].status if daily_rows else None
    statuses = [r.status for r in period_rows]
    present  = sum(1 for s in statuses if s == "present")
    absent   = sum(1 for s in statuses if s == "absent")
    late     = sum(1 for s in statuses if s == "late")
    if absent == len(statuses):
        return "absent"
    if absent and (present or late):
        return "partial"
    if late:
        return "late"
    if present:
        return "present"
    # Fallback — unknown mix, treat as first period's status.
    return statuses[0]


def _day_status_counts(*, eids, start, end):
    """Ticket T3 — group Attendance rows by (enrollment, date), apply
    `_derive_day_status`, and return {enrollment_id: {status: n}}.

    Returns partial as its own key so the caller can surface it.
    """
    if not eids:
        return {}
    rows = (
        Attendance.query.filter(
            Attendance.enrollment_id.in_(eids),
            Attendance.date >= start, Attendance.date <= end,
        ).all()
    )
    # (eid, date) -> [row, ...]
    grouped = {}
    for r in rows:
        grouped.setdefault((r.enrollment_id, r.date), []).append(r)
    counts = {}
    for (eid, _d), day_records in grouped.items():
        status = _derive_day_status(day_records)
        if not status:
            continue
        counts.setdefault(eid, {})[status] = (
            counts.get(eid, {}).get(status, 0) + 1
        )
    return counts


@bp.route("/reports/student/<int:student_id>")
@login_required
@require_permission("attendance", "view")
def student_report(student_id):
    student = _get(Student, student_id)
    end = _parse_date(request.args.get("end")) or date.today()
    start = _parse_date(request.args.get("start")) or (end - timedelta(days=60))

    enrollments = [e for e in student.enrollments if e.status == "active"]
    # Ticket T3 — derive one status per day so `both`-mode schools
    # don't double-count. `day_rows` powers the day-by-day table.
    day_rows = []
    p = a = l = partial = excused = left_early = 0
    records = []
    if enrollments:
        eids = [e.id for e in enrollments]
        records = (
            Attendance.query.filter(
                Attendance.enrollment_id.in_(eids),
                Attendance.date >= start, Attendance.date <= end,
            ).order_by(Attendance.date.desc()).all()
        )
        grouped = {}
        for r in records:
            grouped.setdefault(r.date, []).append(r)
        for d in sorted(grouped.keys(), reverse=True):
            rowset = grouped[d]
            status = _derive_day_status(rowset)
            day_rows.append({
                "date": d, "status": status,
                "period_count": sum(1 for r in rowset if r.period_id is not None),
                "has_daily": any(r.period_id is None for r in rowset),
            })
            if   status == "present":    p += 1
            elif status == "absent":     a += 1
            elif status == "late":       l += 1
            elif status == "partial":    partial += 1
            elif status == "excused":    excused += 1
            elif status == "left_early": left_early += 1
    total = p + a + l + partial + excused + left_early
    rate = round(p / total * 100, 1) if total else 0
    return render_template(
        "attendance/student_report.html",
        student=student, start=start, end=end, records=records,
        day_rows=day_rows,
        present=p, absent=a, late=l, partial=partial,
        excused=excused, left_early=left_early,
        total=total, rate=rate,
    )


@bp.route("/reports/student/<int:student_id>/day/<date_str>",
          endpoint="student_day_detail")
@login_required
@require_permission("attendance", "view")
def student_day_detail(student_id, date_str):
    """Ticket T3 — per-day breakdown of every period row for one
    student. Called from any 'partial' cell in student_report."""
    student = _get(Student, student_id)
    the_day = _parse_date(date_str)
    if not the_day:
        abort(404)
    enrollments = [e for e in student.enrollments if e.status == "active"]
    rows = []
    if enrollments:
        eids = [e.id for e in enrollments]
        rows = (
            Attendance.query.filter(
                Attendance.enrollment_id.in_(eids),
                Attendance.date == the_day,
            ).order_by(Attendance.period_id.asc().nullsfirst()).all()
        )
    derived = _derive_day_status(rows)
    return render_template(
        "attendance/student_day_detail.html",
        student=student, the_day=the_day,
        rows=rows, derived=derived,
    )


def _parse_date(s):
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d").date()
