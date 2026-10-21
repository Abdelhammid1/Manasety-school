"""SAAS-028 — the 5-step "new school" wizard (owner only).

The wizard's answers live in the console session between steps, so
going back never loses a field; every step is validated server-side.
The final POST carries a one-time nonce: a second click (or a refresh)
can't create a second school. The setup link is rendered once in that
response and stored nowhere.
"""
from __future__ import annotations

import secrets
import threading
import time
from collections import deque
from datetime import date

from flask import (abort, current_app, flash, jsonify, make_response, redirect, render_template,
                   request, session, url_for)

from . import bp, current_platform_user, require_platform_role
from ...models import Plan
from ...services import provisioning as prov
from ...services import subscriptions as subs

STEPS = ("school", "settings", "subscription", "admin", "review")
_KEY = "sa_wizard"
_NONCE = "sa_wizard_nonce"

FIELDS = {
    "school": ("name", "name_en", "slug", "phone", "email", "address"),
    "settings": ("currency", "currency_symbol", "fiscal_year_start_month", "invoice_prefix",
                 "default_tax_rate", "attendance_mode"),
    "subscription": ("plan_id", "starts_on", "term", "months", "ends_on", "trial_days"),
    "admin": ("admin_full_name", "admin_email", "admin_phone", "admin_username"),
}
DEFAULTS = {"currency": "EGP", "currency_symbol": "ج.م", "fiscal_year_start_month": "9",
            "invoice_prefix": "INV", "default_tax_rate": "0", "attendance_mode": "daily",
            "term": "months", "months": "12", "admin_username": "admin"}

# Live slug check: per platform user, at most N lookups a minute.
SLUG_CHECKS_PER_MINUTE = 30
_slug_hits: dict[int, deque] = {}
_slug_lock = threading.Lock()


def _data() -> dict:
    return dict(session.get(_KEY) or {})


def _save(data: dict) -> None:
    session[_KEY] = data


def _int(raw, field, msg):
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        raise prov.ProvisionError(msg, field) from None


def _date(raw, field):
    try:
        return date.fromisoformat(str(raw).strip())
    except (TypeError, ValueError):
        raise prov.ProvisionError("تاريخ غير صحيح.", field) from None


def build_spec(d: dict) -> prov.ProvisionSpec:
    """Wizard answers → ProvisionSpec (type conversion only; rules are in
    provisioning.validate_spec)."""
    term = d.get("term") or "months"
    try:
        tax = float(str(d.get("default_tax_rate") or "0").strip())
    except ValueError:
        raise prov.ProvisionError("نسبة الضريبة غير صحيحة.", "default_tax_rate") from None
    return prov.ProvisionSpec(
        name=(d.get("name") or "").strip(), name_en=(d.get("name_en") or "").strip(),
        slug=(d.get("slug") or "").strip(), phone=(d.get("phone") or "").strip(),
        email=(d.get("email") or "").strip(), address=(d.get("address") or "").strip(),
        currency=(d.get("currency") or "").strip().upper(),
        currency_symbol=(d.get("currency_symbol") or "").strip(),
        fiscal_year_start_month=_int(d.get("fiscal_year_start_month") or 9,
                                     "fiscal_year_start_month", "شهر غير صحيح."),
        invoice_prefix=(d.get("invoice_prefix") or "").strip(), default_tax_rate=tax,
        attendance_mode=d.get("attendance_mode") or "daily",
        plan_id=_int(d.get("plan_id") or 0, "plan_id", "اختر باقة."),
        starts_on=_date(d.get("starts_on") or subs.platform_today(subs.get_settings()).isoformat(),
                        "starts_on"),
        months=_int(d.get("months"), "months", "مدة غير صحيحة.") if term == "months" else None,
        ends_on=_date(d.get("ends_on"), "ends_on") if term == "ends_on" else None,
        trial_days=_int(d.get("trial_days"), "trial_days", "مدة غير صحيحة.") if term == "trial" else None,
        admin_full_name=(d.get("admin_full_name") or "").strip(),
        admin_email=(d.get("admin_email") or "").strip(),
        admin_phone=(d.get("admin_phone") or "").strip(),
        admin_username=(d.get("admin_username") or "").strip(),
    )


