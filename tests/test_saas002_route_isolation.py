"""SAAS-002 §4.3 / SAAS-012 — Route Isolation Matrix.

Every route with an `<int:…>` parameter must be either in ROUTE_MATRIX
(attacked on every run) or in ALLOWLIST with a written reason. Pending
endpoints are tagged with the SAAS ticket that will cover them.

What a matrix entry is attacked with (all under
TENANT_RESOLUTION_MODE=enforce, on school A's host):

  * school A user (each listed role) + school B's ids → 403/404, no B
    data in the body, and for writes B's snapshot is unchanged;
  * no session at all → 302 to login or 401;
  * multi-id rules: A's id mixed with B's id → refused;
  * A's session presented on B's host → the SAAS-006 kill hook drops it.

A URL that cannot be built from `rule.arguments` is a FAILURE. The
only way to not run an entry is `Entry(skip="<written reason>")`.

Endpoints that take an id from the form / query string are tracked
separately (FORM_ID_MATRIX / FORM_ID_PENDING), discovered by scanning
view source for `request.form/args/values/json …_id`.

Known gaps found by this sweep are listed in KNOWN_GAPS with the
ticket that fixes them; they run as strict xfails so a fix flips them
red until the entry is removed.
"""

from __future__ import annotations

import inspect
import io
import re
from pathlib import Path
from typing import Iterable

import pytest

from isolation_harness import (
    Entry, HarnessError, build_url, check_blocked, host, rule_for, ticket_for,
)


def _section_state(B):
    from app.extensions import db
    from app.models import Section
    s = db.session.get(Section, B["section"].id)
    return (s.name, s.capacity) if s else None


def _grade_state(B):
    from app.extensions import db
    from app.models import Grade
    g = db.session.get(Grade, B["grade"].id)
    return (g.name, g.order_index) if g else None


def _subject_state(B):
    from app.extensions import db
    from app.models import Subject
    s = db.session.get(Subject, B["subject"].id)
    return (s.name, s.is_active) if s else None


def _row(model: str, key: str, side: str = "B"):
    """Snapshot = the target row (all columns, soft-deleted included)
    + both schools' ledger fingerprint. side="A" reads the peer's id,
    for form-mixing attacks where A's own record is the one at risk."""
    def snap(B):
        from sqlalchemy import select
        from app import models as M
        from app.extensions import db
        from world import ledger_state
        cls = getattr(M, model)
        rid = B["peer"][key] if side == "A" else B[key]
        rid = getattr(rid, "id", rid)          # bundles hold ORM rows for the basics
        row = db.session.execute(
            select(cls.__table__).where(cls.__table__.c.id == rid)
        ).mappings().first()
        return (dict(row) if row else None, ledger_state(B["pair"]))
    return snap


def _fin(key, model, param, methods=("POST",), form=None, roles=("admin",)):
    return Entry(lambda B, k=key, p=param: {p: B[k]}, methods=methods,
                 form=form, roles=roles,
                 snapshot=_row(model, key) if any(m != "GET" for m in methods) else None)


def _id(v):
    return getattr(v, "id", v)


def _cnt(model: str, col: str, key: str):
    """Snapshot = how many `model` rows (any school) point at B's `key`,
    + both ledgers: a cross-tenant create shows up as +1."""
    def snap(B):
        from app import models as M
        from world import ledger_state
        cls = getattr(M, model)
        return (cls.query.filter(getattr(cls, col) == _id(B[key])).count(), ledger_state(B["pair"]))
    return snap


def _tag_links(B):
    from app.extensions import db
    from app.models.student import student_tag_links as t
    return len(db.session.execute(t.select().where(t.c.student_id == B["student"].id)).fetchall())


def _ent(key, model, param, methods=("POST",), form=None, roles=("admin",), snapshot=None, extra=None):
    """URL id = B's `key`; writes snapshot B's row (or `snapshot`)."""
    def ids(B, k=key, p=param):
        out = {p: _id(B[k])}
        out.update(extra(B) if extra else {})
        return out
    writes = any(m != "GET" for m in methods)
    return Entry(ids, methods=methods, form=form, roles=roles,
                 snapshot=(snapshot or (_row(model, key) if writes else None)))


def _user_row(key):
    """B's portal account: password hash + active flag must not move."""
    def snap(B):
        from app.extensions import db
        from app.models import User
        u = db.session.get(User, B[key])
        return (u.password_hash, u.is_active) if u else None
    return snap


PNG_BYTES = b"\x89PNG\r\n\x1a\n0"


# ─── Matrix ──────────────────────────────────────────────────────────

