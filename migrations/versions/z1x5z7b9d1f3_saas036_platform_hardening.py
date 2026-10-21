"""SAAS-036 (2026-10-21) — platform sessions, setup links, immutable audit.

- platform_sessions (the console cookie carries only the session id)
- platform_setup_tokens (one-time invite / reset links)
- audit_prune_guard (SQLite only: lets the retention delete through)
- triggers refusing UPDATE / DELETE on platform_audit_logs and
  support_session_events (Postgres: allowed only with
  SET LOCAL manasety.audit_prune = 'on', used by flask platform-audit-prune)

Existing console sessions end at deploy (they carry no session id) —
accepted, the team is small.
"""

from alembic import op
import sqlalchemy as sa

revision = 'z1x5z7b9d1f3'
down_revision = 'y9v3x5z7b9d1'
branch_labels = None
depends_on = None

TABLES = ("platform_audit_logs", "support_session_events")


def upgrade():
    op.create_table(
        "platform_sessions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("platform_user_id", sa.Integer(), sa.ForeignKey("platform_users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip", sa.String(45)),
        sa.Column("user_agent", sa.String(255)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_platform_sessions_platform_user_id", "platform_sessions", ["platform_user_id"])
    op.create_table(
        "platform_setup_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("platform_user_id", sa.Integer(), sa.ForeignKey("platform_users.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("purpose", sa.String(16), nullable=False, server_default="invite"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_platform_setup_tokens_platform_user_id", "platform_setup_tokens", ["platform_user_id"])
    op.create_table("audit_prune_guard", sa.Column("id", sa.Integer(), primary_key=True))

    # Kept in step with app/services/platform_security.trigger_ddl (which
    # creates the same triggers for create_all databases).
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
CREATE OR REPLACE FUNCTION manasety_audit_immutable() RETURNS trigger AS $$
BEGIN
  IF current_setting('manasety.audit_prune', true) = 'on' AND TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'audit rows are immutable (%)', TG_TABLE_NAME;
END $$ LANGUAGE plpgsql;""")
        for t in TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS {t}_immutable ON {t}")
            op.execute(f"CREATE TRIGGER {t}_immutable BEFORE UPDATE OR DELETE ON {t} "
                       f"FOR EACH ROW EXECUTE FUNCTION manasety_audit_immutable()")
    else:
        for t in TABLES:
            op.execute(f"CREATE TRIGGER IF NOT EXISTS {t}_no_update BEFORE UPDATE ON {t} "
                       f"BEGIN SELECT RAISE(ABORT, 'audit rows are immutable'); END;")
            op.execute(f"CREATE TRIGGER IF NOT EXISTS {t}_no_delete BEFORE DELETE ON {t} "
                       f"WHEN (SELECT COUNT(*) FROM audit_prune_guard) = 0 "
                       f"BEGIN SELECT RAISE(ABORT, 'audit rows are immutable'); END;")


def downgrade():
    bind = op.get_bind()
    for t in TABLES:
        if bind.dialect.name == "postgresql":
            op.execute(f"DROP TRIGGER IF EXISTS {t}_immutable ON {t}")
        else:
            op.execute(f"DROP TRIGGER IF EXISTS {t}_no_update")
            op.execute(f"DROP TRIGGER IF EXISTS {t}_no_delete")
    if bind.dialect.name == "postgresql":
        op.execute("DROP FUNCTION IF EXISTS manasety_audit_immutable()")
    op.drop_table("audit_prune_guard")
    op.drop_table("platform_setup_tokens")
    op.drop_table("platform_sessions")
