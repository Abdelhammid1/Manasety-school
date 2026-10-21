"""SAAS-025 — console login: email + password, then mandatory TOTP.

First login forces TOTP enrolment (QR + confirm) and shows 10 one-time
recovery codes once. Accounts created by the CLI must change their
password right after the first login.
"""
from __future__ import annotations

import time
from datetime import timedelta

from flask import current_app, flash, redirect, render_template, request, session, url_for
from flask_login import login_user

from . import bp, current_platform_user, end_platform_session
from ...extensions import db
from ...models import PlatformUser
from ...services import platform_auth as pa

PENDING_TTL = 300   # seconds between password step and TOTP step
PENDING_MAX_TOTP_FAILS = 3   # then the password step must be passed again
GENERIC_FAIL = "بيانات الدخول غير صحيحة."


def _pending_user():
    data = session.get("sa_pending") or {}
    if not data or time.time() - data.get("at", 0) > PENDING_TTL:
        session.pop("sa_pending", None)
        return None
    user = db.session.get(PlatformUser, data.get("uid"))
    return user if user is not None and user.is_active else None


def _register_failure(user, reason):
    if user is not None and not user.is_locked():
        # An expired lock starts a fresh count; attempts made WHILE locked
        # neither count nor extend the lock (no lock-forever by anyone).
        if user.locked_until is not None:
            user.failed_attempts = 0
            user.locked_until = None
        user.failed_attempts = (user.failed_attempts or 0) + 1
        if user.failed_attempts >= current_app.config["LOCKOUT_MAX_ATTEMPTS"]:
            user.locked_until = pa.utcnow() + timedelta(minutes=current_app.config["LOCKOUT_MINUTES"])
            pa.audit("login_locked", user)
    pa.audit("login_failed", user, reason=reason)
    db.session.commit()


def _pending_guard(user):
    """Second-step gate: a locked account or throttled IP can't keep
    guessing TOTP codes on an already-passed password step."""
    if user.is_locked() or pa.ip_is_throttled():
        session.pop("sa_pending", None)
        flash(GENERIC_FAIL, "danger")
        return redirect(url_for("superadmin.login"))
    return None


def _totp_failed(user, step):
    pa.audit("totp_failed", user, step=step)
    _register_failure(user, "totp")
    data = session.get("sa_pending") or {}
    data["fails"] = data.get("fails", 0) + 1
    if data["fails"] >= PENDING_MAX_TOTP_FAILS:
        session.pop("sa_pending", None)
        flash(GENERIC_FAIL, "danger")
        return redirect(url_for("superadmin.login"))
    session["sa_pending"] = data
    return None


def _complete_login(user):
    session.pop("sa_pending", None)
    user.failed_attempts = 0
    user.locked_until = None
    user.last_login_at = pa.utcnow()
    login_user(user, remember=False)
    session["sa_ver"] = user.session_version or 1
    now = time.time()
    session["sa_login_at"] = now
    session["sa_seen_at"] = now
    session["sa_totp_at"] = now
    from ...services.platform_security import open_session
    open_session(user)                       # SAAS-036 server-side session row
    pa.audit("login_success", user)
    db.session.commit()


@bp.route("/login", methods=["GET", "POST"], endpoint="login")
def login():
    if current_platform_user() is not None:
        return redirect(url_for("superadmin.schools"))
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        if pa.ip_is_throttled():
            pa.audit("login_throttled", None)
            db.session.commit()
            flash("محاولات كثيرة من هذا العنوان. حاول لاحقًا.", "danger")
            return render_template("superadmin/login.html"), 429
        user = PlatformUser.query.filter_by(email=email).first() if email else None
        if user is None:
            pa.dummy_password_check(password)
            _register_failure(None, "unknown")
            flash(GENERIC_FAIL, "danger")
            return render_template("superadmin/login.html"), 401
        password_ok = user.check_password(password)   # always: same timing on every branch
        if not user.is_active or user.is_locked() or not password_ok:
            _register_failure(user, "inactive" if not user.is_active
                              else "locked" if user.is_locked() else "password")
            flash(GENERIC_FAIL, "danger")
            return render_template("superadmin/login.html"), 401
        session["sa_pending"] = {"uid": user.id, "at": time.time()}
        if not user.totp_enabled:
            return redirect(url_for("superadmin.totp_setup"))
        return redirect(url_for("superadmin.totp"))
    return render_template("superadmin/login.html")