def _check_step(step: str, d: dict) -> None:
    """Validate the fields owned by `step` (raises ProvisionError)."""
    if step == "school":
        if not (d.get("name") or "").strip():
            raise prov.ProvisionError("اسم المدرسة مطلوب.", "name")
        ok, msg = prov.slug_available(d.get("slug"))
        if not ok:
            raise prov.ProvisionError(msg, "slug")
        d["slug"] = msg
        if d.get("email") and "@" not in d["email"]:
            raise prov.ProvisionError("إيميل المدرسة غير صحيح.", "email")
        return
    spec = build_spec({**DEFAULTS, **d})
    try:
        prov.validate_spec(spec)
    except prov.ProvisionError as e:
        owner = next((s for s, f in FIELDS.items() if e.field in f), None)
        # Only report errors of this step or an earlier one.
        if owner is None or STEPS.index(owner) <= STEPS.index(step):
            raise


def _render(step, d, error=None):
    plans = Plan.query.filter_by(is_active=True).order_by(Plan.code).all()
    today = subs.platform_today(subs.get_settings()).isoformat()
    shown = {**DEFAULTS, "starts_on": today, **{k: v for k, v in d.items() if v not in (None, "")}}
    return render_template("superadmin/onboarding.html", step=step, steps=STEPS, d=shown,
                           error=error, plans=plans,
                           base_domain=current_app.config.get("BASE_DOMAIN") or "manasety.ai")


@bp.route("/schools/new", methods=["GET"], endpoint="school_new")
@require_platform_role("owner")
def school_new():
    if request.args.get("reset"):
        session.pop(_KEY, None)
    step = request.args.get("step") or "school"
    if step not in STEPS:
        abort(404)
    d = _data()
    # Can't jump ahead of the first step that hasn't been completed.
    done = d.get("_done") or []
    for s in STEPS[:STEPS.index(step)]:
        if s not in done:
            return redirect(url_for("superadmin.school_new", step=s))
    if step == "review":
        session[_NONCE] = secrets.token_urlsafe(16)
    return _render(step, d)


@bp.route("/schools/new/<step>", methods=["POST"], endpoint="school_new_step")
@require_platform_role("owner")
def school_new_step(step):
    if step not in STEPS[:-1]:
        abort(404)
    d = _data()
    for f in FIELDS[step]:
        d[f] = (request.form.get(f) or "").strip()
    _save(d)                                   # going back keeps what was typed
    if request.form.get("nav") == "back":
        prev = STEPS[max(STEPS.index(step) - 1, 0)]
        return redirect(url_for("superadmin.school_new", step=prev))
    try:
        _check_step(step, d)
    except prov.ProvisionError as e:
        return _render(step, d, error=e), 400
    done = [s for s in (d.get("_done") or []) if STEPS.index(s) < STEPS.index(step)]
    d["_done"] = done + [step]
    _save(d)
    return redirect(url_for("superadmin.school_new", step=STEPS[STEPS.index(step) + 1]))


@bp.route("/schools/new/create", methods=["POST"], endpoint="school_create")
@require_platform_role("owner")
def school_create():
    nonce = session.pop(_NONCE, None)
    if not nonce or not secrets.compare_digest(nonce, request.form.get("nonce") or ""):
        # Second click / refresh / stale tab: never a second school. (A
    # replayed cookie still carrying the nonce is stopped by the slug's
    # uniqueness — provision_school refuses an existing slug.)
        flash("تم تنفيذ طلب الإنشاء بالفعل أو انتهت صلاحية النموذج.", "warning")
        return redirect(url_for("superadmin.schools"))
    d = _data()
    try:
        spec = build_spec({**DEFAULTS, **d})
        result = prov.provision_school(spec, current_platform_user())
    except prov.ProvisionError as e:
        session[_NONCE] = secrets.token_urlsafe(16)
        return _render("review", d, error=e), 400
    session.pop(_KEY, None)
    r = make_response(render_template("superadmin/onboarding_result.html", result=result))
    r.headers["Cache-Control"] = "no-store"
    return r


@bp.route("/schools/slug-check", methods=["GET"], endpoint="slug_check")
@require_platform_role("owner")
def slug_check():
    user = current_platform_user()
    if user is None:
        abort(403)
    now = time.monotonic()
    with _slug_lock:
        q = _slug_hits.setdefault(user.id, deque())
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= SLUG_CHECKS_PER_MINUTE:
            return jsonify(ok=False, message="محاولات كثيرة، انتظر دقيقة."), 429
        q.append(now)
    ok, msg = prov.slug_available(request.args.get("slug"))
    return jsonify(ok=ok, message=(f"«{msg}» متاح." if ok else msg), slug=msg if ok else None)