ROUTE_MATRIX: dict[str, Entry] = {
    # SAAS-002 seed (GET).
    "students.student_detail":   Entry(lambda B: {"student_id": B["student"].id},
                                       roles=("admin", "teacher")),
    "students.student_edit":     Entry(lambda B: {"student_id": B["student"].id}),
    "academic.section_detail":   Entry(lambda B: {"section_id": B["section"].id}),
    "schedule.section_schedule": Entry(lambda B: {"section_id": B["section"].id},
                                       roles=("admin", "teacher")),
    "teachers.subject_edit":     Entry(lambda B: {"subject_id": B["subject"].id}),
    "results.section_results":   Entry(lambda B: {"section_id": B["section"].id},
                                       roles=("admin", "teacher")),

    # SAAS-012 — writes, with a before/after snapshot of B's record.
    "academic.section_edit": Entry(
        lambda B: {"section_id": B["section"].id},
        methods=("GET", "POST"),
        form=lambda A, B: {"name": "HACKED-BY-A", "capacity": "99"},
        snapshot=_section_state,
    ),
    "academic.grade_edit": Entry(
        lambda B: {"grade_id": B["grade"].id},
        methods=("GET", "POST"),
        form=lambda A, B: {"name": "HACKED-BY-A", "order_index": "9"},
        snapshot=_grade_state,
    ),
    "teachers.subject_toggle": Entry(
        lambda B: {"subject_id": B["subject"].id},
        methods=("POST",),
        snapshot=_subject_state,
    ),

    # SAAS-012 — multi-id rules, plus an A/B mix.
    "results.term_results": Entry(
        lambda B: {"section_id": B["section"].id, "term_id": B["term"].id},
        roles=("admin", "teacher"),
        mixed=lambda A, B: {"section_id": A["section"].id, "term_id": B["term"].id},
    ),
    "courses.grade_term_subjects": Entry(
        lambda B: {"grade_id": B["grade"].id, "term_id": B["term"].id},
        mixed=lambda A, B: {"grade_id": A["grade"].id, "term_id": B["term"].id},
    ),

    # SAAS-013 — finance (32).
    "finance.account_statement": _fin("account", "Account", "aid", ("GET",)),
    "finance.bank_rec_match": _fin("bank_line", "BankStatementLine", "line_id",
                                   form=lambda A, B: {"journal_line_id": B["journal_line"]}),
    "finance.bank_rec_unmatch": _fin("bank_line", "BankStatementLine", "line_id"),
    "finance.budget_delete": _fin("budget", "Budget", "bid"),
    "finance.cost_center_delete": _fin("cost_center", "CostCenter", "cc_id"),
    "finance.cost_center_toggle": _fin("cost_center", "CostCenter", "cc_id"),
    "finance.discount_type_toggle": _fin("discount_type", "DiscountType", "dt_id"),
    "finance.expense_approve": _fin("expense", "Expense", "eid"),
    "finance.expense_delete": _fin("expense", "Expense", "exp_id"),
    "finance.expense_edit": _fin("expense", "Expense", "exp_id", ("GET", "POST"),
                                 form=lambda A, B: {"description": "HACK", "amount": "1",
                                                    "date": "2026-09-05"}),
    "finance.expense_reject": _fin("expense", "Expense", "eid",
                                   form=lambda A, B: {"reject_reason": "HACK"}),
    "finance.fee_type_delete": _fin("fee_type", "FeeType", "ft_id"),
    "finance.fee_type_edit": _fin("fee_type", "FeeType", "ft_id", ("GET", "POST"),
                                  form=lambda A, B: {"name": "HACK", "default_amount": "1"}),
    "finance.fee_type_toggle": _fin("fee_type", "FeeType", "ft_id"),
    "finance.invoice_detail": _fin("invoice", "Invoice", "invoice_id", ("GET",),
                                   roles=("admin", "parent")),
    "finance.invoice_pay": _fin("invoice", "Invoice", "invoice_id",
                                form=lambda A, B: {"amount": "10",
                                                   "payment_method_id": B["payment_method"]}),
    "finance.invoice_print": _fin("invoice", "Invoice", "invoice_id", ("GET",),
                                  roles=("admin", "parent")),
    "finance.invoice_unvoid": _fin("invoice", "Invoice", "invoice_id"),
    "finance.invoice_void": _fin("invoice", "Invoice", "invoice_id",
                                 form=lambda A, B: {"reason": "HACK"}),
    "finance.payment_method_delete": _fin("payment_method", "PaymentMethod", "pm_id"),
    "finance.payment_method_toggle": _fin("payment_method", "PaymentMethod", "pm_id"),
    "finance.recurring_delete": _fin("recurring", "RecurringFeeSchedule", "rid"),
    "finance.recurring_toggle": _fin("recurring", "RecurringFeeSchedule", "rid"),
    "finance.refund_request_approve": _fin("refund_request", "RefundRequest", "req_id"),
    "finance.refund_request_new": _fin("invoice", "Invoice", "invoice_id",
                                       form=lambda A, B: {"amount": "5", "reason": "HACK",
                                                          "payment_method_id": B["payment_method"]}),
    "finance.refund_request_reject": _fin("refund_request", "RefundRequest", "req_id",
                                          form=lambda A, B: {"reject_reason": "HACK"}),
    "finance.student_discount_approve": _fin("student_discount", "StudentDiscount", "sd_id"),
    "finance.student_discount_reject": _fin("student_discount", "StudentDiscount", "sd_id"),
    "finance.vendor_delete": _fin("vendor", "Vendor", "vendor_id"),
    "finance.vendor_detail": _fin("vendor", "Vendor", "vendor_id", ("GET",)),
    "finance.vendor_edit": _fin("vendor", "Vendor", "vendor_id", ("GET", "POST"),
                                form=lambda A, B: {"name": "HACK"}),
    "finance.vendor_toggle": _fin("vendor", "Vendor", "vendor_id"),

    # SAAS-013 — HR (10).
    "hr.employee_advance_new": _fin("employee", "Employee", "employee_id",
                                    form=lambda A, B: {"amount": "100",
                                                       "payment_method_id": B["payment_method"]}),
    "hr.employee_delete": _fin("employee", "Employee", "employee_id"),
    "hr.employee_detail": _fin("employee", "Employee", "employee_id", ("GET",)),
    "hr.employee_edit": _fin("employee", "Employee", "employee_id", ("GET", "POST"),
                             form=lambda A, B: {"full_name": "HACK", "job_title": "HACK"}),
    "hr.employee_toggle": _fin("employee", "Employee", "employee_id"),
    "hr.leave_request_approve": _fin("leave_request", "LeaveRequest", "req_id"),
    "hr.leave_request_reject": _fin("leave_request", "LeaveRequest", "req_id",
                                    form=lambda A, B: {"reject_reason": "HACK"}),
    "hr.payroll_delete": _fin("payroll", "Payroll", "payroll_id"),
    "hr.payroll_detail": _fin("payroll", "Payroll", "payroll_id", ("GET",)),
    "hr.payroll_settle": _fin("payroll", "Payroll", "payroll_id",
                              form=lambda A, B: {"payment_method_id": B["payment_method"],
                                                 "amount": "100"}),

    # SAAS-014 — students / attendance / portal (42).
    "attendance.mark": _ent("section", "Section", "section_id", ("GET", "POST"),
                            form=lambda A, B: {"date": "2026-09-07", f"status_{B['enrollment'].id}": "present"},
                            snapshot=_cnt("Attendance", "enrollment_id", "enrollment")),
    "attendance.rule_trigger_resolve": _ent("rule_trigger", "AttendanceRuleTriggered", "trigger_id"),
    "attendance.section_report": _ent("section", "Section", "section_id", ("GET",)),
    "attendance.student_day_detail": _ent("student", "Student", "student_id", ("GET",),
                                          extra=lambda B: {"date_str": "2026-09-06"}),
    "attendance.student_report": _ent("student", "Student", "student_id", ("GET",)),
    "portal.pickup_ack": _ent("pickup", "PickupCall", "cid"),
    "portal.pickup_release": _ent("pickup", "PickupCall", "cid"),
    "students.behavior_add": _ent("student", "Student", "student_id",
                                  form=lambda A, B: {"category_id": B["behavior_category"], "description": "HACK",
                                                     "incident_date": "2026-09-08"},
                                  snapshot=_cnt("BehaviorIncident", "student_id", "student")),
    "students.behavior_home": _ent("student", "Student", "student_id", ("GET",)),
    "students.document_delete": _ent("document", "StudentDocument", "doc_id"),
    "students.document_upload": _ent("student", "Student", "student_id",
                                     form=lambda A, B: {"document_type": "other",
                                                        "file": (io.BytesIO(b"%PDF-1.4 x"), "x.pdf")},
                                     snapshot=_cnt("StudentDocument", "student_id", "student")),
    "students.documents": _ent("student", "Student", "student_id", ("GET",)),
    "students.enroll": _ent("student", "Student", "student_id", ("GET", "POST"),
                            form=lambda A, B: {"section_id": B["section"].id, "year_id": B["year"].id},
                            snapshot=_cnt("Enrollment", "student_id", "student")),
    "students.graduate_enrollment": _ent("enrollment", "Enrollment", "enrollment_id"),
    "students.guardian_account_create": _ent("guardian", "Guardian", "guardian_id"),
    "students.guardian_account_reset_password": _ent("guardian", "Guardian", "guardian_id",
                                                     snapshot=_user_row("parent_user")),
    "students.guardian_account_toggle": _ent("guardian", "Guardian", "guardian_id",
                                             snapshot=_user_row("parent_user")),
    "students.guardian_add": _ent("student", "Student", "student_id",
                                  form=lambda A, B: {"full_name": "HACK", "phone": "0100"},
                                  snapshot=_cnt("StudentGuardian", "student_id", "student")),
    "students.guardian_delete": _ent("guardian", "Guardian", "guardian_id"),
    "students.guardian_detail": _ent("guardian", "Guardian", "guardian_id", ("GET",)),
    "students.guardian_edit": _ent("guardian", "Guardian", "guardian_id", ("GET", "POST"),
                                   form=lambda A, B: {"full_name": "HACK"}),
    "students.guardian_link_delete": _ent("guardian_link", "StudentGuardian", "link_id"),
    "students.guardian_link_new": _ent("guardian", "Guardian", "guardian_id",
                                       form=lambda A, B: {"student_id": B["student"].id, "relationship": "uncle"},
                                       snapshot=_cnt("StudentGuardian", "guardian_id", "guardian")),
    "students.guardian_link_update": _ent("guardian_link", "StudentGuardian", "link_id",
                                          form=lambda A, B: {"relationship": "HACK"}),
    "students.health_incident_add": _ent("student", "Student", "student_id",
                                         form=lambda A, B: {"description": "HACK", "incident_date": "2026-09-08"},
                                         snapshot=_cnt("HealthIncident", "student_id", "student")),
    "students.health_profile": _ent("student", "Student", "student_id", ("GET", "POST"),
                                    form=lambda A, B: {"allergies": "HACK"},
                                    snapshot=_row("StudentHealthProfile", "health_profile")),
    "students.previous_school_add": _ent("student", "Student", "student_id",
                                         form=lambda A, B: {"name": "HACK"},
                                         snapshot=_cnt("PreviousSchool", "student_id", "student")),
    "students.previous_school_delete": _ent("previous_school", "PreviousSchool", "row_id"),
    "students.save_exit_checklist": _ent("enrollment", "Enrollment", "enrollment_id",
                                         form=lambda A, B: {"books_returned": "1"}),
    "students.status_change": _ent("enrollment", "Enrollment", "enrollment_id", ("GET", "POST"),
                                   form=lambda A, B: {"status": "withdrawn", "reason": "HACK"}),
    "students.student_360": _ent("student", "Student", "student_id", ("GET",)),
    "students.student_360_json": _ent("student", "Student", "student_id", ("GET",)),
    "students.student_account_reset_password": _ent("student", "Student", "student_id",
                                                    snapshot=_user_row("student_user")),
    "students.student_account_toggle": _ent("student", "Student", "student_id",
                                            snapshot=_user_row("student_user")),
    "students.student_id_card": _ent("student", "Student", "student_id", ("GET",)),
    "students.student_note_add": _ent("student", "Student", "student_id",
                                      form=lambda A, B: {"body": "HACK"},
                                      snapshot=_cnt("StudentNote", "student_id", "student")),
    "students.student_note_delete": _ent("student_note", "StudentNote", "note_id"),
    "students.student_photo_upload": _ent("student", "Student", "student_id",
                                          form=lambda A, B: {"photo": (io.BytesIO(PNG_BYTES), "p.png")}),
    "students.student_siblings_json": _ent("student", "Student", "student_id", ("GET",)),
    "students.student_tag_attach": _ent("student", "Student", "student_id",
                                        form=lambda A, B: {"tag_id": B["student_tag"]},
                                        snapshot=_tag_links),
    "students.student_tag_detach": _ent("student", "Student", "student_id",
                                        form=lambda A, B: {"tag_id": B["student_tag"]},
                                        snapshot=_tag_links),
    "students.transfer": _ent("enrollment", "Enrollment", "enrollment_id", ("GET", "POST"),
                              form=lambda A, B: {"section_id": B["section"].id, "reason": "HACK"}),
}


