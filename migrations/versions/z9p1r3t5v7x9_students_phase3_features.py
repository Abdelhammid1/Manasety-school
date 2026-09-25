"""Students Phase 3 — photo, notes timeline, tags, previous schools,
guardian is_guardian flag.

Ticket refs: S6, S10, S11, S3, S12.
Idempotent — every column and table is guarded by an inspector check
before creation so re-running on a partially migrated DB is a no-op."""

from alembic import op
import sqlalchemy as sa


revision = 'z9p1r3t5v7x9'
down_revision = 'y7n9p1r3t5v7'
branch_labels = None
depends_on = None


def _has(bind, table, col):
    insp = sa.inspect(bind)
    return any(c["name"] == col for c in insp.get_columns(table))


def _has_table(bind, name):
    return sa.inspect(bind).has_table(name)


def upgrade():
    bind = op.get_bind()

    # S6 — students.photo_url
    with op.batch_alter_table("students") as batch:
        if not _has(bind, "students", "photo_url"):
            batch.add_column(sa.Column("photo_url", sa.String(500), nullable=True))

    # S12 — guardians.is_guardian (default True)
    with op.batch_alter_table("guardians") as batch:
        if not _has(bind, "guardians", "is_guardian"):
            batch.add_column(sa.Column(
                "is_guardian", sa.Boolean(),
                nullable=False, server_default=sa.true(),
            ))

    # S10 — student_notes
    if not _has_table(bind, "student_notes"):
        op.create_table(
            "student_notes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("school_id", sa.Integer(),
                      sa.ForeignKey("schools.id"),
                      nullable=False, index=True),
            sa.Column("student_id", sa.Integer(),
                      sa.ForeignKey("students.id", ondelete="CASCADE"),
                      nullable=False, index=True),
            sa.Column("author_id", sa.Integer(),
                      sa.ForeignKey("users.id"), nullable=True),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(),
                      server_default=sa.func.now(), nullable=False),
        )

    # S11 — student_tags + link table
    if not _has_table(bind, "student_tags"):
        op.create_table(
            "student_tags",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("school_id", sa.Integer(),
                      sa.ForeignKey("schools.id"),
                      nullable=False, index=True),
            sa.Column("name", sa.String(60), nullable=False),
            sa.Column("color", sa.String(16), nullable=True),
            sa.Column("created_at", sa.DateTime(),
                      server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("school_id", "name",
                                name="uq_student_tag_school_name"),
        )
    if not _has_table(bind, "student_tag_links"):
        op.create_table(
            "student_tag_links",
            sa.Column("student_id", sa.Integer(),
                      sa.ForeignKey("students.id", ondelete="CASCADE"),
                      primary_key=True),
            sa.Column("tag_id", sa.Integer(),
                      sa.ForeignKey("student_tags.id", ondelete="CASCADE"),
                      primary_key=True),
        )

    # S3 — student_previous_schools
    if not _has_table(bind, "student_previous_schools"):
        op.create_table(
            "student_previous_schools",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("school_id", sa.Integer(),
                      sa.ForeignKey("schools.id"),
                      nullable=False, index=True),
            sa.Column("student_id", sa.Integer(),
                      sa.ForeignKey("students.id", ondelete="CASCADE"),
                      nullable=False, index=True),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("city", sa.String(100), nullable=True),
            sa.Column("from_year", sa.String(20), nullable=True),
            sa.Column("to_year", sa.String(20), nullable=True),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("document_url", sa.String(500), nullable=True),
            sa.Column("created_at", sa.DateTime(),
                      server_default=sa.func.now(), nullable=False),
        )


def downgrade():
    for table in ("student_previous_schools", "student_tag_links",
                  "student_tags", "student_notes"):
        try: op.drop_table(table)
        except Exception: pass
    with op.batch_alter_table("guardians") as batch:
        try: batch.drop_column("is_guardian")
        except Exception: pass
    with op.batch_alter_table("students") as batch:
        try: batch.drop_column("photo_url")
        except Exception: pass
