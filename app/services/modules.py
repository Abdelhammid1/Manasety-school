"""SAAS-030 — the one catalogue of modules a school can have, and the
single answer to "is module X on for school S?".

A module owns blueprints, individual endpoints (mixed blueprints such
as `platform` and `api` are split by endpoint / path), sidebar groups
and can() permission names. Core modules are always on.

Effective modules = the plan's modules ("*" = all) ± per-school
overrides (school_module_overrides). Computed once per request (g).
Turning a module off never deletes data; turning it back on shows
everything again.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from flask import g, has_request_context

from ..extensions import db


@dataclass(frozen=True)
class Module:
    key: str
    label_ar: str
    core: bool = False
    blueprints: tuple[str, ...] = ()
    endpoints: tuple[str, ...] = ()          # endpoint-name prefixes in mixed blueprints
    api_paths: tuple[str, ...] = ()          # regexes on /api/... paths
    sidebar_groups: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()        # names checked by user.can()
    notes: str = ""


MODULES: tuple[Module, ...] = (
    Module("core", "الأساسيات (دخول، لوحة التحكم، الإعدادات، المستخدمون، الرسائل)", core=True,
           blueprints=("auth", "account", "dashboard", "admin", "messaging", "files", "support"),
           endpoints=("platform.user_scopes", "platform.audit_log"),
           api_paths=(r"^/api/auth/", r"^/api/me(/|$)", r"^/api/notifications/",
                      r"^/api/(teacher|student|parent)/home$", r"^/api/teacher/messages",
                      r"^/api/parent/notifications$"),
           sidebar_groups=("admin-system", "teacher-home"),
           permissions=("users", "roles")),
    Module("academic", "البنية الأكاديمية (السنوات، الصفوف، الفصول، المواد، المعلمون)", core=True,
           blueprints=("academic", "teachers"),
           api_paths=(r"^/api/teacher/(terms|sections|students)$",),
           sidebar_groups=("admin-academic", "admin-teachers", "teacher-classes"),
           permissions=("academic_years", "terms", "grades", "sections", "teachers")),
    Module("students", "الطلاب وأولياء الأمور", core=True,
           blueprints=("students",), endpoints=("platform.imports",),
           api_paths=(r"^/api/parent/children$", r"^/api/(parent/)?pickup",),
           sidebar_groups=("admin-students",), permissions=("students",)),
    Module("attendance", "الحضور والغياب",
           blueprints=("attendance",),
           api_paths=(r"^/api/teacher/attendance$", r"^/api/parent/child/\d+/attendance$",
                      r"^/api/student/attendance$"),
           permissions=("attendance",)),
    Module("schedule", "الجدول والقاعات وتغطية الحصص",
           blueprints=("schedule",), endpoints=("platform.room", "platform.substitution"),
           api_paths=(r"^/api/teacher/schedule$", r"^/api/teacher/section/\d+/schedule$",
                      r"^/api/parent/child/\d+/schedule$", r"^/api/student/schedule$"),
           sidebar_groups=("admin-schedule",), permissions=("schedule",)),
    Module("results", "التقييم ورصد الدرجات",
           blueprints=("results",),
           api_paths=(r"^/api/teacher/(grades|components)$", r"^/api/parent/child/\d+/results$",
                      r"^/api/student/(grades|report-card/\d+)$"),
           sidebar_groups=("admin-assessment",), permissions=("results",)),
    Module("lms", "التعلم الإلكتروني (المقررات، بنك الأسئلة، الواجبات، الاختبارات)",
           blueprints=("lms", "courses"),
           api_paths=(r"^/api/teacher/(materials|upload|assignments|quizzes|announcements|templates|exams)",
                      r"^/api/admin/question_bank", r"^/api/parent/child/\d+/materials$",
                      r"^/api/student/(courses|assignments|announcements|lessons|quizzes)"),
           sidebar_groups=("admin-learning", "student-learning"), permissions=("lms",)),
    Module("nafis", "نافس", blueprints=("nafis",), sidebar_groups=("admin-nafis",)),
    Module("finance", "المالية", blueprints=("finance",),
           api_paths=(r"^/api/parent/child/\d+/invoices$",),
           sidebar_groups=("admin-finance",),
           permissions=("finance", "finance_transactions", "expenses")),
    Module("hr", "الموارد البشرية", blueprints=("hr",), endpoints=("platform.staff_attendance",),
           sidebar_groups=("admin-hr",), permissions=("payroll",)),
    Module("portal", "بوابة أولياء الأمور والطلاب", blueprints=("portal",),
           sidebar_groups=("parent-updates",), permissions=("portal",)),
)

BY_KEY = {m.key: m for m in MODULES}
MODULE_KEYS: tuple[str, ...] = tuple(m.key for m in MODULES)
TOGGLEABLE: tuple[str, ...] = tuple(m.key for m in MODULES if not m.core)
# Not school features at all — never gated by a school's modules.
PLATFORM_BLUEPRINTS = frozenset({"superadmin", "cron", "saas012_canary"})
APP_ENDPOINTS = frozenset({"static", "health", "index"})

_PERM_TO_MODULE = {p: m.key for m in MODULES for p in m.permissions}
_API_RULES = [(re.compile(p), m.key) for m in MODULES for p in m.api_paths]


def validate_plan_modules(keys) -> list[str]:
    keys = [k.strip().lower() for k in keys if k and k.strip()]
    if "*" in keys:
        return ["*"]
    unknown = sorted(set(keys) - set(MODULE_KEYS))
    if unknown:
        raise ValueError(f"موديولات غير معروفة: {', '.join(unknown)}")
    return sorted(set(keys))


def module_for_endpoint(endpoint: str | None, path: str = "") -> str | None:
    """Module key owning this endpoint, or None for platform/app routes."""
    if not endpoint or endpoint in APP_ENDPOINTS:
        return None
    bp = endpoint.split(".", 1)[0] if "." in endpoint else None
    if bp in PLATFORM_BLUEPRINTS:
        return None
    if bp == "api":
        for rx, key in _API_RULES:
            if rx.search(path):
                return key
        return "core"
    for m in MODULES:
        if any(endpoint.startswith(p) for p in m.endpoints):
            return m.key
    for m in MODULES:
        if bp in m.blueprints:
            return m.key
    return None


def module_for_permission(perm: str) -> str | None:
    return _PERM_TO_MODULE.get(perm)


# ─── request gate ──────────────────────────────────────────────────

def api_module_refusal(user):
    """(json, 403) when this API endpoint belongs to a module the bearer's
    OWN school doesn't have — independent of the request host (security
    review: the host gate alone fails open when no tenant resolves)."""
    from flask import jsonify, request
    key = module_for_endpoint(request.endpoint, request.path)
    if key is None or BY_KEY[key].core:
        return None
    sid = getattr(user, "school_id", None)
    if sid is not None and not module_enabled(sid, key):
        return jsonify({"error": "module_disabled", "module": key}), 403
    return None

def _request_school_id():
    from flask_login import current_user
    resolved = getattr(g, "tenant_resolved", None)
    if resolved is not None and resolved.kind == "tenant" and resolved.school is not None:
        return resolved.school.id
    if getattr(current_user, "is_authenticated", False) and             not getattr(current_user, "is_platform_user", False):
        return getattr(current_user, "school_id", None)
    return None


def install(app) -> None:
    from flask import abort, jsonify, request

    @app.before_request
    def _module_gate():
        key = module_for_endpoint(request.endpoint, request.path)
        if key is None or BY_KEY[key].core:
            return None
        sid = _request_school_id()
        if sid is None or module_enabled(sid, key):
            return None
        if request.path.startswith("/api/"):
            return jsonify({"error": "module_disabled", "module": key}), 403
        abort(404)

    # Jinja globals (not a context processor) so the sidebar's macros see
    # them too — macros don't get the render context.
    def module_on(key):
        if not has_request_context():
            return True
        sid = _request_school_id()
        return sid is None or module_enabled(sid, key)

    def endpoint_on(endpoint):
        return module_on(module_for_endpoint(endpoint, ""))
    app.jinja_env.globals.update(module_on=module_on, endpoint_on=endpoint_on)


# ─── effective modules ─────────────────────────────────────────────

def _compute_enabled(school_id: int) -> frozenset[str]:
    from ..models import SchoolModuleOverride
    from .subscriptions import current_subscription
    sub = current_subscription(school_id)
    plan_modules = list((sub.plan.modules if sub is not None and sub.plan is not None else None) or [])
    enabled = set(MODULE_KEYS) if "*" in plan_modules else set(plan_modules) & set(MODULE_KEYS)
    for o in SchoolModuleOverride.query.filter_by(school_id=school_id):
        if o.module_key in BY_KEY:
            (enabled.add if o.enabled else enabled.discard)(o.module_key)
    enabled |= {m.key for m in MODULES if m.core}
    return frozenset(enabled)


def enabled_modules(school_id: int | None) -> frozenset[str]:
    if school_id is None:
        return frozenset(MODULE_KEYS)
    if has_request_context():
        cache = g.setdefault("_enabled_modules", {})
        if school_id not in cache:
            cache[school_id] = _compute_enabled(int(school_id))
        return cache[school_id]
    return _compute_enabled(int(school_id))


def module_enabled(school_id: int | None, key: str | None) -> bool:
    if key is None or key not in BY_KEY or BY_KEY[key].core:
        return True
    return key in enabled_modules(school_id)


def module_sources(school_id: int) -> list[dict]:
    """For the console: each module's effective state and where it comes from."""
    from ..models import SchoolModuleOverride
    from .subscriptions import current_subscription
    sub = current_subscription(school_id)
    plan_modules = list((sub.plan.modules if sub is not None and sub.plan is not None else None) or [])
    overrides = {o.module_key: o for o in SchoolModuleOverride.query.filter_by(school_id=school_id)}
    out = []
    for m in MODULES:
        in_plan = m.core or "*" in plan_modules or m.key in plan_modules
        o = overrides.get(m.key)
        on = True if m.core else (o.enabled if o is not None else in_plan)
        out.append({"module": m, "enabled": on, "in_plan": in_plan, "override": o,
                    "source": "core" if m.core else ("override" if o is not None else "plan")})
    return out