# Gaps the sweep found; each is fixed by the named ticket. Strict xfail:
# once fixed the test passes, xfail(strict) turns red, remove the line.
KNOWN_GAPS: dict[tuple[str, str], str] = {}


# ─── Allowlist ───────────────────────────────────────────────────────

# Snapshot (not a wildcard) of <int:…> endpoints still waiting for a
# matrix entry. A new endpoint is NOT covered by this list and fails
# the coverage test until someone classifies it.
_PENDING: tuple[str, ...] = (
    "academic.bulk_transfer", "academic.calendar_day_delete",
    "academic.grade_delete", "academic.grade_detail", "academic.grade_report",
    "academic.section_delete", "academic.subject_report",
    "academic.term_delete", "academic.term_edit", "academic.term_new",
    "academic.terms_list", "academic.year_close", "academic.year_edit",
    "admin.role_delete", "admin.role_edit", "admin.trash_restore",
    "admin.user_edit", "admin.user_toggle", "api.mark_notification_read",
    "api.parent_child_attendance", "api.parent_child_invoices",
    "api.parent_child_materials", "api.parent_child_results",
    "api.parent_child_schedule", "api.parent_pickup_release",
    "api.pickup_ack_api", "api.qbank_set_state",
    "api.student_announcement_detail", "api.student_assignment_detail",
    "api.student_assignment_submit", "api.student_course_detail",
    "api.student_lesson_view", "api.student_quiz_attempt",
    "api.student_quiz_submit", "api.student_report_card",
    "api.teacher_announcement_delete", "api.teacher_assignment_detail",
    "api.teacher_assignment_grade", "api.teacher_assignment_submissions",
    "api.teacher_message_thread", "api.teacher_quiz_stats",
    "api.teacher_section_schedule", "api.teacher_template_add_questions",
    "api.teacher_template_detail", "courses.course_pick_section",
    "courses.delete", "courses.detail", "courses.grade_terms",
    "courses.lesson_delete", "courses.lesson_edit", "courses.lesson_new",
    "courses.lesson_view", "courses.unit_delete", "courses.unit_edit",
    "courses.unit_new", "lms.announcement_delete", "lms.announcement_pin",
    "lms.assignment_analytics", "lms.assignment_delete",
    "lms.assignment_detail", "lms.assignment_edit",
    "lms.assignment_extension_add", "lms.assignment_from_template",
    "lms.assignment_new", "lms.assignment_pick_from_bank",
    "lms.assignment_question_add", "lms.assignment_question_delete",
    "lms.assignment_question_new_version", "lms.assignment_question_update",
    "lms.assignment_questions", "lms.assignment_save_as_template",
    "lms.assignment_submit", "lms.attempt_autosave", "lms.attempt_flag",
    "lms.attempt_tab_switch", "lms.bank_ai_rewrite",
    "lms.bank_ai_rewrite_save", "lms.bank_archive", "lms.bank_delete",
    "lms.bank_edit", "lms.bank_rewrite_panel", "lms.bank_set_state",
    "lms.collection_add", "lms.feedback_template_delete",
    "lms.objective_delete", "lms.passage_delete", "lms.passage_edit",
    "lms.quiz_analysis", "lms.quiz_delete", "lms.quiz_edit",
    "lms.quiz_live_monitor", "lms.quiz_live_monitor_json", "lms.quiz_new",
    "lms.quiz_pick_from_bank", "lms.quiz_publish_results",
    "lms.quiz_question_add", "lms.quiz_question_delete",
    "lms.quiz_question_new_version", "lms.quiz_question_update",
    "lms.quiz_questions", "lms.quiz_result", "lms.quiz_submit",
    "lms.quiz_take", "lms.report_section", "lms.report_student",
    "lms.skill_delete", "lms.submission_ai_grade",
    "lms.submission_grade_panel", "lms.submission_grade_save",
    "lms.submission_rubric_grade", "lms.taxonomy_objective_delete",
    "lms.taxonomy_objective_edit", "lms.taxonomy_skill_delete",
    "lms.taxonomy_skill_edit", "lms.template_ai_generate",
    "lms.template_delete", "lms.template_detail", "lms.template_edit",
    "lms.template_item_delete", "lms.template_item_toggle_hidden",
    "lms.template_items_attach", "lms.template_items_save",
    "lms.template_print", "lms.template_use", "messaging.conversation_view",
    "messaging.message_delete", "nafis.cycle_delete", "nafis.cycle_detail",
    "nafis.cycle_edit", "platform.room_delete", "platform.room_detail",
    "platform.room_edit", "platform.room_slot_save",
    "platform.room_slot_unbook", "platform.room_toggle",
    "platform.user_scopes", "results.grade_sheet", "results.recompute_ranks",
    "results.rubric_delete", "results.rubric_edit", "results.scale_delete",
    "results.scale_edit", "results.transcript_snapshot",
    "results.transcript_view", "schedule.day_delete", "schedule.period_delete",
    "schedule.slot_delete", "schedule.slot_save", "schedule.teacher_schedule",
    "teachers.assignment_remove", "teachers.assignment_update",
    "teachers.section_assignments", "teachers.subject_delete",
    "teachers.teacher_account_reset_password",
    "teachers.teacher_account_toggle", "teachers.teacher_detail",
    "teachers.teacher_edit", "teachers.teacher_specialization",
    "teachers.teacher_toggle",
)

