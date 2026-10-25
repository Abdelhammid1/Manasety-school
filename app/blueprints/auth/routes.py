from datetime import datetime, timedelta

from flask import current_app, flash, g, redirect, render_template, request, session, url_for
from flask_login import login_required, login_user, logout_user

from . import bp
from ...extensions import db
from ...models import User


_VALID_ROLE_HINTS = {"student", "teacher", "parent", "admin"}


def _render_login(status: int = 200):
    """Playwright-tour fix (2026-10-02) — preserve role_hint and
    username across a failed submit so the user doesn't have to
    re-pick the tab and re-type their username on every retry."""
    role_hint = (request.form.get("role_hint") or "student").strip()
    if role_hint not in _VALID_ROLE_HINTS:
        role_hint = "student"
    username = (request.form.get("username") or "").strip()
    return render_template(
        "auth/login.html",
        role_hint=role_hint, prev_username=username,
    ), status


def _request_tenant():
    """SAAS-006 — the tenant the host resolver attached to this
    request, or None if resolution is in `off` mode. Everything
    tenant-scoped in this file branches on this one call so the
    off / log / enforce transition is uniform.

    Returns the ResolvedTenant instance (kind in {tenant, platform,
    unknown, suspended, malformed}) or None."""
    return getattr(g, "tenant_resolved", None)


