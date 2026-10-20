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
GENERIC_FAIL = "بيانات الدخول غير صحيحة."


def _pending_user():
    data = session.get("sa_pending") or {}
    if not data or time.time() - data.get("at", 0) > PENDING_TTL:
        session.pop("sa_pending", None)
        return None
    user = db.session.get(PlatformUser, data.get("uid"))
    return user if user is not None and user.is_active else None


def _register_failure(user, reason):
    if user is not None:
        user.failed_attempts = (user.failed_attempts or 0) + 1
        if user.failed_attempts >= current_app.config["LOCKOUT_MAX_ATTEMPTS"]:
            user.locked_until = pa.utcnow() + timedelta(minutes=current_app.config["LOCKOUT_MINUTES"])
            pa.audit("login_locked", user)
    pa.audit("login_failed", user, reason=reason)
    db.session.commit()


def _complete_login(user):
    session.pop("sa_pending", None)
    user.failed_attempts = 0
    user.locked_until = None
    user.last_login_at = pa.utcnow()
    login_user(user, remember=False)
    now = time.time()
    session["sa_login_at"] = now
    session["sa_seen_at"] = now
    session["sa_totp_at"] = now
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
        if not user.is_active or user.is_locked() or not user.check_password(password):
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
    if request.method == "POST":
        code = (request.form.get("code") or "").strip()
        recovery = (request.form.get("recovery_code") or "").strip()
        ok = False
        if code:
            ok = pa.verify_totp(pa.decrypt(user.totp_secret_encrypted), code)
        elif recovery:
            ok = pa.use_recovery_code(user, recovery)
            if ok:
                pa.audit("recovery_code_used", user)
        if not ok:
            pa.audit("totp_failed", user)
            _register_failure(user, "totp")
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
    secret = pa.decrypt(user.totp_secret_encrypted)
    if not secret:
        # Pending seed lives encrypted in the DB, never in the (signed,
        # readable) session cookie.
        secret = pa.new_totp_secret()
        user.totp_secret_encrypted = pa.encrypt(secret)
        db.session.commit()
    if request.method == "POST":
        if not pa.verify_totp(secret, request.form.get("code")):
            pa.audit("totp_failed", user, step="setup")
            db.session.commit()
            flash("الرمز غير صحيح، تأكد من وقت جهازك وحاول تاني.", "danger")
        else:
            user.totp_enabled = True
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
        db.session.commit()
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
        if not user.check_password(current):
            problem = "كلمة المرور الحالية غير صحيحة."
        elif not pa.verify_totp(pa.decrypt(user.totp_secret_encrypted), request.form.get("code")):
            problem = "رمز التحقق غير صحيح."
        elif new != confirm:
            problem = "كلمتا المرور غير متطابقتين."
        elif new == current:
            problem = "اختر كلمة مرور مختلفة عن الحالية."
        if problem:
            pa.audit("password_change_failed", user)
            db.session.commit()
            flash(problem, "danger")
            return render_template("superadmin/password.html", forced=forced), 400
        user.set_password(new)
        user.password_changed_at = pa.utcnow()
        pa.audit("password_changed", user)
        db.session.commit()
        flash("تم تغيير كلمة المرور.", "success")
        return redirect(url_for("superadmin.schools"))
    return render_template("superadmin/password.html", forced=forced)