_PRE_AUTH_OR_SHARED: dict[str, str] = {
    "static":         "static-file serving, no tenant",
    "auth.login":     "pre-auth form, no id params",
    "auth.logout":    "pre-auth / shared",
    "auth.forgot":    "pre-auth",
    "auth.otp":       "pre-auth",
    "auth.reset":     "pre-auth",
    "auth.sso":       "pre-auth",
    "auth.locked":    "pre-auth",
    "dashboard.home": "no id param, role-dispatched",
    "saas012_canary.leaky":
        "SAAS-012 canary — deliberately leaky, test-app only; "
        "test_harness_catches_leaky_canary proves the harness flags it",
    "saas012_canary.scoped":
        "SAAS-012 canary twin — correctly scoped, test-app only",
    "superadmin.plan_edit":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-025/026 console tests",
    "superadmin.plan_toggle":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-025/026 console tests",
    "superadmin.subscription_renew":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-025/026 console tests",
    "superadmin.subscription_extend":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-025/026 console tests",
    "superadmin.subscription_change_plan":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-025/026 console tests",
    "superadmin.subscription_trial":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-025/026 console tests",
    "superadmin.school_nginx_sync":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-029 console tests",
    "superadmin.school_module_set":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-030 console tests",
    "superadmin.school_limits_set":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-030 console tests",
    "superadmin.support_start":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-031 support tests",
    "superadmin.support_session_detail":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-031 support tests",
    "superadmin.support_revoke":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-031 support tests",
    "superadmin.school_edit":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-032 console tests",
    "superadmin.school_lifecycle":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-032 console tests",
    "superadmin.school_slug_change":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-032 console tests",
    "superadmin.school_staff":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-032 console tests",
    "superadmin.school_staff_action":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-032 console tests",
    "superadmin.school_note_add":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-032 console tests",
    "superadmin.school_contact_add":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-032 console tests",
    "superadmin.school_contact_delete":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-032 console tests",
    "superadmin.school_tags_set":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-032 console tests",
    "superadmin.announcement_delete":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-032 console tests",
    "superadmin.invoice_new":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-033 billing tests",
    "superadmin.invoice_detail":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-033 billing tests",
    "superadmin.invoice_issue":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-033 billing tests",
    "superadmin.invoice_void":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-033 billing tests",
    "superadmin.invoice_payment":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-033 billing tests",
    "superadmin.payment_reverse":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-033 billing tests",
    "superadmin.invoice_pdf":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-033 billing tests",
    "superadmin.school_statement":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-033 billing tests",
    "superadmin.alert_ack":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-034 monitoring tests",
    "superadmin.user_action":
        "platform console (no school tenant, the id is a platform user): 404 on every "
        "school host and when resolution is off — covered by the SAAS-036 tests",
    "superadmin.offboarding":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-035 offboarding tests",
    "superadmin.offboarding_step":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-035 offboarding tests",
    "superadmin.export_download":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-035 offboarding tests",
    "superadmin.app_card":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-037 contract tests",
    "superadmin.school_detail":
        "SAAS-025 platform console (no school tenant): 404 on every school host "
        "and when resolution is off — covered by tests/test_saas025_platform.py",
}

ALLOWLIST: dict[str, str] = {
    **_PRE_AUTH_OR_SHARED,
    **{ep: f"{ticket_for(ep)} — pending matrix entry" for ep in _PENDING},
}


# ─── Form / query-string ids ─────────────────────────────────────────

_FORM_ID_RE = re.compile(
    r"request\.(?:form|args|values)\.get(?:list)?\(\s*[\"'](\w*_id)[\"']")
_JSON_ID_RE = re.compile(r"request\.(?:get_json|json)[^\n]*?[\"'](\w*_id)[\"']")
_NOT_AN_FK = {"national_id"}