def _lookup_user_for_login(username: str) -> User | None:
    """SAAS-006 — scope the user lookup to the tenant of the request
    whenever one is set. Pre-SAAS-004 (resolution off) this falls
    back to the global lookup so the dev DB with a single tenant
    keeps working."""
    tenant = _request_tenant()
    if tenant is not None and tenant.kind == "tenant" and tenant.school is not None:
        return (
            User.query
            .filter_by(school_id=tenant.school.id, username=username)
            .first()
        )
    # Resolution off → preserve legacy single-tenant behaviour.
    return User.query.filter_by(username=username).first()


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        # SAAS-006 — the platform host (lms.manasety.ai) does NOT
        # accept school-user logins. Super-admin login lives in a
        # separate Epic; for now, point school users at their
        # own subdomain so a password submitted here can't match a
        # school admin by accident.
        # SAAS-024 — only `enforce` blocks; `log` is observe-only and
        # keeps the pre-SAAS behaviour so ops can watch before flipping.
        tenant = _request_tenant()
        if tenant is not None and tenant.kind == "platform":
            from ...services.tenancy import resolution_mode
            if resolution_mode() == "enforce":
                # SAAS-025 — the platform host is the Super Admin console.
                return redirect(url_for("superadmin.login"))
            current_app.logger.warning(
                "tenancy[log] would reject platform login host=%r", request.host)

        user = _lookup_user_for_login(username)

        from ...services import audit as _audit
        if not user or not user.is_active:
            if user:                                    # an unknown name has nobody to attribute
                _audit.record_login_event(user, _audit.LOGIN_FAILED, "web", "inactive")
                db.session.commit()
            flash("بيانات الدخول غير صحيحة.", "danger")
            return _render_login(401)

        if user.is_locked():
            _audit.record_login_event(user, _audit.LOGIN_FAILED, "web", "locked")
            db.session.commit()
            remaining = int((user.locked_until - datetime.utcnow()).total_seconds() // 60) + 1
            flash(f"تم قفل الحساب مؤقتًا. حاول بعد {remaining} دقيقة.", "warning")
            return _render_login(423)

        if not user.check_password(password):
            user.failed_attempts += 1
            max_attempts = current_app.config["LOCKOUT_MAX_ATTEMPTS"]
            if user.failed_attempts >= max_attempts:
                user.locked_until = datetime.utcnow() + timedelta(
                    minutes=current_app.config["LOCKOUT_MINUTES"]
                )
                user.failed_attempts = 0
                _audit.record_login_event(user, _audit.LOGIN_LOCKED, "web")
                flash("تم قفل الحساب بعد عدة محاولات فاشلة.", "danger")
            else:
                _audit.record_login_event(user, _audit.LOGIN_FAILED, "web", "password")
                flash("بيانات الدخول غير صحيحة.", "danger")
            db.session.commit()
            return _render_login(401)

        user.failed_attempts = 0
        user.locked_until = None
        user.last_login_at = datetime.utcnow()
        _audit.record_login_event(user, _audit.LOGIN_OK, "web")
        db.session.commit()
        login_user(user, remember=bool(request.form.get("remember")))
        from ...services.subscription_enforcement import stamp_session_epoch
        stamp_session_epoch(user)
        return redirect(url_for("dashboard.home"))

    return render_template(
        "auth/login.html",
        role_hint="student", prev_username="",
    )


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
        #
        # SAAS-006 — scope every candidate lookup to the current
        # tenant when one is resolved. email / phone have no unique
        # index at the DB level, so a bare `.first()` could pick an
        # account in another school and silently send ITS OTP via
        # ITS SMTP settings. Reject multi-match within the same
        # tenant too — never choose arbitrarily.
        tenant = _request_tenant()
        user = None
        base_q = User.query
        if tenant is not None and tenant.kind == "tenant" and tenant.school is not None:
            base_q = base_q.filter_by(school_id=tenant.school.id)

        def _one_or_none(q):
            """Return the single match or None if 0/many."""
            rows = q.limit(2).all()
            if len(rows) == 1:
                return rows[0]
            if len(rows) > 1:
                current_app.logger.warning(
                    "OTP ambiguous — multiple users share identifier "
                    "within tenant; refusing to pick."
                )
            return None

        if "@" in target:
            user = _one_or_none(base_q.filter_by(email=target))
        else:
            user = _one_or_none(base_q.filter_by(phone=target))
            if user is None:
                user = _one_or_none(base_q.filter_by(username=target))
        code = _gen_otp()
        session["otp_code"] = code
        session["otp_target"] = target
        session["otp_channel"] = channel
        session["otp_expires_at"] = (datetime.utcnow() + timedelta(minutes=5)).isoformat()
        session["otp_user_id"] = user.id if user else 0

        # Ticket "SMTP per school + email channel" — try to actually send
        # the OTP via the school's SMTP when the channel is email + we
        # resolved a user + the school has SMTP configured. Fall back to
        # the dev-mode flash only when the environment is truly local
        # (FLASK_DEBUG=1), NEVER on production even if WHATSAPP_PROVIDER
        # is set to stub by accident.
        sent = False
        if channel == "email" and user is not None and user.school_id:
            try:
                from ...models import School
                from ...services import mailer as _mailer
                school = db.session.get(School, user.school_id)
                if school is not None and _mailer.is_configured(school) and target:
                    _mailer.send(
                        school, target,
                        subject=f"رمز التحقق — {school.name}",
                        body=(
                            f"{school.name}\n\n"
                            f"مرحباً {user.username or user.full_name},\n\n"
                            f"رمز التحقق الخاص بك: {code}\n"
                            "الرمز صالح لخمس دقائق فقط.\n\n"
                            "لو مش أنت اللي طلبت الرمز، تجاهل هذه الرسالة."
                        ),
                    )
                    sent = True
                    flash("تم إرسال رمز التحقق إلى بريدك.", "success")
            except Exception as e:  # noqa: BLE001
                current_app.logger.warning("OTP email send failed: %s", e)
        if not sent:
            # Local-dev fallback ONLY. Anti-enumeration is preserved:
            # unauthenticated users on production see nothing about the
            # code — the flash never fires unless FLASK_DEBUG=1.
            if current_app.debug:
                flash(f"[وضع التطوير] رمز التحقق: {code}", "info")
            else:
                flash("إذا كان الحساب موجوداً، تم إرسال الرمز — تحقق من بريدك.",
                      "info")
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
