"""SAAS-028 — starter data for a newly provisioned school.

Each template is a data-only manifest (see default.py); apply() writes
it for one school, idempotently (a second run inserts nothing), and
every row carries that school's id. The Nafis learning-outcomes catalogue
is global and is never copied.
"""
from __future__ import annotations

from datetime import time

from ...extensions import db


def apply(school_id: int, template: str = "default") -> dict:
    """Insert whatever the template lists that the school doesn't have
    yet. Returns {table: inserted_count}."""
    from importlib import import_module
    from ...models import (Account, BehaviorCategory, Day, GradingScale, GradingScaleLevel,
                           PaymentMethod, Period, Role)
    from ...models.finance import ensure_default_chart, ensure_default_cost_centers
    m = import_module(f"{__name__}.{template}")
    counts: dict[str, int] = {}

    def bump(table):
        counts[table] = counts.get(table, 0) + 1

    for name, name_ar, is_system, perms in m.ROLES:
        if Role.query.filter_by(school_id=school_id, name=name).first() is None:
            db.session.add(Role(school_id=school_id, name=name, name_ar=name_ar,
                                is_system=is_system, permissions=m.role_permissions(perms)))
            bump("roles")

    before = Account.query.filter_by(school_id=school_id).count()
    ensure_default_chart(school_id)
    ensure_default_cost_centers(school_id)
    db.session.flush()
    counts["accounts"] = Account.query.filter_by(school_id=school_id).count() - before

    for order, name in enumerate(m.DAYS, start=1):
        if Day.query.filter_by(school_id=school_id, order_index=order).first() is None:
            db.session.add(Day(school_id=school_id, name=name, order_index=order, is_active=True))
            bump("days")

    for order, (name, start, end, is_break) in enumerate(m.PERIODS, start=1):
        if Period.query.filter_by(school_id=school_id, order_index=order).first() is None:
            sh, sm = start
            eh, em = end
            db.session.add(Period(school_id=school_id, name=name, order_index=order,
                                  start_time=time(sh, sm), end_time=time(eh, em),
                                  is_break=is_break, duration_minutes=(eh * 60 + em) - (sh * 60 + sm)))
            bump("periods")

    for name, kind, account_role in m.PAYMENT_METHODS:
        if PaymentMethod.query.filter_by(school_id=school_id, name=name).first() is None:
            acct = Account.query.filter_by(school_id=school_id, account_role=account_role).first() \
                if account_role else None
            db.session.add(PaymentMethod(school_id=school_id, name=name, kind=kind,
                                         account_id=acct.id if acct else None))
            bump("payment_methods")

    for name, kind, points, severity in m.BEHAVIOR_CATEGORIES:
        if BehaviorCategory.query.filter_by(school_id=school_id, name=name).first() is None:
            db.session.add(BehaviorCategory(school_id=school_id, name=name, kind=kind,
                                            default_points=points, severity=severity))
            bump("behavior_categories")

    scale_name, levels = m.GRADING_SCALE
    if GradingScale.query.filter_by(school_id=school_id, name=scale_name).first() is None:
        scale = GradingScale(school_id=school_id, name=scale_name, scale_type="numeric",
                             is_default=True)
        db.session.add(scale)
        db.session.flush()
        for order, (label, lo, hi, passing) in enumerate(levels):
            db.session.add(GradingScaleLevel(scale_id=scale.id, label=label, min_score=lo,
                                             max_score=hi, is_passing=passing, order_index=order))
        bump("grading_scales")
    db.session.flush()
    return counts
