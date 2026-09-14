from datetime import datetime
from decimal import Decimal

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import (
    AcademicYear, AssessmentComponent, Assignment, Enrollment, Grade,
    GradeEntry, PassRule, Section, Student, Subject, Teacher, Term, YearResult,
)


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
    """Return the Teacher row for the logged-in user, or None (admins etc.)."""
    return Teacher.query.filter_by(school_id=_sid(), user_id=current_user.id).first()


def _teacher_can_grade(teacher, section, subject):
    """Sprint 9 (TC-7.3.3): teacher may only enter grades for (section, subject)
    pairs they have an active Assignment for."""
    return Assignment.query.filter_by(
        teacher_id=teacher.id, section_id=section.id,
        subject_id=subject.id, year_id=section.year_id, is_active=True,
    ).first() is not None


def _is_admin():
    """Sprint 10 hotfix — same as attendance/routes.py._is_admin."""
    role_name = getattr(current_user.role, "name", None) if current_user.role else None
    return role_name == "admin"


def _rule_for(year_id):
    rule = PassRule.query.filter_by(school_id=_sid(), year_id=year_id).first()
    if not rule:
        rule = PassRule(school_id=_sid(), year_id=year_id)
        db.session.add(rule)
        db.session.commit()
    return rule


# ---------- T-7.1 Pass rule settings ----------

@bp.route("/settings", methods=["GET", "POST"])
@login_required
@require_permission("results", "view")
def settings():
    year = _active_year()
    if not year:
        flash("لا توجد سنة دراسية نشطة.", "warning")
        return redirect(url_for("dashboard.home"))
    rule = _rule_for(year.id)

    if request.method == "POST":
        if rule.is_frozen:
            flash("القاعدة مجمَّدة (السنة مغلقة). لا يمكن التعديل.", "danger")
            return redirect(url_for("results.settings"))
        if not current_user.can("results", "edit"):
            abort(403)
        # Sprint 10 hotfix — validate thresholds (was allowing 0 which made
        # everyone pass under per_subject / overall_only methods).
        try:
            subj_th = Decimal(request.form["subject_pass_threshold"])
            overall_th = Decimal(request.form["overall_pass_threshold"])
        except Exception:
            flash("قيم غير صالحة لعتبات النجاح.", "danger")
            return redirect(url_for("results.settings"))
        if subj_th < 1 or subj_th > 100 or overall_th < 1 or overall_th > 100:
            flash(
                "عتبات النجاح يجب أن تكون بين 1 و 100. "
                "قيمة صفر تُلغي الرسوب فعليًا وتجعل جميع الطلاب ناجحين.",
                "danger",
            )
            return redirect(url_for("results.settings"))
        method = request.form.get("method") or "overall_only"
        if method not in ("overall_only", "per_subject", "mixed"):
            flash("طريقة النجاح غير معروفة.", "danger")
            return redirect(url_for("results.settings"))
        allowed_failed = int(request.form.get("allowed_failed_subjects") or 0)
        if allowed_failed < 0:
            allowed_failed = 0
        rule.subject_pass_threshold = subj_th
        rule.overall_pass_threshold = overall_th
        rule.method = method
        rule.allowed_failed_subjects = allowed_failed
        db.session.commit()
        flash("تم حفظ قاعدة النجاح.", "success")
        return redirect(url_for("results.settings"))

    return render_template("results/settings.html", year=year, rule=rule)


# ---------- T-7.2 Assessment components ----------

