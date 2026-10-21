"""SAAS-028 — create a ready-to-use school in one atomic step.

provision_school(spec, platform_user) writes, inside one transaction and
inside tenant_context(school.id):

  1. the schools row (settings from the wizard)
  2. its subscription (services/subscriptions)
  3. the starter data (services/school_templates)
  4. the first admin — random unknown password + one-time setup token
  5. events / audit: platform_audit_logs (school_created),
     school_subscription_events, and the school's own first audit_logs row

Any failure rolls everything back; nothing is left behind. The raw setup
token exists only in the returned result (shown once on screen, or
mailed); only its hash is stored, and it never reaches a log.
"""
from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from ..extensions import db

SETUP_TOKEN_TTL = timedelta(hours=72)
CODE_MAX = 32
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,64}$")
ATTENDANCE_MODES = ("daily", "per_period")


class ProvisionError(ValueError):
    """Shown to the console user (Arabic). `field` names the wizard field."""

    def __init__(self, message, field=None):
        super().__init__(message)
        self.field = field


@dataclass
class ProvisionSpec:
    name: str
    slug: str
    admin_full_name: str
    plan_id: int
    starts_on: date
    name_en: str = ""
    phone: str = ""
    email: str = ""
    address: str = ""
    currency: str = "EGP"
    currency_symbol: str = "ج.م"
    fiscal_year_start_month: int = 9
    invoice_prefix: str = "INV"
    default_tax_rate: float = 0
    attendance_mode: str = "daily"
    months: int | None = None          # subscription length, or…
    ends_on: date | None = None        # …an explicit end date, or…
    trial_days: int | None = None      # …a trial
    admin_username: str = "admin"
    admin_email: str = ""
    admin_phone: str = ""


@dataclass
class ProvisionResult:
    school_id: int | None
    slug: str
    url: str
    setup_link: str | None             # raw — show once, never store
    subdomain_status: str
    plan: list[str] = field(default_factory=list)   # dry-run: what would happen
    mailed: bool = False


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def school_url(slug: str) -> str:
    from flask import current_app
    base = current_app.config.get("BASE_DOMAIN") or "manasety.ai"
    return f"https://{slug}.{base}"


def slug_available(raw: str) -> tuple[bool, str]:
    """(ok, Arabic message) — format, reserved list, case-insensitive
    uniqueness. Used by the wizard's live check and by provision."""
    from ..models import School
    from .tenancy import SlugValidationError, validate_slug
    try:
        slug = validate_slug(raw)
    except SlugValidationError as e:
        return False, str(e)
    if School.query.filter(func.lower(School.slug) == slug).first() is not None:
        return False, f"الاسم المختصر «{slug}» مستخدم بالفعل."
    # SAAS-032 — a slug a school ever had stays reserved forever.
    from ..models import SchoolSlugHistory
    if SchoolSlugHistory.query.filter(func.lower(SchoolSlugHistory.old_slug) == slug).first() is not None:
        return False, f"الاسم المختصر «{slug}» محجوز (كان لمدرسة قبل كده)."
    return True, slug


def _unique_code(slug: str) -> str:
    from ..models import School
    base = re.sub(r"[^A-Z0-9]", "", slug.upper())[:CODE_MAX] or "SCHOOL"
    code, n = base, 1
    while School.query.filter_by(code=code).first() is not None:
        n += 1
        suffix = f"-{n}"
        code = base[:CODE_MAX - len(suffix)] + suffix
    return code


