"""SAAS-031 — the school-host side of a support session.

/_support/enter  one-time token → support login (never on the console
                 host, never from inside a support session)
/_support/end    end it and go back to the console
/support/log     the school admin's own list of support visits

install() adds the per-request checks: every request in a support
session re-validates its row, is refused on /api, follows the session's
mode (read-only refuses every write; write mode refuses
FORBIDDEN_ENDPOINTS) and leaves a support_session_events row.
"""
from __future__ import annotations

import logging

from flask import (Blueprint, abort, current_app, g, jsonify, redirect, render_template, request,
                   session, url_for)
from flask_login import current_user, login_required, login_user, logout_user

from ...extensions import db
from ...services import support_policy as sp

bp = Blueprint("support", __name__)
_log = logging.getLogger(__name__)


def _console_url(path: str) -> str:
    hosts = current_app.config.get("PLATFORM_HOSTS") or ["console.manasety.ai"]
    return f"https://{hosts[0]}{path}"


def _school_host_ok(resolved) -> bool:
    return resolved is not None and resolved.school is not None and \
        resolved.kind in ("tenant", "blocked", "suspended")


@bp.route("/_support/enter", methods=["GET"], endpoint="enter")
def enter():
    from ...models import User
    from ...services.platform_auth import audit
    resolved = getattr(g, "tenant_resolved", None)
    if not _school_host_ok(resolved):
        abort(404)                       # console host / unknown host / resolution off
    if sp.is_support_request():
        if sp.why_dead(sp.current_row(), resolved) is None:
            abort(403)                   # no nesting inside a live session
        session.clear()                  # a dead one just goes away
    row = sp.redeem(request.args.get("t") or "", resolved.school.id)
    if row is None:
        # A log line, not an audit row: anyone can hit this URL.
        _log.warning("support enter refused host=%s ip=%s", request.host, request.remote_addr)
        abort(403)
    user = (User.query.execution_options(include_support=True)
            .filter_by(school_id=row.school_id, is_platform_support=True).first())
    if user is None:
        abort(403)
    session.clear()
    login_user(user, remember=False)
    session[sp._SESSION_KEY] = row.id
    audit("support_session_entered", None, school_id=row.school_id, support_session_id=row.id,
          platform_user_id=row.platform_user_id)
    db.session.commit()
    resp = redirect(url_for("dashboard.home"))
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


@bp.route("/_support/end", methods=["POST"], endpoint="end")
def end():
    row = sp.current_row() if sp.is_support_request() else None
    school_id = row.school_id if row is not None else None
    if row is not None:
        sp._end(row, "user")
        db.session.commit()
    logout_user()
    session.clear()
    if school_id is None:
        return redirect(url_for("auth.login"))
    return redirect(_console_url(f"/superadmin/schools/{school_id}"))


@bp.route("/support/log", methods=["GET"], endpoint="log")
@login_required
def support_log():
    """For the school's admin: when platform support visited, how long,
    in which mode and why — no staff names."""
    from ...models import SupportSession
    if getattr(getattr(current_user, "role", None), "name", None) != "admin":
        abort(403)
    rows = (SupportSession.query.filter_by(school_id=current_user.school_id)
            .order_by(SupportSession.id.desc()).limit(200).all())
    return render_template("support_log.html", rows=rows)


# ─── per-request checks ──────────────────────────────────────────────

def _refuse(message, code=403):
    if request.path.startswith("/api/"):
        return jsonify({"error": "support_session_refused", "message_ar": message}), code
    return render_template("errors/support_refused.html", message=message), code


def install(app) -> None:
    from ...services.platform_auth import is_platform_host

    class _StripSupportToken(logging.Filter):
        """The werkzeug access line for /_support/enter carries the token
        in its query string — drop the query before it's written."""

        def filter(self, record):
            msg = record.getMessage() if record.args else str(record.msg)
            if "/_support/enter?" in msg:
                import re
                record.msg = re.sub(r"(/_support/enter)\?\S*", r"\1?[redacted]", msg)
                record.args = ()
            return True
    logging.getLogger("werkzeug").addFilter(_StripSupportToken())

    @app.before_request
    def _support_gate():
        if not sp.is_support_request() or request.endpoint in ("static", "support.enter"):
            return None
        if is_platform_host():
            return None                  # the support cookie only lives on school hosts
        resolved = getattr(g, "tenant_resolved", None)
        row = sp.current_row()
        dead = sp.why_dead(row, resolved)
        if dead is not None:
            if row is not None and row.ended_at is None:
                sp._end(row, dead)
                db.session.commit()
            logout_user()
            session.clear()
            if request.path.startswith("/api/"):
                return jsonify({"error": "unauthorized"}), 401
            return redirect(url_for("auth.login"))
        g.support_session_id = row.id
        g.support_mode = row.mode
        if request.path.startswith("/api/"):
            return _refuse("جلسة الدعم لا تعمل على الـAPI.")
        if request.method in sp.WRITE_METHODS and request.endpoint not in sp.ALWAYS_ALLOWED:
            if row.mode != "write":
                return _refuse("جلسة الدعم للقراءة فقط.")
            body = request.get_json(silent=True) if request.is_json else None
            if request.endpoint in sp.FORBIDDEN_ENDPOINTS or sp.credential_fields(request.form) \
                    or sp.credential_fields(request.args) \
                    or (isinstance(body, dict) and sp.credential_fields(body)):
                return _refuse("هذا الإجراء غير مسموح في جلسات الدعم.")
        if row.mode != "write":
            # GET routes that write anyway are refused, not just logged.
            g.subscription_read_only = True
            g.ro_flush_guard_enforce = True
        return None

    @app.after_request
    def _support_trail(resp):
        sid = g.get("support_session_id")
        if not sid:
            return resp
        try:
            sp.record_event(sid, resp.status_code)
        except Exception:  # noqa: BLE001 — the trail must never break the page
            _log.exception("support trail write failed")
        return resp

    @app.context_processor
    def _support_banner():
        from flask import has_request_context
        if not has_request_context() or not g.get("support_session_id"):
            return {}
        row = sp.current_row()
        return {"support_banner": sp.banner(row)} if row is not None else {}