def set_override(school, key: str, enabled: bool | None, reason: str, user) -> None:
    """enabled=None removes the override (back to the plan)."""
    from ..models import SchoolModuleOverride
    from .platform_auth import audit
    from .subscriptions import SubscriptionError, _event
    if key not in TOGGLEABLE:
        raise SubscriptionError("هذا الموديول أساسي ولا يمكن إيقافه.")
    if not reason or not reason.strip():
        raise SubscriptionError("السبب مطلوب.")
    row = SchoolModuleOverride.query.filter_by(school_id=school.id, module_key=key).first()
    before = None if row is None else row.enabled
    if enabled is None:
        if row is not None:
            db.session.delete(row)
    else:
        if row is None:
            row = SchoolModuleOverride(school_id=school.id, module_key=key)
            db.session.add(row)
        row.enabled = bool(enabled)
        row.reason = reason.strip()
        row.updated_by_platform_user_id = getattr(user, "id", None)
    _event(school.id, "module_override", f"{key}:{before}", f"{key}:{enabled}", reason.strip(), user)
    audit("module_override", user, school_id=school.id, module=key, before=before, after=enabled)


def clear_overrides_for_plan_change(school_id: int) -> int:
    """After a plan change, drop overrides that now just repeat the plan,
    so no stale exception lingers by mistake."""
    from ..models import SchoolModuleOverride
    from .subscriptions import current_subscription
    sub = current_subscription(school_id)
    plan_modules = list((sub.plan.modules if sub is not None and sub.plan is not None else None) or [])
    n = 0
    for o in SchoolModuleOverride.query.filter_by(school_id=school_id).all():
        in_plan = "*" in plan_modules or o.module_key in plan_modules
        if o.enabled == in_plan:
            db.session.delete(o)
            n += 1
    return n
