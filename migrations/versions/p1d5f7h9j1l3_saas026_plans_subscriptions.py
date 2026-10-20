"""SAAS-026 (2026-10-21) — plans, school subscriptions, events, settings.

Seeds one `internal` plan (no limits, all modules: modules = ["*"]) and
gives every existing school an open-ended current subscription starting
on its creation date, so nothing is blocked when SAAS-027 enforces
subscriptions. Fails loudly if any school ends up without a current
subscription. No prices are seeded.
"""

from datetime import date, datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = 'p1d5f7h9j1l3'
down_revision = 'o9b3d5f7h9j1'
branch_labels = None
depends_on = None


def upgrade():
    # SAAS-025 security-review follow-up (no TOTP replay, server-side revoke).
    with op.batch_alter_table("platform_users") as b:
        b.add_column(sa.Column("totp_last_counter", sa.BigInteger()))
        b.add_column(sa.Column("session_version", sa.Integer(), nullable=False, server_default="1"))
    op.create_table(
        "plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name_ar", sa.String(128), nullable=False),
        sa.Column("name_en", sa.String(128)),
        sa.Column("max_students", sa.Integer()),
        sa.Column("max_users", sa.Integer()),
        sa.Column("max_storage_mb", sa.Integer()),
        sa.Column("modules", sa.JSON(), nullable=False),
        sa.Column("price_amount", sa.Numeric(12, 2)),
        sa.Column("currency", sa.String(8)),
        sa.Column("billing_cycle", sa.String(16), nullable=False, server_default="monthly"),
        sa.Column("trial_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("code", name="uq_plans_code"),
        sa.CheckConstraint("billing_cycle IN ('monthly', 'yearly', 'custom')",
                           name="ck_plans_billing_cycle"),
    )
    op.create_table(
        "school_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("plans.id"), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date()),
        sa.Column("trial_ends_on", sa.Date()),
        sa.Column("grace_days", sa.Integer(), nullable=False, server_default="14"),
        sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.Text()),
        sa.Column("created_by_platform_user_id", sa.Integer(), sa.ForeignKey("platform_users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("ends_on IS NULL OR ends_on >= starts_on",
                           name="ck_school_subscriptions_dates"),
    )
    op.create_index("ix_school_subscriptions_school_id", "school_subscriptions", ["school_id"])
    op.create_index("uq_school_subscriptions_current", "school_subscriptions", ["school_id"],
                    unique=True, postgresql_where=sa.text("is_current"),
                    sqlite_where=sa.text("is_current = 1"))
    op.create_table(
        "school_subscription_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("from_value", sa.String(255)),
        sa.Column("to_value", sa.String(255)),
        sa.Column("reason", sa.Text()),
        sa.Column("platform_user_id", sa.Integer(), sa.ForeignKey("platform_users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for col in ("school_id", "kind", "created_at"):
        op.create_index(f"ix_school_subscription_events_{col}", "school_subscription_events", [col])
    op.create_table(
        "platform_settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.Text()),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("platform_users.id")),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )

    bind = op.get_bind()
    now = datetime.now(timezone.utc)
    plans = sa.table("plans", sa.column("id", sa.Integer), sa.column("code", sa.String),
                     sa.column("name_ar", sa.String), sa.column("name_en", sa.String),
                     sa.column("modules", sa.JSON), sa.column("billing_cycle", sa.String),
                     sa.column("trial_days", sa.Integer), sa.column("is_active", sa.Boolean),
                     sa.column("created_at", sa.DateTime))
    bind.execute(plans.insert().values(
        code="internal", name_ar="داخلية (بلا حدود)", name_en="Internal (unlimited)",
        modules=["*"], billing_cycle="custom", trial_days=0, is_active=True, created_at=now))
    plan_id = bind.execute(sa.text("SELECT id FROM plans WHERE code = 'internal'")).scalar()

    subs = sa.table("school_subscriptions", sa.column("school_id", sa.Integer),
                    sa.column("plan_id", sa.Integer), sa.column("starts_on", sa.Date),
                    sa.column("grace_days", sa.Integer), sa.column("auto_renew", sa.Boolean),
                    sa.column("is_current", sa.Boolean), sa.column("notes", sa.Text),
                    sa.column("created_at", sa.DateTime))
    events = sa.table("school_subscription_events", sa.column("school_id", sa.Integer),
                      sa.column("kind", sa.String), sa.column("to_value", sa.String),
                      sa.column("reason", sa.Text), sa.column("created_at", sa.DateTime))
    for sid, created in bind.execute(sa.text("SELECT id, created_at FROM schools")).all():
        if isinstance(created, str):
            created = datetime.fromisoformat(created)
        starts = created.date() if created is not None else date.today()
        bind.execute(subs.insert().values(
            school_id=sid, plan_id=plan_id, starts_on=starts, grace_days=14, auto_renew=False,
            is_current=True, notes="SAAS-026 migration — existing school", created_at=now))
        bind.execute(events.insert().values(
            school_id=sid, kind="created", to_value=f"internal:{starts}..∞",
            reason="SAAS-026 migration", created_at=now))
    missing = bind.execute(sa.text(
        "SELECT COUNT(*) FROM schools s WHERE NOT EXISTS (SELECT 1 FROM school_subscriptions x "
        "WHERE x.school_id = s.id AND x.is_current)")).scalar()
    if missing:
        raise RuntimeError(f"SAAS-026: {missing} school(s) left without a current subscription")
    print(f"[SAAS-026] internal plan id={plan_id}; subscriptions created for all schools")


def downgrade():
    op.drop_table("platform_settings")
    op.drop_table("school_subscription_events")
    op.drop_index("uq_school_subscriptions_current", table_name="school_subscriptions")
    op.drop_table("school_subscriptions")
    op.drop_table("plans")
    with op.batch_alter_table("platform_users") as b:
        b.drop_column("session_version")
        b.drop_column("totp_last_counter")
