"""LMS Phase 2 — simple column additions across bank/quiz/assignment/submission.

Covers ticket items:
  · #1  BankQuestion.cognitive_level
  · #8  Quiz.negative_marking_value
  · #9  Quiz.navigation_mode
  · #15 Quiz.retake_policy + retake_cooldown_minutes
  · #16 Quiz.result_publish_mode + result_publish_at + show_answers_after
  · #20 Submission.submission_kind + external_url
  · #21 CourseAssignment.late_penalty_percent + late_penalty_per_day + max_penalty_percent
  · #22 CourseAssignment.max_attempts + allow_resubmit; Submission.attempt_number
  · #30 Quiz.allow_review, CourseAssignment.allow_review
  · #31 BankQuestion.explanation_video_url, Question.explanation_video_url
  · #32 BankQuestion.hint_text, Question.hint_text
  · #33 BankQuestion.notes
  · #34 BankQuestion.internal_label

Idempotent: every add is guarded on the current column list.
"""

from alembic import op
import sqlalchemy as sa


revision = 'x5l7n9p1r3t5'
down_revision = 'w3j5l7n9p1r3'
branch_labels = None
depends_on = None


def _has(bind, table, col):
    insp = sa.inspect(bind)
    return any(c["name"] == col for c in insp.get_columns(table))


def _has_constraint(bind, table, name):
    insp = sa.inspect(bind)
    return any(uc.get("name") == name for uc in insp.get_unique_constraints(table))


