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

import logging
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
           blueprints=("auth", "account", "dashboard", "admin", "messaging", "files", "support", "branding"),
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
        if key is None:
            return None
        sid = _request_school_id()
        if sid is None:
            return None
        if not BY_KEY[key].core and not module_enabled(sid, key):
            if request.path.startswith("/api/"):
                return jsonify({"error": "module_disabled", "module": key}), 403
            abort(404)
        # a page turned off for this school inside a module that is on —
        # for a signed-in user: a visitor gets the page's own login
        # redirect first (every non-essential page needs a login), so the
        # school's choices are never shown to a stranger
        from flask_login import current_user
        if getattr(current_user, "is_authenticated", False) and \
                not feature_enabled(sid, feature_for_endpoint(request.endpoint)):
            abort(404)
        return None

    # Jinja globals (not a context processor) so the sidebar's macros see
    # them too — macros don't get the render context.
    def module_on(key):
        if not has_request_context():
            return True
        sid = _request_school_id()
        return sid is None or module_enabled(sid, key)

    def feature_on(key):
        if not has_request_context():
            return True
        return feature_enabled(_request_school_id(), key)

    def endpoint_on(endpoint):
        return module_on(module_for_endpoint(endpoint, "")) and feature_on(feature_for_endpoint(endpoint))
    app.jinja_env.globals.update(module_on=module_on, endpoint_on=endpoint_on, feature_on=feature_on)


# ─── effective modules ─────────────────────────────────────────────

def _compute_enabled(school_id: int) -> frozenset[str]:
    from ..models import SchoolModuleOverride
    from .subscriptions import current_subscription
    from .tenancy import resolution_mode
    sub = current_subscription(school_id)
    if sub is None and resolution_mode() != "enforce":
        # before enforcement nothing new may take a module away: a school
        # created outside the console (CLI, old seed) keeps them all
        plan_modules = ["*"]
    else:
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


def set_override(school, key: str, enabled: bool | None, reason: str, user, *, record: bool = True) -> None:
    """enabled=None removes the override (back to the plan). record=False
    leaves the event / audit to the caller (set_school_access)."""
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
    if record:
        _event(school.id, "module_override", f"{key}:{before}", f"{key}:{enabled}", reason.strip(), user)
        audit("module_override", user, school_id=school.id, module=key, before=before, after=enabled)
    if has_request_context():
        g.pop("_enabled_modules", None)
        g.pop("_effective_features", None)


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


# ─── features: pages / abilities inside a module ───────────────────
# Every web route of a school module belongs to exactly one feature
# (tests/test_features.py fails on a route with none, or two). A feature
# is on = its module is on AND (the school's override, else default_on).
# Essential features never turn off. API routes stay at module level.
# Approved catalogue (Abdelhamid, 2026-10-25): 69 features, 10 essential;
# lms.ai is off by default for new schools.

@dataclass(frozen=True)
class Feature:
    key: str
    label_ar: str
    endpoints: tuple[str, ...] = ()
    essential: bool = False
    default_on: bool = True

    @property
    def module(self) -> str:
        return self.key.split(".", 1)[0]


def _f(key, label, *endpoints, essential=False, default_on=True):
    return Feature(key, label, tuple(endpoints), essential=essential, default_on=default_on)


