"""Ticket #3 — LMS ↔ SIS grade auto-sync.

When a Quiz attempt or an assignment Submission finishes grading,
mirror the score into a GradeEntry against the AssessmentComponent
that ticked auto_sync + source_type='lms_quiz' or 'lms_assignment' +
source_id equal to the Quiz.id / CourseAssignment.id.

Scale conversion: the AssessmentComponent.max_score is the target
sky-ceiling; the LMS score becomes
  (student_score / lms_max) * component_max_score
rounded to 2dp. When the LMS max is 0 (a broken quiz) the sync is
skipped rather than divide-by-zero'ed.
"""
from decimal import Decimal

from ..extensions import db
from ..models import (
    AssessmentComponent, GradeEntry, Enrollment,
    Quiz, QuizAttempt, Answer, Question,
    CourseAssignment, Submission, AssignmentQuestion,
)


def _lms_quiz_max(quiz):
    total = Decimal(0)
    for q in quiz.questions:
        total += Decimal(str(q.points or 0))
    return total


def _lms_assignment_max(assignment):
    total = Decimal(0)
    for q in assignment.questions:
        total += Decimal(str(q.points or 0))
    if total > 0:
        return total
    # Fall back to the assignment's max_score field when no questions
    # exist (free-form assignments).
    return Decimal(str(assignment.max_score or 0))


def _active_enrollment_id(student_id, school_id):
    """GradeEntry keys off enrollment, not student. Resolve the student's
    active enrollment in the school; returns None if none active (in
    which case we skip the sync — the grade would be orphaned)."""
    en = Enrollment.query.filter_by(
        student_id=student_id, school_id=school_id, status="active",
    ).order_by(Enrollment.enrolled_at.desc()).first()
    return en.id if en else None


def _upsert_grade_entry(component, student_id, awarded):
    en_id = _active_enrollment_id(student_id, component.school_id)
    if not en_id:
        return None
    row = GradeEntry.query.filter_by(
        component_id=component.id, enrollment_id=en_id,
    ).first()
    if row is None:
        row = GradeEntry(
            school_id=component.school_id,
            component_id=component.id, enrollment_id=en_id,
            score=awarded,
        )
        db.session.add(row)
    else:
        row.score = awarded
    return row


def sync_quiz_attempt(attempt: QuizAttempt):
    """Called from quiz_submit right after auto-grading. Idempotent —
    re-running just rewrites the same GradeEntry."""
    if attempt is None or attempt.score is None:
        return None
    quiz = attempt.quiz
    if quiz is None:
        return None
    component = AssessmentComponent.query.filter_by(
        source_type="lms_quiz", source_id=quiz.id, auto_sync=True,
    ).first()
    if component is None:
        return None
    lms_max = _lms_quiz_max(quiz)
    if lms_max <= 0:
        return None
    student_score = Decimal(str(attempt.score))
    scaled = (student_score / lms_max) * Decimal(str(component.max_score))
    scaled = scaled.quantize(Decimal("0.01"))
    row = _upsert_grade_entry(component, attempt.student_id, scaled)
    db.session.flush()
    return row


def sync_assignment_submission(submission: Submission):
    """Called from assignment_submit right after auto-grading (or later
    when the teacher finalises the essay grade)."""
    if submission is None or submission.score is None:
        return None
    assignment = submission.assignment
    if assignment is None:
        return None
    component = AssessmentComponent.query.filter_by(
        source_type="lms_assignment", source_id=assignment.id, auto_sync=True,
    ).first()
    if component is None:
        return None
    lms_max = _lms_assignment_max(assignment)
    if lms_max <= 0:
        return None
    student_score = Decimal(str(submission.score))
    scaled = (student_score / lms_max) * Decimal(str(component.max_score))
    scaled = scaled.quantize(Decimal("0.01"))
    row = _upsert_grade_entry(component, submission.student_id, scaled)
    db.session.flush()
    return row
