"""SAAS-026 — plan management (owner + finance edit, support reads)."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from flask import abort, flash, redirect, render_template, request, url_for

from . import bp, current_platform_user, require_platform_role
from ...extensions import db
from ...models import BILLING_CYCLES, Plan, SchoolSubscription
from ...services import platform_auth as pa

_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
EDIT_ROLES = ("owner", "finance")


def _opt_int(name):
    raw = (request.form.get(name) or "").strip()
    if not raw:
        return None
    if not raw.isdigit():
        raise ValueError(f"{name} يجب أن يكون رقمًا صحيحًا موجبًا.")
    return int(raw)


def _apply_form(plan: Plan):
    plan.name_ar = (request.form.get("name_ar") or "").strip()
    plan.name_en = (request.form.get("name_en") or "").strip() or None
    if not plan.name_ar:
        raise ValueError("اسم الباقة بالعربي مطلوب.")
    plan.max_students = _opt_int("max_students")
    plan.max_users = _opt_int("max_users")
    plan.max_storage_mb = _opt_int("max_storage_mb")
    from ...services.ai_quota import parse_cap
    plan.max_ai_tokens_month = parse_cap(request.form.get("max_ai_tokens_month"))   # ValueError: shown
    plan.trial_days = _opt_int("trial_days") or 0
    cycle = request.form.get("billing_cycle") or "monthly"
    if cycle not in BILLING_CYCLES:
        raise ValueError("دورة فوترة غير معروفة.")
    plan.billing_cycle = cycle
    price = (request.form.get("price_amount") or "").strip()
    try:
        plan.price_amount = Decimal(price) if price else None
    except InvalidOperation:
        raise ValueError("السعر غير صالح.")
    if plan.price_amount is not None and plan.price_amount < 0:
        raise ValueError("السعر لا يمكن أن يكون سالبًا.")
    plan.currency = (request.form.get("currency") or "").strip().upper() or None
    modules = [m.strip() for m in (request.form.get("modules") or "").split(",") if m.strip()]
    from ...services.modules import validate_plan_modules
    plan.modules = validate_plan_modules(modules)


@bp.route("/plans", endpoint="plans")
def plans():
    rows = Plan.query.order_by(Plan.is_active.desc(), Plan.code).all()
    in_use = dict(db.session.query(SchoolSubscription.plan_id, db.func.count(SchoolSubscription.id))
                  .filter(SchoolSubscription.is_current.is_(True))
                  .group_by(SchoolSubscription.plan_id).all())
    user = current_platform_user()
    return render_template("superadmin/plans.html", plans=rows, in_use=in_use,
                           can_edit=user.role in EDIT_ROLES, cycles=BILLING_CYCLES)


@bp.route("/plans/new", methods=["POST"], endpoint="plan_new")
@require_platform_role(*EDIT_ROLES)
def plan_new():
    code = (request.form.get("code") or "").strip().lower()
    if not _CODE_RE.match(code):
        flash("كود الباقة: حروف صغيرة وأرقام وشرطة فقط.", "danger")
        return redirect(url_for("superadmin.plans"))
    if Plan.query.filter_by(code=code).first():
        flash("كود الباقة مستخدم.", "danger")
        return redirect(url_for("superadmin.plans"))
    plan = Plan(code=code, is_active=True)
    try:
        _apply_form(plan)
    except ValueError as e:
        flash(str(e), "danger")
        return redirect(url_for("superadmin.plans"))
    db.session.add(plan)
    db.session.flush()
    pa.audit("plan_created", current_platform_user(), plan=code)
    db.session.commit()
    flash("تم إنشاء الباقة.", "success")
    return redirect(url_for("superadmin.plans"))


@bp.route("/plans/<int:plan_id>/edit", methods=["POST"], endpoint="plan_edit")
@require_platform_role(*EDIT_ROLES)
def plan_edit(plan_id):
    plan = db.session.get(Plan, plan_id) or abort(404)
    try:
        _apply_form(plan)
    except ValueError as e:
        db.session.rollback()
        flash(str(e), "danger")
        return redirect(url_for("superadmin.plans"))
    pa.audit("plan_edited", current_platform_user(), plan=plan.code)
    db.session.commit()
    flash("تم حفظ الباقة.", "success")
    return redirect(url_for("superadmin.plans"))


@bp.route("/plans/<int:plan_id>/toggle", methods=["POST"], endpoint="plan_toggle")
@require_platform_role(*EDIT_ROLES)
def plan_toggle(plan_id):
    plan = db.session.get(Plan, plan_id) or abort(404)
    if plan.is_active:
        used = SchoolSubscription.query.filter_by(plan_id=plan.id, is_current=True).count()
        if used:
            flash(f"لا يمكن إيقاف باقة عليها {used} اشتراك حالي.", "danger")
            return redirect(url_for("superadmin.plans"))
    plan.is_active = not plan.is_active
    pa.audit("plan_toggled", current_platform_user(), plan=plan.code, active=plan.is_active)
    db.session.commit()
    return redirect(url_for("superadmin.plans"))
