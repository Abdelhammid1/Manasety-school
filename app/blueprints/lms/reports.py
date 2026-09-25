"""Mastery reports — per-student and per-section (ticket P1-18 split).

Two public routes: `report_student` and `report_section`. Both roll up
`AssignmentAnswer` + `Answer` rows into subject → unit buckets. The
heavy lifting is a single joined query per side (ticket P1-9 killed the
old N+1); Python only accumulates the tuples afterwards."""

from decimal import Decimal

from flask import render_template
from flask_login import login_required

from . import bp
from ...extensions import db
from ...models import (
    Answer, AssignmentAnswer, AssignmentQuestion,
    BankQuestion, Course, CourseAssignment,
    Question, Quiz, QuizAttempt,
    Section, Student, Subject, Submission, Unit,
)


def _mastery_by_unit(rows):
    """Given (unit_id, unit_title, correct_bool, awarded, max) tuples,
    return the UI-ready list of dicts grouped by unit."""
    buckets = {}
    for uid, utitle, is_correct, awarded, max_pts in rows:
        b = buckets.setdefault(uid, {
            "unit_id": uid, "unit_title": utitle,
            "answered": 0, "correct": 0,
            "max_pts": Decimal(0), "awarded": Decimal(0),
        })
        b["answered"] += 1
        if is_correct:
            b["correct"] += 1
        b["max_pts"] += Decimal(str(max_pts or 0))
        b["awarded"] += Decimal(str(awarded or 0))
    out = []
    for b in buckets.values():
        pct = int(round((b["correct"] * 100) / b["answered"])) if b["answered"] else 0
        b["percent"] = pct
        b["label"] = "قوة" if pct >= 80 else ("متوسط" if pct >= 60 else "ضعف")
        out.append(b)
    out.sort(key=lambda x: x["percent"], reverse=True)
    return out


def _accumulate(subjects_data, row):
    subject_id, subject_name, u_id, u_title, is_correct, awarded, max_pts = row
    subjects_data.setdefault(subject_id, {
        "subject_id": subject_id, "subject_name": subject_name, "rows": [],
    })["rows"].append((u_id, u_title, is_correct, awarded, max_pts))


def _rollup_subjects(subjects_data):
    result = []
    for sd in subjects_data.values():
        units = _mastery_by_unit(sd["rows"])
        overall_pct = int(round(sum(u["percent"] for u in units) / len(units))) if units else 0
        result.append({
            "subject_id": sd["subject_id"], "subject_name": sd["subject_name"],
            "units": units, "overall": overall_pct,
            "answered_total": sum(u["answered"] for u in units),
        })
    result.sort(key=lambda x: x["overall"], reverse=True)
    return result


def _student_assignment_mastery_rows(student_id):
    q = (
        db.session.query(
            Course.subject_id, Subject.name,
            BankQuestion.unit_id, Unit.title,
            AssignmentAnswer.is_correct, AssignmentAnswer.awarded_points,
            AssignmentQuestion.points,
        )
        .join(AssignmentQuestion, AssignmentQuestion.id == AssignmentAnswer.question_id)
        .join(Submission, Submission.id == AssignmentAnswer.submission_id)
        .join(CourseAssignment, CourseAssignment.id == AssignmentQuestion.assignment_id)
        .join(Course, Course.id == CourseAssignment.course_id)
        .join(Subject, Subject.id == Course.subject_id)
        .outerjoin(BankQuestion, BankQuestion.id == AssignmentQuestion.source_bank_id)
        .outerjoin(Unit, Unit.id == BankQuestion.unit_id)
        .filter(Submission.student_id == student_id)
    )
    for subj_id, subj_name, u_id, u_title, ok, awarded, max_pts in q.all():
        yield (subj_id, subj_name,
               u_id or 0, u_title or "بدون وحدة",
               bool(ok), awarded or 0, max_pts or 0)


