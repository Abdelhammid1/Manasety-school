"""SAAS-021 (2026-10-20) — wave 3: school_id on choices, flagged questions and rubric scores.

Same contract as SAAS-019 (app/services/schema_waves.py). The waves run
in depth order because each backfills from tables the previous wave
gave a school_id. Timing of each wave on a restored copy goes in the PR.
"""

import time

from alembic import op

from app.services.schema_waves import Child, drop_school_id, run_wave

revision = 'm5x9z1b3d5f7'
down_revision = 'l3v7x9z1b3d5'
branch_labels = None
depends_on = None

WAVE_3 = (
    Child("lms_choices", "lms_questions", "question_id"),
    Child("lms_attempt_flagged_questions", "lms_quiz_attempts", "attempt_id",
          (("lms_questions", "question_id"),)),
    Child("lms_assignment_choices", "lms_assignment_questions", "question_id"),
    # A rubric score belongs to a submission OR a grade entry.
    Child("rubric_scores", "lms_submissions", "submission_id",
          (("rubric_criteria", "criterion_id"), ("users", "graded_by_id")),
          alt=("grade_entries", "grade_entry_id")),
)


def upgrade():
    t0 = time.perf_counter()
    run_wave(op, "SAAS-021/wave3", WAVE_3)
    print(f"[SAAS-021/wave3] {time.perf_counter() - t0:.2f}s")


def downgrade():
    for child in reversed(WAVE_3):
        drop_school_id(op, child)