@bp.route("/components", methods=["GET", "POST"])
@login_required
@require_permission("results", "edit")
def components():
    year = _active_year()
    if not year:
        flash("لا توجد سنة دراسية نشطة.", "warning")
        return redirect(url_for("dashboard.home"))

    terms = Term.query.filter_by(school_id=_sid(), year_id=year.id).order_by(Term.order_index).all()
    subjects = Subject.query.filter_by(school_id=_sid()).order_by(Subject.name).all()

    term_id = request.values.get("term_id", type=int)
    subject_id = request.values.get("subject_id", type=int)

    components_list = []
    total = Decimal(0)
    if term_id and subject_id:
        components_list = (
            AssessmentComponent.query.filter_by(
                school_id=_sid(), term_id=term_id, subject_id=subject_id,
            ).order_by(AssessmentComponent.id).all()
        )
        total = sum((c.max_score for c in components_list), Decimal(0))

    if request.method == "POST" and term_id and subject_id:
        action = request.form.get("action")
        if action == "add":
            comp = AssessmentComponent(
                school_id=_sid(),
                term_id=term_id, subject_id=subject_id,
                name=request.form["name"].strip(),
                max_score=Decimal(request.form["max_score"]),
            )
            db.session.add(comp)
            db.session.commit()
            flash("تمت إضافة المكوّن.", "success")
            return redirect(url_for("results.components", term_id=term_id, subject_id=subject_id))
        if action == "delete":
            cid = int(request.form["component_id"])
            comp = _get(AssessmentComponent, cid)
            if GradeEntry.query.filter_by(component_id=cid).first():
                flash("لا يمكن حذف مكوّن مرتبط بدرجات مرصودة.", "danger")
            else:
                db.session.delete(comp)
                db.session.commit()
                flash("تم حذف المكوّن.", "success")
            return redirect(url_for("results.components", term_id=term_id, subject_id=subject_id))

    return render_template(
        "results/components.html",
        year=year, terms=terms, subjects=subjects,
        term_id=term_id, subject_id=subject_id,
        components=components_list, total=total,
    )


# ---------- T-7.3 / T-7.4 Grade entry per (section, term, subject) ----------

@bp.route("/grades")
@login_required
@require_permission("results", "view")
def grades_index():
    year = _active_year()
    sections = []
    terms = []
    subjects = []
    if year:
        sections_q = (
            Section.query.filter_by(school_id=_sid(), year_id=year.id).join(Grade)
        )
        subjects_q = Subject.query.filter_by(school_id=_sid())

        # Sprint 9 TC-7.3.3 (hardened Sprint 10): admins see everything;
        # non-admins see ONLY their assigned (section, subject) pairs.
        # Non-admin without a Teacher record → empty (was leaking as admin).
        if _is_admin():
            sections = sections_q.order_by(Grade.order_index, Section.name).all()
            subjects = subjects_q.order_by(Subject.name).all()
        else:
            teacher = _teacher_for_current_user()
            if not teacher:
                sections = subjects = []
            else:
                assignments = Assignment.query.filter_by(
                    teacher_id=teacher.id, year_id=year.id, is_active=True,
                ).all()
                assigned_section_ids = {a.section_id for a in assignments}
                assigned_subject_ids = {a.subject_id for a in assignments}
                if not assignments:
                    sections = subjects = []
                else:
                    sections = (
                        sections_q.filter(Section.id.in_(assigned_section_ids))
                        .order_by(Grade.order_index, Section.name).all()
                    )
                    subjects = (
                        subjects_q.filter(Subject.id.in_(assigned_subject_ids))
                        .order_by(Subject.name).all()
                    )

        terms = Term.query.filter_by(school_id=_sid(), year_id=year.id).order_by(Term.order_index).all()
    return render_template(
        "results/grades_index.html",
        year=year, sections=sections, terms=terms, subjects=subjects,
    )


