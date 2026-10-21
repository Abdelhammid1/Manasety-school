"""SAAS-026 — subscription state, computed at request time.

`effective_state()` is the single, pure (no DB) function every caller
uses — web, API, cron — so they can never disagree. The DB helpers
around it load inputs and record history; a subscription is never
edited in place: every renewal / extension / plan change / trial is a
new row and the previous one stops being current.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from ..extensions import db

# The only states. Do not add more without sign-off; anything unknown
# is treated as blocked.
STATES = ("trial", "active", "grace", "expired", "not_started",
          "no_subscription", "suspended", "archived")
BLOCKED_STATES = frozenset({"expired", "not_started", "no_subscription", "suspended", "archived"})

DEFAULT_SETTINGS = {
    "default_trial_days": "14",
    "default_grace_days": "14",
    "reminder_days": "30,14,7,3,1",
    "support_email": "",
    "support_phone": "",
    "support_whatsapp": "",
    "platform_timezone": "Africa/Cairo",
}


@dataclass(frozen=True)
class SubscriptionState:
    state: str
    days_left: int | None = None
    grace_days_left: int | None = None
    ends_on: date | None = None

    @property
    def read_only(self) -> bool:
        return self.state == "grace"

    @property
    def blocked(self) -> bool:
        return self.state in BLOCKED_STATES or self.state not in STATES


def effective_state(school, subscription, today: date, settings: dict | None = None) -> SubscriptionState:
    """Pure: school.status first (manual lifecycle), then the dates of the
    current subscription. End dates are inclusive."""
    status = getattr(school, "status", None)
    if status == "archived":
        return SubscriptionState("archived")
    if status != "active":
        # suspended — and any unknown status fails closed the same way
        return SubscriptionState("suspended")
    if subscription is None or not getattr(subscription, "is_current", False):
        return SubscriptionState("no_subscription")
    starts, ends = subscription.starts_on, subscription.ends_on
    if today < starts:
        return SubscriptionState("not_started", ends_on=ends)
    trial_end = subscription.trial_ends_on
    if trial_end is not None and today <= trial_end:
        return SubscriptionState("trial", days_left=(trial_end - today).days, ends_on=trial_end)
    if ends is None:
        return SubscriptionState("active")
    if today <= ends:
        return SubscriptionState("active", days_left=(ends - today).days, ends_on=ends)
    grace_end = ends + timedelta(days=int(subscription.grace_days or 0))
    if today <= grace_end:
        return SubscriptionState("grace", grace_days_left=(grace_end - today).days, ends_on=ends)
    return SubscriptionState("expired", ends_on=ends)


# ─── settings / clock ───────────────────────────────────────────────

def get_settings() -> dict:
    from ..models import PlatformSetting
    out = dict(DEFAULT_SETTINGS)
    for row in PlatformSetting.query.all():
        if row.value is not None:
            out[row.key] = row.value
    return out


def platform_today(settings: dict | None = None, now: datetime | None = None) -> date:
    """'Today' in the platform timezone (not UTC)."""
    tz = ZoneInfo((settings or DEFAULT_SETTINGS).get("platform_timezone") or "Africa/Cairo")
    now = now or datetime.now(tz)
    return now.astimezone(tz).date()


def reminder_days(settings: dict) -> list[int]:
    out = []
    for part in (settings.get("reminder_days") or "").split(","):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return sorted(set(out), reverse=True)


# ─── DB helpers ─────────────────────────────────────────────────────

def current_subscription(school_id: int):
    from ..models import SchoolSubscription
    return SchoolSubscription.query.filter_by(school_id=school_id, is_current=True).first()


def school_state(school, today: date | None = None, settings: dict | None = None) -> SubscriptionState:
    settings = settings or get_settings()
    return effective_state(school, current_subscription(school.id),
                           today or platform_today(settings), settings)


def set_school_status(school, status: str) -> None:
    """The only writer of schools.status; keeps the legacy is_active
    column in step. Nothing reads is_active for an access decision."""
    from .tenancy import SCHOOL_STATUSES
    if status not in SCHOOL_STATUSES:
        raise ValueError(f"unknown status {status!r}")
    school.status = status
    school.is_active = status == "active"


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


class SubscriptionError(ValueError):
    """Shown to the console user (Arabic)."""


def _event(school_id, kind, from_value=None, to_value=None, reason=None, user=None):
    from ..models import SchoolSubscriptionEvent
    db.session.add(SchoolSubscriptionEvent(
        school_id=school_id, kind=kind, from_value=from_value, to_value=to_value,
        reason=reason, platform_user_id=getattr(user, "id", None)))


def _replace(school_id, user, **fields):
    """End the current row and insert a new current one (copying unset
    fields from the old one)."""
    from ..models import SchoolSubscription
    old = current_subscription(school_id)
    base = {}
    if old is not None:
        base = {k: getattr(old, k) for k in ("plan_id", "starts_on", "ends_on", "trial_ends_on",
                                              "grace_days", "auto_renew", "notes")}
        old.is_current = False
        db.session.flush()       # the partial unique index allows one current row
    base.update(fields)
    if base.get("ends_on") is not None and base["ends_on"] < base["starts_on"]:
        raise SubscriptionError("تاريخ النهاية لا يمكن أن يسبق تاريخ البداية.")
    new = SchoolSubscription(school_id=school_id, is_current=True,
                             created_by_platform_user_id=getattr(user, "id", None), **base)
    db.session.add(new)
    db.session.flush()
    return old, new


def create_subscription(school, plan, starts_on, ends_on=None, trial_ends_on=None,
                        grace_days=None, user=None, reason=None):
    settings = get_settings()
    grace = int(grace_days if grace_days is not None else settings["default_grace_days"])
    old, new = _replace(school.id, user, plan_id=plan.id, starts_on=starts_on, ends_on=ends_on,
                        trial_ends_on=trial_ends_on, grace_days=grace)
    _event(school.id, "created", None, f"{plan.code}:{starts_on}..{ends_on or '∞'}", reason, user)
    return new


def internal_plan():
    """The unlimited `internal` plan (seeded by the SAAS-026 migration;
    created here for DBs built with create_all — seeds / tests)."""
    from ..models import Plan
    plan = Plan.query.filter_by(code="internal").first()
    if plan is None:
        plan = Plan(code="internal", name_ar="داخلية (بلا حدود)", name_en="Internal (unlimited)",
                    modules=["*"], billing_cycle="custom", trial_days=0, is_active=True)
        db.session.add(plan)
        db.session.flush()
    return plan


def ensure_subscription(school, reason="seed"):
    """Give a school with no current subscription an open-ended internal
    one, so a freshly seeded school isn't locked out by SAAS-027."""
    cur = current_subscription(school.id)
    if cur is not None:
        return cur
    return create_subscription(school, internal_plan(), starts_on=platform_today(get_settings()),
                               reason=reason)


