"""Phase-3 larger features — SubjectPrerequisite, graduation, exit checklist.

Ticket refs: A1, A9 (via audit registration in code), S4, S5.
Idempotent."""

from alembic import op
import sqlalchemy as sa


revision = 'a1r3t5v7x9z1'
down_revision = 'z9p1r3t5v7x9'
branch_labels = None
depends_on = None


def _has(bind, table, col):
    insp = sa.inspect(bind)
    return any(c["name"] == col for c in insp.get_columns(table))


def _has_table(bind, name):
    return sa.inspect(bind).has_table(name)


def upgrade():
    bind = op.get_bind()

    # A1 — subject_prerequisites
    if not _has_table(bind, "subject_prerequisites"):
        op.create_table(
            "subject_prerequisites",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("school_id", sa.Integer(),
                      sa.ForeignKey("schools.id"),
                      nullable=False, index=True),
            sa.Column("subject_id", sa.Integer(),
                      sa.ForeignKey("subjects.id", ondelete="CASCADE"),
                      nullable=False, index=True),
            sa.Column("requires_subject_id", sa.Integer(),
                      sa.ForeignKey("subjects.id", ondelete="CASCADE"),
                      nullable=False, index=True),
            sa.Column("note", sa.String(255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now()),
            sa.UniqueConstraint(
                "school_id", "subject_id", "requires_subject_id",
                name="uq_subject_prereq",
            ),
        )

    # S4 + S5 — enrollments extra columns
    with op.batch_alter_table("enrollments") as batch:
        if not _has(bind, "enrollments", "graduation_date"):
            batch.add_column(sa.Column(
                "graduation_date", sa.Date(), nullable=True,
            ))
        if not _has(bind, "enrollments", "exit_checklist"):
            batch.add_column(sa.Column(
                "exit_checklist", sa.JSON(), nullable=True,
            ))


def downgrade():
    try: op.drop_table("subject_prerequisites")
    except Exception: pass
    with op.batch_alter_table("enrollments") as batch:
        for c in ("exit_checklist", "graduation_date"):
            try: batch.drop_column(c)
            except Exception: pass
