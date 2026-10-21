"""SAAS-027 — enforce the subscription state decided by the resolver.

Single decision point: `g.tenant_resolved` (tenancy.resolve_host +
subscriptions.effective_state). This module only reacts to it:

  * blocked (suspended / expired / not_started / no_subscription):
    web → errors/subscription_blocked.html (403, no login form),
    /api → 403 {"error": "subscription_blocked", ...}, /files → 404
  * grace (read_only): any write method is refused except the explicit
    allow-list below; a before_flush guard (SUBSCRIPTION_RO_FLUSH_GUARD,
    log|enforce) catches writes slipping through GET routes
  * kill switch: schools.auth_epoch — sessions and JWTs minted before
    the last bump are dead on their next request

Enforcement runs in TENANT_RESOLUTION_MODE=enforce only (log = observe).
The API error codes are a fixed contract for the mobile apps (SAAS-037).
"""
from __future__ import annotations

import logging

from flask import g, jsonify, render_template, request, session

from ..extensions import db

_log = logging.getLogger(__name__)

# Writes still allowed in read-only (grace): sign in/out and the user's
# own password. Endpoint names — one list, one place.
READ_ONLY_ALLOWED_ENDPOINTS = frozenset({
    "auth.login", "auth.otp", "auth.forgot", "auth.reset", "auth.sso",
    "api.login", "api.change_password", "account.set_password",
    # mobile sign-in / sign-out register and drop the push token
    "api.register_device_token", "api.unregister_device_token",
    # token-authenticated, cross-school; skips blocked schools itself
    "cron.tick",
})
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# Rows that may still change during read-only: login bookkeeping only.
USER_LOGIN_FIELDS = frozenset({"last_login_at", "failed_attempts", "locked_until"})

MESSAGES_AR = {
    "suspended": "حساب المدرسة موقوف مؤقتًا.",
    "expired": "انتهى اشتراك المدرسة.",
    "not_started": "اشتراك المدرسة لم يبدأ بعد.",
    "no_subscription": "لا يوجد اشتراك فعّال للمدرسة.",
    "archived": "هذه المدرسة غير متاحة.",
    "read_only": "اشتراك المدرسة منتهي، والنظام متاح للقراءة فقط حتى التجديد.",
}


def _support(settings):
    return {k: settings.get(k) or "" for k in ("support_email", "support_phone", "support_whatsapp")}


def _is_api():
    return request.path.startswith("/api/")


def _state_name(resolved):
    sub = getattr(resolved, "subscription", None)
    return sub.state if sub is not None else "suspended"


def blocked_response(resolved):
    from .tenancy import _request_settings
    reason = _state_name(resolved)
    if request.endpoint == "static":
        return None          # the blocked page needs its CSS / logo
    if request.path.startswith("/files/"):
        from flask import abort
        abort(404)           # never confirm a file exists
    if _is_api():
        return jsonify({"error": "subscription_blocked", "reason": reason,
                        "message_ar": MESSAGES_AR.get(reason, MESSAGES_AR["suspended"])}), 403
    settings = _request_settings()
    return render_template("errors/subscription_blocked.html", reason=reason,
                           message=MESSAGES_AR.get(reason, MESSAGES_AR["suspended"]),
                           school=resolved.school, support=_support(settings)), 403


def _read_only_response():
    from .tenancy import _request_settings
    if _is_api():
        return jsonify({"error": "subscription_read_only", "reason": "grace",
                        "message_ar": MESSAGES_AR["read_only"]}), 403
    return render_template("errors/subscription_blocked.html", reason="read_only",
                           message=MESSAGES_AR["read_only"], school=None,
                           support=_support(_request_settings()), read_only=True), 403


# ─── kill switch (auth_epoch) ───────────────────────────────────────

def _school_epoch(school_id):
    from ..models import School
    resolved = getattr(g, "tenant_resolved", None)
    school = resolved.school if resolved is not None and resolved.school is not None \
        and resolved.school.id == school_id else db.session.get(School, school_id)
    return int(getattr(school, "auth_epoch", 0) or 0)


