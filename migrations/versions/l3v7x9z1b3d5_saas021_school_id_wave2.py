"""SAAS-021 (2026-10-20) — wave 2: school_id on 7 LMS tables one level under the roots.

Same contract as SAAS-019 (app/services/schema_waves.py). The waves run
in depth order because each backfills from tables the previous wave
gave a school_id. Timing of each wave on a restored copy goes in the PR.
"""

import time

from alembic import op

from app.services.schema_waves import Child, drop_school_id, run_wave

revision = 'l3v7x9z1b3d5'
down_revision = 'k1t5v7x9z1b3'
branch_labels = None
depends_on = None

WAVE_2 = (
    Child("lms_lessons", "lms_courses", "course_id", (("lms_units", "unit_id"),)),
    Child("lms_questions", "lms_quizzes", "quiz_id",
          (("rubrics", "rubric_id"), ("lms_bank_questions", "source_bank_id"))),
    Child("lms_quiz_attempts", "lms_quizzes", "quiz_id", (("students", "student_id"),)),
    Child("lms_submissions", "lms_assignments", "assignment_id",
          (("students", "student_id"), ("users", "graded_by_id"))),
    Child("lms_assignment_questions", "lms_assignments", "assignment_id",
          (("rubrics", "rubric_id"), ("lms_bank_questions", "source_bank_id"))),
    Child("lms_assignment_extensions", "lms_assignments", "assignment_id",
          (("students", "student_id"), ("users", "granted_by_id"))),
    Child("lms_assignment_template_choices", "lms_assignment_template_questions", "question_id"),
)


def upgrade():
    t0 = time.perf_counter()
    run_wave(op, "SAAS-021/wave2", WAVE_2)
    print(f"[SAAS-021/wave2] {time.perf_counter() - t0:.2f}s")


def downgrade():
    for child in reversed(WAVE_2):
        drop_school_id(op, child)