def _student_quiz_mastery_rows(student_id):
    q = (
        db.session.query(
            Course.subject_id, Subject.name,
            BankQuestion.unit_id, Unit.title,
            Answer.is_correct, Answer.awarded_points, Question.points,
        )
        .join(QuizAttempt, QuizAttempt.id == Answer.attempt_id)
        .join(Question, Question.id == Answer.question_id)
        .join(Quiz, Quiz.id == Question.quiz_id)
        .join(Course, Course.id == Quiz.course_id)
        .join(Subject, Subject.id == Course.subject_id)
        .outerjoin(BankQuestion, BankQuestion.id == Question.source_bank_id)
        .outerjoin(Unit, Unit.id == BankQuestion.unit_id)
        .filter(QuizAttempt.student_id == student_id)
    )
    for subj_id, subj_name, u_id, u_title, ok, awarded, max_pts in q.all():
        yield (subj_id, subj_name,
               u_id or 0, u_title or "بدون وحدة",
               bool(ok), awarded or 0, max_pts or 0)


def _section_assignment_mastery_rows(student_ids):
    q = (
        db.session.query(
            Course.subject_id, Subject.name,
            BankQuestion.unit_id, Unit.title,
            AssignmentAnswer.is_correct, AssignmentAnswer.awarded_points,
            AssignmentQuestion.points,
        )
        .join(AssignmentQuestion, AssignmentQuestion.id == AssignmentAnswer.question_id)
        .join(Submission, Submission.id == AssignmentAnswer.submission_id)
        .join(CourseAssignment, CourseAssignment.id == AssignmentQuestion.assignment_id)
        .join(Course, Course.id == CourseAssignment.course_id)
        .join(Subject, Subject.id == Course.subject_id)
        .outerjoin(BankQuestion, BankQuestion.id == AssignmentQuestion.source_bank_id)
        .outerjoin(Unit, Unit.id == BankQuestion.unit_id)
        .filter(Submission.student_id.in_(student_ids))
    )
    for subj_id, subj_name, u_id, u_title, ok, awarded, max_pts in q.all():
        yield (subj_id, subj_name,
               u_id or 0, u_title or "بدون وحدة",
               bool(ok), awarded or 0, max_pts or 0)


def _section_quiz_mastery_rows(student_ids):
    q = (
        db.session.query(
            Course.subject_id, Subject.name,
            BankQuestion.unit_id, Unit.title,
            Answer.is_correct, Answer.awarded_points, Question.points,
        )
        .join(QuizAttempt, QuizAttempt.id == Answer.attempt_id)
        .join(Question, Question.id == Answer.question_id)
        .join(Quiz, Quiz.id == Question.quiz_id)
        .join(Course, Course.id == Quiz.course_id)
        .join(Subject, Subject.id == Course.subject_id)
        .outerjoin(BankQuestion, BankQuestion.id == Question.source_bank_id)
        .outerjoin(Unit, Unit.id == BankQuestion.unit_id)
        .filter(QuizAttempt.student_id.in_(student_ids))
    )
    for subj_id, subj_name, u_id, u_title, ok, awarded, max_pts in q.all():
        yield (subj_id, subj_name,
               u_id or 0, u_title or "بدون وحدة",
               bool(ok), awarded or 0, max_pts or 0)


@bp.route("/reports/student/<int:student_id>", endpoint="report_student")
@login_required
def report_student(student_id):
    """Per-student mastery per subject × unit — one query per side."""
    student = Student.query.get_or_404(student_id)
    subjects_data = {}
    for row in _student_assignment_mastery_rows(student.id):
        _accumulate(subjects_data, row)
    for row in _student_quiz_mastery_rows(student.id):
        _accumulate(subjects_data, row)
    result = _rollup_subjects(subjects_data)
    return render_template("lms/report_student.html", student=student, subjects=result)


@bp.route("/reports/section/<int:section_id>", endpoint="report_section")
@login_required
def report_section(section_id):
    """Per-section mastery — two queries total regardless of size."""
    from ...models import Enrollment
    section = Section.query.get_or_404(section_id)
    students = (
        Student.query.join(Enrollment, Enrollment.student_id == Student.id)
        .filter(Enrollment.section_id == section.id,
                Enrollment.status == "active").all()
    )
    student_ids = [s.id for s in students]
    subjects_data = {}
    if student_ids:
        for row in _section_assignment_mastery_rows(student_ids):
            _accumulate(subjects_data, row)
        for row in _section_quiz_mastery_rows(student_ids):
            _accumulate(subjects_data, row)
    result = _rollup_subjects(subjects_data)
    return render_template(
        "lms/report_section.html",
        section=section, students=students, subjects=result,
    )
