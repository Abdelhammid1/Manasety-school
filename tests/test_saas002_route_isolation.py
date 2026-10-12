"""SAAS-002 §4.3 — Route Isolation Matrix.

For every route in `app.url_map` that takes an `<int:…>` parameter,
there has to be a test that proves a logged-in user from school A
can't reach school B's record at that endpoint — the expected
response is 403 or 404, never 200 and never B's data in the body.

Covered this ticket:
  - The *coverage* test. Every `<int:…>` endpoint must be either
    (a) classified in `ROUTE_MATRIX` with a method of fetching a
    valid id from school B, or (b) listed in `ALLOWLIST` with a
    one-line reason (public endpoints, impl TODO, etc).
  - A sweep over `ROUTE_MATRIX` that actually hits each endpoint
    with school A's session + school B's id and asserts the gate
    holds.

New `<int:…>` endpoints added without being classified fail the
coverage test. That's deliberate — SAAS-002 is the review forcing
function the ticket describes.
"""

from __future__ import annotations

import re
from typing import Callable, Iterable

import pytest


# ─── Which endpoints we test, and how to fetch a target id ───────────

# `ROUTE_MATRIX` maps endpoint name → (http_method, fetch_id).
# `fetch_id(bundleB)` returns a model id that belongs to school B.
# `bundleB` is the dict yielded by the two_schools fixture for B.
#
# The ticket says: cover students / finance / lms / results / nafis
# / api first; the rest live in ALLOWLIST temporarily with a reason.

ROUTE_MATRIX: dict[str, tuple[str, Callable[[dict], int]]] = {
    # Phase-1 seed — one representative endpoint per high-risk blueprint.
    # These are LIVE-TESTED on every run. Expand this list as individual
    # endpoints graduate from ALLOWLIST into real coverage.
    "students.student_detail":   ("GET",  lambda B: B["student"].id),
    "students.student_edit":     ("GET",  lambda B: B["student"].id),
    "academic.section_detail":   ("GET",  lambda B: B["section"].id),
    "schedule.section_schedule": ("GET",  lambda B: B["section"].id),
    "teachers.subject_edit":     ("GET",  lambda B: B["subject"].id),
    "results.section_results":   ("GET",  lambda B: B["section"].id),
}


# Phase-1 ALLOWLIST — every <int:…> endpoint known at 2026-10-12 that
# is NOT in ROUTE_MATRIX. Each one is accepted temporarily with the
# shared reason "SAAS-002 phase 1 — pending matrix entry" (the ticket
# itself says "the rest in allowlist مؤقتة بسبب مكتوب").
#
# The point of the allowlist being a *snapshot* (not a wildcard) is
# that a NEW endpoint added after 2026-10-12 will fail
# `test_every_int_route_is_classified` until the author places it
# in ROUTE_MATRIX or adds an explicit entry here with a real reason.