@bp.route("/grades/<int:section_id>/<int:term_id>/<int:subject_id>", methods=["GET", "POST"])
@login_required
@require_permission("results", "view")
def grade_sheet(section_id, term_id, subject_id):
    section = _get(Section, section_id)
    term = _get(Term, term_id)
    subject = _get(Subject, subject_id)

    # Sprint 9 TC-7.3.3 (hardened Sprint 10): non-admins must have an
    # active Assignment for this exact (section, subject) pair.
    if not _is_admin():
        teacher = _teacher_for_current_user()
        if not teacher or not _teacher_can_grade(teacher, section, subject):
            flash(
                "لا تملك صلاحية رصد درجات هذه المادة لهذا الفصل — يمكنك رصد درجات المواد المسندة إليك فقط.",
                "danger",
            )
            return redirect(url_for("results.grades_index"))

    locked = YearResult.query.join(Enrollment).filter(
        Enrollment.section_id == section.id,
        Enrollment.year_id == section.year_id,
    ).first() is not None

    components = (
        AssessmentComponent.query.filter_by(
            school_id=_sid(), term_id=term.id, subject_id=subject.id,
        ).order_by(AssessmentComponent.id).all()
    )
    enrollments = (
        Enrollment.query.filter_by(
            school_id=_sid(), year_id=section.year_id,
            section_id=section.id, status="active",
        ).join(Student).order_by(Student.full_name).all()
    )

    entries = {}
    for ge in GradeEntry.query.filter(
        GradeEntry.component_id.in_([c.id for c in components]),
        GradeEntry.enrollment_id.in_([e.id for e in enrollments]),
    ).all():
        entries[(ge.enrollment_id, ge.component_id)] = ge

    if request.method == "POST":
        if locked:
            flash("النتائج معتمدة لهذه السنة. لا يمكن التعديل إلا بصلاحية أعلى.", "danger")
            return redirect(url_for("results.grade_sheet",
                                    section_id=section.id, term_id=term.id, subject_id=subject.id))
        if not current_user.can("results", "edit"):
            abort(403)

        rejected = 0
        saved = 0
        for e in enrollments:
            for c in components:
                key = f"score_{e.id}_{c.id}"
                raw = (request.form.get(key) or "").strip()
                if raw == "":
                    continue
                try:
                    score = Decimal(raw)
                except Exception:  # noqa: BLE001
                    rejected += 1
                    continue
                if score < 0 or score > c.max_score:
                    rejected += 1
                    continue
                ge = entries.get((e.id, c.id))
                if ge:
                    ge.score = score
                    ge.recorded_by_user_id = current_user.id
                    ge.recorded_at = datetime.utcnow()
                else:
                    ge = GradeEntry(
                        school_id=_sid(),
                        enrollment_id=e.id, component_id=c.id, score=score,
                        recorded_by_user_id=current_user.id,
                    )
                    db.session.add(ge)
                saved += 1
        db.session.commit()
        msg = f"تم حفظ {saved} درجة."
        if rejected:
            msg += f" تم رفض {rejected} قيمة تجاوزت الحد الأقصى أو غير صالحة."
        flash(msg, "warning" if rejected else "success")
        return redirect(url_for("results.grade_sheet",
                                section_id=section.id, term_id=term.id, subject_id=subject.id))

    # T-7.4 per-student term-subject totals
    term_totals = {}
    for e in enrollments:
        recorded = 0
        total_score = Decimal(0)
        for c in components:
            ge = entries.get((e.id, c.id))
            if ge:
                total_score += ge.score
                recorded += 1
        complete = recorded == len(components) and components
        term_totals[e.id] = {"score": total_score, "complete": complete}

    return render_template(
        "results/grade_sheet.html",
        section=section, term=term, subject=subject,
        components=components, enrollments=enrollments,
        entries=entries, term_totals=term_totals, locked=locked,
    )


# ---------- T-7.5 / T-7.6 Year results + approval ----------