def validate_spec(spec: ProvisionSpec) -> str:
    """Server-side checks for every wizard field. Returns the clean slug."""
    from ..models import Plan
    ok, msg = slug_available(spec.slug)
    if not ok:
        raise ProvisionError(msg, "slug")
    if not (spec.name or "").strip():
        raise ProvisionError("اسم المدرسة مطلوب.", "name")
    if len(spec.name) > 255 or len(spec.name_en or "") > 255:
        raise ProvisionError("اسم المدرسة طويل جدًا.", "name")
    if spec.attendance_mode not in ATTENDANCE_MODES:
        raise ProvisionError("نمط الحضور غير صحيح.", "attendance_mode")
    if not 1 <= int(spec.fiscal_year_start_month) <= 12:
        raise ProvisionError("شهر بداية السنة المالية غير صحيح.", "fiscal_year_start_month")
    if not 0 <= float(spec.default_tax_rate) <= 100:
        raise ProvisionError("نسبة الضريبة يجب أن تكون بين 0 و100.", "default_tax_rate")
    if not (spec.currency or "").strip() or len(spec.currency) > 8 or len(spec.currency_symbol or "") > 8:
        raise ProvisionError("العملة غير صحيحة.", "currency")
    if not (spec.invoice_prefix or "").strip() or len(spec.invoice_prefix) > 16:
        raise ProvisionError("بادئة الفواتير غير صحيحة.", "invoice_prefix")
    plan = db.session.get(Plan, int(spec.plan_id)) if spec.plan_id else None
    if plan is None or not plan.is_active:
        raise ProvisionError("اختر باقة فعّالة.", "plan_id")
    chosen = [x for x in (spec.months, spec.ends_on, spec.trial_days) if x]
    if len(chosen) > 1:
        raise ProvisionError("اختر مدة أو تاريخ نهاية أو تجربة — واحد فقط.", "months")
    if spec.months is not None and int(spec.months) <= 0:
        raise ProvisionError("مدة الاشتراك يجب أن تكون موجبة.", "months")
    if spec.trial_days is not None and int(spec.trial_days) <= 0:
        raise ProvisionError("مدة التجربة يجب أن تكون موجبة.", "trial_days")
    if spec.ends_on is not None and spec.ends_on < spec.starts_on:
        raise ProvisionError("تاريخ النهاية لا يمكن أن يسبق تاريخ البداية.", "ends_on")
    if not (spec.admin_full_name or "").strip():
        raise ProvisionError("اسم المدير مطلوب.", "admin_full_name")
    if not USERNAME_RE.match(spec.admin_username or ""):
        raise ProvisionError("اسم المستخدم: 3–64 حرفًا إنجليزيًا أو أرقام أو . _ -", "admin_username")
    if spec.admin_email and "@" not in spec.admin_email:
        raise ProvisionError("إيميل المدير غير صحيح.", "admin_email")
    return msg


# ─── steps (module-level so tests can inject a failure in each) ──────

def _create_school(spec, slug):
    from ..models import School
    school = School(
        code=_unique_code(slug), name=spec.name.strip(), slug=slug, status="active",
        is_active=True, phone=spec.phone or None, address=spec.address or None,
        email=spec.email or None, legal_name_ar=spec.name.strip(),
        legal_name_en=(spec.name_en or "").strip() or None,
        currency=spec.currency.strip(), currency_symbol=(spec.currency_symbol or "").strip() or spec.currency,
        fiscal_year_start_month=int(spec.fiscal_year_start_month),
        invoice_prefix=spec.invoice_prefix.strip(), default_tax_rate=spec.default_tax_rate,
        attendance_mode=spec.attendance_mode,
    )
    db.session.add(school)
    db.session.flush()
    return school


def _create_subscription(school, spec, user):
    from ..models import Plan
    from . import subscriptions as subs
    from .subscriptions import add_months
    plan = db.session.get(Plan, int(spec.plan_id))
    if spec.trial_days:
        subs.start_trial(school, plan, user, days=int(spec.trial_days), reason="provisioned",
                         today=spec.starts_on)
        return
    ends = spec.ends_on
    if spec.months:
        ends = add_months(spec.starts_on, int(spec.months)) - timedelta(days=1)
    subs.create_subscription(school, plan, starts_on=spec.starts_on, ends_on=ends, user=user,
                             reason="provisioned")


def _apply_template(school):
    from .school_templates import apply
    return apply(school.id)


