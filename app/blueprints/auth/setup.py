"""SAAS-028 — /set-password/<token>: the provisioned admin's one-time
"choose your password" link, served on the school's own host.

The token is looked up by hash only. The first GET moves it into the
session and redirects to the clean URL /set-password, so the raw token
stays out of the browser history, the Referer header and any log line
after that first request.
"""
from datetime import datetime

from flask import Blueprint, flash, g, make_response, redirect, render_template, request, session, url_for

from ...extensions import db

bp = Blueprint("account", __name__, template_folder="../../templates/auth")

MIN_PASSWORD = 10
_SESSION_KEY = "setup_token_hash"


def _valid_token(token_hash):
    """The live token row for this host's school, or None."""
    from ...models import AccountSetupToken
    if not token_hash:
        return None
    row = AccountSetupToken.query.filter_by(token_hash=token_hash).first()
    if row is None or row.used_at is not None or row.expires_at < datetime.utcnow():
        return None
    user = row.user
    if user is None or not user.is_active:
        return None
    resolved = getattr(g, "tenant_resolved", None)
    # Only on the user's own school host. With resolution off (single-
    # tenant dev) there is no host tenant to compare against.
    if resolved is not None and (resolved.kind != "tenant" or resolved.school is None
                                 or int(resolved.school.id) != int(user.school_id)):
        return None
    return row


def _no_store(resp, status=None):
    resp = make_response(resp) if status is None else make_response(resp, status)
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


@bp.route("/set-password/<token>", methods=["GET"])
def set_password_link(token):
    from ...services.provisioning import hash_token
    h = hash_token(token)
    if _valid_token(h) is None:
        return _no_store(render_template("set_password.html", invalid=True), 404)
    session[_SESSION_KEY] = h
    return _no_store(redirect(url_for("account.set_password")))


@bp.route("/set-password", methods=["GET", "POST"])
def set_password():
    from ...models import AccountSetupToken
    row = _valid_token(session.get(_SESSION_KEY))
    if row is None:
        session.pop(_SESSION_KEY, None)
        return _no_store(render_template("set_password.html", invalid=True), 404)
    if request.method == "POST":
        pw = request.form.get("password") or ""
        if len(pw) < MIN_PASSWORD:
            flash(f"كلمة المرور يجب ألا تقل عن {MIN_PASSWORD} أحرف.", "danger")
        elif pw != (request.form.get("confirm") or ""):
            flash("كلمتا المرور غير متطابقتين.", "danger")
        else:
            user = row.user
            user.set_password(pw)
            user.failed_attempts = 0
            user.locked_until = None
            now = datetime.utcnow()
            # This token and every other outstanding one for the user die.
            AccountSetupToken.query.filter(AccountSetupToken.user_id == user.id,
                                           AccountSetupToken.used_at.is_(None)) \
                .update({"used_at": now}, synchronize_session=False)
            db.session.commit()
            session.pop(_SESSION_KEY, None)
            flash("تم ضبط كلمة المرور. سجّل الدخول الآن.", "success")
            return _no_store(redirect(url_for("auth.login")))
    return _no_store(render_template("set_password.html", invalid=False,
                                     username=row.user.username, min_len=MIN_PASSWORD))
