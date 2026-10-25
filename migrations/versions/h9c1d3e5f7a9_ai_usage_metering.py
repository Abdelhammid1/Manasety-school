"""AI usage metering (2026-10-25, ticket D).

  * ai_usage_events (school table): one row per DeepSeek call — school,
    user, operation, model, status and token counts; index (school_id,
    occurred_at). Never any prompt or answer text.
  * ai_price_cards (platform): cost and sale price per 1M tokens per model.
  * ai_usage_charges (platform): each call's cost and price; deleted with
    its event (ON DELETE CASCADE).

New tables only — nothing existing is touched. Downgrade drops them.
"""

from alembic import op
import sqlalchemy as sa

# like every foreign key since SAAS-048 (c4d6f8a0b2c4)
DEFER = {"deferrable": True, "initially": "IMMEDIATE"}

revision = 'h9c1d3e5f7a9'
down_revision = 'g8b0c2d4e6f8'
branch_labels = None
depends_on = None

MONEY = sa.Numeric(18, 8)


def upgrade():
    op.create_table(
        "ai_usage_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id", **DEFER), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL", **DEFER), nullable=True),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("prompt_cache_hit_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prompt_cache_miss_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ai_usage_events_school_occurred", "ai_usage_events", ["school_id", "occurred_at"])
    op.create_index("ix_ai_usage_events_user_id", "ai_usage_events", ["user_id"])
    op.create_table(
        "ai_price_cards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("cost_hit", MONEY, nullable=False),
        sa.Column("cost_miss", MONEY, nullable=False),
        sa.Column("cost_output", MONEY, nullable=False),
        sa.Column("price_hit", MONEY, nullable=False),
        sa.Column("price_miss", MONEY, nullable=False),
        sa.Column("price_output", MONEY, nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("created_by_platform_user_id", sa.Integer(), sa.ForeignKey("platform_users.id", **DEFER)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ai_price_cards_model", "ai_price_cards", ["model"])
    op.create_table(
        "ai_usage_charges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("ai_usage_events.id", ondelete="CASCADE", **DEFER),
                  nullable=False, unique=True),
        sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id", **DEFER), nullable=False),
        sa.Column("card_id", sa.Integer(), sa.ForeignKey("ai_price_cards.id", **DEFER), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("cost", MONEY, nullable=False),
        sa.Column("price", MONEY, nullable=False),
        sa.Column("priced_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ai_usage_charges_school_id", "ai_usage_charges", ["school_id"])


def downgrade():
    op.drop_table("ai_usage_charges")
    op.drop_table("ai_price_cards")
    op.drop_table("ai_usage_events")
