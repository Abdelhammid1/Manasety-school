"""Deferred features — A2 subject weight, T3 rules engine, T4 risk score.

Ticket refs:
- A2  subject_grades.weight
- T3  attendance_rules + attendance_rule_triggers
- T4  student_risk_scores

Idempotent — every column and table is guarded by an inspector check
before it's touched."""

from alembic import op
import sqlalchemy as sa


revision = 'b3t5v7x9z1c3'
down_revision = 'a1r3t5v7x9z1'
branch_labels = None
depends_on = None


def _has(bind, table, col):
    insp = sa.inspect(bind)
    return any(c["name"] == col for c in insp.get_columns(table))


def _has_table(bind, name):
    return sa.inspect(bind).has_table(name)


def upgrade():
    bind = op.get_bind()

    # A2 — subject_grades.weight (default 1.0)
    if _has_table(bind, "subject_grades") and not _has(bind, "subject_grades", "weight"):
        with op.batch_alter_table("subject_grades") as batch:
            batch.add_column(sa.Column(
                "weight", sa.Numeric(5, 2),
                nullable=False, server_default="1.00",
            ))

    # T3 — attendance_rules
    if not _has_table(bind, "attendance_rules"):
        op.create_table(
            "attendance_rules",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("school_id", sa.Integer(),
                      sa.ForeignKey("schools.id"),
                      nullable=False, index=True),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("kind", sa.String(20), nullable=False),
            sa.Column("threshold", sa.Integer(), nullable=False),
            sa.Column("window", sa.String(20),
                      nullable=False, server_default="term"),
            sa.Column("action", sa.String(24),
                      nullable=False, server_default="warning"),
            sa.Column("is_active", sa.Boolean(),
                      nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(),
                      server_default=sa.func.now(), nullable=False),
        )

    # T3 — attendance_rule_triggers
    if not _has_table(bind, "attendance_rule_triggers"):
        op.create_table(
            "attendance_rule_triggers",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("school_id", sa.Integer(),
                      sa.ForeignKey("schools.id"),
                      nullable=False, index=True),
            sa.Column("rule_id", sa.Integer(),
                      sa.ForeignKey("attendance_rules.id", ondelete="CASCADE"),
                      nullable=False, index=True),
            sa.Column("student_id", sa.Integer(),
                      sa.ForeignKey("students.id", ondelete="CASCADE"),
                      nullable=False, index=True),
            sa.Column("triggered_on", sa.Date(), nullable=False),
            sa.Column("count_at_trigger", sa.Integer(), nullable=False),
            sa.Column("resolved", sa.Boolean(),
                      nullable=False, server_default=sa.false()),
        )

    # T4 — student_risk_scores
    if not _has_table(bind, "student_risk_scores"):
        op.create_table(
            "student_risk_scores",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("school_id", sa.Integer(),
                      sa.ForeignKey("schools.id"),
                      nullable=False, index=True),
            sa.Column("student_id", sa.Integer(),
                      sa.ForeignKey("students.id", ondelete="CASCADE"),
                      nullable=False, unique=True, index=True),
            sa.Column("score", sa.Integer(),
                      nullable=False, server_default="0"),
            sa.Column("tier", sa.String(16),
                      nullable=False, server_default="low"),
            sa.Column("inputs", sa.JSON(), nullable=True),
            sa.Column("computed_at", sa.DateTime(),
                      server_default=sa.func.now(), nullable=False),
        )


def downgrade():
    for table in ("student_risk_scores",
                  "attendance_rule_triggers",
                  "attendance_rules"):
        try: op.drop_table(table)
        except Exception: pass
    if _has_table(op.get_bind(), "subject_grades"):
        with op.batch_alter_table("subject_grades") as batch:
            try: batch.drop_column("weight")
            except Exception: pass
