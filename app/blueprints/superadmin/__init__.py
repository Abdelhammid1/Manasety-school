"""SAAS-025 — Super Admin console, served only on the platform host
(console.manasety.ai). Not to be confused with the `platform` blueprint,
which holds per-school features (rooms, staff attendance, substitutions).

Every route 404s unless the resolver attached kind == "platform" —
so with TENANT_RESOLUTION_MODE=off the whole console is invisible.
"""
from __future__ import annotations

import time

from flask import Blueprint, abort, g, redirect, render_template, request, session, url_for
from flask_login import current_user, logout_user

bp = Blueprint("superadmin", __name__, url_prefix="/superadmin",
               template_folder="../../templates/superadmin", cli_group=None)

# Reachable before a full login (password / TOTP steps).
PUBLIC_ENDPOINTS = frozenset({
    "superadmin.login", "superadmin.totp", "superadmin.totp_setup",
    "superadmin.setup",                                   # SAAS-036 one-time link
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
    sid = session.get("sa_sid")
    if sid:
        from ...services.platform_security import utcnow as _now
        from ...models import PlatformSession as _PS
        from ...extensions import db as _db
        row = _db.session.get(_PS, sid)
        if row is not None and row.revoked_at is None:
            row.revoked_at = _now()
    if revoke_user is not None:
        from ...services.platform_security import revoke_sessions
        revoke_sessions(revoke_user.id)
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
    # SAAS-036 — optional IP allow-list: outside it the console doesn't exist
    from ...services.platform_security import ip_allowed
    if not ip_allowed(request.remote_addr):
        abort(404)
    from ...services import platform_permissions as perms
    if request.endpoint not in perms.ROUTES:
        abort(404)                       # fail closed: an unlisted route isn't served
    # past the host, IP allow-list and route checks: from here on an error
    # may show the console's own page (before this the console must not exist)
    g.console_gate_passed = True
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None
    user = current_platform_user()
    if user is None:
        return redirect(url_for("superadmin.login"))
    from ...services.platform_security import check_session
    if session.get("sa_ver") != user.session_version or not check_session(user):
        # Revoked server-side (logout elsewhere, password / TOTP change).
        from ...extensions import db
        end_platform_session()
        db.session.commit()
        return redirect(url_for("superadmin.login"))
    from flask import current_app
    now = time.time()
    idle = current_app.config["PLATFORM_SESSION_MINUTES"] * 60
    max_age = current_app.config["PLATFORM_SESSION_MAX_HOURS"] * 3600
    if now - session.get("sa_seen_at", 0) > idle or now - session.get("sa_login_at", 0) > max_age:
        from ...extensions import db
        from ...services.platform_auth import audit
        audit("session_expired", user)
        end_platform_session()          # marks the server-side row revoked …
        db.session.commit()             # … and keeps it so
        return redirect(url_for("superadmin.login"))
    session["sa_seen_at"] = now
    if user.password_changed_at is None and request.endpoint not in PASSWORD_CHANGE_ENDPOINTS:
        return redirect(url_for("superadmin.password"))
    # SAAS-036 — the one role × route matrix (services/platform_permissions.py)
    if not perms.allowed(request.endpoint, request.method, user.role):
        abort(403)
    return None


@bp.app_context_processor
def _csp_nonce():
    """SAAS-036 — every inline <script> in the console carries this nonce."""
    import secrets
    if "csp_nonce" not in g:
        g.csp_nonce = secrets.token_urlsafe(16)
    return {"csp_nonce": g.csp_nonce}


# Console errors get the console's own self-contained page: the shared
# school error page loads web fonts / an icon font the console CSP blocks
# (icons showed as text). 404 stays the shared page on purpose — the
# console must look like any unknown path from outside.
def _request_id() -> str:
    """Short id shown on the error page and written to the log line, so a
    screenshot can be matched to the log (SAAS-044)."""
    # always ours: a client-sent X-Request-ID would let anyone write
    # arbitrary text into the log line (security review)
    if "request_id" not in g:
        import secrets
        g.request_id = secrets.token_hex(6)
    return g.request_id


_SHARED = {403: ("غير مصرّح", "لا تملك صلاحية الوصول إلى هذه الصفحة."),
           404: ("الصفحة غير موجودة", "تعذّر العثور على ما تبحث عنه."),
           500: ("خطأ داخلي", "حدث خطأ في الخادم. تواصل مع الدعم الفنّي.")}


def _console_error(code, title, msg):
    if not g.get("console_gate_passed"):
        # school host, an IP outside the allow-list, or an unlisted route:
        # exactly the app-wide page, no console page and no request id
        t, m = _SHARED[code]
        return render_template("errors/error.html", code=code, title=t, msg=m), code
    rid = _request_id()
    resp = render_template("superadmin/error.html", code=code, title=title, msg=msg, request_id=rid)
    return resp, code, {"X-Request-ID": rid}


@bp.errorhandler(403)
def _console_403(_e):
    return _console_error(403, "غير مسموح", "دورك في اللوحة لا يسمح بهذه الصفحة.")


@bp.errorhandler(404)
def _console_404(_e):
    # the gate's own 404s (school host, IP outside the allow-list, unlisted
    # route) stay the shared page — see _console_error
    return _console_error(404, "الصفحة مش موجودة", "الرابط ده مش موجود في اللوحة.")


@bp.errorhandler(500)
def _console_500(e):
    from flask import current_app
    from ...extensions import db
    rid = _request_id()
    current_app.logger.error("console 500 request_id=%s path=%s", rid, request.path,
                             exc_info=getattr(e, "original_exception", None) or e)
    try:
        db.session.rollback()          # the failed request may have left a broken transaction
    except Exception:  # noqa: BLE001
        pass
    return _console_error(500, "حصل خطأ",
                          "حصل خطأ غير متوقع في اللوحة واتسجّل. جرّب تاني، ولو اتكرر بلّغ الفريق التقني.")


@bp.after_request
def _headers(resp):
    from flask import current_app
    import secrets
    nonce = g.get("csp_nonce") or secrets.token_urlsafe(16)
    base = current_app.config.get("BASE_DOMAIN") or "manasety.ai"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; "
        "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
        # the support hand-off posts here and lands on a school host
        f"form-action 'self' https://*.{base}")
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "same-origin"
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
from . import billing         # noqa: E402,F401  SAAS-033
from . import monitoring      # noqa: E402,F401  SAAS-034
from . import offboarding     # noqa: E402,F401  SAAS-035
from . import app_card        # noqa: E402,F401  SAAS-037
from . import seed_cli        # noqa: E402,F401  SAAS-041
from . import users           # noqa: E402,F401  SAAS-036
from . import cli            # noqa: E402,F401