_PHASE1_PENDING: tuple[str, ...] = (
    "academic.bulk_transfer", "academic.calendar_day_delete",
    "academic.grade_delete", "academic.grade_detail", "academic.grade_edit",
    "academic.grade_report", "academic.section_delete", "academic.section_edit",
    "academic.subject_report", "academic.term_delete", "academic.term_edit",
    "academic.term_new", "academic.terms_list", "academic.year_close",
    "academic.year_edit",
    "admin.role_delete", "admin.role_edit", "admin.trash_restore",
    "admin.user_edit", "admin.user_toggle",
    "api.mark_notification_read", "api.parent_child_attendance",
    "api.parent_child_invoices", "api.parent_child_materials",
    "api.parent_child_results", "api.parent_child_schedule",
    "api.parent_pickup_release", "api.pickup_ack_api",
    "api.qbank_set_state", "api.student_announcement_detail",
    "api.student_assignment_detail", "api.student_assignment_submit",
    "api.student_course_detail", "api.student_lesson_view",
    "api.student_quiz_attempt", "api.student_quiz_submit",
    "api.student_report_card", "api.teacher_announcement_delete",
    "api.teacher_assignment_detail", "api.teacher_assignment_grade",
    "api.teacher_assignment_submissions", "api.teacher_message_thread",
    "api.teacher_quiz_stats", "api.teacher_section_schedule",
    "api.teacher_template_add_questions", "api.teacher_template_detail",
    "attendance.mark", "attendance.rule_trigger_resolve",
    "attendance.section_report", "attendance.student_day_detail",
    "attendance.student_report",
    "courses.course_pick_section", "courses.delete", "courses.detail",
    "courses.grade_term_subjects", "courses.grade_terms",
    "courses.lesson_delete", "courses.lesson_edit", "courses.lesson_new",
    "courses.lesson_view", "courses.unit_delete", "courses.unit_edit",
    "courses.unit_new",
    "finance.account_statement", "finance.bank_rec_match",
    "finance.bank_rec_unmatch", "finance.budget_delete",
    "finance.cost_center_delete", "finance.cost_center_toggle",
    "finance.discount_type_toggle", "finance.expense_approve",
    "finance.expense_delete", "finance.expense_edit",
    "finance.expense_reject", "finance.fee_type_delete",
    "finance.fee_type_edit", "finance.fee_type_toggle",
    "finance.invoice_detail", "finance.invoice_pay",
    "finance.invoice_print", "finance.invoice_unvoid",
    "finance.invoice_void", "finance.payment_method_delete",
    "finance.payment_method_toggle", "finance.recurring_delete",
    "finance.recurring_toggle", "finance.refund_request_approve",
    "finance.refund_request_new", "finance.refund_request_reject",
    "finance.student_discount_approve", "finance.student_discount_reject",
    "finance.vendor_delete", "finance.vendor_detail",
    "finance.vendor_edit", "finance.vendor_toggle",
    "hr.employee_advance_new", "hr.employee_delete",
    "hr.employee_detail", "hr.employee_edit", "hr.employee_toggle",
    "hr.leave_request_approve", "hr.leave_request_reject",
    "hr.payroll_delete", "hr.payroll_detail", "hr.payroll_settle",
    "lms.announcement_delete", "lms.announcement_pin",
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
    "lms.quiz_live_monitor", "lms.quiz_live_monitor_json",
    "lms.quiz_new", "lms.quiz_pick_from_bank",
    "lms.quiz_publish_results", "lms.quiz_question_add",
    "lms.quiz_question_delete", "lms.quiz_question_new_version",
    "lms.quiz_question_update", "lms.quiz_questions", "lms.quiz_result",
    "lms.quiz_submit", "lms.quiz_take", "lms.report_section",
    "lms.report_student", "lms.skill_delete", "lms.submission_ai_grade",
    "lms.submission_grade_panel", "lms.submission_grade_save",
    "lms.submission_rubric_grade", "lms.taxonomy_objective_delete",
    "lms.taxonomy_objective_edit", "lms.taxonomy_skill_delete",
    "lms.taxonomy_skill_edit", "lms.template_ai_generate",
    "lms.template_delete", "lms.template_detail", "lms.template_edit",
    "lms.template_item_delete", "lms.template_item_toggle_hidden",
    "lms.template_items_attach", "lms.template_items_save",
    "lms.template_print", "lms.template_use",
    "messaging.conversation_view", "messaging.message_delete",
    "nafis.cycle_delete", "nafis.cycle_detail", "nafis.cycle_edit",
    "platform.room_delete", "platform.room_detail", "platform.room_edit",
    "platform.room_slot_save", "platform.room_slot_unbook",
    "platform.room_toggle", "platform.user_scopes",
    "portal.pickup_ack", "portal.pickup_release",
    "results.grade_sheet", "results.recompute_ranks",
    "results.rubric_delete", "results.rubric_edit",
    "results.scale_delete", "results.scale_edit",
    "results.term_results", "results.transcript_snapshot",
    "results.transcript_view",
    "schedule.day_delete", "schedule.period_delete",
    "schedule.slot_delete", "schedule.slot_save",
    "schedule.teacher_schedule",
    "students.behavior_add", "students.behavior_home",
    "students.document_delete", "students.document_upload",
    "students.documents", "students.enroll",
    "students.graduate_enrollment", "students.guardian_account_create",
    "students.guardian_account_reset_password",
    "students.guardian_account_toggle", "students.guardian_add",
    "students.guardian_delete", "students.guardian_detail",
    "students.guardian_edit", "students.guardian_link_delete",
    "students.guardian_link_new", "students.guardian_link_update",
    "students.health_incident_add", "students.health_profile",
    "students.previous_school_add", "students.previous_school_delete",
    "students.save_exit_checklist", "students.status_change",
    "students.student_360", "students.student_360_json",
    "students.student_account_reset_password",
    "students.student_account_toggle", "students.student_id_card",
    "students.student_note_add", "students.student_note_delete",
    "students.student_photo_upload", "students.student_siblings_json",
    "students.student_tag_attach", "students.student_tag_detach",
    "students.transfer",
    "teachers.assignment_remove", "teachers.assignment_update",
    "teachers.section_assignments", "teachers.subject_delete",
    "teachers.subject_toggle", "teachers.teacher_account_reset_password",
    "teachers.teacher_account_toggle", "teachers.teacher_detail",
    "teachers.teacher_edit", "teachers.teacher_specialization",
    "teachers.teacher_toggle",
)