def discover_form_id_endpoints(app) -> dict[str, list[str]]:
    out = {}
    for ep, fn in app.view_functions.items():
        try:
            src = inspect.getsource(inspect.unwrap(fn))
        except (OSError, TypeError):
            continue
        ids = (set(_FORM_ID_RE.findall(src)) | set(_JSON_ID_RE.findall(src))) - _NOT_AN_FK
        if ids:
            out[ep] = sorted(ids)
    return out


def _section_count_for_grade(B):
    from app.models import Section
    return Section.query.filter_by(grade_id=B["grade"].id).count()


# endpoint -> (url_params(A,B), method, query/form(A,B), snapshot(B) or None)
def _mix(key, model, param, form):
    """A's own record in the URL, a B-owned id in the body; A's record
    and both ledgers must be untouched."""
    return Entry(lambda B, k=key, p=param: {p: B[k]}, methods=("POST",), form=form,
                 mixed=lambda A, B, k=key, p=param: {p: A[k]},
                 snapshot=_row(model, key, side="A"))


def _xlink(model: str, *cols: tuple[str, str]):
    """Snapshot = how many school-A rows of `model` point at each given
    B id (col, key), + both ledgers. Any increase is a cross-tenant link."""
    def snap(B):
        from app import models as M
        from world import ledger_state
        cls = getattr(M, model)
        a_id = B["pair"][0]
        def bid(key):
            v = B[key]
            return getattr(v, "id", v)
        counts = tuple(
            cls.query.filter(cls.school_id == a_id, getattr(cls, col) == bid(key)).count()
            for col, key in cols)
        return (counts, ledger_state(B["pair"]))
    return snap


def _post(form, snapshot):
    return Entry(lambda B: {}, methods=("POST",), form=form, snapshot=snapshot)


def _get_q(form):
    return Entry(lambda B: {}, form=form)


def _tag_link_count(B):
    """How many students carry B's tag (any school) — a cross link adds one."""
    from app.extensions import db
    from app.models.student import student_tag_links as t
    return len(db.session.execute(t.select().where(t.c.tag_id == B["student_tag"])).fetchall())


def _both(*snaps):
    def snap(B):
        return tuple(f(B) for f in snaps)
    return snap


def _in_a(param, key, methods=("POST",), form=None, snapshot=None):
    """A's own record in the URL, B's ids in the form."""
    return Entry(lambda B, k=key, p=param: {p: _id(B[k])}, methods=methods, form=form,
                 mixed=lambda A, B, k=key, p=param: {p: _id(A[k])}, snapshot=snapshot)


