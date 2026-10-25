"""Monthly AI token cap per school (ticket E).

The cap: the school's own value (school_limit_overrides) if set, else its
plan's, else none (unlimited) — the same precedence as the other limits,
but counted and checked here, apart from services/limits.py: this is a
flow per month, not a count of things that exist.

Used = total_tokens of the school's successful calls in the current
calendar month (ai_usage.month_bounds, shared with the usage reports).
The check runs before each call; tokens are only known after it, so the
last call (or calls made at the same moment) can go over by its own size:
the cap is approximate by one call. Raising or lowering the cap applies
at once; nothing is deleted.
"""

from __future__ import annotations

from sqlalchemy import func

from ..extensions import db
from .ai_usage import month_bounds

WARN_RATIO = 0.9
LIMIT_MESSAGE = ("وصلت مدرستك للحد الشهري لاستخدام الذكاء الاصطناعي. يتجدد مع بداية الشهر القادم، "
                 "أو تواصل مع الدعم لزيادته.")


def effective_ai_cap(school_id: int) -> tuple[int | None, str | None]:
    """(cap, source) — source "school" / "plan", or (None, None)."""
    from ..models import SchoolLimitOverride
    from .subscriptions import current_subscription
    o = db.session.get(SchoolLimitOverride, school_id)
    if o is not None and o.max_ai_tokens_month is not None:
        return int(o.max_ai_tokens_month), "school"
    sub = current_subscription(school_id)
    plan = sub.plan if sub is not None else None
    if plan is not None and plan.max_ai_tokens_month is not None:
        return int(plan.max_ai_tokens_month), "plan"
    return None, None


def ai_month_used(school_id: int, at=None) -> int:
    from ..models import AIUsageEvent
    start, end = month_bounds(at)
    return int(db.session.query(func.coalesce(func.sum(AIUsageEvent.total_tokens), 0))
               .filter(AIUsageEvent.school_id == school_id, AIUsageEvent.status == "ok",
                       AIUsageEvent.occurred_at >= start, AIUsageEvent.occurred_at < end).scalar() or 0)


def ai_quota_status(school_id: int, at=None) -> dict:
    cap, source = effective_ai_cap(school_id)
    used = ai_month_used(school_id, at)
    ratio = (used / cap) if cap else None
    return {"cap": cap, "source": source, "used": used,
            "remaining": max(0, cap - used) if cap is not None else None,
            "ratio": ratio, "percent": round(ratio * 100) if ratio is not None else None,
            "warn": ratio is not None and ratio >= WARN_RATIO,
            "full": ratio is not None and ratio >= 1}


def parse_cap(raw) -> int | None:
    """A form value: empty → None (the plan's / unlimited); a whole number
    >= 1 → it; anything else → ValueError with the Arabic message."""
    v = (raw or "").strip()
    if not v:
        return None
    if not v.isdigit():
        raise ValueError("الحد الشهري للـ AI لازم رقم صحيح (1 أو أكثر) أو فاضي.")
    n = int(v)
    if n == 0:
        raise ValueError("لإيقاف الـ AI استخدم مفتاح الميزة، لا الحد.")
    if n > 2_000_000_000:
        raise ValueError("الحد الشهري للـ AI كبير جدًا.")
    return n
