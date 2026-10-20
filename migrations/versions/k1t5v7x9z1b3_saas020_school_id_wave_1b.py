"""SAAS-020 (2026-10-20) — wave 1B: school_id NOT NULL on 12 tables — the
LMS roots (quizzes, assignments, units) and the question bank and its
templates. Same contract as SAAS-019 (app/services/schema_waves.py).
Must land before SAAS-021: every deeper LMS table backfills from these.
"""

from alembic import op

from app.services.schema_waves import Child, drop_school_id, run_wave

revision = 'k1t5v7x9z1b3'
down_revision = 'j9r3t5v7x9z1'
branch_labels = None
depends_on = None

WAVE_1B = (
    Child("lms_quizzes", "lms_courses", "course_id"),
    Child("lms_assignments", "lms_courses", "course_id",
          (("rubrics", "rubric_id"), ("lms_assignment_templates", "source_template_id"))),
    Child("lms_units", "lms_courses", "course_id"),
    Child("lms_bank_choices", "lms_bank_questions", "question_id"),
    Child("lms_assignment_template_questions", "lms_assignment_templates", "template_id",
          (("lms_bank_questions", "source_bank_id"),)),
    Child("lms_assessment_template_questions", "lms_assessment_templates", "template_id",
          (("lms_bank_questions", "bank_question_id"),)),
    Child("lms_bank_question_tags", "lms_bank_questions", "question_id",
          (("lms_bank_tags", "tag_id"),)),
    Child("lms_bank_question_skills", "lms_bank_questions", "question_id",
          (("lms_skills", "skill_id"),)),
    Child("lms_bank_question_objectives", "lms_bank_questions", "question_id",
          (("lms_learning_objectives", "objective_id"),)),
    Child("lms_question_stats", "lms_bank_questions", "bank_question_id"),
    Child("lms_course_sections", "lms_courses", "course_id", (("sections", "section_id"),)),
    Child("lms_bank_question_collection_items", "lms_question_collections", "collection_id",
          (("lms_bank_questions", "question_id"),)),
)


def upgrade():
    run_wave(op, "SAAS-020", WAVE_1B)


def downgrade():
    for child in reversed(WAVE_1B):
        drop_school_id(op, child)
