"""AI usage metering (ticket D): record every DeepSeek call, price it, and
report a school's own usage.

record_call() writes on its own connection — outside the request's
transaction and the ORM tenant guard — with an explicit school_id, so a
call is billed even when the page's own work is rolled back, and a
failure to write never takes the AI answer away from the user (it is
logged as an ERROR). Nothing of the prompt or the answer is stored.

A call is priced with the card in effect when it happened (the newest
card for its model whose effective_from is not after the call). A call
without a card stays "بدون تسعيرة" until price_pending() runs after a card
is added; an already-priced call never changes.

The school's own report (school_month_report) shows tokens and what WE
CHARGE — never our cost or margin.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import and_, case, func, select

from ..extensions import db

log = logging.getLogger(__name__)
PER = Decimal(1_000_000)
Q8 = Decimal("0.00000001")

OPERATION_LABELS = {
    "generate_similar": "توليد أسئلة مشابهة",
    "rewrite_question": "إعادة صياغة سؤال",
    "suggest_blueprint": "اقتراح توزيع اختبار",
    "review_pending": "مراجعة ذكية لبنك الأسئلة",
    "grade_free_form": "تصحيح إجابة مقالية",
    "summarize_exam": "تحليل نتائج اختبار",
}


# ─── the month (shared with the monthly cap, ticket E) ──────────────

def month_bounds(at: datetime | None = None, tz_name: str | None = None) -> tuple[datetime, datetime]:
    """[start, end) of the calendar month of `at` in the platform's time
    zone, as UTC datetimes. The one definition both the usage reports and
    the monthly cap use."""
    from zoneinfo import ZoneInfo
    if tz_name is None:
        try:
            from .subscriptions import get_settings
            tz_name = get_settings().get("platform_timezone") or "Africa/Cairo"
        except Exception:  # noqa: BLE001 — a report must not fail on a setting
            tz_name = "Africa/Cairo"
    tz = ZoneInfo(tz_name)
    at = (at or datetime.now(timezone.utc))
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    local = at.astimezone(tz)
    start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def parse_month(raw: str | None) -> datetime:
    """'YYYY-MM' → a moment inside that month (UTC); this month otherwise."""
    try:
        y, m = (int(x) for x in (raw or "").split("-"))
        return datetime(y, m, 15, tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


# ─── recording ──────────────────────────────────────────────────────

def tokens_from(usage) -> dict:
    """The three billed classes (+ total) from DeepSeek's `usage` object."""
    u = usage if isinstance(usage, dict) else {}

    def n(key):
        try:
            return max(0, int(u.get(key) or 0))
        except (TypeError, ValueError):
            return 0
    hit = n("prompt_cache_hit_tokens")
    miss = n("prompt_cache_miss_tokens")
    if not hit and not miss and n("prompt_tokens"):
        miss = n("prompt_tokens")                 # no cache split reported: all billed as a miss
    out = n("completion_tokens")
    total = n("total_tokens") or (hit + miss + out)
    return {"prompt_cache_hit_tokens": hit, "prompt_cache_miss_tokens": miss,
            "completion_tokens": out, "total_tokens": total}


def record_call(*, school_id: int, user_id: int | None, operation: str, model: str,
                status: str, usage=None, at: datetime | None = None) -> int | None:
    """One row for one call (ok or error), priced if a card exists. Never
    raises: a failure is logged and the caller carries on."""
    from ..models import AIUsageEvent
    t = tokens_from(usage) if status == "ok" else tokens_from(None)
    at = at or datetime.now(timezone.utc)
    try:
        with db.engine.begin() as conn:
            event_id = conn.execute(AIUsageEvent.__table__.insert().values(
                school_id=int(school_id), user_id=user_id, operation=operation[:32], model=(model or "")[:64],
                status=status, occurred_at=at, **t)).inserted_primary_key[0]
            if status == "ok":
                _price(conn, event_id, int(school_id), model, at, t)
        return event_id
    except Exception:  # noqa: BLE001 — billing must never break the AI answer
        log.exception("AI usage: could not record the call (school=%s, user=%s, op=%s)",
                      school_id, user_id, operation)
        return None


