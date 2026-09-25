"""Phase-3 academic dashboards (tickets A4, A5, A8).

- section_capacity_dashboard  — A5
- grade_report                 — A4  (whole-grade rollup)
- subject_report               — A4  (one subject across every grade)
- bulk_transfer                — A8  (multi-student transfer form + POST)
"""

from flask import (
    abort, flash, redirect, render_template, request, url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import func

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import (
    AcademicYear, Enrollment, Grade, Section, Student, Subject,
    Attendance, GradeEntry,
)


def _sid():
    return current_user.school_id


def _active_year():
    return AcademicYear.query.filter_by(school_id=_sid(), status="active").first()


# ─── A5 — Section capacity dashboard ───────────────────────────────
@bp.route("/dashboards/section-capacity",
          endpoint="section_capacity_dashboard")
@login_required
@require_permission("students", "view")
def section_capacity_dashboard():
    """Ticket A5 — one screen showing occupancy for every section in
    the current year. Uses a single GROUP BY query (mirrors the
    `grades_list` pattern) instead of hitting Section.current_count
    per-row (which is a property → N+1)."""
    year = _active_year()
    sections = []
    if year:
        # sections joined to their grade so we can render grouped.
        sections = (
            Section.query.filter_by(school_id=_sid(), year_id=year.id)
            .join(Grade, Grade.id == Section.grade_id)
            .order_by(Grade.order_index, Section.name)
            .all()
        )
    # Batch-count active enrollments per section.
    counts_by_section = dict(
        db.session.query(
            Enrollment.section_id, func.count(Enrollment.id),
        )
        .filter(
            Enrollment.school_id == _sid(),
            Enrollment.status == "active",
            Enrollment.section_id.in_([s.id for s in sections] or [0]),
        )
        .group_by(Enrollment.section_id)
        .all()
    )
    rows = []
    for s in sections:
        cnt = counts_by_section.get(s.id, 0)
        cap = s.capacity or 0
        pct = int(round(cnt / cap * 100)) if cap else 0
        rows.append({
            "grade":       s.grade.name,
            "section":     s.name,
            "current":     cnt,
            "capacity":    cap,
            "pct":         pct,
            "over":        cap and cnt > cap,
            "id":          s.id,
        })
    # Group by grade for the template.
    by_grade = {}
    for r in rows:
        by_grade.setdefault(r["grade"], []).append(r)
    return render_template(
        "academic/section_capacity_dashboard.html",
        year=year, rows=rows, by_grade=by_grade,
    )


# ─── A4 — Grade-level rollup ───────────────────────────────────────
@bp.route("/dashboards/grade/<int:grade_id>", endpoint="grade_report")
@login_required
@require_permission("students", "view")
def grade_report(grade_id):
    """Ticket A4 — aggregate attendance rate + average grade across
    every section in a given Grade for the active academic year."""
    grade = Grade.query.filter_by(id=grade_id, school_id=_sid()).first_or_404()
    year = _active_year()
    per_section = []
    if year:
        sections = (
            Section.query.filter_by(
                school_id=_sid(), year_id=year.id, grade_id=grade.id)
            .order_by(Section.name).all()
        )
        for s in sections:
            eids = [e.id for e in Enrollment.query.filter_by(
                school_id=_sid(), section_id=s.id, status="active",
            ).all()]
            att = _attendance_bucket_totals(eids)
            gpa = _grade_avg(eids)
            per_section.append({
                "id":      s.id, "name": s.name,
                "student_count": len(eids),
                "present": att["present"], "absent": att["absent"],
                "late":    att["late"], "attendance_rate": att["rate"],
                "avg_grade": gpa,
            })
    # Grade-wide averages.
    total_students = sum(r["student_count"] for r in per_section)
    total_present  = sum(r["present"] for r in per_section)
    total_abs      = sum(r["absent"] for r in per_section)
    total_days     = total_present + total_abs + sum(r["late"] for r in per_section)
    overall_att = round(total_present / total_days * 100, 1) if total_days else 0
    grade_avg   = (
        round(sum((r["avg_grade"] or 0) * r["student_count"]
                  for r in per_section) / total_students, 2)
        if total_students else 0
    )
    return render_template(
        "academic/grade_report.html",
        grade=grade, year=year, per_section=per_section,
        stats={"total_students": total_students,
               "attendance_rate": overall_att,
               "avg_grade": grade_avg},
    )


@bp.route("/dashboards/subject/<int:subject_id>", endpoint="subject_report")
@login_required
@require_permission("students", "view")
def subject_report(subject_id):
    """Ticket A4 — subject rollup across every grade it's taught in."""
    subject = Subject.query.filter_by(
        id=subject_id, school_id=_sid()).first_or_404()
    year = _active_year()

    # Grade-level entries for this subject (one row per grade with
    # aggregate figures). Relies on GradeEntry.subject_id when present.
    rows = []
    if year and hasattr(GradeEntry, "subject_id"):
        rows = (
            db.session.query(
                Grade.id, Grade.name,
                func.count(GradeEntry.id).label("entries"),
                func.avg(GradeEntry.value).label("avg_value"),
            )
            .join(Enrollment, Enrollment.id == GradeEntry.enrollment_id)
            .join(Grade, Grade.id == Enrollment.grade_id)
            .filter(
                Enrollment.school_id == _sid(),
                GradeEntry.subject_id == subject.id,
            )
            .group_by(Grade.id, Grade.name)
            .order_by(Grade.order_index).all()
        )
    return render_template(
        "academic/subject_report.html",
        subject=subject, year=year, rows=rows,
    )


def _attendance_bucket_totals(enrollment_ids):
    if not enrollment_ids:
        return {"present": 0, "absent": 0, "late": 0, "rate": 0}
    rows = dict(
        db.session.query(Attendance.status, func.count(Attendance.id))
        .filter(Attendance.enrollment_id.in_(enrollment_ids))
        .group_by(Attendance.status).all()
    )
    p = rows.get("present", 0)
    a = rows.get("absent", 0)
    l = rows.get("late", 0)
    total = p + a + l
    rate = round(p / total * 100, 1) if total else 0
    return {"present": p, "absent": a, "late": l, "rate": rate}


def _grade_avg(enrollment_ids):
    if not enrollment_ids:
        return None
    val = (
        db.session.query(func.avg(GradeEntry.value))
        .filter(GradeEntry.enrollment_id.in_(enrollment_ids))
        .scalar()
    )
    return round(float(val), 2) if val is not None else None


# ─── A8 — Bulk transfer ────────────────────────────────────────────
@bp.route("/sections/<int:from_id>/bulk-transfer",
          methods=["GET", "POST"], endpoint="bulk_transfer")
@login_required
@require_permission("students", "edit")
def bulk_transfer(from_id):
    """Ticket A8 — move multiple students at once between sections in
    the same grade. Reuses the single-student transfer semantics
    (transfer_date + TransferLog + capacity check) inside a loop so
    partial success is possible: successful moves commit, refusals
    are collected and shown at the top."""
    src = Section.query.filter_by(
        id=from_id, school_id=_sid()).first_or_404()
    year = _active_year()
    sibling_sections = (
        Section.query.filter_by(
            school_id=_sid(), year_id=year.id if year else 0,
            grade_id=src.grade_id,
        ).filter(Section.id != src.id)
        .order_by(Section.name).all()
    )
    enrollments = (
        Enrollment.query.filter_by(
            school_id=_sid(), section_id=src.id, status="active")
        .join(Student).order_by(Student.full_name).all()
    )

    if request.method == "POST":
        target_id = request.form.get("target_section_id", type=int)
        picked = [int(x) for x in request.form.getlist("enrollment_ids") if x.isdigit()]
        target = Section.query.filter_by(
            id=target_id, school_id=_sid(),
            grade_id=src.grade_id, year_id=src.year_id,
        ).first()
        if not target:
            flash("الفصل الهدف غير صالح.", "danger")
            return redirect(url_for("academic.bulk_transfer", from_id=src.id))

        from datetime import date as _date
        from ...models import TransferLog
        moved = 0
        skipped_full = 0
        for eid in picked:
            e = Enrollment.query.filter_by(
                id=eid, school_id=_sid(), section_id=src.id,
                status="active").first()
            if not e:
                continue
            # Capacity guard — check on the fly since we may have moved
            # students earlier in this loop.
            live_count = Enrollment.query.filter_by(
                school_id=_sid(), section_id=target.id, status="active",
            ).count()
            if target.capacity and live_count >= target.capacity:
                skipped_full += 1
                continue
            db.session.add(TransferLog(
                school_id=_sid(), enrollment_id=e.id,
                from_section_id=src.id, to_section_id=target.id,
                performed_by_user_id=getattr(current_user, "id", None),
                notes=(request.form.get("reason") or "").strip() or None,
            ))
            e.section_id = target.id
            moved += 1
        db.session.commit()
        msg = f"تم نقل {moved} طالب إلى {target.name}."
        if skipped_full:
            msg += f" تم رفض {skipped_full} لعدم توفر السعة."
        flash(msg, "success" if moved else "warning")
        return redirect(url_for("academic.bulk_transfer", from_id=src.id))

    return render_template(
        "academic/bulk_transfer.html",
        section=src, sibling_sections=sibling_sections,
        enrollments=enrollments,
    )