FORM_ID_MATRIX: dict[str, Entry] = {
    # SAAS-013 — creators that took an FK id from the body unchecked.
    "finance.account_new": _post(
        lambda A, B: {"parent_id": B["account"], "name": "x", "type": "asset", "code": "9991"},
        _xlink("Account", ("parent_id", "account"))),
    "finance.budget_new": _post(
        lambda A, B: {"account_id": B["account"], "cost_center_id": B["cost_center"],
                      "planned_amount": "1"},
        _xlink("Budget", ("account_id", "account"), ("cost_center_id", "cost_center"))),
    "finance.discount_type_new": _post(
        lambda A, B: {"name": "x", "applies_to_fee_type_id": B["fee_type"]},
        _xlink("DiscountType", ("applies_to_fee_type_id", "fee_type"))),
    "finance.student_discount_new": _post(
        lambda A, B: {"enrollment_id": B["enrollment"].id, "discount_type_id": A["discount_type"]},
        _xlink("StudentDiscount", ("enrollment_id", "enrollment"))),
    "finance.payment_method_new": _post(
        lambda A, B: {"name": "x", "kind": "immediate_cash", "account_id": B["account"]},
        _xlink("PaymentMethod", ("account_id", "account"))),
    "finance.recurring_new": _post(
        lambda A, B: {"fee_type_id": B["fee_type"], "frequency": "monthly",
                      "day_of_period": "1", "applies_to_grade_id": B["grade"].id},
        _xlink("RecurringFeeSchedule", ("fee_type_id", "fee_type"))),
    "finance.bank_rec_import": _post(
        lambda A, B: {"account_id": B["bank_account"],
                      "statement": (io.BytesIO(b"date,desc,amount\n2026-09-05,x,10\n"),
                                    "s.csv")},
        _xlink("BankStatementLine", ("bank_account_id", "bank_account"))),
    "finance.expense_new": _post(
        lambda A, B: {"amount": "10", "date": "2026-09-05", "description": "x",
                      "expense_account_id": A["account"],
                      "payment_method_id": A["payment_method"],
                      "cost_center_id": B["cost_center"]},
        _xlink("Expense", ("cost_center_id", "cost_center"))),
    "finance.petty_cash_issue": _post(
        lambda A, B: {"amount": "10", "payment_method_id": A["payment_method"],
                      "custodian_employee_id": B["employee"]},
        _xlink("PettyCashTransaction", ("custodian_employee_id", "employee"))),
    "finance.petty_cash_settle": _post(
        lambda A, B: {"amount": "10", "expense_account_id": B["account"]},
        _xlink("PettyCashTransaction", ("counter_account_id", "account"))),
    "finance.treasury_transfer": _post(
        lambda A, B: {"amount": "10", "from_account_id": A["account"],
                      "to_account_id": B["account"]},
        _xlink("JournalEntry")),   # ledger foreign_lines does the work
    "hr.leave_request_new": _post(
        lambda A, B: {"employee_id": B["employee"], "leave_type": "annual",
                      "start_date": "2026-09-13", "end_date": "2026-09-14"},
        _xlink("LeaveRequest", ("employee_id", "employee"))),
    "hr.leave_balance_new": _post(
        lambda A, B: {"employee_id": B["employee"], "leave_type": "annual",
                      "total_days": "5", "year": "2026"},
        _xlink("LeaveBalance", ("employee_id", "employee"))),
    "finance.journal": _get_q(lambda A, B: {"account_id": B["account"]}),
    "finance.report_general_ledger": _get_q(lambda A, B: {"account_id": B["account"]}),
    "finance.bank_rec": _get_q(lambda A, B: {"account_id": B["bank_account"]}),
    "finance.account_suggest_code": _get_q(lambda A, B: {"parent_id": B["account"]}),
    # Not found by the *_id scanner (params are year_a / year_b).
    "finance.report_year_comparison": _get_q(lambda A, B: {"year_a": B["year"].id,
                                                           "year_b": B["year"].id}),

    # SAAS-013 — second id from the body, mixed across schools.
    "finance.bank_rec_match": _mix("bank_line", "BankStatementLine", "line_id",
                                   lambda A, B: {"journal_line_id": B["journal_line"]}),
    "finance.invoice_pay": _mix("invoice", "Invoice", "invoice_id",
                                lambda A, B: {"amount": "10",
                                              "payment_method_id": B["payment_method"]}),
    "finance.refund_request_new": _mix("invoice", "Invoice", "invoice_id",
                                       lambda A, B: {"amount": "5", "reason": "x",
                                                     "payment_method_id": B["payment_method"]}),
    "finance.expense_edit": _mix("expense", "Expense", "exp_id",
                                 lambda A, B: {"description": "x", "amount": "50",
                                               "date": "2026-09-02",
                                               "vendor_id": B["vendor"],
                                               "payment_method_id": B["payment_method"]}),
    "hr.employee_advance_new": _mix("employee", "Employee", "employee_id",
                                    lambda A, B: {"amount": "100",
                                                  "payment_method_id": B["payment_method"]}),
    "hr.payroll_settle": _mix("payroll", "Payroll", "payroll_id",
                              lambda A, B: {"amount": "100",
                                            "payment_method_id": B["payment_method"]}),
    # SAAS-013B — the last finance / HR form ids.
    "finance.fee_type_new": _post(
        lambda A, B: {"name": "x", "default_amount": "1", "revenue_account_id": B["revenue_account"]},
        _xlink("FeeType", ("revenue_account_id", "revenue_account"))),
    "finance.fee_type_edit": _mix("fee_type", "FeeType", "ft_id",
                                  lambda A, B: {"name": "x", "default_amount": "1",
                                                "revenue_account_id": B["revenue_account"]}),
    "finance.invoice_new": _post(
        lambda A, B: {"enrollment_id": B["enrollment"].id, "fee_type_id": B["fee_type"], "amount": "10"},
        _xlink("Invoice", ("enrollment_id", "enrollment"))),
    "finance.bulk_payment": Entry(
        lambda B: {}, methods=("GET", "POST"),
        form=lambda A, B: {"guardian_id": B["guardian"], "payment_method_id": A["payment_method"],
                           "auto_fifo": "1", "total_amount": "10", f"amt_{B['invoice']}": "10"},
        snapshot=_xlink("Payment", ("invoice_id", "invoice"))),
    "finance.quick_journal_run": Entry(
        lambda B: {"key": "capital_increase"}, methods=("POST",),
        form=lambda A, B: {"amount": "10", "counter_account_id": B["account"], "description": "x"},
        snapshot=_xlink("JournalEntry")),
    "hr.payroll_new": _post(
        lambda A, B: {"employee_id": B["employee"], "period_year": "2026", "period_month": "10",
                      "base_salary": "1"},
        _xlink("Payroll", ("employee_id", "employee"))),
    # SAAS-014 — students / portal form ids (10).
    "students.behavior_add": _in_a("student_id", "student",
                                   form=lambda A, B: {"category_id": B["behavior_category"],
                                                      "description": "x", "incident_date": "2026-09-08"},
                                   snapshot=_xlink("BehaviorIncident", ("category_id", "behavior_category"))),
    "students.guardian_link_new": _in_a("guardian_id", "guardian",
                                        form=lambda A, B: {"student_id": B["student"].id, "relationship": "uncle"},
                                        snapshot=_cnt("StudentGuardian", "student_id", "student")),
    "students.guardian_new": _post(
        lambda A, B: {"full_name": "x", "phone": "0100", "student_ids": B["student"].id,
                      "primary_student_id": B["student"].id},
        _cnt("StudentGuardian", "student_id", "student")),
    "students.promotion": _post(
        lambda A, B: {"from_year_id": B["year"].id, "grade_id": B["grade"].id,
                      "promote_section_id": B["section"].id, "retain_section_id": B["section"].id},
        _both(_cnt("Enrollment", "section_id", "section"), _cnt("Enrollment", "student_id", "student"))),
    "students.student_detail": Entry(lambda B: {"student_id": B["student"].id},
                                     mixed=lambda A, B: {"student_id": A["student"].id},
                                     form=lambda A, B: {"new_enrollment_id": B["enrollment"].id}),
    "students.student_edit": _in_a("student_id", "student",
                                   form=lambda A, B: {"full_name": "x", "parent_user_id": B["parent_user"]},
                                   snapshot=_xlink("Student", ("parent_user_id", "parent_user"))),
    "students.student_new": _post(
        lambda A, B: {"full_name": "x", "parent_user_id": B["parent_user"],
                      "existing_guardian_id": B["guardian"]},
        _both(_xlink("Student", ("parent_user_id", "parent_user")),
              _cnt("StudentGuardian", "guardian_id", "guardian"))),
    "students.student_tag_attach": _in_a("student_id", "student",
                                         form=lambda A, B: {"tag_id": B["student_tag"]},
                                         snapshot=_tag_link_count),
    "students.student_tag_detach": _in_a("student_id", "student",
                                         form=lambda A, B: {"tag_id": B["student_tag"]},
                                         snapshot=_tag_link_count),
    "portal.pickup_call": _post(lambda A, B: {"student_id": B["student"].id},
                                _cnt("PickupCall", "student_id", "student")),
    "students.students_list": Entry(
        lambda B: {},
        form=lambda A, B: {"section_id": B["section"].id},
    ),
    "academic.section_new": Entry(
        lambda B: {},
        methods=("POST",),
        form=lambda A, B: {"grade_id": B["grade"].id, "name": "HACK-new"},
        snapshot=_section_count_for_grade,
    ),
}

# Console endpoints whose form ids point at PLATFORM tables (plans), not
# school data — no tenant to cross. Reason recorded per endpoint.
FORM_ID_PLATFORM: dict[str, str] = {
    "superadmin.subscription_change_plan": "plan_id → plans (platform table, SAAS-026)",
    "superadmin.subscription_trial": "plan_id → plans (platform table, SAAS-026)",
    "superadmin.invoice_new": "plan_id → plans (platform table, SAAS-033)",
}

FORM_ID_PENDING: tuple[str, ...] = (
    "academic.bulk_transfer", "admin.audit_log", "api.qbank_questions",
    "api.teacher_attendance_existing", "api.teacher_components",
    "api.teacher_grades_existing", "api.teacher_students",
    "api.teacher_templates", "api.teacher_upload", "courses.lesson_edit",
    "courses.lesson_new", "courses.new", "lms.announcement_new",
    "lms.assignment_edit", "lms.assignment_extension_add",
    "lms.assignment_from_template", "lms.assignment_new",
    "lms.assignment_pick_from_bank", "lms.bank_home", "lms.objective_new",
    "lms.qbank_dashboard", "lms.quiz_pick_from_bank", "lms.quiz_submit",
    "lms.skill_new", "lms.taxonomy_objective_edit",
    "lms.taxonomy_objective_new", "lms.taxonomy_skill_edit",
    "lms.taxonomy_skill_new", "lms.template_detail", "lms.template_home",
    "lms.template_use", "lms.templates_gallery", "messaging.conversation_new",
    "nafis.cycle_edit", "nafis.cycle_new", "platform.room_slot_save",
    "platform.substitution_new", "results.components", "results.rubric_edit",
    "results.rubric_new", "schedule.slot_save", "teachers.section_assignments",
)


