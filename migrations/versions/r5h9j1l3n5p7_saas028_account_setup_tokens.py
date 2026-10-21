"""SAAS-028 (2026-10-21) — account_setup_tokens (provisioned admin's
one-time set-password link). Tenant-owned through users.user_id.
No data changes to existing tables.
"""

from alembic import op
import sqlalchemy as sa

revision = 'r5h9j1l3n5p7'
down_revision = 'q3f7h9j1l3n5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "account_setup_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_account_setup_tokens_school_id", "account_setup_tokens", ["school_id"])
    op.create_index("ix_account_setup_tokens_user_id", "account_setup_tokens", ["user_id"])
    op.create_index("uq_account_setup_tokens_token_hash", "account_setup_tokens", ["token_hash"], unique=True)


def downgrade():
    op.drop_table("account_setup_tokens")