def card_for(conn, model: str, at: datetime):
    from ..models import AIPriceCard
    c = AIPriceCard.__table__.c
    return conn.execute(select(AIPriceCard.__table__)
                        .where(c.model == model, c.effective_from <= at)
                        .order_by(c.effective_from.desc(), c.id.desc()).limit(1)).first()


def amounts(card, t: dict) -> tuple[Decimal, Decimal]:
    """(cost, price) of a call: Σ tokens × price-per-million / 1,000,000, 8 places."""
    hit, miss, out = (Decimal(t["prompt_cache_hit_tokens"]), Decimal(t["prompt_cache_miss_tokens"]),
                      Decimal(t["completion_tokens"]))
    cost = (hit * Decimal(card.cost_hit) + miss * Decimal(card.cost_miss) + out * Decimal(card.cost_output)) / PER
    price = (hit * Decimal(card.price_hit) + miss * Decimal(card.price_miss)
             + out * Decimal(card.price_output)) / PER
    return cost.quantize(Q8, ROUND_HALF_UP), price.quantize(Q8, ROUND_HALF_UP)


def _price(conn, event_id, school_id, model, at, t) -> bool:
    from ..models import AIUsageCharge
    card = card_for(conn, model, at)
    if card is None:
        return False
    cost, price = amounts(card, t)
    conn.execute(AIUsageCharge.__table__.insert().values(
        event_id=event_id, school_id=school_id, card_id=card.id, currency=card.currency,
        cost=cost, price=price, priced_at=datetime.now(timezone.utc)))
    return True


# ─── the school's own report (no cost, no margin) ───────────────────

def school_month_report(school_id: int, month_at: datetime | None = None) -> dict:
    """This school's month: calls, tokens and what it is charged, per user
    and per operation. Read in the school's own scope."""
    from ..models import AIUsageCharge, AIUsageEvent, User
    start, end = month_bounds(month_at)
    e, ch = AIUsageEvent, AIUsageCharge
    base = (db.session.query(e.user_id, e.operation, e.status,
                             func.count(e.id), func.coalesce(func.sum(e.total_tokens), 0),
                             ch.currency, func.coalesce(func.sum(ch.price), 0),
                             func.sum(case((and_(ch.id.is_(None), e.status == "ok"), 1), else_=0)))
            .outerjoin(ch, ch.event_id == e.id)
            .filter(e.school_id == school_id, e.occurred_at >= start, e.occurred_at < end)
            .group_by(e.user_id, e.operation, e.status, ch.currency))
    users: dict = {}
    ops: dict = {}
    totals = {"calls": 0, "errors": 0, "tokens": 0, "amounts": {}, "unpriced": 0}
    for user_id, op, status, calls, tokens, currency, price, unpriced in base.all():
        u = users.setdefault(user_id, {"user_id": user_id, "calls": 0, "tokens": 0, "amounts": {}})
        o = ops.setdefault(op, {"operation": op, "label": OPERATION_LABELS.get(op, op), "calls": 0, "tokens": 0})
        for row in (u, o):
            row["calls"] += calls
            row["tokens"] += int(tokens)
        totals["calls"] += calls
        totals["tokens"] += int(tokens)
        if status == "error":
            totals["errors"] += calls
        totals["unpriced"] += int(unpriced or 0)
        if currency:
            u["amounts"][currency] = u["amounts"].get(currency, Decimal(0)) + Decimal(price)
            totals["amounts"][currency] = totals["amounts"].get(currency, Decimal(0)) + Decimal(price)
    names = {}
    ids = [i for i in users if i]
    if ids:
        names = {u.id: (u.full_name or u.username) for u in
                 User.query.filter(User.school_id == school_id, User.id.in_(ids))}
    for uid, row in users.items():
        row["name"] = names.get(uid, "مستخدم محذوف") if uid else "—"
    return {"start": start, "end": end, "totals": totals,
            "users": sorted(users.values(), key=lambda r: -r["tokens"]),
            "operations": sorted(ops.values(), key=lambda r: -r["tokens"])}