# ─── Fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def enforce_app(app, monkeypatch):
    """Enforce-mode tenancy, CSRF off so a POST is judged on isolation,
    not on a missing token (a 400 must never pass as "blocked")."""
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    return app


def _int_rules(app) -> Iterable:
    for rule in app.url_map.iter_rules():
        if "<int:" in rule.rule and (rule.methods or set()) - {"HEAD", "OPTIONS"}:
            yield rule


def _cases(kind: str):
    out = []
    for ep, e in sorted(ROUTE_MATRIX.items()):
        if kind == "attack":
            for m in e.methods:
                for role in e.roles:
                    out.append(pytest.param(ep, m, role, id=f"{ep}-{m}-{role}",
                                            marks=_gap_mark(ep, m)))
        elif kind == "unauth":
            for m in e.methods:
                out.append(pytest.param(ep, m, id=f"{ep}-{m}"))
        elif kind == "mixed" and e.mixed:
            out.append(pytest.param(ep, id=ep, marks=_gap_mark(ep, "mixed")))
    return out


def _gap_mark(ep, axis):
    reason = KNOWN_GAPS.get((ep, axis))
    return [pytest.mark.xfail(strict=True, reason=reason)] if reason else []


# ─── Coverage / classification ───────────────────────────────────────

def test_every_int_route_is_classified(app):
    unclassified = [
        (r.endpoint, r.rule) for r in _int_rules(app)
        if r.endpoint not in ROUTE_MATRIX and r.endpoint not in ALLOWLIST
    ]
    assert not unclassified, (
        "Unclassified <int:…> endpoint(s) — add each to ROUTE_MATRIX "
        "(with an id fetcher for school B) or ALLOWLIST (with a reason):\n  - "
        + "\n  - ".join(f"{ep}  {path}" for ep, path in unclassified)
    )


def test_matrix_and_allowlist_do_not_overlap():
    both = sorted(set(ROUTE_MATRIX) & set(ALLOWLIST))
    assert not both, f"in both ROUTE_MATRIX and ALLOWLIST: {both}"


def test_every_pending_endpoint_names_its_ticket():
    bad = [ep for ep in _PENDING
           if not re.match(r"^SAAS-01[3-8] ", ALLOWLIST[ep])]
    assert not bad, f"pending endpoints without a SAAS-013..018 ticket: {bad}"


def test_every_allowlist_reason_is_written():
    blank = [ep for ep, why in ALLOWLIST.items() if len(why.strip()) < 8]
    assert not blank, f"ALLOWLIST entries without a real reason: {blank}"


def test_skips_carry_a_written_reason():
    for ep, e in {**ROUTE_MATRIX, **FORM_ID_MATRIX}.items():
        if e.skip:
            assert len(e.skip.strip()) >= 15, f"{ep}: skip reason too thin"


def test_matrix_urls_build_for_every_entry(app, world):
    """A fetcher whose params don't match the rule fails here — the old
    harness silently skipped these."""
    A, B = world["A"], world["B"]
    for ep, e in ROUTE_MATRIX.items():
        if e.skip:
            continue
        build_url(app, ep, e.ids(B), host(A))
        if e.mixed:
            build_url(app, ep, e.mixed(A, B), host(A))


def test_build_url_fails_loudly_on_wrong_params(app):
    with pytest.raises(HarnessError):
        build_url(app, "students.student_detail", {"section_id": 1},
                  "http://alpha.manasety.ai")
    with pytest.raises(HarnessError):
        rule_for(app, "no_such.endpoint")


# ─── Isolation sweep ─────────────────────────────────────────────────

@pytest.mark.parametrize("endpoint,method,role", _cases("attack"))
def test_cross_tenant_access_blocked(enforce_app, world, login_as,
                                     endpoint, method, role):
    app = enforce_app
    A, B = world["A"], world["B"]
    e = ROUTE_MATRIX[endpoint]
    url = build_url(app, endpoint, e.ids(B), host(A))
    with app.test_client() as c:
        login_as(c, A["users"][role], base_url=host(A))
        check_blocked(app, c, endpoint, e, method, url, A, B)


@pytest.mark.parametrize("endpoint", _cases("mixed"))
def test_mixed_tenant_ids_rejected(enforce_app, world, login_as, endpoint):
    app = enforce_app
    A, B = world["A"], world["B"]
    e = ROUTE_MATRIX[endpoint]
    assert e.mixed is not None
    url = build_url(app, endpoint, e.mixed(A, B), host(A))
    with app.test_client() as c:
        login_as(c, A["users"]["admin"], base_url=host(A))
        for m in e.methods:
            check_blocked(app, c, endpoint, e, m, url, A, B)


@pytest.mark.parametrize("endpoint,method", _cases("unauth"))
def test_unauthenticated_is_not_served(enforce_app, world, endpoint, method):
    app = enforce_app
    A, B = world["A"], world["B"]
    e = ROUTE_MATRIX[endpoint]
    url = build_url(app, endpoint, e.ids(A), host(A))
    with app.test_client() as c:
        r = c.open(url, method=method, base_url=host(A))
    assert r.status_code in (302, 401), f"{endpoint} {method} -> {r.status_code}"
    if r.status_code == 302:
        assert "/auth/login" in r.headers.get("Location", "")


def test_cross_tenant_session_is_killed(enforce_app, two_schools, login_as):
    """A's session cookie replayed on B's host: SAAS-006 kill hook logs
    it out and redirects to login; B's page is never rendered."""
    app = enforce_app
    A, B = two_schools["A"], two_schools["B"]
    url = build_url(app, "students.student_detail",
                    {"student_id": B["student"].id}, host(B))
    with app.test_client() as c:
        login_as(c, A["users"]["admin"], base_url=host(B))
        r = c.get(url, base_url=host(B))
        assert r.status_code == 302, r.status_code
        assert "/auth/login" in r.headers.get("Location", "")
        assert not any(m in r.get_data(as_text=True) for m in B["markers"])
        with c.session_transaction(base_url=host(B)) as sess:
            assert "_user_id" not in sess


# ─── Form / query ids ────────────────────────────────────────────────