# ─── manual lifecycle (SAAS-027) ─────────────────────────────────────

def bump_auth_epoch(school) -> None:
    """Kill switch: every session / JWT minted before this is refused on
    its next request (SAAS-027)."""
    school.auth_epoch = int(school.auth_epoch or 0) + 1


def suspend_school(school, user, reason: str) -> None:
    if not reason or not reason.strip():
        raise SubscriptionError("سبب الإيقاف مطلوب.")
    if school.status == "suspended":
        raise SubscriptionError("المدرسة موقوفة بالفعل.")
    if school.status == "archived":
        raise SubscriptionError("المدرسة مؤرشفة.")
    prev = school.status
    set_school_status(school, "suspended")
    bump_auth_epoch(school)
    _event(school.id, "suspended", prev, "suspended", reason.strip(), user)
    from .nginx_queue import request_nginx_sync
    request_nginx_sync("school_suspended", school_id=school.id, user=user)


def resume_school(school, user, reason: str) -> None:
    if not reason or not reason.strip():
        raise SubscriptionError("سبب الاستئناف مطلوب.")
    if school.status != "suspended":
        raise SubscriptionError("المدرسة ليست موقوفة.")
    set_school_status(school, "active")
    _event(school.id, "resumed", "suspended", "active", reason.strip(), user)
    from .nginx_queue import request_nginx_sync
    request_nginx_sync("school_resumed", school_id=school.id, user=user)


