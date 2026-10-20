"""SAAS-025 (2026-10-21) — platform (Super Admin) identity tables.

platform_users, platform_recovery_codes, platform_audit_logs. New tables
only — no existing table changes. No school_id: these are platform
tables (see app/services/tenant_guard.py PLATFORM_TABLES). No seeding:
the first platform user is created with `flask platform-user-create`.
"""

from alembic import op
import sqlalchemy as sa

revision = 'o9b3d5f7h9j1'
down_revision = 'n7z1b3d5f7h9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "platform_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(160), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("password_changed_at", sa.DateTime(timezone=True)),
        sa.Column("totp_secret_encrypted", sa.Text()),
        sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("email", name="uq_platform_users_email"),
        sa.CheckConstraint("role IN ('owner', 'support', 'finance')", name="ck_platform_users_role"),
    )
    op.create_table(
        "platform_recovery_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("platform_user_id", sa.Integer(),
                  sa.ForeignKey("platform_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code_hash", sa.String(128), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_platform_recovery_codes_platform_user_id",
                    "platform_recovery_codes", ["platform_user_id"])
    op.create_table(
        "platform_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("platform_user_id", sa.Integer(), sa.ForeignKey("platform_users.id")),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_school_id", sa.Integer(), sa.ForeignKey("schools.id")),
        sa.Column("ip", sa.String(45)),
        sa.Column("user_agent", sa.String(255)),
        sa.Column("meta", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for col in ("platform_user_id", "action", "target_school_id", "created_at"):
        op.create_index(f"ix_platform_audit_logs_{col}", "platform_audit_logs", [col])


def downgrade():
    op.drop_table("platform_audit_logs")
    op.drop_table("platform_recovery_codes")
    op.drop_table("platform_users")
