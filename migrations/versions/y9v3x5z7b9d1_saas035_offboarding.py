"""SAAS-035 (2026-10-21) — school_offboarding (the leaving path).
Platform table. No data changes; nothing is ever deleted automatically.
"""

from alembic import op
import sqlalchemy as sa

revision = 'y9v3x5z7b9d1'
down_revision = 'x7t1v3x5z7b9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "school_offboarding",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False, unique=True),
        sa.Column("requested_by", sa.Integer(), sa.ForeignKey("platform_users.id")),
        sa.Column("requested_at", sa.DateTime(timezone=True)),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("export_job_id", sa.Integer(), sa.ForeignKey("platform_jobs.id")),
        sa.Column("export_file", sa.String(255)),
        sa.Column("export_verified_at", sa.DateTime(timezone=True)),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("retention_until", sa.DateTime(timezone=True)),
        sa.Column("purge_requested_by", sa.Integer(), sa.ForeignKey("platform_users.id")),
        sa.Column("purge_requested_at", sa.DateTime(timezone=True)),
        sa.Column("purge_approved_by", sa.Integer(), sa.ForeignKey("platform_users.id")),
        sa.Column("purge_approved_at", sa.DateTime(timezone=True)),
        sa.Column("approvals_required", sa.Integer()),
        sa.Column("purged_at", sa.DateTime(timezone=True)),
    )


def downgrade():
    op.drop_table("school_offboarding")
