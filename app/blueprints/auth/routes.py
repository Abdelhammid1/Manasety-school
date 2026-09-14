from datetime import datetime, timedelta

from flask import current_app, flash, redirect, render_template, request, session, url_for
from flask_login import login_required, login_user, logout_user

from . import bp
from ...extensions import db
from ...models import User


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        user = User.query.filter_by(username=username).first()

        if not user or not user.is_active:
            flash("بيانات الدخول غير صحيحة.", "danger")
            return render_template("auth/login.html"), 401

        if user.is_locked():
            remaining = int((user.locked_until - datetime.utcnow()).total_seconds() // 60) + 1
            flash(f"تم قفل الحساب مؤقتًا. حاول بعد {remaining} دقيقة.", "warning")
            return render_template("auth/login.html"), 423

        if not user.check_password(password):
            user.failed_attempts += 1
            max_attempts = current_app.config["LOCKOUT_MAX_ATTEMPTS"]
            if user.failed_attempts >= max_attempts:
                user.locked_until = datetime.utcnow() + timedelta(
                    minutes=current_app.config["LOCKOUT_MINUTES"]
                )
                user.failed_attempts = 0
                flash("تم قفل الحساب بعد عدة محاولات فاشلة.", "danger")
            else:
                flash("بيانات الدخول غير صحيحة.", "danger")
            db.session.commit()
            return render_template("auth/login.html"), 401

        user.failed_attempts = 0
        user.locked_until = None
        user.last_login_at = datetime.utcnow()
        db.session.commit()
        login_user(user, remember=bool(request.form.get("remember")))
        return redirect(url_for("dashboard.home"))

    return render_template("auth/login.html")


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("تم تسجيل الخروج بنجاح.", "success")
    return redirect(url_for("auth.login"))


# --- Password recovery flow ---------------------------------------------------
# Real routes so the login page's "forgot password" link works. The delivery
# side (email/SMS) is stubbed: the code is generated + kept in the session and
# shown to the user via a dev-mode flash. Wire a real provider in
# services/notifications.py when SMTP/SMS credentials are configured.

def _gen_otp() -> str:
    import secrets
    return f"{secrets.randbelow(1000000):06d}"


@bp.route("/forgot", methods=["GET", "POST"])
def forgot():
    if request.method == "POST":
        channel = request.form.get("channel", "email")
        target = (request.form.get("target") or "").strip()
        if not target:
            flash("يرجى إدخال البريد الإلكتروني أو رقم الجوال.", "danger")
            return render_template("auth/forgot.html", channel=channel)
        # Anti-enumeration: always advance to OTP even if no user matched.
        user = None
        if "@" in target:
            user = User.query.filter_by(email=target).first()
        else:
            user = (User.query.filter_by(phone=target).first()
                    or User.query.filter_by(username=target).first())
        code = _gen_otp()
        session["otp_code"] = code
        session["otp_target"] = target
        session["otp_channel"] = channel
        session["otp_expires_at"] = (datetime.utcnow() + timedelta(minutes=5)).isoformat()
        session["otp_user_id"] = user.id if user else 0
        # DEV: surface the code so QA can complete the flow without an SMTP.
        if current_app.debug or current_app.config.get("WHATSAPP_PROVIDER") == "stub":
            flash(f"[وضع التطوير] رمز التحقق: {code}", "info")
        return redirect(url_for("auth.otp"))
    return render_template("auth/forgot.html", channel="email")


@bp.route("/otp", methods=["GET", "POST"])
def otp():
    if "otp_code" not in session:
        return redirect(url_for("auth.forgot"))
    if request.method == "POST":
        entered = "".join([request.form.get(f"d{i}", "") for i in range(1, 7)]) or \
                  request.form.get("code", "")
        entered = entered.strip()
        exp = session.get("otp_expires_at")
        expired = exp and datetime.fromisoformat(exp) < datetime.utcnow()
        if expired:
            flash("انتهت صلاحية الرمز. أعد الطلب.", "warning")
            return redirect(url_for("auth.forgot"))
        if entered != session.get("otp_code"):
            flash("الرمز غير صحيح.", "danger")
            return render_template("auth/otp.html"), 400
        session["otp_verified"] = True
        return redirect(url_for("auth.reset"))
    return render_template("auth/otp.html")


@bp.route("/reset", methods=["GET", "POST"])
def reset():
    if not session.get("otp_verified"):
        return redirect(url_for("auth.forgot"))
    if request.method == "POST":
        pw = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""
        if len(pw) < 8:
            flash("كلمة المرور يجب أن تحتوي على 8 أحرف على الأقل.", "danger")
            return render_template("auth/reset.html"), 400
        if pw != confirm:
            flash("كلمتا المرور غير متطابقتين.", "danger")
            return render_template("auth/reset.html"), 400
        uid = session.get("otp_user_id")
        if uid:
            u = db.session.get(User, uid)
            if u:
                u.set_password(pw)
                u.failed_attempts = 0
                u.locked_until = None
                db.session.commit()
                flash("تم تغيير كلمة المرور. سجّل الدخول الآن.", "success")
        for k in ("otp_code", "otp_target", "otp_channel", "otp_expires_at",
                  "otp_user_id", "otp_verified"):
            session.pop(k, None)
        return redirect(url_for("auth.login"))
    return render_template("auth/reset.html")


@bp.route("/locked")
def locked():
    """Standalone lockout screen; used when we prefer a focus view over a flash."""
    return render_template("auth/locked.html"), 423


@bp.route("/sso", methods=["POST"])
def sso():
    """SSO handoff placeholder. Real providers plug in here once we hold their
    client_id/secret; for now surface a clear "not configured" flash so the
    button is honest, not silent.
    """
    provider = (request.form.get("provider") or "").strip()
    label = {"nafath": "النفاذ الوطني الموحد", "microsoft": "مايكروسوفت 365"}.get(provider, provider)
    flash(f"مزود الدخول ({label}) لم يُفعّل بعد على هذه المدرسة. راجع مدير النظام.", "warning")
    return redirect(url_for("auth.login"))
