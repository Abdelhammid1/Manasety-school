"""LMS Phase 2 — new tables + M:N + a couple of column follow-ups.

Covers ticket items:
  · #2  Skills taxonomy (`lms_skills`) + M:N (`lms_bank_question_skills`)
  · #3  Learning Objectives (`lms_learning_objectives`) + M:N
  · #5  Question performance stats (`lms_question_stats`)
  · #10 QuizAttempt.tab_switch_count
  · #11 Attempt-flagged questions (`lms_attempt_flagged_questions`)
  · #14 QuizAttempt.variant_label
  · #24 Assignment extensions (`lms_assignment_extensions`)
  · #26 BankQuestion.visibility
  · #28 Question collections + M:N
  · #29 Feedback templates

Idempotent: every add is guarded on the current schema so re-runs on a
partially-migrated DB stay a no-op."""

from alembic import op
import sqlalchemy as sa


revision = 'y7n9p1r3t5v7'
down_revision = 'x5l7n9p1r3t5'
branch_labels = None
depends_on = None


def _has_table(bind, name):
    return sa.inspect(bind).has_table(name)


def _has(bind, table, col):
    insp = sa.inspect(bind)
    return any(c["name"] == col for c in insp.get_columns(table))


def upgrade():
    bind = op.get_bind()

    # #2 — Skills
    if not _has_table(bind, "lms_skills"):
        op.create_table(
            "lms_skills",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("school_id", sa.Integer(),
                      sa.ForeignKey("schools.id"),
                      nullable=False, index=True),
            sa.Column("parent_id", sa.Integer(),
                      sa.ForeignKey("lms_skills.id", ondelete="SET NULL"),
                      nullable=True, index=True),
            sa.Column("title", sa.String(160), nullable=False),
            sa.Column("description", sa.Text(), server_default=""),
            sa.Column("order_index", sa.Integer(),
                      nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now()),
        )
    if not _has_table(bind, "lms_bank_question_skills"):
        op.create_table(
            "lms_bank_question_skills",
            sa.Column("question_id", sa.Integer(),
                      sa.ForeignKey("lms_bank_questions.id",
                                    ondelete="CASCADE"),
                      primary_key=True),
            sa.Column("skill_id", sa.Integer(),
                      sa.ForeignKey("lms_skills.id",
                                    ondelete="CASCADE"),
                      primary_key=True),
        )

    # #3 — Learning Objectives
    if not _has_table(bind, "lms_learning_objectives"):
        op.create_table(
            "lms_learning_objectives",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("school_id", sa.Integer(),
                      sa.ForeignKey("schools.id"),
                      nullable=False, index=True),
            sa.Column("lesson_id", sa.Integer(),
                      sa.ForeignKey("lms_lessons.id", ondelete="CASCADE"),
                      nullable=True, index=True),
            sa.Column("code",  sa.String(40), nullable=True, index=True),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("description", sa.Text(), server_default=""),
            sa.Column("order_index", sa.Integer(),
                      nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now()),
        )
    if not _has_table(bind, "lms_bank_question_objectives"):
        op.create_table(
            "lms_bank_question_objectives",
            sa.Column("question_id", sa.Integer(),
                      sa.ForeignKey("lms_bank_questions.id",
                                    ondelete="CASCADE"),
                      primary_key=True),
            sa.Column("objective_id", sa.Integer(),
                      sa.ForeignKey("lms_learning_objectives.id",
                                    ondelete="CASCADE"),
                      primary_key=True),
        )

    # #5 — Question stats
    if not _has_table(bind, "lms_question_stats"):
        op.create_table(
            "lms_question_stats",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("bank_question_id", sa.Integer(),
                      sa.ForeignKey("lms_bank_questions.id",
                                    ondelete="CASCADE"),
                      nullable=False, unique=True, index=True),
            sa.Column("usage_count", sa.Integer(),
                      nullable=False, server_default="0"),
            sa.Column("avg_score", sa.Numeric(6, 3), nullable=True),
            sa.Column("avg_time_seconds", sa.Numeric(8, 2), nullable=True),
            sa.Column("difficulty_index", sa.Numeric(6, 4), nullable=True),
            sa.Column("discrimination_index", sa.Numeric(6, 4), nullable=True),
            sa.Column("last_computed_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now()),
        )

    # #11 — attempt-flagged questions
    if not _has_table(bind, "lms_attempt_flagged_questions"):
        op.create_table(
            "lms_attempt_flagged_questions",
            sa.Column("attempt_id", sa.Integer(),
                      sa.ForeignKey("lms_quiz_attempts.id",
                                    ondelete="CASCADE"),
                      primary_key=True),
            sa.Column("question_id", sa.Integer(),
                      sa.ForeignKey("lms_questions.id",
                                    ondelete="CASCADE"),
                      primary_key=True),
            sa.Column("flagged_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now()),
        )

    # #24 — Assignment extensions
    if not _has_table(bind, "lms_assignment_extensions"):
        op.create_table(
            "lms_assignment_extensions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("assignment_id", sa.Integer(),
                      sa.ForeignKey("lms_assignments.id",
                                    ondelete="CASCADE"),
                      nullable=False, index=True),
            sa.Column("student_id", sa.Integer(),
                      sa.ForeignKey("students.id",
                                    ondelete="CASCADE"),
                      nullable=False, index=True),
            sa.Column("new_due_at", sa.DateTime(timezone=True),
                      nullable=False),
            sa.Column("reason", sa.Text(), server_default=""),
            sa.Column("granted_by_id", sa.Integer(),
                      sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now()),
            sa.UniqueConstraint("assignment_id", "student_id",
                                name="uq_extension_assignment_student"),
        )

    # #28 — Question collections
    if not _has_table(bind, "lms_question_collections"):
        op.create_table(
            "lms_question_collections",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("school_id", sa.Integer(),
                      sa.ForeignKey("schools.id"),
                      nullable=False, index=True),
            sa.Column("owner_user_id", sa.Integer(),
                      sa.ForeignKey("users.id"), nullable=True),
            sa.Column("title", sa.String(160), nullable=False),
            sa.Column("description", sa.Text(), server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now()),
        )
    if not _has_table(bind, "lms_bank_question_collection_items"):
        op.create_table(
            "lms_bank_question_collection_items",
            sa.Column("collection_id", sa.Integer(),
                      sa.ForeignKey("lms_question_collections.id",
                                    ondelete="CASCADE"),
                      primary_key=True),
            sa.Column("question_id", sa.Integer(),
                      sa.ForeignKey("lms_bank_questions.id",
                                    ondelete="CASCADE"),
                      primary_key=True),
        )

    # #29 — Feedback templates
    if not _has_table(bind, "lms_feedback_templates"):
        op.create_table(
            "lms_feedback_templates",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("school_id", sa.Integer(),
                      sa.ForeignKey("schools.id"),
                      nullable=False, index=True),
            sa.Column("owner_user_id", sa.Integer(),
                      sa.ForeignKey("users.id"), nullable=True),
            sa.Column("title", sa.String(160), nullable=False),
            sa.Column("body",  sa.Text(),
                      nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now()),
        )

    # #10 — QuizAttempt.tab_switch_count + #14 — variant_label
    with op.batch_alter_table("lms_quiz_attempts") as batch:
        if not _has(bind, "lms_quiz_attempts", "tab_switch_count"):
            batch.add_column(sa.Column(
                "tab_switch_count", sa.Integer(),
                nullable=False, server_default="0",
            ))
        if not _has(bind, "lms_quiz_attempts", "variant_label"):
            batch.add_column(sa.Column(
                "variant_label", sa.String(4), nullable=True,
            ))

    # #26 — BankQuestion.visibility
    with op.batch_alter_table("lms_bank_questions") as batch:
        if not _has(bind, "lms_bank_questions", "visibility"):
            batch.add_column(sa.Column(
                "visibility", sa.String(16),
                nullable=False, server_default="private",
            ))


def downgrade():
    for table in [
        "lms_bank_question_collection_items",
        "lms_question_collections",
        "lms_feedback_templates",
        "lms_assignment_extensions",
        "lms_attempt_flagged_questions",
        "lms_question_stats",
        "lms_bank_question_objectives",
        "lms_learning_objectives",
        "lms_bank_question_skills",
        "lms_skills",
    ]:
        try: op.drop_table(table)
        except Exception: pass
    with op.batch_alter_table("lms_quiz_attempts") as batch:
        for col in ("tab_switch_count", "variant_label"):
            try: batch.drop_column(col)
            except Exception: pass
    with op.batch_alter_table("lms_bank_questions") as batch:
        try: batch.drop_column("visibility")
        except Exception: pass