def test_every_form_id_endpoint_is_classified(app):
    found = discover_form_id_endpoints(app)
    pending = set(FORM_ID_PENDING) | set(FORM_ID_PLATFORM)
    unclassified = sorted(ep for ep in found
                          if ep not in FORM_ID_MATRIX and ep not in pending)
    assert not unclassified, (
        "Endpoint(s) reading an *_id from form/query/json are unclassified — "
        "add to FORM_ID_MATRIX or FORM_ID_PENDING:\n  - "
        + "\n  - ".join(f"{ep} {found[ep]}" for ep in unclassified)
    )


@pytest.mark.parametrize("endpoint", sorted(FORM_ID_MATRIX))
def test_form_ids_from_other_school_rejected(enforce_app, world,
                                             login_as, endpoint):
    """B's id in the body / query with A's session: no B data back, no
    B-side effect, no crash. A form re-render (200) is an acceptable
    rejection here — the id is not the resource being addressed."""
    app = enforce_app
    A, B = world["A"], world["B"]
    e = FORM_ID_MATRIX[endpoint]
    params = e.mixed(A, B) if e.mixed else e.ids(B)
    url = build_url(app, endpoint, params, host(A))
    from isolation_harness import _snap
    with app.test_client() as c:
        login_as(c, A["users"]["admin"], base_url=host(A))
        for m in e.methods:
            before = _snap(app, e, B)
            payload = e.form(A, B) if e.form else {}
            if m == "GET":
                r = c.get(url, query_string=payload, base_url=host(A))
            else:
                r = c.open(url, method=m, data=payload, base_url=host(A))
            body = r.get_data(as_text=True)
            assert r.status_code < 500, f"{endpoint}: {r.status_code}"
            leaked = [mk for mk in B["markers"] if mk in body]
            assert not leaked, f"{endpoint}: B data in body {leaked}"
            assert _snap(app, e, B) == before, f"{endpoint}: B changed"


# ─── Test of the test ────────────────────────────────────────────────

def test_harness_catches_leaky_canary(enforce_app, two_schools, login_as):
    app = enforce_app
    A, B = two_schools["A"], two_schools["B"]
    e = Entry(lambda B: {"student_id": B["student"].id})
    url = build_url(app, "saas012_canary.leaky", e.ids(B), host(A))
    with app.test_client() as c:
        login_as(c, A["users"]["admin"], base_url=host(A))
        with pytest.raises(AssertionError, match="ISOLATION GAP"):
            check_blocked(app, c, "saas012_canary.leaky", e, "GET", url, A, B)


def test_harness_passes_scoped_canary(enforce_app, two_schools, login_as):
    app = enforce_app
    A, B = two_schools["A"], two_schools["B"]
    e = Entry(lambda B: {"student_id": B["student"].id})
    url = build_url(app, "saas012_canary.scoped", e.ids(B), host(A))
    with app.test_client() as c:
        login_as(c, A["users"]["admin"], base_url=host(A))
        check_blocked(app, c, "saas012_canary.scoped", e, "GET", url, A, B)
        # and the scoped twin still serves A's own student
        own = build_url(app, "saas012_canary.scoped",
                        {"student_id": A["student"].id}, host(A))
        assert c.get(own, base_url=host(A)).status_code == 200


# ─── Coverage report ─────────────────────────────────────────────────

REPORT_PATH = Path(__file__).parent / "_reports" / "saas012_isolation_report.md"


def build_coverage_report(app) -> str:
    rules = sorted({r.endpoint for r in _int_rules(app)} - {
        "saas012_canary.leaky", "saas012_canary.scoped"})
    total = len(rules)
    covered = [ep for ep in rules if ep in ROUTE_MATRIX]
    pending = [ep for ep in rules if ep in _PENDING]
    by_ticket: dict[str, int] = {}
    for ep in pending:
        by_ticket[ticket_for(ep)] = by_ticket.get(ticket_for(ep), 0) + 1
    form_found = discover_form_id_endpoints(app)
    form_cov = [ep for ep in form_found if ep in FORM_ID_MATRIX]
    lines = [
        "# SAAS-012 isolation coverage",
        "",
        f"- `<int:…>` endpoints: **{total}**",
        f"- in ROUTE_MATRIX: **{len(covered)}** ({len(covered) / total:.1%})",
        f"- pending: **{len(pending)}**",
        f"- form/query-id endpoints: **{len(form_found)}**, "
        f"covered **{len(form_cov)}**, pending **{len(form_found) - len(form_cov)}**",
        f"- known gaps (strict xfail): **{len(KNOWN_GAPS)}**",
        "",
        "| ticket | pending <int:> endpoints | pending form-id endpoints |",
        "|---|---|---|",
    ]
    form_by_ticket: dict[str, int] = {}
    for ep in FORM_ID_PENDING:
        form_by_ticket[ticket_for(ep)] = form_by_ticket.get(ticket_for(ep), 0) + 1
    for t in sorted(set(by_ticket) | set(form_by_ticket)):
        lines.append(f"| {t} | {by_ticket.get(t, 0)} | {form_by_ticket.get(t, 0)} |")
    lines += ["", "## Covered", ""] + [f"- `{ep}`" for ep in covered]
    if KNOWN_GAPS:
        lines += ["", "## Known gaps", ""] + [
            f"- `{ep}` [{axis}] — {why}" for (ep, axis), why in sorted(KNOWN_GAPS.items())]
    return "\n".join(lines) + "\n"


def test_coverage_report(app):
    report = build_coverage_report(app)
    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print("\n" + report)
    assert "endpoints" in report


# ─── Sweep rule: a foreign id and a missing id look the same ─────────

def _single_id_gets():
    out = []
    for ep, e in sorted(ROUTE_MATRIX.items()):
        if "GET" in e.methods and e.skip == "":
            out.append(pytest.param(ep, id=ep))
    return out


@pytest.mark.parametrize("endpoint", _single_id_gets())
def test_foreign_and_missing_ids_get_the_same_answer(enforce_app, world, login_as, endpoint):
    """No enumeration (isolation sweep, every ticket): B's id and an id
    that doesn't exist give the same status — and, apart from the id
    echoed in the page, the same body."""
    app = enforce_app
    A, B = world["A"], world["B"]
    e = ROUTE_MATRIX[endpoint]
    real = e.ids(B)
    fake = {k: (987654321 if isinstance(v, int) else v) for k, v in real.items()}
    with app.test_client() as c:
        login_as(c, A["users"][e.roles[0]], base_url=host(A))
        r1 = c.get(build_url(app, endpoint, real, host(A)), base_url=host(A))
        r2 = c.get(build_url(app, endpoint, fake, host(A)), base_url=host(A))
    assert r1.status_code == r2.status_code, f"{endpoint}: foreign {r1.status_code} vs missing {r2.status_code}"
    def norm(r):
        # the id is echoed in links / canonical URL: mask every number
        return re.sub(r"\d+", "N", r.get_data(as_text=True))
    assert norm(r1) == norm(r2), f"{endpoint}: foreign and missing pages differ"
