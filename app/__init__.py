from flask import Flask, redirect, render_template, url_for

from .config import Config
from .extensions import db, migrate, login_manager, bcrypt, csrf


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    bcrypt.init_app(app)
    csrf.init_app(app)

    # Global soft-delete filter — every SELECT on a SoftDeleteMixin
    # class transparently appends `deleted_at IS NULL`. See
    # app/services/soft_delete.py for the escape hatch.
    from .services.soft_delete import register as _register_soft_delete
    _register_soft_delete(app)

    from .models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # Ticket 6 — install audit-log SQLAlchemy listeners once per process.
    # Must run AFTER models are imported so the classes exist.
    from .services import audit
    audit.install()

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