def _create_admin(school, spec):
    from ..models import AccountSetupToken, Role, User
    role = Role.query.filter_by(school_id=school.id, name="admin").first()
    if role is None:
        raise ProvisionError("قالب المدرسة لا يحتوي على دور المدير.")
    admin = User(school_id=school.id, role_id=role.id, username=spec.admin_username,
                 full_name=spec.admin_full_name.strip(), email=spec.admin_email or None,
                 phone=spec.admin_phone or None, is_active=True)
    # Long random password nobody knows; the admin sets their own via the link.
    admin.set_password(secrets.token_urlsafe(48))
    db.session.add(admin)
    db.session.flush()
    raw = secrets.token_urlsafe(32)
    db.session.add(AccountSetupToken(user_id=admin.id, token_hash=hash_token(raw),
                                     expires_at=datetime.utcnow() + SETUP_TOKEN_TTL))
    db.session.flush()
    return admin, raw


def _record_events(school, admin, user, counts):
    from ..models import AuditLog
    from .platform_auth import audit
    audit("school_created", user, school_id=school.id, slug=school.slug,
          admin_username=admin.username, seeded=counts)
    db.session.add(AuditLog(
        school_id=school.id, user_id=None, action="create", entity_type="School",
        entity_id=school.id,
        new_value={"note": "تم إنشاء المدرسة بواسطة إدارة المنصة", "slug": school.slug}))
    db.session.flush()


def subdomain_status(school_id) -> str:
    from .nginx_queue import school_subdomain_status
    return school_subdomain_status(school_id)


def _after_create(school, user=None):
    """SAAS-029: queue an nginx sync; the server applies it within a minute."""
    from .nginx_queue import request_nginx_sync
    request_nginx_sync("school_created", school_id=school.id, user=user)


def provision_school(spec: ProvisionSpec, platform_user, *, dry_run: bool = False) -> ProvisionResult:
    from .tenancy import tenant_context
    slug = validate_spec(spec)
    if dry_run:
        plan = [f"schools: {slug} (code {_unique_code(slug)})",
                "school_subscriptions: 1 + event",
                "starter data: services/school_templates/default.py",
                f"users: {spec.admin_username} (admin) + 1 setup token (72h)",
                "platform_audit_logs: school_created; audit_logs: first row"]
        return ProvisionResult(None, slug, school_url(slug), None, "dry_run", plan)
    try:
        school = _create_school(spec, slug)
        with tenant_context(school.id):
            _create_subscription(school, spec, platform_user)
            counts = _apply_template(school)
            admin, raw = _create_admin(school, spec)
            from .support_policy import ensure_support_user
            ensure_support_user(school)            # SAAS-031
            _record_events(school, admin, platform_user, counts)
            _after_create(school, platform_user)
        db.session.commit()
    except IntegrityError:
        # Lost a race on the slug / code unique index (double submit).
        db.session.rollback()
        raise ProvisionError(f"الاسم المختصر «{slug}» مستخدم بالفعل.", "slug") from None
    except Exception:
        db.session.rollback()
        raise
    url = school_url(slug)
    link = f"{url}/set-password/{raw}"
    return ProvisionResult(school.id, slug, url, link, subdomain_status(school.id),
                           mailed=_mail_setup_link(spec, school, link))


def _mail_setup_link(spec, school, link) -> bool:
    """Best effort: the result screen always shows the link anyway."""
    from . import platform_mailer
    if not spec.admin_email or not platform_mailer.is_configured():
        return False
    try:
        platform_mailer.send(
            spec.admin_email, f"منصتي — حساب مدير {school.name}",
            "\n".join([
                f"مرحبًا {spec.admin_full_name}،",
                "",
                f"تم إنشاء حساب مدير لمدرسة {school.name} على منصتي.",
                f"اسم المستخدم: {spec.admin_username}",
                "",
                "لاختيار كلمة المرور افتح الرابط التالي (صالح 72 ساعة ولمرة واحدة):",
                link,
            ]))
    except platform_mailer.PlatformMailError:
        return False
    return True
