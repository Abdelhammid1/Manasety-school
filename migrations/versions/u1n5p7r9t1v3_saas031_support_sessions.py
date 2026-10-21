"""SAAS-031 (2026-10-21) — support sessions.

- users.is_platform_support (+ partial unique index: one per school)
- schools.notify_on_support_access (default on)
- audit_logs.support_session_id
- support_sessions, support_session_events (platform tables)
- one support user per existing school ("__manasety_support__", the
  school's admin role, a random unusable bcrypt hash). Schools without
  an admin role are listed and skipped (provisioning creates it later).
"""

import secrets
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = 'u1n5p7r9t1v3'
down_revision = 't9l3n5p7r9t1'
branch_labels = None
depends_on = None


def upgrade():
    import bcrypt
    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("is_platform_support", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index("uq_users_one_support_per_school", "users", ["school_id"], unique=True,
                    sqlite_where=sa.text("is_platform_support = 1"),
                    postgresql_where=sa.text("is_platform_support"))
    with op.batch_alter_table("schools") as b:
        b.add_column(sa.Column("notify_on_support_access", sa.Boolean(), nullable=False, server_default=sa.true()))
    with op.batch_alter_table("audit_logs") as b:
        b.add_column(sa.Column("support_session_id", sa.Integer()))

    op.create_table(
        "support_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("platform_user_id", sa.Integer(), sa.ForeignKey("platform_users.id"), nullable=False),
        sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False, server_default="read_only"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("end_reason", sa.String(32)),
        sa.Column("ip", sa.String(45)),
        sa.Column("user_agent", sa.String(255)),
        sa.Column("nonce_hash", sa.String(64)),
        sa.Column("nonce_used_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("mode IN ('read_only','write')", name="ck_support_sessions_mode"),
    )
    op.create_index("ix_support_sessions_platform_user_id", "support_sessions", ["platform_user_id"])
    op.create_index("ix_support_sessions_school_id", "support_sessions", ["school_id"])
    op.create_table(
        "support_session_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("support_session_id", sa.Integer(), sa.ForeignKey("support_sessions.id"), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("method", sa.String(8), nullable=False),
        sa.Column("endpoint", sa.String(128)),
        sa.Column("path", sa.String(512), nullable=False),
        sa.Column("status", sa.Integer()),
        sa.Column("ip", sa.String(45)),
        sa.Column("field_names", sa.JSON()),
    )
    op.create_index("ix_support_session_events_session_ts", "support_session_events",
                    ["support_session_id", "ts"])

    bind = op.get_bind()
    users = sa.table("users", sa.column("school_id", sa.Integer), sa.column("role_id", sa.Integer),
                     sa.column("username", sa.String), sa.column("full_name", sa.String),
                     sa.column("password_hash", sa.String), sa.column("is_active", sa.Boolean),
                     sa.column("is_platform_support", sa.Boolean),
                     sa.column("failed_attempts", sa.Integer), sa.column("created_at", sa.DateTime))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    skipped = []
    for (sid,) in bind.execute(sa.text("SELECT id FROM schools")).all():
        role = bind.execute(sa.text("SELECT id FROM roles WHERE school_id = :s AND name = 'admin' "
                                    "ORDER BY id LIMIT 1"), {"s": sid}).scalar()
        if role is None:
            skipped.append(sid)
            continue
        pw = bcrypt.hashpw(secrets.token_urlsafe(48).encode(), bcrypt.gensalt()).decode()
        bind.execute(users.insert().values(
            school_id=sid, role_id=role, username="__manasety_support__", full_name="دعم منصتي",
            password_hash=pw, is_active=True, is_platform_support=True, failed_attempts=0,
            created_at=now))
    if skipped:
        print(f"[SAAS-031] schools without an admin role (no support user yet): {skipped}")


def downgrade():
    bind = op.get_bind()
    acted = bind.execute(sa.text(
        "SELECT COUNT(*) FROM audit_logs WHERE user_id IN "
        "(SELECT id FROM users WHERE is_platform_support)")).scalar()
    if acted:
        raise RuntimeError(
            f"SAAS-031 downgrade refused: {acted} audit_logs rows were written by support users; "
            "deleting those users would break (or destroy) the audit trail. Keep this revision.")
    bind.execute(sa.text("DELETE FROM users WHERE is_platform_support"))
    op.drop_table("support_session_events")
    op.drop_table("support_sessions")
    with op.batch_alter_table("audit_logs") as b:
        b.drop_column("support_session_id")
    with op.batch_alter_table("schools") as b:
        b.drop_column("notify_on_support_access")
    op.drop_index("uq_users_one_support_per_school", table_name="users")
    with op.batch_alter_table("users") as b:
        b.drop_column("is_platform_support")