FEATURES: tuple[Feature, ...] = (
    # ── core ──
    _f("core.auth", "الدخول وكلمات المرور",
       "auth.login", "auth.logout", "auth.forgot", "auth.otp", "auth.reset", "auth.locked", "auth.sso",
       "account.app_landing", "account.set_password", "account.set_password_link", essential=True),
    _f("core.dashboard", "لوحة التحكم",
       "dashboard.home", "dashboard.notifications", "dashboard.notifications_json",
       "files.download", "branding.logo", essential=True),
    _f("core.users", "المستخدمون",
       "admin.users_list", "admin.user_new", "admin.user_edit", "admin.user_toggle",
       "platform.user_scopes", essential=True),
    _f("core.roles", "الأدوار والصلاحيات",
       "admin.roles_list", "admin.role_new", "admin.role_edit", "admin.role_delete", essential=True),
    _f("core.settings", "إعدادات المدرسة", "admin.school_settings", "admin.smtp_test", essential=True),
    _f("core.support_log", "سجل دخول الدعم", "support.log", "support.enter", "support.end", essential=True),
    _f("core.ai_usage", "استخدام الذكاء الاصطناعي", "admin.ai_usage", essential=True),
    _f("core.search", "البحث الشامل", "dashboard.global_search", "dashboard.global_search_json"),
    _f("core.messaging", "الرسائل",
       "messaging.inbox", "messaging.conversation_new", "messaging.conversation_view",
       "messaging.message_delete", "messaging.messages_search", "messaging.preferences"),
    _f("core.audit", "سجل النشاط",
       "admin.audit_log", "platform.audit_log_viewer", "platform.audit_log_export"),
    _f("core.trash", "المحذوفات", "admin.trash_home", "admin.trash_restore"),
    _f("core.backups", "النسخ الاحتياطي والاسترجاع",
       "admin.backups_home", "admin.backup_new", "admin.backup_status", "admin.backup_delete",
       "admin.backup_download_prepare", "admin.backup_download",
       "admin.browse_home", "admin.browse_view", "admin.browse_table", "admin.browse_export",
       "admin.restore_home", "admin.restore_new", "admin.restore_detail", "admin.restore_confirm",
       "admin.restore_status", "admin.restore_undo"),
    # ── academic ──
    _f("academic.structure", "السنوات والفصول والصفوف والشعب",
       "academic.years_list", "academic.year_new", "academic.year_edit", "academic.year_close",
       "academic.terms_list", "academic.term_new", "academic.term_edit", "academic.term_delete",
       "academic.grades_list", "academic.grade_new", "academic.grade_edit", "academic.grade_delete",
       "academic.grade_detail", "academic.grade_report",
       "academic.sections_list", "academic.section_new", "academic.section_edit", "academic.section_delete",
       "academic.section_detail", "academic.section_capacity_dashboard", "academic.bulk_transfer",
       essential=True),
    _f("academic.calendar", "التقويم الدراسي",
       "academic.calendar_month", "academic.calendar_day_add", "academic.calendar_day_delete",
       "academic.calendar_generate", "academic.calendar_clear_weekends"),
    _f("academic.subjects", "المواد",
       "teachers.subjects_list", "teachers.subject_new", "teachers.subject_edit", "teachers.subject_delete",
       "teachers.subject_toggle", "academic.subject_prerequisites", "academic.subject_report"),
    _f("academic.teachers", "المعلمون وحساباتهم",
       "teachers.teachers_list", "teachers.teacher_new", "teachers.teacher_edit", "teachers.teacher_detail",
       "teachers.teacher_toggle", "teachers.teacher_specialization",
       "teachers.teacher_account_toggle", "teachers.teacher_account_reset_password"),
    _f("academic.teaching", "إسناد التدريس",
       "teachers.assignments_list", "teachers.section_assignments", "teachers.assignment_update",
       "teachers.assignment_remove"),
    # ── students ──
    _f("students.records", "الطلاب",
       "students.students_list", "students.student_new", "students.student_edit", "students.student_detail",
       "students.enroll", "students.status_change", "students.transfer", "students.graduate_enrollment",
       "students.save_exit_checklist", "students.student_account_toggle",
       "students.student_account_reset_password", "students.student_photo_upload",
       "students.student_siblings_json", "students.student_note_add", "students.student_note_delete",
       "students.student_tag_new", "students.student_tag_attach", "students.student_tag_detach",
       "students.previous_school_add", "students.previous_school_delete", essential=True),
    _f("students.guardians", "أولياء الأمور",
       "students.guardians_list", "students.guardian_new", "students.guardian_add", "students.guardian_detail",
       "students.guardian_edit", "students.guardian_delete", "students.guardian_link_new",
       "students.guardian_link_update", "students.guardian_link_delete",
       "students.guardian_account_create", "students.guardian_account_toggle",
       "students.guardian_account_reset_password", essential=True),
    _f("students.documents", "المستندات",
       "students.documents", "students.document_upload", "students.document_delete"),
    _f("students.behavior", "السلوك",
       "students.behavior_home", "students.behavior_add", "students.behavior_categories"),
    _f("students.health", "الملف الصحي", "students.health_profile", "students.health_incident_add"),
    _f("students.id_card", "بطاقة الهوية", "students.student_id_card"),
    _f("students.view360", "Student 360", "students.student_360", "students.student_360_json"),
    _f("students.promotion", "ترقية نهاية السنة", "students.promotion"),
    _f("students.imports", "استيراد Excel",
       "platform.imports_home", "platform.imports_preview", "platform.imports_commit",
       "platform.imports_template"),
    # ── attendance ──
    _f("attendance.mark", "رصد الحضور", "attendance.index", "attendance.mark"),
    _f("attendance.reports", "تقارير ولوحات الحضور",
       "attendance.attendance_dashboard", "attendance.attendance_correlation", "attendance.period_utilization",
       "attendance.section_report", "attendance.student_report", "attendance.student_day_detail"),
    _f("attendance.risk", "قواعد الحضور وإنذار الخطر",
       "attendance.risk_dashboard", "attendance.risk_recompute", "attendance.rules_list",
       "attendance.rule_trigger_resolve"),
    # ── schedule ──
    _f("schedule.timetable", "الجدول المدرسي",
       "schedule.index", "schedule.settings", "schedule.auto_generate", "schedule.day_new", "schedule.day_delete",
       "schedule.period_new", "schedule.period_delete", "schedule.section_schedule", "schedule.slot_save",
       "schedule.slot_delete", "schedule.teacher_schedule"),
    _f("schedule.rooms", "القاعات",
       "platform.rooms_list", "platform.room_new", "platform.room_detail", "platform.room_edit",
       "platform.room_delete", "platform.room_toggle", "platform.room_slot_save", "platform.room_slot_unbook"),
    _f("schedule.substitutions", "تغطية الحصص", "platform.substitutions_list", "platform.substitution_new"),
    # ── results ──
    _f("results.gradebook", "رصد الدرجات والنتائج",
       "results.grades_index", "results.grade_sheet", "results.section_results", "results.term_results",
       "results.recompute_ranks", "results.components", "results.component_templates",
       "results.class_average_report", "results.missing_grades_report"),
    _f("results.scales", "سلالم الدرجات",
       "results.scales_list", "results.scale_new", "results.scale_edit", "results.scale_delete",
       "results.scale_templates", "results.scale_template_apply"),
    _f("results.rubrics", "معايير التقييم",
       "results.rubrics_list", "results.rubric_new", "results.rubric_edit", "results.rubric_delete",
       "results.rubric_templates", "results.rubric_template_apply"),
    _f("results.transcripts", "كشوف الدرجات", "results.transcript_view", "results.transcript_snapshot"),
    _f("results.settings", "إعدادات النتائج", "results.settings"),
    # ── lms ──
    _f("lms.courses", "المقررات والدروس",
       "courses.list_courses", "courses.new", "courses.detail", "courses.delete", "courses.grade_terms",
       "courses.grade_term_subjects", "courses.course_pick_section", "courses.unit_new", "courses.unit_edit",
       "courses.unit_delete", "courses.lesson_new", "courses.lesson_edit", "courses.lesson_delete",
       "courses.lesson_view", "courses.section_link", "courses.section_unlink",
       "courses.section_course_link"),
    _f("lms.qbank", "بنك الأسئلة والتصنيف",
       "lms.bank_home", "lms.bank_new", "lms.bank_smart_new", "lms.bank_edit", "lms.bank_delete",
       "lms.bank_archive", "lms.bank_set_state", "lms.qbank_dashboard",
       "lms.passages_home", "lms.passage_new", "lms.passage_edit", "lms.passage_delete",
       "lms.taxonomy_home", "lms.taxonomy_objective_new", "lms.taxonomy_objective_edit",
       "lms.taxonomy_objective_delete", "lms.taxonomy_skill_new", "lms.taxonomy_skill_edit",
       "lms.taxonomy_skill_delete", "lms.objective_new", "lms.objective_delete", "lms.skill_new",
       "lms.skill_delete", "lms.collection_new", "lms.collection_add"),
    _f("lms.assignments", "الواجبات والتسليمات",
       "lms.assignments_home", "lms.assignment_new", "lms.assignment_edit", "lms.assignment_detail",
       "lms.assignment_delete", "lms.assignment_submit", "lms.assignment_analytics",
       "lms.assignment_extension_add", "lms.assignment_from_template", "lms.assignment_save_as_template",
       "lms.assignment_pick_from_bank", "lms.assignment_questions", "lms.assignment_question_add",
       "lms.assignment_question_update", "lms.assignment_question_new_version",
       "lms.assignment_question_delete", "lms.submission_grade_panel", "lms.submission_grade_save",
       "lms.submission_rubric_grade", "lms.feedback_templates_json", "lms.feedback_template_new",
       "lms.feedback_template_delete"),
    _f("lms.quizzes", "الاختبارات",
       "lms.quizzes_home", "lms.quiz_new", "lms.quiz_edit", "lms.quiz_delete", "lms.quiz_take",
       "lms.quiz_submit", "lms.quiz_result", "lms.quiz_analysis", "lms.quiz_live_monitor",
       "lms.quiz_live_monitor_json", "lms.quiz_publish_results", "lms.quiz_pick_from_bank",
       "lms.quiz_questions", "lms.quiz_question_add", "lms.quiz_question_update",
       "lms.quiz_question_new_version", "lms.quiz_question_delete",
       "lms.attempt_autosave", "lms.attempt_flag", "lms.attempt_tab_switch"),
    _f("lms.exam_blueprint", "توليد Blueprint", "lms.blueprint_exam_new", "lms.blueprint_exam_create"),
    _f("lms.templates", "مكتبة النماذج",
       "lms.templates_gallery", "lms.template_home", "lms.template_new", "lms.template_detail",
       "lms.template_edit", "lms.template_delete", "lms.template_use", "lms.template_print",
       "lms.template_items_attach", "lms.template_items_save", "lms.template_item_delete",
       "lms.template_item_toggle_hidden"),
    _f("lms.announcements", "الإعلانات",
       "lms.announcements_home", "lms.announcement_new", "lms.announcement_pin", "lms.announcement_delete"),
    _f("lms.reports", "تقارير التعلم", "lms.report_section", "lms.report_student"),
    _f("lms.ai", "الذكاء الاصطناعي",
       "lms.bank_ai_review", "lms.bank_ai_rewrite", "lms.bank_ai_rewrite_save", "lms.bank_rewrite_panel",
       "lms.blueprint_ai_suggest", "lms.submission_ai_grade", "lms.template_ai_generate",
       default_on=False),
    # ── nafis ──
    _f("nafis.outcomes", "نواتج التعلم", "nafis.outcomes_home"),
    _f("nafis.cycles", "دورات نافس",
       "nafis.cycles_list", "nafis.cycle_new", "nafis.cycle_detail", "nafis.cycle_edit", "nafis.cycle_delete"),
    _f("nafis.gaps", "الفجوات والخطط العلاجية", "nafis.gaps_home"),
    # ── finance ──
    _f("finance.dashboard", "لوحة المالية", "finance.dashboard"),
    _f("finance.invoices", "الفواتير والمدفوعات",
       "finance.invoices_list", "finance.invoice_new", "finance.invoice_detail", "finance.invoice_pay",
       "finance.invoice_print", "finance.invoice_void", "finance.invoice_unvoid", "finance.bulk_payment"),
    _f("finance.fees", "أنواع الرسوم وطرق الدفع",
       "finance.fee_types", "finance.fee_type_new", "finance.fee_type_edit", "finance.fee_type_delete",
       "finance.fee_type_toggle", "finance.payment_methods_list", "finance.payment_method_new",
       "finance.payment_method_toggle", "finance.payment_method_delete"),
    _f("finance.recurring", "الرسوم المتكررة",
       "finance.recurring_list", "finance.recurring_new", "finance.recurring_toggle", "finance.recurring_delete"),
    _f("finance.discounts", "الخصومات والمنح",
       "finance.discount_types", "finance.discount_type_new", "finance.discount_type_toggle",
       "finance.student_discounts", "finance.student_discount_new", "finance.student_discount_approve",
       "finance.student_discount_reject"),
    _f("finance.refunds", "المرتجعات",
       "finance.refunds_list", "finance.refund_request_new", "finance.refund_request_approve",
       "finance.refund_request_reject"),
    _f("finance.expenses", "المصروفات",
       "finance.expenses_list", "finance.expense_new", "finance.expense_edit", "finance.expense_delete",
       "finance.expense_approve", "finance.expense_reject"),
    _f("finance.vendors", "الموردون",
       "finance.vendors_list", "finance.vendor_new", "finance.vendor_detail", "finance.vendor_edit",
       "finance.vendor_delete", "finance.vendor_toggle"),
    _f("finance.treasury", "الخزينة والعهدة",
       "finance.treasury", "finance.treasury_transfer", "finance.petty_cash_home", "finance.petty_cash_issue",
       "finance.petty_cash_settle"),
    _f("finance.bank_rec", "التسوية البنكية",
       "finance.bank_rec", "finance.bank_rec_import", "finance.bank_rec_match", "finance.bank_rec_unmatch"),
    _f("finance.accounting", "دليل الحسابات والقيود ومراكز التكلفة",
       "finance.accounts", "finance.account_new", "finance.account_statement", "finance.account_suggest_code",
       "finance.journal", "finance.quick_journal_index", "finance.quick_journal_run",
       "finance.cost_centers_list", "finance.cost_center_new", "finance.cost_center_toggle",
       "finance.cost_center_delete"),
    _f("finance.budgets", "الموازنة", "finance.budgets_home", "finance.budget_new", "finance.budget_delete"),
    _f("finance.reports", "التقارير المالية",
       "finance.reports", "finance.reports_index", "finance.reports_export", "finance.report_aging",
       "finance.report_balance_sheet", "finance.report_budget_vs_actual", "finance.report_cash_flow",
       "finance.report_collection", "finance.report_cost_centers", "finance.report_cost_per_student",
       "finance.report_discounts_grants", "finance.report_forecast", "finance.report_general_ledger",
       "finance.report_income_statement", "finance.report_overdue_by_grade",
       "finance.report_payroll_summary", "finance.report_revenue_by_fee_type",
       "finance.report_trial_balance", "finance.report_year_comparison"),
    # ── hr ──
    _f("hr.employees", "الموظفون",
       "hr.employees_list", "hr.employee_new", "hr.employee_detail", "hr.employee_edit", "hr.employee_delete",
       "hr.employee_toggle", "hr.employee_advance_new"),
    _f("hr.leaves", "الإجازات",
       "hr.leave_requests_list", "hr.leave_request_new", "hr.leave_request_approve", "hr.leave_request_reject",
       "hr.leave_balances_list", "hr.leave_balance_new", "hr.leave_balances_reset"),
    _f("hr.payroll", "الرواتب",
       "hr.payroll_list", "hr.payroll_new", "hr.payroll_detail", "hr.payroll_delete", "hr.payroll_settle"),
    _f("hr.staff_attendance", "حضور الموظفين", "platform.staff_attendance", "platform.staff_attendance_save"),
    # ── portal ──
    _f("portal.home", "بوابتي", "portal.home"),
    _f("portal.materials", "المكتبة الرقمية", "portal.materials", "portal.material_new"),
    _f("portal.pickup", "نداء استلام الطالب",
       "portal.pickup_home", "portal.pickup_call", "portal.pickup_ack", "portal.pickup_release",
       "portal.pickup_active_json"),
)

