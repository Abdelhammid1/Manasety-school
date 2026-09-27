"""Tickets #12 + #16 (2026-09-27) — per-question rubric override
+ per-grade AssessmentComponent scope.

Adds:
  - lms_assignment_questions.rubric_id (nullable FK → rubrics.id)
  - lms_questions.rubric_id           (nullable FK → rubrics.id)
  - assessment_components.grade_id    (nullable FK → grades.id)
  - assessment_components uniqueness widened to include grade_id.

All columns nullable so pre-migration rows keep working (rubric
falls back to the parent's rubric_id; NULL grade_id = shared
across every grade that teaches the subject).
"""

from alembic import op
import sqlalchemy as sa


revision = 'f1j5l7n9p1r3'
down_revision = 'e9h3j5l7n9p1'
branch_labels = None
depends_on = None


def _has(bind, table, col):
    insp = sa.inspect(bind)
    return any(c["name"] == col for c in insp.get_columns(table))


def _has_index(bind, table, name):
    insp = sa.inspect(bind)
    return any(ix["name"] == name for ix in insp.get_indexes(table))


def _has_uc(bind, table, name):
    insp = sa.inspect(bind)
    try:
        return any(uc["name"] == name for uc in insp.get_unique_constraints(table))
    except Exception:
        return False


def upgrade():
    bind = op.get_bind()

    # ── Ticket #12 — rubric_id on AssignmentQuestion + Question ────
    if not _has(bind, "lms_assignment_questions", "rubric_id"):
        with op.batch_alter_table("lms_assignment_questions") as batch:
            batch.add_column(sa.Column(
                "rubric_id", sa.Integer(),
                sa.ForeignKey("rubrics.id", ondelete="SET NULL"),
                nullable=True,
            ))
        if not _has_index(bind, "lms_assignment_questions",
                          "ix_lms_assignment_questions_rubric_id"):
            op.create_index(
                "ix_lms_assignment_questions_rubric_id",
                "lms_assignment_questions", ["rubric_id"],
            )

    if not _has(bind, "lms_questions", "rubric_id"):
        with op.batch_alter_table("lms_questions") as batch:
            batch.add_column(sa.Column(
                "rubric_id", sa.Integer(),
                sa.ForeignKey("rubrics.id", ondelete="SET NULL"),
                nullable=True,
            ))
        if not _has_index(bind, "lms_questions", "ix_lms_questions_rubric_id"):
            op.create_index(
                "ix_lms_questions_rubric_id",
                "lms_questions", ["rubric_id"],
            )

    # ── Ticket #16 — grade_id on AssessmentComponent ───────────────
    if not _has(bind, "assessment_components", "grade_id"):
        with op.batch_alter_table("assessment_components") as batch:
            batch.add_column(sa.Column(
                "grade_id", sa.Integer(),
                sa.ForeignKey("grades.id", ondelete="SET NULL"),
                nullable=True,
            ))
        if not _has_index(bind, "assessment_components",
                          "ix_assessment_components_grade_id"):
            op.create_index(
                "ix_assessment_components_grade_id",
                "assessment_components", ["grade_id"],
            )

    # Widen the uniqueness to include grade_id. Drop the old
    # 3-column constraint if it exists; add the new 4-column one.
    with op.batch_alter_table("assessment_components") as batch:
        if _has_uc(bind, "assessment_components",
                   "uq_component_term_subject_name"):
            try:
                batch.drop_constraint(
                    "uq_component_term_subject_name",
                    type_="unique",
                )
            except Exception:
                pass
        if not _has_uc(bind, "assessment_components",
                       "uq_component_term_subject_grade_name"):
            batch.create_unique_constraint(
                "uq_component_term_subject_grade_name",
                ["term_id", "subject_id", "grade_id", "name"],
            )


def downgrade():
    with op.batch_alter_table("assessment_components") as batch:
        try:
            batch.drop_constraint(
                "uq_component_term_subject_grade_name", type_="unique")
        except Exception:
            pass
        try:
            batch.create_unique_constraint(
                "uq_component_term_subject_name",
                ["term_id", "subject_id", "name"])
        except Exception:
            pass
        try:
            batch.drop_column("grade_id")
        except Exception:
            pass
    for table, col, ix in (
        ("lms_questions", "rubric_id", "ix_lms_questions_rubric_id"),
        ("lms_assignment_questions", "rubric_id",
         "ix_lms_assignment_questions_rubric_id"),
    ):
        try:
            op.drop_index(ix, table_name=table)
        except Exception:
            pass
        try:
            with op.batch_alter_table(table) as batch:
                batch.drop_column(col)
        except Exception:
            pass