def stamp_session_epoch(user) -> None:
    """Call right after a school user's login_user()."""
    sid = getattr(user, "school_id", None)
    if sid is not None:
        session["ae"] = _school_epoch(sid)


def session_epoch_is_stale(user) -> bool:
    sid = getattr(user, "school_id", None)
    if sid is None or getattr(user, "is_platform_user", False):
        return False
    if getattr(user, "is_platform_support", False):
        return False     # SAAS-031: checked against support_sessions instead
    # Sessions from before SAAS-027 carry no epoch: treat as 0 so nobody
    # is logged out at deploy time.
    return int(session.get("ae", 0) or 0) < _school_epoch(sid)


def jwt_epoch_is_stale(payload: dict, user) -> bool:
    return int(payload.get("ae", 0) or 0) < _school_epoch(user.school_id)


def user_school_state(user):
    """Subscription state of the user's OWN school — independent of the
    request host (security review: a token must not dodge the gate by
    being replayed on a host that resolves differently)."""
    from ..models import School
    from .subscriptions import SubscriptionState, current_subscription, effective_state, platform_today
    from .tenancy import _request_settings
    sid = getattr(user, "school_id", None)
    if sid is None:
        return None
    resolved = getattr(g, "tenant_resolved", None)
    sub = getattr(resolved, "subscription", None) if resolved is not None else None
    if sub is not None and resolved.school is not None and resolved.school.id == sid:
        return sub
    school = db.session.get(School, sid)
    if school is None:
        return SubscriptionState("no_subscription")
    settings = _request_settings()
    return effective_state(school, current_subscription(sid), platform_today(settings), settings)


def api_refusal(user):
    """(json, 403) when the bearer's own school may not use the API for
    this request, else None. Enforce mode only, like the host gate."""
    from .tenancy import resolution_mode
    if resolution_mode() != "enforce":
        return None
    st = user_school_state(user)
    if st is None:
        return None
    if st.blocked:
        return jsonify({"error": "subscription_blocked", "reason": st.state,
                        "message_ar": MESSAGES_AR.get(st.state, MESSAGES_AR["suspended"])}), 403
    if st.read_only and request.method in WRITE_METHODS and             request.endpoint not in READ_ONLY_ALLOWED_ENDPOINTS:
        return jsonify({"error": "subscription_read_only", "reason": "grace",
                        "message_ar": MESSAGES_AR["read_only"]}), 403
    return None


# ─── hooks ──────────────────────────────────────────────────────────

def install(app) -> None:
    from sqlalchemy import event
    from .tenancy import resolution_mode

    @app.before_request
    def _subscription_gate():
        resolved = getattr(g, "tenant_resolved", None)
        if resolved is None or resolution_mode() != "enforce" or g.get("tenant_health_ok"):
            return None
        # blocked is answered by the resolver itself (tenancy.init_app)
        if getattr(resolved, "support_bypass", False):
            return None
        if resolved.read_only:
            g.subscription_read_only = True
            if request.method in WRITE_METHODS and \
                    request.endpoint not in READ_ONLY_ALLOWED_ENDPOINTS:
                return _read_only_response()
        return None

    @app.before_request
    def _kill_stale_sessions():
        from flask_login import current_user, logout_user
        if not getattr(current_user, "is_authenticated", False):
            return None
        if session_epoch_is_stale(current_user):
            _log.warning("auth_epoch — closed stale session user=%s", current_user.get_id())
            logout_user()
            session.pop("ae", None)
            from flask import redirect, url_for
            if _is_api():
                return jsonify({"error": "unauthorized"}), 401
            return redirect(url_for("auth.login"))
        return None

    @app.context_processor
    def _subscription_banner():
        from flask import has_request_context
        if not has_request_context():
            return {}               # e-mail / PDF rendering from cron
        return {"subscription_banner": banner_for_request(),
                "limit_warnings": limit_warnings_for_request(),
                "support_notices": support_notices_for_request()}

    if not event.contains(db.session, "before_flush", _read_only_flush_guard):
        event.listen(db.session, "before_flush", _read_only_flush_guard)


