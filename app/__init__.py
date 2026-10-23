from flask import Flask, abort, redirect, render_template, request, url_for

from .config import Config
from .extensions import db, migrate, login_manager, bcrypt, csrf


def install_proxy_fix(app):
    """SAAS-009 — behind nginx: client IP from the LAST X-Forwarded-For
    hop (nginx appends the real peer) and scheme from X-Forwarded-Proto.
    x_host stays 0: tenant resolution (SAAS-004) must read the Host nginx
    passes, never a client-supplied X-Forwarded-Host."""
    if not app.config.get("TRUST_PROXY_HEADERS"):
        return
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=0, x_prefix=0)


# SEC-05 — the minimum every response carries (pages, errors, static,
# JSON, files). setdefault: a stronger value set by a view or a
# blueprint (the console: DENY + CSP + no-store) runs first and stays.
# SAMEORIGIN, not DENY: lesson pages embed the school's own PDFs.
BASELINE_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "same-origin",
}


def install_security_headers(app):
    @app.after_request
    def _baseline_security_headers(resp):
        for name, value in BASELINE_SECURITY_HEADERS.items():
            resp.headers.setdefault(name, value)
        return resp


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(config_class)
    # `<hid:…>` route parameters / `|hid`: link codes instead of raw ids.
    # Registered before any blueprint (rules are parsed at registration).
    from .services import hashid as _hashid
    _hashid.init_app(app)

    # SAAS-001 — surface a visible warning in development/testing when
    # the SECRET_KEY falls back to the dev sentinel. Production boot
    # already fails hard in Config._resolve_secret_key.
    from .config import APP_ENV as _APP_ENV, _DEV_FALLBACK_SECRET
    if (_APP_ENV in ("development", "testing")
            and app.config.get("SECRET_KEY") == _DEV_FALLBACK_SECRET):
        app.logger.warning(
            "SECRET_KEY is using the dev fallback. OK for %s only — "
            "never deploy to production like this.", _APP_ENV,
        )

    install_proxy_fix(app)
    install_security_headers(app)
    # SAAS-025 — the platform host gets its own session cookie.
    from .services.platform_auth import HostAwareSessionInterface
    app.session_interface = HostAwareSessionInterface()
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    bcrypt.init_app(app)
    csrf.init_app(app)

    # SAAS-004 — resolve the tenant from the request Host before any
    # view runs. Mode defaults to `off` (no behaviour change) and is
    # flipped to `log` / `enforce` via TENANT_RESOLUTION_MODE env.
    from .services import tenancy as _tenancy
    _tenancy.init_app(app)
    # LEGACY_HOSTS — explicit host → school aliases (e.g. lms.manasety.ai
    # → demo). Empty unless the environment sets it (SAAS-024/038).
    app.config.setdefault("LEGACY_HOSTS", {})
    app.config.setdefault("BASE_DOMAIN", "manasety.ai")
    app.config.setdefault("PLATFORM_HOSTS", ["console.manasety.ai"])

    # Global soft-delete filter — every SELECT on a SoftDeleteMixin
    # class transparently appends `deleted_at IS NULL`. See
    # app/services/soft_delete.py for the escape hatch.
    from .services.soft_delete import register as _register_soft_delete
    _register_soft_delete(app)
    # SAAS-031 — the platform support user is invisible to every query.
    from .services.support_policy import register_filter as _register_support_filter
    _register_support_filter()

    from .models import PlatformUser, User

    @login_manager.user_loader
    def load_user(user_id):
        # SAAS-025 — platform users carry "p:<id>" and exist only on the
        # platform host; school users ("<id>") never load there. An id
        # collision can therefore never turn one kind into the other.
        from .services.platform_auth import is_platform_host
        uid = str(user_id)
        on_platform = is_platform_host()
        if uid.startswith("p:"):
            if not on_platform or not uid[2:].isdigit():
                return None
            pu = db.session.get(PlatformUser, int(uid[2:]))
            return pu if pu is not None and pu.is_active else None
        if on_platform or not uid.isdigit():
            return None
        # SAAS-031 — the support user loads only inside a support session.
        from .services.support_policy import is_support_request
        user = db.session.get(User, int(uid), execution_options={"include_support": True})
        if user is not None and user.is_platform_support and not is_support_request():
            return None
        # Security review (SAAS-032): deactivating a user ends their
        # sessions on the next request.
        if user is not None and not user.is_active:
            return None
        return user

    # Ticket 6 — install audit-log SQLAlchemy listeners once per process.
    # Must run AFTER models are imported so the classes exist.
    from .services import audit
    audit.install()
    # SAAS-022 — refuse flushes that link rows across schools.
    from .services import tenant_guard
    tenant_guard.install(app)
    # SAAS-025 — the platform read-scope listener refuses school-table writes.
    from .services import platform_scope
    platform_scope.install()
    # SAAS-036 — audit tables refuse UPDATE / DELETE (DB triggers)
    from .services.platform_security import install_triggers
    install_triggers(app)
    # SAAS-027 — subscription enforcement (read-only grace, kill switch,
    # banners). Blocked schools are answered by the resolver above.
    from .services import subscription_enforcement
    subscription_enforcement.install(app)
    # SAAS-030 — per-school modules (plan ± console overrides).
    from .services import modules as _modules
    _modules.install(app)

    from .blueprints.auth import bp as auth_bp
    from .blueprints.dashboard import bp as dashboard_bp
    from .blueprints.admin import bp as admin_bp
    from .blueprints.academic import bp as academic_bp
    from .blueprints.students import bp as students_bp
    from .blueprints.teachers import bp as teachers_bp
    from .blueprints.schedule import bp as schedule_bp
    from .blueprints.attendance import bp as attendance_bp
    from .blueprints.results import bp as results_bp
    from .blueprints.finance import bp as finance_bp
    from .blueprints.hr import bp as hr_bp
    from .blueprints.portal import bp as portal_bp
    from .blueprints.api import bp as api_bp
    from .blueprints.courses import bp as courses_bp
    from .blueprints.lms import bp as lms_bp
    from .blueprints.messaging import bp as messaging_bp
    from .blueprints.platform import bp as platform_bp
    from .blueprints.cron import bp as cron_bp
    from .blueprints.nafis import bp as nafis_bp

    app.register_blueprint(auth_bp, url_prefix="/auth")
    # SAAS-029 — health probe used by `flask nginx-sync` after a reload.
    # No data: just "this host resolved". (Unknown hosts 404 in enforce.)
    @app.route("/_health", endpoint="health")
    def _health():
        from flask import jsonify
        return jsonify(ok=True)

    # SAAS-031 — support sessions (school-host side).
    from .blueprints.support import bp as support_bp, install as _install_support
    app.register_blueprint(support_bp)
    _install_support(app)

    # SAAS-028 — /set-password/<token> for provisioned school admins.
    from .blueprints.auth.setup import bp as account_bp
    app.register_blueprint(account_bp)
    app.register_blueprint(dashboard_bp, url_prefix="/")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(academic_bp, url_prefix="/academic")
    app.register_blueprint(students_bp, url_prefix="/students")
    app.register_blueprint(teachers_bp, url_prefix="/teachers")
    app.register_blueprint(schedule_bp, url_prefix="/schedule")
    app.register_blueprint(attendance_bp, url_prefix="/attendance")
    app.register_blueprint(results_bp, url_prefix="/results")
    app.register_blueprint(finance_bp, url_prefix="/finance")
    app.register_blueprint(hr_bp, url_prefix="/hr")
    app.register_blueprint(portal_bp, url_prefix="/portal")
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(courses_bp, url_prefix="/courses")
    app.register_blueprint(lms_bp, url_prefix="/lms")
    app.register_blueprint(messaging_bp, url_prefix="/msg")
    app.register_blueprint(platform_bp, url_prefix="/platform")
    app.register_blueprint(cron_bp, url_prefix="/cron")
    app.register_blueprint(nafis_bp, url_prefix="/nafis")
    # SAAS-011 — uploads are served only through the checked route.
    from .blueprints.files import bp as files_bp
    app.register_blueprint(files_bp)
    # SAAS-025 — Super Admin console (platform host only).
    from .blueprints.superadmin import bp as superadmin_bp, install_platform_host_guard
    app.register_blueprint(superadmin_bp)
    install_platform_host_guard(app)

    @app.before_request
    def _no_public_uploads():
        # Two layers: the normalised, case-folded request path, and the
        # real path the static view would open (catches spellings the
        # filesystem treats as equal, e.g. trailing dots on Windows).
        import os
        import posixpath
        from pathlib import Path
        norm = posixpath.normpath("/" + request.path.replace("\\", "/")).lower()
        if norm == "/static/uploads" or norm.startswith("/static/uploads/"):
            abort(404)
        if request.endpoint == "static" and app.static_folder:
            fname = (request.view_args or {}).get("filename") or ""
            uploads = os.path.normcase(str(Path(app.static_folder, "uploads").resolve()))
            real = os.path.normcase(str(Path(app.static_folder, fname).resolve()))
            if real == uploads or real.startswith(uploads + os.sep):
                abort(404)

    @app.route("/")
    def index():
        return render_template("landing.html")

    # Hotfix (2026-09-26) — invoice_detail.html was calling `today()`
    # from Jinja without any route passing it, so every invoice view
    # crashed with 500. Rather than patching each route to inject it,
    # register it once here as a template global so ANY template can
    # ask for the current date without help from the view.
    from datetime import date as _date_cls
    app.jinja_env.globals["today"] = _date_cls.today
    # An empty optional field renders as nothing, not as the word "None"
    # (value="{{ F.phone if F else '' }}" printed "None" for a NULL phone).
    app.jinja_env.finalize = lambda v: "" if v is None else v

    @app.context_processor
    def inject_globals():
        # Base branding vars — always available in every template.
        ctx = {
            "app_name": "منصتي",
            "app_name_en": "Manasety",
            "app_tagline": "منصة التعلم الذكية للمدارس",
            "school_name": app.config["DEFAULT_SCHOOL_NAME"],
        }
        # Per-request extras for the Stitch topbar (active year + notifications).
        try:
            from flask_login import current_user
            from .models import AcademicYear, NotificationLog
            if current_user.is_authenticated:
                sid = getattr(current_user, "school_id", None)
                if sid:
                    year = AcademicYear.query.filter_by(
                        school_id=sid, status="active"
                    ).first()
                    if year:
                        ctx["active_year"] = year.name
                    ctx["topbar_notifications_count"] = NotificationLog.query.filter_by(
                        school_id=sid, read_at=None
                    ).count()
        except Exception:
            # never let context enrichment blank a page
            pass
        return ctx

    @app.errorhandler(401)
    def err_401(_):
        return redirect(url_for("auth.login"))

    @app.errorhandler(403)
    def err_403(_):
        return render_template("errors/error.html", code=403,
                               title="غير مصرّح", msg="لا تملك صلاحية الوصول إلى هذه الصفحة."), 403

    @app.errorhandler(404)
    def err_404(_):
        return render_template("errors/error.html", code=404,
                               title="الصفحة غير موجودة", msg="تعذّر العثور على ما تبحث عنه."), 404

    @app.errorhandler(500)
    def err_500(_):
        return render_template("errors/error.html", code=500,
                               title="خطأ داخلي", msg="حدث خطأ في الخادم. تواصل مع الدعم الفنّي."), 500

    return app