@bp.route("/section/<int:section_id>", methods=["GET", "POST"])
@login_required
@require_permission("results", "view")
def section_results(section_id):
    section = _get(Section, section_id)
    year = section.year
    rule = _rule_for(year.id)
    terms = Term.query.filter_by(school_id=_sid(), year_id=year.id).order_by(Term.order_index).all()

    # Sprint 9 TC-7.1.2 (part 2): for CLOSED years, include promoted_out
    # enrollments so historical results remain visible after year archival.
    enroll_filter = {
        "school_id": _sid(), "year_id": year.id, "section_id": section.id,
    }
    if year.status == "closed":
        enrollments = (
            Enrollment.query.filter_by(**enroll_filter)
            .filter(Enrollment.status.in_(["active", "promoted_out"]))
            .join(Student).order_by(Student.full_name).all()
        )
    else:
        enrollments = (
            Enrollment.query.filter_by(**enroll_filter, status="active")
            .join(Student).order_by(Student.full_name).all()
        )

    subjects = _subjects_for_grade(section.grade_id)

    rows = [_compute_year(e, terms, subjects, rule) for e in enrollments]
    approved = {
        yr.enrollment_id: yr for yr in YearResult.query.filter(
            YearResult.enrollment_id.in_([e.id for e in enrollments])
        ).all()
    }

    if request.method == "POST":
        if not current_user.can("results", "edit"):
            abort(403)
        approved_count = 0
        skipped = 0
        for row in rows:
            if row["incomplete"]:
                skipped += 1
                continue
            if row["enrollment"].id in approved:
                continue
            snap = YearResult(
                school_id=_sid(),
                enrollment_id=row["enrollment"].id,
                average=row["average"],
                status=row["status"],
                failed_subjects=row["failed_count"],
                rule_snapshot={
                    "method": rule.method,
                    "subject_pass_threshold": float(rule.subject_pass_threshold),
                    "overall_pass_threshold": float(rule.overall_pass_threshold),
                    "allowed_failed_subjects": rule.allowed_failed_subjects,
                },
                subject_scores={s.name: float(score) for s, score in row["subjects"]},
                approved_by_user_id=current_user.id,
            )
            row["enrollment"].final_result = row["status"]
            db.session.add(snap)
            approved_count += 1
        db.session.commit()
        flash(
            f"تم اعتماد {approved_count} نتيجة. {skipped} متعذّر اعتمادها (غير مكتملة).",
            "success",
        )
        return redirect(url_for("results.section_results", section_id=section.id))

    return render_template(
        "results/section_results.html",
        section=section, year=year, rule=rule, rows=rows, approved=approved,
    )


@bp.route("/section/<int:section_id>/term/<int:term_id>")
@login_required
@require_permission("results", "view")
def term_results(section_id, term_id):
    """Sprint 9 TC-7.5.1 — per-term result view.

    Shows one row per student × one column per subject with the total score
    earned that term (sum of component scores) and per-subject pass/fail
    against the PassRule subject threshold.
    """
    section = _get(Section, section_id)
    term = _get(Term, term_id)
    rule = _rule_for(section.year_id)
    subjects = _subjects_for_grade(section.grade_id)
    enrollments = (
        Enrollment.query.filter_by(
            school_id=_sid(), year_id=section.year_id,
            section_id=section.id, status="active",
        ).join(Student).order_by(Student.full_name).all()
    )

    # Preload GradeEntry rows for all (enrollment × component) in this term.
    components_by_subject = {}
    for subject in subjects:
        components_by_subject[subject.id] = (
            AssessmentComponent.query.filter_by(
                school_id=_sid(), term_id=term.id, subject_id=subject.id,
            ).all()
        )
    all_component_ids = {
        c.id for comps in components_by_subject.values() for c in comps
    }
    entries = {}
    if all_component_ids and enrollments:
        for ge in GradeEntry.query.filter(
            GradeEntry.component_id.in_(all_component_ids),
            GradeEntry.enrollment_id.in_([e.id for e in enrollments]),
        ).all():
            entries[(ge.enrollment_id, ge.component_id)] = ge

    # Build a matrix: rows keyed by enrollment_id, cols keyed by subject_id.
    matrix = {}
    for e in enrollments:
        row = {"enrollment": e, "cells": {}}
        for subject in subjects:
            comps = components_by_subject[subject.id]
            if not comps:
                row["cells"][subject.id] = {"score": None, "max": None, "status": "no_components"}
                continue
            recorded = [entries[(e.id, c.id)] for c in comps if (e.id, c.id) in entries]
            if len(recorded) < len(comps):
                row["cells"][subject.id] = {
                    "score": sum((r.score for r in recorded), Decimal(0)),
                    "max": sum((c.max_score for c in comps), Decimal(0)),
                    "status": "incomplete",
                }
            else:
                total_score = sum((r.score for r in recorded), Decimal(0))
                total_max = sum((c.max_score for c in comps), Decimal(0))
                percent = (total_score / total_max * 100) if total_max else Decimal(0)
                row["cells"][subject.id] = {
                    "score": total_score,
                    "max": total_max,
                    "percent": percent,
                    "status": (
                        "pass" if percent >= rule.subject_pass_threshold else "fail"
                    ),
                }
        matrix[e.id] = row

    return render_template(
        "results/term_results.html",
        section=section, term=term, rule=rule,
        subjects=subjects, matrix=matrix,
        enrollments=enrollments,
    )