def upgrade():
    bind = op.get_bind()

    # BankQuestion — ticket #1 + #31-#34.
    with op.batch_alter_table("lms_bank_questions") as batch:
        if not _has(bind, "lms_bank_questions", "cognitive_level"):
            batch.add_column(sa.Column("cognitive_level", sa.String(20), nullable=True))
        if not _has(bind, "lms_bank_questions", "explanation_video_url"):
            batch.add_column(sa.Column("explanation_video_url", sa.String(500), nullable=True))
        if not _has(bind, "lms_bank_questions", "hint_text"):
            batch.add_column(sa.Column("hint_text", sa.Text(), nullable=True))
        if not _has(bind, "lms_bank_questions", "notes"):
            batch.add_column(sa.Column("notes", sa.Text(), nullable=True))
        if not _has(bind, "lms_bank_questions", "internal_label"):
            batch.add_column(sa.Column("internal_label", sa.String(120), nullable=True))

    # Question — ticket #31 + #32 (carried on clone).
    with op.batch_alter_table("lms_questions") as batch:
        if not _has(bind, "lms_questions", "explanation_video_url"):
            batch.add_column(sa.Column("explanation_video_url", sa.String(500), nullable=True))
        if not _has(bind, "lms_questions", "hint_text"):
            batch.add_column(sa.Column("hint_text", sa.Text(), nullable=True))

    # AssignmentQuestion — same two.
    with op.batch_alter_table("lms_assignment_questions") as batch:
        if not _has(bind, "lms_assignment_questions", "explanation_video_url"):
            batch.add_column(sa.Column("explanation_video_url", sa.String(500), nullable=True))
        if not _has(bind, "lms_assignment_questions", "hint_text"):
            batch.add_column(sa.Column("hint_text", sa.Text(), nullable=True))

    # Quiz — tickets #8, #9, #15, #16, #30.
    with op.batch_alter_table("lms_quizzes") as batch:
        if not _has(bind, "lms_quizzes", "negative_marking_value"):
            batch.add_column(sa.Column("negative_marking_value", sa.Numeric(6, 2), nullable=True))
        if not _has(bind, "lms_quizzes", "navigation_mode"):
            batch.add_column(sa.Column(
                "navigation_mode", sa.String(24),
                nullable=False, server_default="free",
            ))
        if not _has(bind, "lms_quizzes", "retake_policy"):
            batch.add_column(sa.Column(
                "retake_policy", sa.String(20),
                nullable=False, server_default="on_request",
            ))
        if not _has(bind, "lms_quizzes", "retake_cooldown_minutes"):
            batch.add_column(sa.Column("retake_cooldown_minutes", sa.Integer(), nullable=True))
        if not _has(bind, "lms_quizzes", "result_publish_mode"):
            batch.add_column(sa.Column(
                "result_publish_mode", sa.String(20),
                nullable=False, server_default="immediate",
            ))
        if not _has(bind, "lms_quizzes", "result_publish_at"):
            batch.add_column(sa.Column("result_publish_at", sa.DateTime(timezone=True), nullable=True))
        if not _has(bind, "lms_quizzes", "show_answers_after"):
            batch.add_column(sa.Column(
                "show_answers_after", sa.String(20),
                nullable=False, server_default="immediate",
            ))
        if not _has(bind, "lms_quizzes", "allow_review"):
            batch.add_column(sa.Column(
                "allow_review", sa.Boolean(),
                nullable=False, server_default=sa.true(),
            ))

    # CourseAssignment — tickets #21, #22, #30.
    with op.batch_alter_table("lms_assignments") as batch:
        if not _has(bind, "lms_assignments", "late_penalty_percent"):
            batch.add_column(sa.Column("late_penalty_percent", sa.Numeric(5, 2), nullable=True))
        if not _has(bind, "lms_assignments", "late_penalty_per_day"):
            batch.add_column(sa.Column("late_penalty_per_day", sa.Numeric(5, 2), nullable=True))
        if not _has(bind, "lms_assignments", "max_penalty_percent"):
            batch.add_column(sa.Column("max_penalty_percent", sa.Numeric(5, 2), nullable=True))
        if not _has(bind, "lms_assignments", "max_attempts"):
            batch.add_column(sa.Column(
                "max_attempts", sa.Integer(),
                nullable=False, server_default="1",
            ))
        if not _has(bind, "lms_assignments", "allow_resubmit"):
            batch.add_column(sa.Column(
                "allow_resubmit", sa.Boolean(),
                nullable=False, server_default=sa.false(),
            ))
        if not _has(bind, "lms_assignments", "allow_review"):
            batch.add_column(sa.Column(
                "allow_review", sa.Boolean(),
                nullable=False, server_default=sa.true(),
            ))

    # Submission — ticket #20 + #22.
    with op.batch_alter_table("lms_submissions") as batch:
        if not _has(bind, "lms_submissions", "submission_kind"):
            batch.add_column(sa.Column("submission_kind", sa.String(20), nullable=True))
        if not _has(bind, "lms_submissions", "external_url"):
            batch.add_column(sa.Column("external_url", sa.String(500), nullable=True))
        if not _has(bind, "lms_submissions", "attempt_number"):
            batch.add_column(sa.Column(
                "attempt_number", sa.Integer(),
                nullable=False, server_default="1",
            ))

    # Swap the old (assignment_id, student_id) unique for the new
    # 3-tuple that includes attempt_number so max_attempts > 1 works.
    if _has_constraint(bind, "lms_submissions", "uq_submission_assignment_student"):
        op.drop_constraint(
            "uq_submission_assignment_student",
            "lms_submissions", type_="unique",
        )
    if not _has_constraint(bind, "lms_submissions",
                            "uq_submission_assignment_student_attempt"):
        op.create_unique_constraint(
            "uq_submission_assignment_student_attempt",
            "lms_submissions",
            ["assignment_id", "student_id", "attempt_number"],
        )


def downgrade():
    # Best-effort reverse. Every drop is idempotent-safe.
    for table, cols in [
        ("lms_bank_questions",  ["cognitive_level", "explanation_video_url",
                                 "hint_text", "notes", "internal_label"]),
        ("lms_questions",       ["explanation_video_url", "hint_text"]),
        ("lms_assignment_questions", ["explanation_video_url", "hint_text"]),
        ("lms_quizzes",         ["negative_marking_value", "navigation_mode",
                                 "retake_policy", "retake_cooldown_minutes",
                                 "result_publish_mode", "result_publish_at",
                                 "show_answers_after", "allow_review"]),
        ("lms_assignments",     ["late_penalty_percent", "late_penalty_per_day",
                                 "max_penalty_percent", "max_attempts",
                                 "allow_resubmit", "allow_review"]),
        ("lms_submissions",     ["submission_kind", "external_url",
                                 "attempt_number"]),
    ]:
        with op.batch_alter_table(table) as batch:
            for col in cols:
                try: batch.drop_column(col)
                except Exception: pass