FEATURES_BY_KEY = {f.key: f for f in FEATURES}
FEATURE_KEYS: tuple[str, ...] = tuple(f.key for f in FEATURES)
ESSENTIAL_FEATURES = frozenset(f.key for f in FEATURES if f.essential)
_ENDPOINT_TO_FEATURE = {ep: f.key for f in FEATURES for ep in f.endpoints}
_feature_log = logging.getLogger(__name__)


def feature_for_endpoint(endpoint: str | None) -> str | None:
    """The feature owning a web endpoint; None for API / platform / app routes."""
    return _ENDPOINT_TO_FEATURE.get(endpoint or "")


def _compute_features(school_id: int) -> frozenset[str]:
    from ..models import SchoolFeatureOverride
    modules = enabled_modules(school_id)
    overrides = {o.feature_key: o.enabled
                 for o in SchoolFeatureOverride.query.filter_by(school_id=school_id)}
    on = set()
    for f in FEATURES:
        if f.essential:
            on.add(f.key)
        elif f.module in modules and overrides.get(f.key, f.default_on):
            on.add(f.key)
    return frozenset(on)


def effective_features(school_id: int | None) -> frozenset[str]:
    """The school's features that are on (once per request)."""
    if school_id is None:
        return frozenset(FEATURE_KEYS)
    if has_request_context():
        cache = g.setdefault("_effective_features", {})
        if school_id not in cache:
            cache[school_id] = _compute_features(int(school_id))
        return cache[school_id]
    return _compute_features(int(school_id))


