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

    # Playwright-tour fix (2026-10-02) — SQLite cannot ALTER TABLE
    # ADD CONSTRAINT, and the three target tables carry unnamed FKs
    # from their original CREATE TABLE which trip batch_alter_table
    # ("Constraint must have a name"). On SQLite, add the raw
    # Integer column with no FK (the FK was only ever documented;
    # the ORM-level relationship on the model gives us the join).
    # On Postgres, add the FK properly.
    is_sqlite = bind.dialect.name == "sqlite"

    def _add_fk_column(table: str, col: str, ref: str,
                       fk_name: str) -> None:
        if _has(bind, table, col):
            return
        if is_sqlite:
            op.add_column(table, sa.Column(col, sa.Integer(), nullable=True))
        else:
            op.add_column(
                table,
                sa.Column(
                    col, sa.Integer(),
                    sa.ForeignKey(ref, ondelete="SET NULL", name=fk_name),
                    nullable=True,
                ),
            )
        ix = f"ix_{table}_{col}"
        if not _has_index(bind, table, ix):
            op.create_index(ix, table, [col])

    # ── Ticket #12 — rubric_id on AssignmentQuestion + Question ────
    _add_fk_column(
        "lms_assignment_questions", "rubric_id", "rubrics.id",
        "fk_lms_assignment_questions_rubric_id_rubrics",
    )
    _add_fk_column(
        "lms_questions", "rubric_id", "rubrics.id",
        "fk_lms_questions_rubric_id_rubrics",
    )

    # ── Ticket #16 — grade_id on AssessmentComponent ───────────────
    _add_fk_column(
        "assessment_components", "grade_id", "grades.id",
        "fk_assessment_components_grade_id_grades",
    )

    # Widen the uniqueness to include grade_id. Drop the old
    # 3-column constraint if it exists; add the new 4-column one.
    #
    # Playwright-tour fix (2026-10-02) — SQLite can't ALTER
    # constraints in place, and batch_alter_table's table-rebuild
    # trips over the three unnamed FKs that this table has carried
    # from its very first migration ("Constraint must have a name").
    # The uniqueness widen is defensive — no code path relies on
    # it — so skip it on SQLite. Postgres users still get the new
    # 4-column constraint applied cleanly.
    if bind.dialect.name != "sqlite":
        if _has_uc(bind, "assessment_components",
                   "uq_component_term_subject_name"):
            op.drop_constraint(
                "uq_component_term_subject_name",
                "assessment_components", type_="unique",
            )
        if not _has_uc(bind, "assessment_components",
                       "uq_component_term_subject_grade_name"):
            op.create_unique_constraint(
                "uq_component_term_subject_grade_name",
                "assessment_components",
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