def renew(school, user, reason, months=None, ends_on=None, today=None):
    """New period starting the day after the current end (or today if the
    subscription already ended)."""
    cur = current_subscription(school.id)
    if cur is None:
        raise SubscriptionError("لا يوجد اشتراك حالي للتجديد.")
    today = today or platform_today(get_settings())
    start = today if (cur.ends_on is None or cur.ends_on < today) else cur.ends_on + timedelta(days=1)
    if months:
        new_end = add_months(start, int(months)) - timedelta(days=1)
    elif ends_on:
        new_end = ends_on
    else:
        raise SubscriptionError("حدد مدة التجديد بالشهور أو تاريخ نهاية جديد.")
    old, new = _replace(school.id, user, starts_on=start, ends_on=new_end, trial_ends_on=None)
    _event(school.id, "renewed", str(cur.ends_on or "∞"), str(new_end), reason, user)
    return new


def extend(school, user, days: int, reason: str):
    cur = current_subscription(school.id)
    if cur is None or cur.ends_on is None:
        raise SubscriptionError("التمديد يحتاج اشتراكًا له تاريخ نهاية.")
    if not reason or not reason.strip():
        raise SubscriptionError("سبب التمديد مطلوب.")
    if int(days) <= 0:
        raise SubscriptionError("عدد الأيام يجب أن يكون موجبًا.")
    new_end = cur.ends_on + timedelta(days=int(days))
    _replace(school.id, user, ends_on=new_end)
    _event(school.id, "extended", str(cur.ends_on), str(new_end), reason.strip(), user)


def change_plan(school, plan, user, reason=None):
    cur = current_subscription(school.id)
    if cur is None:
        raise SubscriptionError("لا يوجد اشتراك حالي.")
    if not plan.is_active:
        raise SubscriptionError("الباقة موقوفة.")
    old_code = cur.plan.code if cur.plan else str(cur.plan_id)
    _replace(school.id, user, plan_id=plan.id)
    _event(school.id, "plan_changed", old_code, plan.code, reason, user)
    # SAAS-030 — module exceptions that now merely repeat the new plan go.
    from .modules import clear_overrides_for_plan_change
    clear_overrides_for_plan_change(school.id)


def start_trial(school, plan, user, days=None, reason=None, today=None):
    settings = get_settings()
    days = int(days if days is not None else settings["default_trial_days"])
    today = today or platform_today(settings)
    trial_end = today + timedelta(days=days - 1)
    _replace(school.id, user, plan_id=plan.id, starts_on=today, ends_on=trial_end,
             trial_ends_on=trial_end)
    _event(school.id, "trial_started", None, str(trial_end), reason, user)


# ─── daily tick (state history + due reminders) ─────────────────────

def last_recorded_state(school_id: int) -> str | None:
    from ..models import SchoolSubscriptionEvent
    row = (SchoolSubscriptionEvent.query
           .filter_by(school_id=school_id, kind="state_changed")
           .order_by(SchoolSubscriptionEvent.id.desc()).first())
    return row.to_value if row else None


def due_reminder(state: SubscriptionState, settings: dict) -> dict | None:
    """What reminder (if any) this state calls for today. Prepared only;
    sending is SAAS-033."""
    if state.state in ("active", "trial") and state.days_left is not None \
            and state.days_left in reminder_days(settings):
        return {"kind": "expiring", "days_left": state.days_left}
    if state.state == "active" and state.days_left == 0:
        return {"kind": "expires_today", "days_left": 0}
    if state.state == "grace" and state.grace_days_left is not None \
            and state.grace_days_left % 3 == 0:
        return {"kind": "grace", "grace_days_left": state.grace_days_left}
    return None


def run_subscriptions_tick(today: date | None = None) -> dict:
    """Record state transitions and list due reminders. Idempotent: a
    second run on the same day writes nothing new."""
    from ..models import School
    from .locks import named_lock
    settings = get_settings()
    today = today or platform_today(settings)
    results = {}
    with named_lock("subscriptions-tick"):
        for sid in [s for (s,) in db.session.query(School.id).order_by(School.id)]:
            try:
                school = db.session.get(School, sid)
                st = effective_state(school, current_subscription(sid), today, settings)
                prev = last_recorded_state(sid)
                if prev != st.state:
                    _event(sid, "state_changed", prev, st.state, f"tick {today.isoformat()}")
                db.session.commit()
                results[sid] = {"status": "ok", "state": st.state, "changed": prev != st.state,
                                "reminder": due_reminder(st, settings)}
            except Exception as e:  # noqa: BLE001
                db.session.rollback()
                from flask import current_app
                current_app.logger.exception("subscriptions-tick failed for school %s", sid)
                results[sid] = {"status": "failed", "error": type(e).__name__}
    return {"today": today.isoformat(), "schools": results}
