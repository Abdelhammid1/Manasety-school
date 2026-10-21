"""SAAS-030 (2026-10-21) — school_module_overrides, school_limit_overrides.
Console-managed; no rows created, so every school keeps its plan's
modules and limits (the internal plan = everything, unlimited).
"""

from alembic import op
import sqlalchemy as sa

revision = 't9l3n5p7r9t1'
down_revision = 's7j1l3n5p7r9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "school_module_overrides",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("module_key", sa.String(32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_by_platform_user_id", sa.Integer(), sa.ForeignKey("platform_users.id")),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("school_id", "module_key", name="uq_school_module_override"),
    )
    op.create_index("ix_school_module_overrides_school_id", "school_module_overrides", ["school_id"])
    op.create_table(
        "school_limit_overrides",
        sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), primary_key=True),
        sa.Column("max_students", sa.Integer()),
        sa.Column("max_users", sa.Integer()),
        sa.Column("max_storage_mb", sa.Integer()),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_by_platform_user_id", sa.Integer(), sa.ForeignKey("platform_users.id")),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )


def downgrade():
    op.drop_table("school_limit_overrides")
    op.drop_table("school_module_overrides")
