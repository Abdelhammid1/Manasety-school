"""SAAS-047 (2026-10-22) — school_backups: a school's own backups (and
the queue the server CLI runs).
"""

from alembic import op
import sqlalchemy as sa

revision = 'a2b4c6d8e0f2'
down_revision = 'z1x5z7b9d1f3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "school_backups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("file_name", sa.String(255)),
        sa.Column("size_bytes", sa.BigInteger()),
        sa.Column("error", sa.String(255)),
        sa.Column("requested_by_user_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('pending','running','succeeded','failed')",
                           name="ck_school_backups_status"),
    )
    op.create_index("ix_school_backups_school_id", "school_backups", ["school_id"])
    op.create_index("ix_school_backups_status", "school_backups", ["status"])


def downgrade():
    op.drop_index("ix_school_backups_status", table_name="school_backups")
    op.drop_index("ix_school_backups_school_id", table_name="school_backups")
    op.drop_table("school_backups")