def _read_only_flush_guard(session_, _flush_context, _instances):
    """Second line: a GET route that writes during grace. Mode log only
    reports; enforce raises. AuditLog is written outside the ORM."""
    from flask import current_app, has_request_context
    if not has_request_context() or not g.get("subscription_read_only"):
        return
    from ..models import User
    from .tenant_guard import owned_tables
    owned = owned_tables()
    offenders = []
    for obj in list(session_.new) + list(session_.dirty) + list(session_.deleted):
        table = getattr(getattr(obj, "__table__", None), "name", None)
        if table not in owned and table != "users":
            continue
        if isinstance(obj, User) and obj not in session_.new and obj not in session_.deleted:
            from sqlalchemy import inspect
            st = inspect(obj)
            changed = {a.key for a in st.attrs if a.history.has_changes()} if st else set()
            if changed <= USER_LOGIN_FIELDS:
                continue
        offenders.append(table)
    if not offenders:
        return
    mode = (current_app.config.get("SUBSCRIPTION_RO_FLUSH_GUARD") or "log").lower()
    if g.get("ro_flush_guard_enforce"):
        mode = "enforce"          # SAAS-031: read-only support sessions
    msg = f"read-only school write via {request.method} {request.endpoint}: {sorted(set(offenders))}"
    if mode == "enforce":
        raise PermissionError(msg)
    _log.warning("subscription[log] would refuse %s", msg)


# ─── banners ────────────────────────────────────────────────────────

def support_notices_for_request():
    """SAAS-031 — the school admin's in-app notice of recent support
    visits (dashboard only; not shown to support itself)."""
    from flask_login import current_user
    if request.endpoint != "dashboard.home" or not getattr(current_user, "is_authenticated", False)             or getattr(current_user, "is_platform_user", False)             or getattr(current_user, "is_platform_support", False)             or getattr(getattr(current_user, "role", None), "name", None) != "admin":
        return []
    from .support_policy import recent_for_admin
    return recent_for_admin(current_user.school_id)


def limit_warnings_for_request():
    """SAAS-030 — limits at ≥ 90 %, for a school admin on the dashboard
    only (counting storage walks the upload folder)."""
    from flask_login import current_user
    if request.endpoint != "dashboard.home" or not getattr(current_user, "is_authenticated", False)             or getattr(current_user, "is_platform_user", False)             or getattr(getattr(current_user, "role", None), "name", None) != "admin":
        return []
    from .limits import limit_report
    return [r for r in limit_report(current_user.school_id) if r["warn"]]

def banner_for_request():
    """{kind, text} for the school app's base template, or None."""
    from flask_login import current_user
    resolved = getattr(g, "tenant_resolved", None)
    sub = getattr(resolved, "subscription", None) if resolved is not None else None
    if sub is None or not getattr(current_user, "is_authenticated", False):
        return None
    from .subscriptions import reminder_days
    from .tenancy import _request_settings
    settings = _request_settings()
    support = _support(settings)
    if sub.state == "grace":
        until = sub.ends_on and sub.ends_on.isoformat()
        return {"kind": "grace", "support": support,
                "text": f"اشتراك المدرسة منتهي، النظام للقراءة فقط"
                        + (f" (انتهى {until})" if until else "") + ". جدّد الاشتراك لاستعادة كل الصلاحيات."}
    days = reminder_days(settings)
    is_admin = getattr(getattr(current_user, "role", None), "name", None) == "admin"
    if is_admin and sub.days_left is not None and days and sub.days_left <= days[0]:
        return {"kind": "expiring", "support": support,
                "text": f"اشتراك المدرسة ينتهي خلال {sub.days_left} يوم."}
    return None
