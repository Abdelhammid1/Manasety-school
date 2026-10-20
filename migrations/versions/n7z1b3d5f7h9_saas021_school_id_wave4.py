"""SAAS-021 (2026-10-20) — wave 4: school_id on student answers (quiz + assignment).

Same contract as SAAS-019 (app/services/schema_waves.py). The waves run
in depth order because each backfills from tables the previous wave
gave a school_id. Timing of each wave on a restored copy goes in the PR.
"""

import time

from alembic import op

from app.services.schema_waves import Child, drop_school_id, run_wave

revision = 'n7z1b3d5f7h9'
down_revision = 'm5x9z1b3d5f7'
branch_labels = None
depends_on = None

WAVE_4 = (
    Child("lms_answers", "lms_quiz_attempts", "attempt_id",
          (("lms_choices", "choice_id"), ("lms_questions", "question_id"))),
    Child("lms_assignment_answers", "lms_submissions", "submission_id",
          (("lms_assignment_choices", "choice_id"), ("lms_assignment_questions", "question_id"))),
)


def upgrade():
    t0 = time.perf_counter()
    run_wave(op, "SAAS-021/wave4", WAVE_4)
    print(f"[SAAS-021/wave4] {time.perf_counter() - t0:.2f}s")


def downgrade():
    for child in reversed(WAVE_4):
        drop_school_id(op, child)
