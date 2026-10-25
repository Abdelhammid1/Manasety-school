"""AI usage metering (ticket D).

  * AIUsageEvent (tenant table) — one row per DeepSeek call: school, user,
    operation, model, status and the three token counts. Never the
    question, the answer or any prompt text.
  * AIPriceCard (platform) — what a model costs us and what we charge,
    per 1,000,000 tokens in each of DeepSeek's three classes. A card is
    never edited: a new card with a later `effective_from` takes over.
  * AIUsageCharge (platform) — the cost and price of one call, from the
    card in effect when it happened. Deleted with its event (cascade).
"""

from datetime import datetime, timezone

from ..extensions import db


def _utcnow():
    return datetime.now(timezone.utc)


AI_OPERATIONS = ("generate_similar", "rewrite_question", "suggest_blueprint", "review_pending",
                 "grade_free_form", "summarize_exam")


class AIUsageEvent(db.Model):
    __tablename__ = "ai_usage_events"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    operation = db.Column(db.String(32), nullable=False)
    model = db.Column(db.String(64), nullable=False)
    status = db.Column(db.String(8), nullable=False, default="ok")        # ok | error
    prompt_cache_hit_tokens = db.Column(db.Integer, nullable=False, default=0)
    prompt_cache_miss_tokens = db.Column(db.Integer, nullable=False, default=0)
    completion_tokens = db.Column(db.Integer, nullable=False, default=0)
    total_tokens = db.Column(db.Integer, nullable=False, default=0)
    occurred_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (db.Index("ix_ai_usage_events_school_occurred", "school_id", "occurred_at"),)


class AIPriceCard(db.Model):
    __tablename__ = "ai_price_cards"

    id = db.Column(db.Integer, primary_key=True)
    model = db.Column(db.String(64), nullable=False, index=True)
    currency = db.Column(db.String(8), nullable=False)
    # per 1,000,000 tokens — what DeepSeek charges us …
    cost_hit = db.Column(db.Numeric(18, 8), nullable=False)
    cost_miss = db.Column(db.Numeric(18, 8), nullable=False)
    cost_output = db.Column(db.Numeric(18, 8), nullable=False)
    # … and what we charge the school
    price_hit = db.Column(db.Numeric(18, 8), nullable=False)
    price_miss = db.Column(db.Numeric(18, 8), nullable=False)
    price_output = db.Column(db.Numeric(18, 8), nullable=False)
    effective_from = db.Column(db.DateTime(timezone=True), nullable=False)
    note = db.Column(db.Text)
    created_by_platform_user_id = db.Column(db.Integer, db.ForeignKey("platform_users.id"))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)


class AIUsageCharge(db.Model):
    __tablename__ = "ai_usage_charges"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("ai_usage_events.id", ondelete="CASCADE"),
                         nullable=False, unique=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    card_id = db.Column(db.Integer, db.ForeignKey("ai_price_cards.id"), nullable=False)
    currency = db.Column(db.String(8), nullable=False)
    cost = db.Column(db.Numeric(18, 8), nullable=False)
    price = db.Column(db.Numeric(18, 8), nullable=False)
    priced_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)
