"""SAAS-025 — Super Admin console, served only on the platform host
(console.manasety.ai). Not to be confused with the `platform` blueprint,
which holds per-school features (rooms, staff attendance, substitutions).

Every route 404s unless the resolver attached kind == "platform" —
so with TENANT_RESOLUTION_MODE=off the whole console is invisible.
"""
from __future__ import annotations

import time

from flask import Blueprint, abort, g, redirect, request, session, url_for
from flask_login import current_user, logout_user

bp = Blueprint("superadmin", __name__, url_prefix="/superadmin",
               template_folder="../../templates/superadmin", cli_group=None)

# Reachable before a full login (password / TOTP steps).
PUBLIC_ENDPOINTS = frozenset({
    "superadmin.login", "superadmin.totp", "superadmin.totp_setup",
})
# Reachable while a password change is being forced.
PASSWORD_CHANGE_ENDPOINTS = frozenset({"superadmin.password", "superadmin.logout"})


def is_platform_request() -> bool:
    t = getattr(g, "tenant_resolved", None)
    return t is not None and t.kind == "platform"


def current_platform_user():
    if getattr(current_user, "is_authenticated", False) and \
            getattr(current_user, "is_platform_user", False):
        return current_user._get_current_object()
    return None


def end_platform_session(revoke_user=None):
    """Clear this browser's console session; with `revoke_user`, also
    kill every other session of that user (bumps session_version)."""
    if revoke_user is not None:
        revoke_user.session_version = (revoke_user.session_version or 1) + 1
        # SAAS-031 security review — and every support session of theirs.
        from ...services.support_policy import end_for_platform_user
        end_for_platform_user(revoke_user.id, "platform_session_revoked")
    logout_user()
    for k in [k for k in session if k.startswith("sa_")]:
        session.pop(k, None)


def require_platform_role(*roles):
    """Allow only these platform roles (403 otherwise). SAAS-036 turns
    this into the full role × route matrix."""
    from functools import wraps

    def deco(view):
        @wraps(view)
        def wrapped(*a, **kw):
            user = current_platform_user()
            if user is None or user.role not in roles:
                abort(403)
            return view(*a, **kw)
        return wrapped
    return deco


@bp.before_request
def _gate():
    if not is_platform_request():
        abort(404)
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None
    user = current_platform_user()
    if user is None:
        return redirect(url_for("superadmin.login"))
    if session.get("sa_ver") != user.session_version:
        # Revoked server-side (logout elsewhere, password / TOTP change).
        end_platform_session()
        return redirect(url_for("superadmin.login"))
    from flask import current_app
    now = time.time()
    idle = current_app.config["PLATFORM_SESSION_MINUTES"] * 60
    max_age = current_app.config["PLATFORM_SESSION_MAX_HOURS"] * 3600
    if now - session.get("sa_seen_at", 0) > idle or now - session.get("sa_login_at", 0) > max_age:
        from ...extensions import db
        from ...services.platform_auth import audit
        audit("session_expired", user)
        db.session.commit()
        end_platform_session()
        return redirect(url_for("superadmin.login"))
    session["sa_seen_at"] = now
    if user.password_changed_at is None and request.endpoint not in PASSWORD_CHANGE_ENDPOINTS:
        return redirect(url_for("superadmin.password"))
    return None


@bp.after_request
def _headers(resp):
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


def install_platform_host_guard(app) -> None:
    """On the platform host (enforce mode) nothing but the console is
    served: the school login page and "/" redirect to the console login,
    every other school route 404s."""
    from ...services.tenancy import resolution_mode

    @app.before_request
    def _platform_host_serves_only_console():
        if not is_platform_request() or resolution_mode() != "enforce":
            return None
        bp_name = request.blueprint
        if bp_name == "superadmin" or request.endpoint in (None, "static"):
            return None
        if request.endpoint in ("auth.login", "index"):
            return redirect(url_for("superadmin.login"))
        abort(404)


from . import auth           # noqa: E402,F401
from . import schools        # noqa: E402,F401
from . import plans          # noqa: E402,F401  SAAS-026
from . import subscriptions  # noqa: E402,F401  SAAS-026
from . import onboarding     # noqa: E402,F401  SAAS-028
from . import modules_limits  # noqa: E402,F401  SAAS-030
from . import support        # noqa: E402,F401  SAAS-031
from . import school_admin    # noqa: E402,F401  SAAS-032
from . import cli            # noqa: E402,F401
