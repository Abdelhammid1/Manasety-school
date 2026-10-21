"""SAAS-034 (2026-10-21) — platform_usage_snapshots, platform_alerts.
Platform tables, numbers only. No data changes.
"""

from alembic import op
import sqlalchemy as sa

revision = 'x7t1v3x5z7b9'
down_revision = 'w5r9t1v3x5z7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "platform_usage_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("students_active", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("staff_users", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("storage_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("last_activity_at", sa.DateTime()),
        sa.Column("active_users_7d", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("subscription_state", sa.String(24)),
        sa.UniqueConstraint("school_id", "day", name="uq_usage_snapshot_school_day"),
    )
    op.create_index("ix_platform_usage_snapshots_school_id", "platform_usage_snapshots", ["school_id"])
    op.create_index("ix_platform_usage_snapshots_day", "platform_usage_snapshots", ["day"])
    op.create_table(
        "platform_alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(48), nullable=False),
        sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id")),
        sa.Column("severity", sa.String(8), nullable=False, server_default="warn"),
        sa.Column("message_ar", sa.Text(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("acknowledged_by", sa.Integer(), sa.ForeignKey("platform_users.id")),
    )
    op.create_index("ix_platform_alerts_kind", "platform_alerts", ["kind"])


def downgrade():
    op.drop_table("platform_alerts")
    op.drop_table("platform_usage_snapshots")