def feature_enabled(school_id: int | None, key: str | None) -> bool:
    """None key / platform user (school_id None) → on; unknown key → off."""
    if key is None or school_id is None:
        return True
    if key not in FEATURES_BY_KEY:
        _feature_log.warning("feature_enabled: unknown feature %r", key)
        return False
    return key in effective_features(school_id)


def feature_sources(school_id: int) -> list[dict]:
    """For the console: each module with its features — effective state,
    where it comes from (essential / module_off / override / default),
    the override and its reason, and the default."""
    from ..models import SchoolFeatureOverride
    modules = {row["module"].key: row for row in module_sources(school_id)}
    overrides = {o.feature_key: o for o in SchoolFeatureOverride.query.filter_by(school_id=school_id)}
    out = []
    for m in MODULES:
        mrow = modules[m.key]
        feats = []
        for f in FEATURES:
            if f.module != m.key:
                continue
            o = overrides.get(f.key)
            if f.essential:
                on, source = True, "essential"
            elif not mrow["enabled"]:
                on, source = False, "module_off"
            elif o is not None:
                on, source = o.enabled, "override"
            else:
                on, source = f.default_on, "default"
            feats.append({"feature": f, "enabled": on, "source": source, "override": o,
                          "stored": (o.enabled if o is not None else f.default_on),
                          "default_on": f.default_on})
        out.append({**mrow, "features": feats})
    return out