def _subjects_for_grade(grade_id: int):
    return (
        Subject.query.filter_by(school_id=_sid())
        .join(Subject.grades).filter(Grade.id == grade_id)
        .all()
    )


def _compute_year(enrollment, terms, subjects, rule: PassRule):
    """Compute the year result for one enrollment based on current grades."""
    subj_scores = []
    incomplete = False

    for subject in subjects:
        term_scores = []
        for term in terms:
            comps = AssessmentComponent.query.filter_by(
                term_id=term.id, subject_id=subject.id
            ).all()
            if not comps:
                continue
            entries = GradeEntry.query.filter(
                GradeEntry.enrollment_id == enrollment.id,
                GradeEntry.component_id.in_([c.id for c in comps]),
            ).all()
            if len(entries) < len(comps):
                incomplete = True
                term_scores.append((term, None))
            else:
                total = sum((e.score for e in entries), Decimal(0))
                term_scores.append((term, total))

        # weighted average across terms
        weighted = Decimal(0)
        weight_total = Decimal(0)
        for term, score in term_scores:
            if score is None:
                continue
            weighted += score * (term.weight or 0)
            weight_total += (term.weight or 0)
        if weight_total:
            year_subject_score = weighted / weight_total
        else:
            year_subject_score = Decimal(0)
            incomplete = True
        subj_scores.append((subject, year_subject_score))

    average = (
        sum((s for _, s in subj_scores), Decimal(0)) / Decimal(len(subj_scores))
        if subj_scores else Decimal(0)
    )
    # Sprint 10 hotfix — defensive floor of 1 for either threshold.
    # A stored 0 was making every student pass under per_subject / overall_only
    # (0 >= 0 = True; 0 < 0 = False). Settings form now blocks saving zero,
    # but any historical DB rows with 0 also get corrected here.
    subj_th = rule.subject_pass_threshold or Decimal(1)
    if subj_th < Decimal(1):
        subj_th = Decimal(1)
    overall_th = rule.overall_pass_threshold or Decimal(1)
    if overall_th < Decimal(1):
        overall_th = Decimal(1)
    failed = [(s, sc) for s, sc in subj_scores if sc < subj_th]

    if incomplete:
        status = "incomplete"
    else:
        method = rule.method or "overall_only"
        if method == "overall_only":
            status = "pass" if average >= overall_th else "fail"
        elif method == "per_subject":
            status = "fail" if failed else "pass"
        else:  # mixed
            if average < overall_th:
                status = "fail"
            elif len(failed) <= (rule.allowed_failed_subjects or 0):
                status = "pass"
            else:
                status = "fail"

    return {
        "enrollment": enrollment,
        "subjects": subj_scores,
        "average": round(average, 2),
        "failed_count": len(failed),
        "failed_subjects": failed,
        "status": status,
        "incomplete": incomplete,
    }
