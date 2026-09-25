"""Phase-3 T3 — Missing grades + class-average reports.

Two read-only endpoints hanging off the results blueprint. They both
reuse grade_sheet()'s (year, term, section, subject) picker so the
teacher can switch context without leaving the report.
"""
from decimal import Decimal

from flask import render_template, request
from flask_login import current_user, login_required
from sqlalchemy import func

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import (
    AcademicYear, AssessmentComponent, Enrollment, GradeEntry,
    Section, Student, Subject, Term,
)


def _sid():
    return current_user.school_id


def _active_year():
    return AcademicYear.query.filter_by(school_id=_sid(), status="active").first()


def _picker_context(year_id, term_id, section_id, subject_id):
    """Return the drop-down data for the shared filter bar. Kept in one
    place so both reports render the same picker."""
    years = (
        AcademicYear.query.filter_by(school_id=_sid())
        .order_by(AcademicYear.start_date.desc()).all()
    )
    terms = (
        Term.query.filter_by(school_id=_sid(), year_id=year_id)
        .order_by(Term.order_index).all()
        if year_id else []
    )
    sections = (
        Section.query.filter_by(school_id=_sid(), year_id=year_id)
        .order_by(Section.name).all()
        if year_id else []
    )
    subjects = (
        Subject.query.filter_by(school_id=_sid())
        .order_by(Subject.name).all()
    )
    return {
        "years": years, "terms": terms,
        "sections": sections, "subjects": subjects,
    }


def _resolve_filters():
    """Read query args + reasonable defaults."""
    year = _active_year()
    year_id = request.args.get("year_id", type=int) or (year.id if year else None)
    term_id = request.args.get("term_id", type=int)
    section_id = request.args.get("section_id", type=int)
    subject_id = request.args.get("subject_id", type=int)
    return year_id, term_id, section_id, subject_id


@bp.route("/reports/missing-grades", endpoint="missing_grades_report")
@login_required
@require_permission("results", "view")
def missing_grades_report():
    """Ticket T3 — per-component list of students without a GradeEntry.

    For each AssessmentComponent in the picked (term, subject), fetch
    the section's active enrollments and diff against the components'
    already-recorded GradeEntry rows. Any student without an entry
    shows up in `missing_by_component[component_id]`.
    """
    year_id, term_id, section_id, subject_id = _resolve_filters()

    rows = []
    if year_id and term_id and section_id:
        section = (
            Section.query.filter_by(id=section_id, school_id=_sid()).first()
        )
        enrollments = (
            Enrollment.query.filter_by(
                school_id=_sid(), year_id=year_id,
                section_id=section_id, status="active",
            ).join(Student).order_by(Student.full_name).all()
            if section else []
        )
        # Base list of components — narrow to subject if picked.
        comp_q = AssessmentComponent.query.filter_by(
            school_id=_sid(), term_id=term_id,
        )
        if subject_id:
            comp_q = comp_q.filter_by(subject_id=subject_id)
        components = comp_q.order_by(
            AssessmentComponent.subject_id, AssessmentComponent.id,
        ).all()

        # Pre-load every GradeEntry for the (enrollments, components)
        # intersection in one query; two nested loops in Python are
        # cheap on the resulting set.
        if enrollments and components:
            recorded = {
                (ge.enrollment_id, ge.component_id)
                for ge in GradeEntry.query.filter(
                    GradeEntry.enrollment_id.in_([e.id for e in enrollments]),
                    GradeEntry.component_id.in_([c.id for c in components]),
                ).all()
            }
            for c in components:
                missing_students = [
                    e.student for e in enrollments
                    if (e.id, c.id) not in recorded
                ]
                subject = (
                    Subject.query.get(c.subject_id) if c.subject_id else None
                )
                rows.append({
                    "component_id":   c.id,
                    "component_name": c.name,
                    "subject_name":   subject.name if subject else "—",
                    "max_score":      c.max_score,
                    "expected":       len(enrollments),
                    "recorded":       len(enrollments) - len(missing_students),
                    "missing_count":  len(missing_students),
                    "missing":        missing_students,
                })

    return render_template(
        "results/missing_grades_report.html",
        rows=rows,
        filters={"year_id": year_id, "term_id": term_id,
                 "section_id": section_id, "subject_id": subject_id},
        picker=_picker_context(year_id, term_id, section_id, subject_id),
    )


@bp.route("/reports/class-average", endpoint="class_average_report")
@login_required
@require_permission("results", "view")
def class_average_report():
    """Ticket T3 — per-component avg/min/max + 10%-bucket histogram."""
    year_id, term_id, section_id, subject_id = _resolve_filters()

    rows = []
    if year_id and term_id and section_id:
        comp_q = AssessmentComponent.query.filter_by(
            school_id=_sid(), term_id=term_id,
        )
        if subject_id:
            comp_q = comp_q.filter_by(subject_id=subject_id)
        components = comp_q.order_by(
            AssessmentComponent.subject_id, AssessmentComponent.id,
        ).all()

        enrollment_ids = [
            e.id for e in Enrollment.query.filter_by(
                school_id=_sid(), year_id=year_id,
                section_id=section_id, status="active",
            ).all()
        ]

        for c in components:
            if not enrollment_ids:
                continue
            stats = (
                db.session.query(
                    func.avg(GradeEntry.score),
                    func.min(GradeEntry.score),
                    func.max(GradeEntry.score),
                    func.count(GradeEntry.id),
                )
                .filter(GradeEntry.component_id == c.id,
                        GradeEntry.enrollment_id.in_(enrollment_ids))
                .first()
            )
            avg_val, min_val, max_val, n = stats
            if not n:
                continue
            # Build a 10-bucket histogram (0-9%, 10-19%, ..., 90-100%).
            buckets = [0] * 10
            for score, in (
                db.session.query(GradeEntry.score)
                .filter(GradeEntry.component_id == c.id,
                        GradeEntry.enrollment_id.in_(enrollment_ids))
                .all()
            ):
                if not c.max_score or c.max_score == 0:
                    idx = 0
                else:
                    pct = int(float(score) / float(c.max_score) * 100)
                    idx = 9 if pct >= 100 else max(0, pct // 10)
                buckets[idx] += 1
            subject = Subject.query.get(c.subject_id) if c.subject_id else None
            rows.append({
                "component_id":   c.id,
                "component_name": c.name,
                "subject_name":   subject.name if subject else "—",
                "max_score":      c.max_score,
                "n":              n,
                "avg":            round(float(avg_val), 2),
                "min":            round(float(min_val), 2),
                "max":            round(float(max_val), 2),
                "buckets":        buckets,
            })

    return render_template(
        "results/class_average_report.html",
        rows=rows,
        filters={"year_id": year_id, "term_id": term_id,
                 "section_id": section_id, "subject_id": subject_id},
        picker=_picker_context(year_id, term_id, section_id, subject_id),
    )