def set_feature_overrides(school, changes: dict, reason: str, user, *, record: bool = True) -> dict:
    """Apply {feature_key: True | False | None} for one school (None = back
    to the default). All or nothing: an unknown or essential key, or an
    empty reason, refuses everything. A value equal to the default stores
    no row (the override is removed instead). Writes one subscription
    event and one platform audit line with the before / after of what
    changed. The caller commits. Returns {key: (before, after)}."""
    from ..models import SchoolFeatureOverride
    from .platform_auth import audit
    from .subscriptions import SubscriptionError, _event
    reason = (reason or "").strip()
    if not reason:
        raise SubscriptionError("السبب مطلوب.")
    unknown = sorted(k for k in changes if k not in FEATURES_BY_KEY)
    if unknown:
        raise SubscriptionError(f"صفحات غير معروفة: {', '.join(unknown)}")
    essential = sorted(k for k in changes if k in ESSENTIAL_FEATURES)
    if essential:
        names = "، ".join(FEATURES_BY_KEY[k].label_ar for k in essential)
        raise SubscriptionError(f"صفحات أساسية لا يمكن إيقافها: {names}")
    rows = {o.feature_key: o for o in SchoolFeatureOverride.query.filter_by(school_id=school.id)}
    diff = {}
    for key, want in changes.items():
        f = FEATURES_BY_KEY[key]
        row = rows.get(key)
        before = row.enabled if row is not None else f.default_on
        after = f.default_on if want is None else bool(want)
        if after == f.default_on:
            if row is not None:
                db.session.delete(row)
        else:
            if row is None:
                row = SchoolFeatureOverride(school_id=school.id, feature_key=key)
                db.session.add(row)
            row.enabled = after
            row.reason = reason
            row.updated_by_platform_user_id = getattr(user, "id", None)
        if before != after:
            diff[key] = (before, after)
    if diff and record:
        before_s = ",".join(f"{k}:{v[0]}" for k, v in sorted(diff.items()))
        after_s = ",".join(f"{k}:{v[1]}" for k, v in sorted(diff.items()))
        _event(school.id, "feature_override", before_s[:255], after_s[:255], reason, user)
        audit("feature_override", user, school_id=school.id,
              changes={k: {"before": v[0], "after": v[1]} for k, v in diff.items()})
    if has_request_context():
        g.pop("_effective_features", None)
    return diff


