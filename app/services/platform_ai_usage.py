"""AI usage across schools, for the console (ticket D): price cards, the
pricing of calls that had no card yet, and cost / price / profit per
school and for the platform. Every cross-school read goes through
platform_read_scope (SAAS-025); only platform tables are written.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import func

from ..extensions import db
from .ai_usage import OPERATION_LABELS, amounts, card_for, month_bounds
from .platform_scope import platform_read_scope

CARD_FIELDS = ("cost_hit", "cost_miss", "cost_output", "price_hit", "price_miss", "price_output")
CARD_LABELS = {"cost_hit": "تكلفة الإدخال (cache hit)", "cost_miss": "تكلفة الإدخال (cache miss)",
               "cost_output": "تكلفة الإخراج", "price_hit": "سعر الإدخال (cache hit)",
               "price_miss": "سعر الإدخال (cache miss)", "price_output": "سعر الإخراج"}


class CardError(ValueError):
    pass


def add_card(form, user):
    """A new price card. Never edits an old one: a later effective_from
    takes over from that moment, and calls already priced keep their amounts."""
    from ..models import AIPriceCard
    model = (form.get("model") or "").strip()
    currency = (form.get("currency") or "").strip().upper()
    if not model or len(model) > 64:
        raise CardError("اسم الموديل مطلوب (حتى 64 حرف).")
    if not currency or len(currency) > 8:
        raise CardError("العملة مطلوبة (حتى 8 حروف).")
    values = {}
    for f in CARD_FIELDS:
        try:
            v = Decimal((form.get(f) or "").strip())
        except (InvalidOperation, ValueError):
            raise CardError(f"{CARD_LABELS[f]}: رقم مطلوب.") from None
        if not v.is_finite() or v < 0:
            raise CardError(f"{CARD_LABELS[f]}: لازم صفر أو أكثر.")
        values[f] = v
    raw_from = (form.get("effective_from") or "").strip()
    if raw_from:
        try:
            eff = datetime.fromisoformat(raw_from)
        except ValueError:
            raise CardError("تاريخ السريان غير صحيح.") from None
        eff = eff if eff.tzinfo else eff.replace(tzinfo=timezone.utc)
    else:
        eff = datetime.now(timezone.utc)
    card = AIPriceCard(model=model, currency=currency, effective_from=eff,
                       note=(form.get("note") or "").strip() or None,
                       created_by_platform_user_id=getattr(user, "id", None), **values)
    db.session.add(card)
    from .platform_auth import audit
    db.session.flush()
    audit("ai_price_card_added", user, card_id=card.id, model=model, currency=currency,
          effective_from=eff.isoformat(), **{k: str(v) for k, v in values.items()})
    return card


def cards():
    from ..models import AIPriceCard
    return AIPriceCard.query.order_by(AIPriceCard.model, AIPriceCard.effective_from.desc()).all()


def price_pending(user) -> int:
    """Price every successful call that has no charge yet and now has a
    card in effect at its time. Already-priced calls never change."""
    from ..models import AIUsageCharge, AIUsageEvent
    e, ch = AIUsageEvent, AIUsageCharge
    n = 0
    with platform_read_scope("ai_usage_priced", user):
        rows = (db.session.query(e).outerjoin(ch, ch.event_id == e.id)
                .filter(ch.id.is_(None), e.status == "ok").order_by(e.id).all())
        conn = db.session.connection()
        now = datetime.now(timezone.utc)
        for ev in rows:
            at = ev.occurred_at if ev.occurred_at.tzinfo else ev.occurred_at.replace(tzinfo=timezone.utc)
            card = card_for(conn, ev.model, at)
            if card is None:
                continue
            cost, price = amounts(card, {"prompt_cache_hit_tokens": ev.prompt_cache_hit_tokens,
                                         "prompt_cache_miss_tokens": ev.prompt_cache_miss_tokens,
                                         "completion_tokens": ev.completion_tokens})
            db.session.add(AIUsageCharge(event_id=ev.id, school_id=ev.school_id, card_id=card.id,
                                         currency=card.currency, cost=cost, price=price, priced_at=now))
            n += 1
        db.session.flush()
    return n


def _usage_rows(start, end, school_id=None):
    """(school_id, currency|None, calls, tokens, cost, price, unpriced) for the window."""
    from ..models import AIUsageCharge, AIUsageEvent
    from sqlalchemy import and_, case
    e, ch = AIUsageEvent, AIUsageCharge
    q = (db.session.query(e.school_id, ch.currency, func.count(e.id),
                          func.coalesce(func.sum(e.total_tokens), 0),
                          func.coalesce(func.sum(ch.cost), 0), func.coalesce(func.sum(ch.price), 0),
                          func.sum(case((and_(ch.id.is_(None), e.status == "ok"), 1), else_=0)))
         .outerjoin(ch, ch.event_id == e.id)
         .filter(e.occurred_at >= start, e.occurred_at < end))
    if school_id is not None:
        q = q.filter(e.school_id == school_id)
    return q.group_by(e.school_id, ch.currency).all()


def _fold(rows):
    """{school_id: {"calls", "tokens", "unpriced", "money": {currency: {cost, price, profit}}}}"""
    out: dict = {}
    for sid, currency, calls, tokens, cost, price, unpriced in rows:
        r = out.setdefault(sid, {"calls": 0, "tokens": 0, "unpriced": 0, "money": {}})
        r["calls"] += calls
        r["tokens"] += int(tokens)
        r["unpriced"] += int(unpriced or 0)
        if currency:
            m = r["money"].setdefault(currency, {"cost": Decimal(0), "price": Decimal(0)})
            m["cost"] += Decimal(cost)
            m["price"] += Decimal(price)
    for r in out.values():
        for m in r["money"].values():
            m["profit"] = m["price"] - m["cost"]
    return out


def overview(user, month_at=None) -> dict:
    """Every school with usage this month, and the platform's total."""
    from ..models import School
    start, end = month_bounds(month_at)
    from .ai_quota import ai_quota_status
    from .modules import feature_enabled
    this_month = month_bounds()[0] == start
    with platform_read_scope("ai_usage_overview", user, month=start.isoformat()):
        per = _fold(_usage_rows(start, end))
        schools = School.query.filter(School.status != "archived").all()
        ai_on = {sc.id for sc in schools if feature_enabled(sc.id, "lms.ai")}
        for sid in ai_on:                          # AI open with no use yet: still listed
            per.setdefault(sid, {"calls": 0, "tokens": 0, "unpriced": 0, "money": {}})
        names = {sc.id: sc.name for sc in schools}
        names.update({sc.id: sc.name for sc in School.query.filter(School.id.in_(list(per) or [-1]))})
        for sid, r in per.items():
            q = ai_quota_status(sid, start)
            r["cap"], r["cap_source"] = q["cap"], q["source"]
            r["percent"] = round(r["tokens"] / q["cap"] * 100) if q["cap"] else None
            r["warn"] = r["percent"] is not None and r["percent"] >= 90
            r["ai_on"] = sid in ai_on
            r["open_no_cap"] = r["ai_on"] and q["cap"] is None and this_month
    total = {"calls": 0, "tokens": 0, "unpriced": 0, "money": {}}
    for r in per.values():
        for k in ("calls", "tokens", "unpriced"):
            total[k] += r[k]
        for cur, m in r["money"].items():
            t = total["money"].setdefault(cur, {"cost": Decimal(0), "price": Decimal(0), "profit": Decimal(0)})
            for k in ("cost", "price", "profit"):
                t[k] += m[k]
    rows = [{"school_id": sid, "name": names.get(sid, f"#{sid}"), **r}
            for sid, r in sorted(per.items(), key=lambda kv: -kv[1]["tokens"])]
    return {"start": start, "end": end, "rows": rows, "total": total}


def school_usage(user, school_id: int, month_at=None) -> dict:
    """One school's month for its console page: totals, money and the
    split by operation."""
    from ..models import AIUsageEvent
    start, end = month_bounds(month_at)
    from .ai_quota import ai_quota_status
    with platform_read_scope("ai_usage_school", user, school_id=school_id, month=start.isoformat()):
        quota = ai_quota_status(school_id, start)
        r = _fold(_usage_rows(start, end, school_id)).get(school_id,
                                                           {"calls": 0, "tokens": 0, "unpriced": 0, "money": {}})
        ops = (db.session.query(AIUsageEvent.operation, func.count(AIUsageEvent.id),
                                func.coalesce(func.sum(AIUsageEvent.total_tokens), 0))
               .filter(AIUsageEvent.school_id == school_id, AIUsageEvent.occurred_at >= start,
                       AIUsageEvent.occurred_at < end)
               .group_by(AIUsageEvent.operation).all())
    return {"start": start, "end": end, **r, "quota": quota,
            "operations": [{"label": OPERATION_LABELS.get(op, op), "calls": c, "tokens": int(t)}
                           for op, c, t in sorted(ops, key=lambda x: -x[2])]}
