from datetime import datetime, timedelta

from flask import current_app, flash, redirect, render_template, request, url_for
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
        login_user(user)
        return redirect(url_for("dashboard.home"))

    return render_template("auth/login.html")


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("تم تسجيل الخروج بنجاح.", "success")
    return redirect(url_for("auth.login"))