@bp.route("/login/totp", methods=["GET", "POST"], endpoint="totp")
def totp():
    user = _pending_user()
    if user is None:
        return redirect(url_for("superadmin.login"))
    if not user.totp_enabled:
        return redirect(url_for("superadmin.totp_setup"))
    blocked = _pending_guard(user)
    if blocked is not None:
        return blocked
    if request.method == "POST":
        code = (request.form.get("code") or "").strip()
        recovery = (request.form.get("recovery_code") or "").strip()
        ok = False
        if code:
            ok = pa.verify_totp(pa.decrypt(user.totp_secret_encrypted), code, user=user)
        elif recovery:
            ok = pa.use_recovery_code(user, recovery)
            if ok:
                pa.audit("recovery_code_used", user)
        if not ok:
            gone = _totp_failed(user, "login")
            if gone is not None:
                return gone
            flash("الرمز غير صحيح.", "danger")
            return render_template("superadmin/totp.html"), 401
        _complete_login(user)
        return redirect(url_for("superadmin.schools"))
    return render_template("superadmin/totp.html")


@bp.route("/login/totp/setup", methods=["GET", "POST"], endpoint="totp_setup")
def totp_setup():
    user = _pending_user()
    if user is None:
        return redirect(url_for("superadmin.login"))
    if user.totp_enabled:
        return redirect(url_for("superadmin.totp"))
    blocked = _pending_guard(user)
    if blocked is not None:
        return blocked
    secret = pa.decrypt(user.totp_secret_encrypted)
    if not secret:
        # Pending seed lives encrypted in the DB, never in the (signed,
        # readable) session cookie.
        secret = pa.new_totp_secret()
        user.totp_secret_encrypted = pa.encrypt(secret)
        db.session.commit()
    if request.method == "POST":
        if not pa.verify_totp(secret, request.form.get("code"), user=user):
            gone = _totp_failed(user, "setup")
            if gone is not None:
                return gone
            flash("الرمز غير صحيح، تأكد من وقت جهازك وحاول تاني.", "danger")
        else:
            user.totp_enabled = True
            user.session_version = (user.session_version or 1) + 1   # old sessions die
            codes = pa.issue_recovery_codes(user)
            pa.audit("totp_enabled", user)
            _complete_login(user)
            # Shown exactly once, never stored in clear.
            return render_template("superadmin/recovery_codes.html", codes=codes)
    qr = pa.qr_svg(pa.provisioning_uri(secret, user.email))
    return render_template("superadmin/totp_setup.html", qr=qr, secret=secret)


@bp.route("/logout", methods=["POST"], endpoint="logout")
def logout():
    user = current_platform_user()
    if user is not None:
        pa.audit("logout", user)
        # SAAS-031 — logging out of the console ends any support session.
        from ...services.support_policy import end_for_platform_user
        end_for_platform_user(user.id, "platform_logout")
        end_platform_session(revoke_user=user)
        db.session.commit()
    else:
        end_platform_session()
    return redirect(url_for("superadmin.login"))


@bp.route("/password", methods=["GET", "POST"], endpoint="password")
def password():
    user = current_platform_user()
    assert user is not None   # _gate() guarantees a logged-in platform user
    forced = user.password_changed_at is None
    if request.method == "POST":
        current = request.form.get("current_password") or ""
        new = request.form.get("new_password") or ""
        confirm = request.form.get("confirm_password") or ""
        problem = pa.password_problem(new)
        bad_credentials = not user.check_password(current)
        if bad_credentials:
            problem = "كلمة المرور الحالية أو رمز التحقق غير صحيح."
        elif new != confirm:
            problem = "كلمتا المرور غير متطابقتين."
        elif new == current:
            problem = "اختر كلمة مرور مختلفة عن الحالية."
        # TOTP last: a request rejected for another reason must not burn
        # the code (it can be used only once).
        if problem is None and not pa.verify_totp(
                pa.decrypt(user.totp_secret_encrypted), request.form.get("code"), user=user):
            problem = "كلمة المرور الحالية أو رمز التحقق غير صحيح."
            bad_credentials = True
        if problem:
            if bad_credentials and not user.is_locked():
                user.failed_attempts = (user.failed_attempts or 0) + 1
                if user.failed_attempts >= current_app.config["LOCKOUT_MAX_ATTEMPTS"]:
                    user.locked_until = pa.utcnow() + timedelta(minutes=current_app.config["LOCKOUT_MINUTES"])
                    pa.audit("login_locked", user)
            pa.audit("password_change_failed", user)
            db.session.commit()
            flash(problem, "danger")
            return render_template("superadmin/password.html", forced=forced), 400
        user.set_password(new)
        user.password_changed_at = pa.utcnow()
        # Every other session of this user dies; this one carries on.
        user.session_version = (user.session_version or 1) + 1
        session["sa_ver"] = user.session_version
        from ...services.platform_security import revoke_sessions
        revoke_sessions(user.id, except_sid=session.get("sa_sid"))
        pa.audit("password_changed", user)
        db.session.commit()
        flash("تم تغيير كلمة المرور.", "success")
        return redirect(url_for("superadmin.schools"))
    return render_template("superadmin/password.html", forced=forced)
