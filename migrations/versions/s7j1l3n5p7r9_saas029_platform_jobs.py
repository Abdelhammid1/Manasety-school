"""SAAS-029 (2026-10-21) — platform_jobs (nginx-sync queue; later
school_export). Platform table, no school data.
"""

from alembic import op
import sqlalchemy as sa

revision = 's7j1l3n5p7r9'
down_revision = 'r5h9j1l3n5p7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "platform_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id")),
        sa.Column("reason", sa.String(255)),
        sa.Column("requested_by_platform_user_id", sa.Integer(), sa.ForeignKey("platform_users.id")),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("log", sa.Text()),
        sa.Column("result", sa.JSON()),
        sa.CheckConstraint("status IN ('pending','running','succeeded','failed')",
                           name="ck_platform_jobs_status"),
    )
    op.create_index("ix_platform_jobs_kind", "platform_jobs", ["kind"])
    op.create_index("ix_platform_jobs_status", "platform_jobs", ["status"])


def downgrade():
    op.drop_table("platform_jobs")