def _state(v) -> str:
    return "plan" if v is None else ("on" if v else "off")


def set_school_access(school, modules: dict, features: dict, reason: str, user) -> dict:
    """The console's one save: module states {key: True | False | None
    (the plan)} and feature states {key: True | False | None (default)}
    under one reason. All or nothing — any refusal raises before a row is
    written (the caller rolls back). Only what really changes is written,
    as ONE subscription event and ONE platform audit line with the before /
    after of every module and page. Returns {"modules": {...}, "features": {...}}."""
    from ..models import SchoolModuleOverride
    from .platform_auth import audit
    from .subscriptions import SubscriptionError, _event
    reason = (reason or "").strip()
    if not reason:
        raise SubscriptionError("السبب مطلوب.")
    bad = sorted(k for k in modules if k not in TOGGLEABLE)
    if bad:
        raise SubscriptionError(f"موديولات أساسية أو غير معروفة: {', '.join(bad)}")
    current = {o.module_key: o.enabled for o in SchoolModuleOverride.query.filter_by(school_id=school.id)}
    mod_diff = {}
    for key, want in modules.items():
        before = current.get(key)
        if before != want:
            mod_diff[key] = (before, want)
    # features are validated (unknown / essential) before anything is written
    feat_diff = set_feature_overrides(school, features, reason, user, record=False) if features else {}
    for key, (_before, want) in mod_diff.items():
        set_override(school, key, want, reason, user, record=False)
    if mod_diff or feat_diff:
        kind = "feature_override" if feat_diff else "module_override"
        parts_before = [f"{k}:{_state(b)}" for k, (b, _a) in sorted(mod_diff.items())] +                        [f"{k}:{_state(b)}" for k, (b, _a) in sorted(feat_diff.items())]
        parts_after = [f"{k}:{_state(a)}" for k, (_b, a) in sorted(mod_diff.items())] +                       [f"{k}:{_state(a)}" for k, (_b, a) in sorted(feat_diff.items())]
        _event(school.id, kind, ", ".join(parts_before)[:255], ", ".join(parts_after)[:255], reason, user)
        audit(kind, user, school_id=school.id,
              modules={k: {"before": _state(b), "after": _state(a)} for k, (b, a) in mod_diff.items()},
              changes={k: {"before": b, "after": a} for k, (b, a) in feat_diff.items()})
    return {"modules": mod_diff, "features": feat_diff}