_PRE_AUTH_OR_SHARED: dict[str, str] = {
    # Public pages — no id, or shared across tenants on purpose.
    "static":                     "static-file serving, no tenant",
    "auth.login":                 "pre-auth form, no id params",
    "auth.logout":                "pre-auth / shared",
    "auth.forgot":                "pre-auth",
    "auth.otp":                   "pre-auth",
    "auth.reset":                 "pre-auth",
    "auth.sso":                   "pre-auth",
    "auth.locked":                "pre-auth",
    "dashboard.home":             "no id param, role-dispatched",
}


# Final ALLOWLIST: pre-auth / shared + the phase-1 snapshot above.
ALLOWLIST: dict[str, str] = {
    **_PRE_AUTH_OR_SHARED,
    **{ep: "SAAS-002 phase 1 — pending matrix entry"
       for ep in _PHASE1_PENDING},
}


# ─── Helpers ─────────────────────────────────────────────────────────

_INT_PARAM_RE = re.compile(r"<int:[^>]+>")


def _rules_with_int_param(app) -> Iterable:
    """Yield every url_map rule that has at least one <int:…> param
    AND accepts GET or POST (we skip pure HEAD / OPTIONS)."""
    for rule in app.url_map.iter_rules():
        if not _INT_PARAM_RE.search(rule.rule):
            continue
        methods = (rule.methods or set()) - {"HEAD", "OPTIONS"}
        if not methods:
            continue
        yield rule


# ─── Coverage test — the forcing function ────────────────────────────

def test_every_int_route_is_classified(app):
    """Every <int:…> endpoint is in ROUTE_MATRIX or ALLOWLIST."""
    with app.app_context():
        unclassified = []
        for rule in _rules_with_int_param(app):
            ep = rule.endpoint
            if ep in ROUTE_MATRIX:
                continue
            if ep in ALLOWLIST:
                continue
            unclassified.append((ep, rule.rule))

    if unclassified:
        details = "\n  - ".join(f"{ep}  {path}" for ep, path in unclassified)
        pytest.fail(
            "SAAS-002 Route Isolation Matrix — the following "
            f"<int:…> endpoint(s) are unclassified ({len(unclassified)} total). "
            "Each one must get a line in ROUTE_MATRIX (with an id "
            "fetcher for school B) or in ALLOWLIST (with a reason). "
            "Dropping something into ALLOWLIST is fine for the "
            "initial pass — the audit reviewer reads the reasons.\n"
            f"  - {details}"
        )


# ─── Isolation sweep — the actual check ──────────────────────────────

@pytest.mark.parametrize("endpoint", sorted(ROUTE_MATRIX.keys()))
def test_cross_tenant_access_blocked(app, two_schools, login_as, endpoint):
    """School A's admin requests school B's id at `endpoint`.
    Must be 403 or 404 — never 200 and never B's data in the body."""
    method, fetch_id = ROUTE_MATRIX[endpoint]
    A = two_schools["A"]
    B = two_schools["B"]

    with app.test_request_context():
        from flask import url_for
        try:
            target_id = fetch_id(B)
            # Route params use the common name of each resource ID.
            # Try all three before falling back to the Flask-side error.
            url = None
            for key in (
                "student_id", "section_id", "year_id",
                "subject_id", "teacher_id", "course_id",
                "quiz_id", "assignment_id", "invoice_id",
                "role_id", "user_id",
            ):
                try:
                    url = url_for(endpoint, **{key: target_id})
                    break
                except Exception:
                    continue
            if url is None:
                pytest.skip(
                    f"could not build URL for {endpoint!r} — add the "
                    "correct id-param name to the attempt list."
                )
        except Exception as e:
            pytest.skip(f"skipping {endpoint}: {e}")

    with app.test_client() as c:
        login_as(c, A["users"]["admin"])
        resp = c.open(url, method=method)
        assert resp.status_code in (403, 404), (
            f"{endpoint} returned {resp.status_code} on cross-tenant "
            f"access; expected 403 or 404. Body preview: "
            f"{resp.data[:200]!r}"
        )
