"""SAAS-019 (2026-10-20) — wave 1A: school_id NOT NULL on 17 child tables
whose parents already carry school_id (finance, messaging, links,
settings, nafis).

Contract (app/services/schema_waves.py): add nullable + index + FK,
backfill from the primary parent, fail loudly on any NULL or any other
school-owned parent that disagrees, then NOT NULL. Row counts are
checked before/after. Downgrade drops the column, index and FK.
"""

from alembic import op

from app.services.schema_waves import Child, drop_school_id, run_wave

revision = 'j9r3t5v7x9z1'
down_revision = 'i8q2s4u6w8y0'
branch_labels = None
depends_on = None

WAVE_1A = (
    Child("installments", "invoices", "invoice_id"),
    Child("invoice_lines", "invoices", "invoice_id",
          (("cost_centers", "cost_center_id"), ("fee_types", "fee_type_id"))),
    Child("journal_lines", "journal_entries", "entry_id",
          (("accounts", "account_id"), ("cost_centers", "cost_center_id"))),
    Child("messages", "conversations", "conversation_id", (("users", "sender_user_id"),)),
    Child("conversation_participants", "conversations", "conversation_id",
          (("users", "user_id"),)),
    Child("notification_preferences", "users", "user_id"),
    Child("student_guardians", "students", "student_id", (("guardians", "guardian_id"),)),
    Child("student_tag_links", "students", "student_id", (("student_tags", "tag_id"),)),
    Child("behavior_actions", "behavior_incidents", "incident_id",
          (("users", "taken_by_user_id"),)),
    Child("subject_grades", "subjects", "subject_id", (("grades", "grade_id"),)),
    Child("subject_terms", "subjects", "subject_id", (("terms", "term_id"),)),
    Child("teacher_subjects", "teachers", "teacher_id", (("subjects", "subject_id"),)),
    Child("grading_scale_levels", "grading_scales", "scale_id"),
    Child("intervention_plan_outcomes", "intervention_plans", "plan_id",
          (("learning_outcomes", "outcome_id"),)),
    Child("intervention_sessions", "intervention_plans", "plan_id"),
    Child("nafis_outcome_scores", "nafis_results", "result_id",
          (("learning_outcomes", "outcome_id"),)),
    Child("rubric_criteria", "rubrics", "rubric_id"),
)


def upgrade():
    run_wave(op, "SAAS-019", WAVE_1A)


def downgrade():
    for child in reversed(WAVE_1A):
        drop_school_id(op, child)
