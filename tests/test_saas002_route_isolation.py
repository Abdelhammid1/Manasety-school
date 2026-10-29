"""SAAS-002 §4.3 / SAAS-012 — Route Isolation Matrix.

Every route with an `<int:…>` or `<hid:…>` parameter must be either in ROUTE_MATRIX
(attacked on every run) or in ALLOWLIST with a written reason. The
isolation sweep (SAAS-013B..018) closed the last pending endpoint: a
new route that is in neither fails CI until someone classifies it.

What a matrix entry is attacked with (all under
TENANT_RESOLUTION_MODE=enforce, on school A's host):

  * school A user (each listed role) + school B's ids → 403/404, no B
    data in the body, and for writes B's snapshot is unchanged;
  * no session at all → 302 to login or 401;
  * multi-id rules: A's id mixed with B's id → refused;
  * A's session presented on B's host → the SAAS-006 kill hook drops it.

A URL that cannot be built from `rule.arguments` is a FAILURE. The
only way to not run an entry is `Entry(skip="<written reason>")`.

Endpoints that take an id from the form / query string / JSON body
are tracked separately (FORM_ID_MATRIX, or FORM_ID_PLATFORM for platform
tables), discovered by scanning view source — and the same-module
helpers it calls — for `request.form/args/values/json …_id`.

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
    Entry, HarnessError, body_kwargs, build_url, check_blocked, host, rule_for,
)


@pytest.fixture
def login_as(login_as, app):
    """Session login + a Bearer token for the same user, so the matrix
    reaches the JWT-only mobile API (SAAS-017) with the same attacker.
    Web views ignore the Authorization header."""
    def _login(client, user, base_url=None):
        from app.services.auth_jwt import issue_token
        login_as(client, user, base_url=base_url)
        with app.app_context():
            client.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {issue_token(user)}"
    return _login


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


def _both(*snaps):
    def snap(B):
        return tuple(f(B) for f in snaps)
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

    # SAAS-015 / 016 — LMS (admin / teacher side, and the student path).
    "lms.announcement_delete": _ent("announcement", "Announcement", "aid", ('POST',), roles=("admin", "teacher")),
    "lms.announcement_pin": _ent("announcement", "Announcement", "aid", ('POST',), roles=("admin", "teacher")),
    "lms.assignment_analytics": _ent("assignment", "CourseAssignment", "aid", ('GET',), roles=("admin", "teacher")),
    "lms.assignment_delete": _ent("assignment", "CourseAssignment", "aid", ('POST',), roles=("admin", "teacher")),
    "lms.assignment_detail": _ent("assignment", "CourseAssignment", "aid", ('GET',), roles=("admin", "teacher")),
    "lms.assignment_edit": _ent("assignment", "CourseAssignment", "aid", ('GET', 'POST'), form=lambda A, B: {"title": "HACK"}, roles=("admin", "teacher")),
    "lms.assignment_extension_add": _ent("assignment", "CourseAssignment", "aid", ('POST',), form=lambda A, B: {"student_id": B["student"].id, "new_due_at": "2027-01-01T10:00"}, roles=("admin", "teacher")),
    "lms.assignment_from_template": _ent("course", "Course", "cid", ('GET', 'POST'), form=lambda A, B: {"template_id": B["assign_template"]}, roles=("admin", "teacher")),
    "lms.assignment_new": _ent("course", "Course", "cid", ('GET', 'POST'), form=lambda A, B: {"title": "HACK"}, roles=("admin", "teacher")),
    "lms.assignment_pick_from_bank": _ent("assignment", "CourseAssignment", "aid", ('GET', 'POST'), form=lambda A, B: {"bank_ids": B["bank_question"]}, roles=("admin", "teacher")),
    "lms.assignment_question_add": _ent("assignment", "CourseAssignment", "aid", ('POST',), form=lambda A, B: {"prompt": "HACK"}, roles=("admin", "teacher")),
    "lms.assignment_question_delete": _ent("assignment_question", "AssignmentQuestion", "qid", ('POST',), roles=("admin", "teacher")),
    "lms.assignment_question_new_version": _ent("assignment_question", "AssignmentQuestion", "qid", ('POST',), roles=("admin", "teacher")),
    "lms.assignment_question_update": _ent("assignment_question", "AssignmentQuestion", "qid", ('POST',), form=lambda A, B: {"prompt": "HACK"}, roles=("admin", "teacher")),
    "lms.assignment_questions": _ent("assignment", "CourseAssignment", "aid", ('GET',), roles=("admin", "teacher")),
    "lms.assignment_save_as_template": _ent("assignment", "CourseAssignment", "aid", ('POST',), form=lambda A, B: {"title": "HACK"}, roles=("admin", "teacher")),
    "lms.assignment_submit": _ent("assignment", "CourseAssignment", "aid", ('POST',), form=lambda A, B: {"body": "HACK"}, roles=("admin", "student")),
    "lms.attempt_autosave": _ent("attempt", "QuizAttempt", "attempt_id", ('POST',), roles=("admin", "student")),
    "lms.attempt_flag": _ent("attempt", "QuizAttempt", "attempt_id", ('POST',), roles=("admin", "student")),
    "lms.attempt_tab_switch": _ent("attempt", "QuizAttempt", "attempt_id", ('POST',), roles=("admin", "student")),
    "lms.bank_ai_rewrite": _ent("bank_question", "BankQuestion", "bid", ('POST',), roles=("admin", "teacher")),
    "lms.bank_ai_rewrite_save": _ent("bank_question", "BankQuestion", "bid", ('POST',), form=lambda A, B: {"prompt": "HACK"}, roles=("admin", "teacher")),
    "lms.bank_archive": _ent("bank_question", "BankQuestion", "bid", ('POST',), roles=("admin", "teacher")),
    "lms.bank_delete": _ent("bank_question", "BankQuestion", "bid", ('POST',), roles=("admin", "teacher")),
    "lms.bank_edit": _ent("bank_question", "BankQuestion", "bid", ('GET', 'POST'), form=lambda A, B: {"prompt": "HACK"}, roles=("admin", "teacher")),
    "lms.bank_rewrite_panel": _ent("bank_question", "BankQuestion", "bid", ('GET',), roles=("admin", "teacher")),
    "lms.bank_set_state": _ent("bank_question", "BankQuestion", "bid", ('POST',), form=lambda A, B: {"state": "archived"}, roles=("admin", "teacher")),
    "lms.collection_add": _ent("collection", "QuestionCollection", "cid", ('POST',), form=lambda A, B: {"bank_id": B["bank_question"]}, roles=("admin", "teacher")),
    "lms.feedback_template_delete": _ent("feedback_template", "FeedbackTemplate", "tid", ('POST',), roles=("admin", "teacher")),
    "lms.objective_delete": _ent("objective", "LearningObjective", "oid", ('POST',), roles=("admin", "teacher")),
    "lms.passage_delete": _ent("passage", "Passage", "pid", ('POST',), roles=("admin", "teacher")),
    "lms.passage_edit": _ent("passage", "Passage", "pid", ('GET', 'POST'), form=lambda A, B: {"title": "HACK"}, roles=("admin", "teacher")),
    "lms.quiz_analysis": _ent("quiz", "Quiz", "qid", ('GET',), roles=("admin", "teacher")),
    "lms.quiz_delete": _ent("quiz", "Quiz", "qid", ('POST',), roles=("admin", "teacher")),
    "lms.quiz_edit": _ent("quiz", "Quiz", "qid", ('GET', 'POST'), form=lambda A, B: {"title": "HACK"}, roles=("admin", "teacher")),
    "lms.quiz_live_monitor": _ent("quiz", "Quiz", "qid", ('GET',), roles=("admin", "teacher")),
    "lms.quiz_live_monitor_json": _ent("quiz", "Quiz", "qid", ('GET',), roles=("admin", "teacher")),
    "lms.quiz_new": _ent("course", "Course", "cid", ('GET', 'POST'), form=lambda A, B: {"title": "HACK"}, roles=("admin", "teacher")),
    "lms.quiz_pick_from_bank": _ent("quiz", "Quiz", "qid", ('GET', 'POST'), form=lambda A, B: {"bank_ids": B["bank_question"]}, roles=("admin", "teacher")),
    "lms.quiz_publish_results": _ent("quiz", "Quiz", "qid", ('POST',), roles=("admin", "teacher")),
    "lms.quiz_question_add": _ent("quiz", "Quiz", "qid", ('POST',), form=lambda A, B: {"prompt": "HACK"}, roles=("admin", "teacher")),
    "lms.quiz_question_delete": _ent("question", "Question", "qid", ('POST',), roles=("admin", "teacher")),
    "lms.quiz_question_new_version": _ent("question", "Question", "qid", ('POST',), roles=("admin", "teacher")),
    "lms.quiz_question_update": _ent("question", "Question", "qid", ('POST',), form=lambda A, B: {"prompt": "HACK"}, roles=("admin", "teacher")),
    "lms.quiz_questions": _ent("quiz", "Quiz", "qid", ('GET',), roles=("admin", "teacher")),
    "lms.quiz_result": _ent("attempt", "QuizAttempt", "attempt_id", ('GET',), roles=("admin", "student")),
    "lms.quiz_submit": _ent("quiz", "Quiz", "qid", ('POST',), roles=("admin", "student")),
    "lms.quiz_take": _ent("quiz", "Quiz", "qid", ('GET',), roles=("admin", "student")),
    "lms.report_section": _ent("section", "Section", "section_id", ('GET',), roles=("admin", "teacher")),
    "lms.report_student": _ent("student", "Student", "student_id", ('GET',), roles=("admin", "teacher")),
    "lms.skill_delete": _ent("skill", "Skill", "sid", ('POST',), roles=("admin", "teacher")),
    "lms.submission_ai_grade": _ent("submission", "Submission", "sid", ('POST',), roles=("admin", "teacher")),
    "lms.submission_grade_panel": _ent("submission", "Submission", "sid", ('GET',), roles=("admin", "teacher")),
    "lms.submission_grade_save": _ent("submission", "Submission", "sid", ('POST',), form=lambda A, B: {"score": "99"}, roles=("admin", "teacher")),
    "lms.submission_rubric_grade": _ent("submission", "Submission", "submission_id", ('GET', 'POST'), roles=("admin", "teacher")),
    "lms.taxonomy_objective_delete": _ent("objective", "LearningObjective", "oid", ('POST',), roles=("admin", "teacher")),
    "lms.taxonomy_objective_edit": _ent("objective", "LearningObjective", "oid", ('POST',), form=lambda A, B: {"title": "HACK"}, roles=("admin", "teacher")),
    "lms.taxonomy_skill_delete": _ent("skill", "Skill", "sid", ('POST',), roles=("admin", "teacher")),
    "lms.taxonomy_skill_edit": _ent("skill", "Skill", "sid", ('POST',), form=lambda A, B: {"title": "HACK"}, roles=("admin", "teacher")),
    "lms.template_ai_generate": _ent("assess_template", "AssessmentTemplate", "tid", ('POST',), roles=("admin", "teacher")),
    "lms.template_delete": _ent("assign_template", "AssignmentTemplate", "tid", ('POST',), roles=("admin", "teacher")),
    "lms.template_detail": _ent("assess_template", "AssessmentTemplate", "tid", ('GET',), roles=("admin", "teacher")),
    "lms.template_edit": _ent("assess_template", "AssessmentTemplate", "tid", ('GET', 'POST'), form=lambda A, B: {"title": "HACK"}, roles=("admin", "teacher")),
    "lms.template_items_attach": _ent("assess_template", "AssessmentTemplate", "tid", ('POST',), form=lambda A, B: {"bank_ids": B["bank_question"]}, roles=("admin", "teacher")),
    "lms.template_items_save": _ent("assess_template", "AssessmentTemplate", "tid", ('POST',), roles=("admin", "teacher")),
    "lms.template_print": _ent("assess_template", "AssessmentTemplate", "tid", ('GET',), roles=("admin", "teacher")),
    "lms.template_use": _ent("assess_template", "AssessmentTemplate", "tid", ('GET', 'POST'), roles=("admin", "teacher")),
    "lms.template_item_delete": _ent("template_item", "AssessmentTemplateItem", "iid", ("POST",), roles=("admin", "teacher"), extra=lambda B: {"tid": B["assess_template"]}),
    "lms.template_item_toggle_hidden": _ent("template_item", "AssessmentTemplateItem", "iid", ("POST",), roles=("admin", "teacher"), extra=lambda B: {"tid": B["assess_template"]}),

    # SAAS-018 — academic / admin / platform / teachers / results /
    # schedule / nafis / messaging (53).
    "academic.bulk_transfer": _ent("section", "Section", "from_id", ('GET', 'POST'),
                                   form=lambda A, B: {"to_section_id": B["section"].id,
                                                      "enrollment_ids": B["enrollment"].id},
                                   snapshot=_both(_row("Section", "section"), _row("Enrollment", "enrollment"))),
    "academic.calendar_day_delete": _ent("calendar_day", "SchoolCalendarDay", "day_id"),
    "academic.grade_delete": _ent("grade", "Grade", "grade_id"),
    "academic.grade_detail": _ent("grade", "Grade", "grade_id", ('GET',)),
    "academic.grade_report": _ent("grade", "Grade", "grade_id", ('GET',)),
    "academic.section_delete": _ent("section", "Section", "section_id"),
    "academic.subject_report": _ent("subject", "Subject", "subject_id", ('GET',)),
    "academic.term_delete": _ent("term", "Term", "term_id"),
    "academic.term_edit": _ent("term", "Term", "term_id", ('GET', 'POST'),
                               form=lambda A, B: {"name": "HACK", "order_index": 1, "weight": 50,
                                                  "start_date": "2026-09-01", "end_date": "2027-01-31"}),
    "academic.term_new": _ent("year", "AcademicYear", "year_id", ('GET', 'POST'),
                              form=lambda A, B: {"name": "HACK", "order_index": 2, "weight": 50,
                                                 "start_date": "2027-02-01", "end_date": "2027-06-01"},
                              snapshot=_cnt("Term", "year_id", "year")),
    "academic.terms_list": _ent("year", "AcademicYear", "year_id", ('GET',)),
    "academic.year_close": _ent("year", "AcademicYear", "year_id", ('GET', 'POST'),
                                form=lambda A, B: {"confirm": "1"},
                                snapshot=_both(_row("AcademicYear", "year"), _row("Enrollment", "enrollment"))),
    "academic.year_edit": _ent("year", "AcademicYear", "year_id", ('GET', 'POST'),
                               form=lambda A, B: {"name": "HACK", "start_date": "2026-09-01",
                                                  "end_date": "2027-06-15"}),
    "admin.role_delete": _ent("role", "Role", "role_id"),
    "admin.role_edit": _ent("role", "Role", "role_id", ('GET', 'POST'),
                            form=lambda A, B: {"name": "HACK", "perm_students_view": "1"}),
    "admin.trash_restore": _ent("trash_vendor", "Vendor", "oid",
                                extra=lambda B: {"kind": "vendors"}),
    "admin.user_edit": _ent("teacher_user", "User", "user_id", ('GET', 'POST'),
                            form=lambda A, B: {"full_name": "HACK", "role_id": A["roles"]["admin"].id}),
    "admin.user_toggle": _ent("teacher_user", "User", "user_id"),
    "messaging.conversation_view": _ent("conversation", "Conversation", "conv_id", ('GET', 'POST'),
                                        form=lambda A, B: {"body": "HACK"},
                                        snapshot=_cnt("Message", "conversation_id", "conversation")),
    "messaging.message_delete": _ent("message", "Message", "msg_id"),
    "nafis.cycle_delete": _ent("nafis_cycle", "NafisCycle", "cycle_id"),
    "nafis.cycle_detail": _ent("nafis_cycle", "NafisCycle", "cycle_id", ('GET',)),
    "nafis.cycle_edit": _ent("nafis_cycle", "NafisCycle", "cycle_id", ('GET', 'POST'),
                             form=lambda A, B: {"name_ar": "HACK"}),
    "platform.room_delete": _ent("room", "Room", "room_id"),
    "platform.room_detail": _ent("room", "Room", "room_id", ('GET',)),
    "platform.room_edit": _ent("room", "Room", "room_id", form=lambda A, B: {"name": "HACK"}),
    "platform.room_slot_save": _ent("room", "Room", "room_id", form=lambda A, B: {"slot_id": B["slot"]},
                                    snapshot=_both(_row("Room", "room"), _row("ScheduleSlot", "slot"))),
    "platform.room_slot_unbook": _ent("room", "Room", "room_id", extra=lambda B: {"slot_id": B["slot"]},
                                      snapshot=_row("ScheduleSlot", "slot")),
    "platform.room_toggle": _ent("room", "Room", "room_id"),
    "platform.user_scopes": _ent("teacher_user", "User", "user_id", ('GET', 'POST'),
                                 form=lambda A, B: {"scope_type": "stage", "scope_value": "HACK"},
                                 snapshot=_cnt("UserScope", "user_id", "teacher_user")),
    "results.grade_sheet": _ent("section", "Section", "section_id", ('GET', 'POST'),
                                extra=lambda B: {"term_id": B["term"].id, "subject_id": B["subject"].id},
                                snapshot=_cnt("GradeEntry", "enrollment_id", "enrollment")),
    "results.recompute_ranks": _ent("section", "Section", "section_id",
                                    snapshot=_both(_row("Enrollment", "enrollment"),
                                                   _cnt("YearResult", "enrollment_id", "enrollment"))),
    "results.rubric_delete": _ent("rubric", "Rubric", "rubric_id"),
    "results.rubric_edit": _ent("rubric", "Rubric", "rubric_id", ('GET', 'POST'), form=lambda A, B: {"title": "HACK"}),
    "results.scale_delete": _ent("scale", "GradingScale", "scale_id"),
    "results.scale_edit": _ent("scale", "GradingScale", "scale_id", ('GET', 'POST'), form=lambda A, B: {"name": "HACK"}),
    "results.transcript_snapshot": _ent("student", "Student", "student_id",
                                        snapshot=_cnt("TranscriptSnapshot", "student_id", "student")),
    "results.transcript_view": _ent("student", "Student", "student_id", ('GET',)),
    "schedule.day_delete": _ent("day", "Day", "day_id"),
    "schedule.period_delete": _ent("period", "Period", "period_id"),
    "schedule.slot_delete": _ent("section", "Section", "section_id", extra=lambda B: {"slot_id": B["slot"]},
                                 snapshot=_row("ScheduleSlot", "slot")),
    "schedule.slot_save": _ent("section", "Section", "section_id",
                               form=lambda A, B: {"day_id": B["day"], "period_id": B["period"],
                                                  "subject_id": B["subject"].id, "teacher_id": B["teacher"]},
                               snapshot=_cnt("ScheduleSlot", "section_id", "section")),
    "schedule.teacher_schedule": _ent("teacher", "Teacher", "teacher_id", ('GET',)),
    "teachers.assignment_remove": _ent("teacher_assignment", "Assignment", "assignment_id"),
    "teachers.assignment_update": _ent("teacher_assignment", "Assignment", "assignment_id",
                                       form=lambda A, B: {"teacher_id": B["teacher"]}),
    "teachers.section_assignments": _ent("section", "Section", "section_id", ('GET', 'POST'),
                                         form=lambda A, B: {"subject_id": B["subject"].id,
                                                            "teacher_id": B["teacher"]},
                                         snapshot=_cnt("Assignment", "section_id", "section")),
    "teachers.subject_delete": _ent("subject", "Subject", "subject_id"),
    "teachers.teacher_account_reset_password": _ent("teacher", "Teacher", "teacher_id",
                                                    snapshot=_user_row("teacher_user")),
    "teachers.teacher_account_toggle": _ent("teacher", "Teacher", "teacher_id",
                                            snapshot=_user_row("teacher_user")),
    "teachers.teacher_detail": _ent("teacher", "Teacher", "teacher_id", ('GET',)),
    "teachers.teacher_edit": _ent("teacher", "Teacher", "teacher_id", ('GET', 'POST'),
                                  form=lambda A, B: {"full_name": "HACK", "specialization": "HACK"}),
    "teachers.teacher_specialization": _ent("teacher", "Teacher", "teacher_id",
                                            form=lambda A, B: {"specialization": "HACK"}),
    "teachers.teacher_toggle": _ent("teacher", "Teacher", "teacher_id"),

    # SAAS-016 — courses (11).
    "courses.course_pick_section": _ent("grade", "Grade", "grade_id", ('GET',),
                                        extra=lambda B: {"subject_id": B["subject"].id}),
    "courses.delete": _ent("course", "Course", "course_id"),
    "courses.detail": _ent("course", "Course", "course_id", ('GET',), roles=("admin", "teacher")),
    "courses.grade_terms": _ent("grade", "Grade", "grade_id", ('GET',)),
    "courses.lesson_delete": _ent("lesson", "Lesson", "lesson_id"),
    "courses.lesson_edit": _ent("lesson", "Lesson", "lesson_id", ('GET', 'POST'),
                                form=lambda A, B: {"title": "HACK"}),
    "courses.lesson_new": _ent("course", "Course", "course_id", ('GET', 'POST'),
                               form=lambda A, B: {"title": "HACK"},
                               snapshot=_cnt("Lesson", "course_id", "course")),
    "courses.lesson_view": _ent("lesson", "Lesson", "lesson_id", ('GET',), roles=("admin", "teacher", "student")),
    "courses.unit_delete": _ent("unit", "Unit", "unit_id"),
    # BUG-007 — publish a course to sections: B's course / B's link
    "courses.section_link": _ent("course", "Course", "course_id",
                                 form=lambda A, B: {"section_ids": [str(A["section"].id)]},
                                 snapshot=_cnt("CourseSection", "course_id", "course")),
    "courses.section_unlink": _ent("course", "Course", "course_id",
                                   extra=lambda B: {"link_id": B["course_section"]},
                                   snapshot=_cnt("CourseSection", "course_id", "course")),
    "courses.unit_edit": _ent("unit", "Unit", "unit_id", form=lambda A, B: {"title": "HACK"}),
    "courses.unit_new": _ent("course", "Course", "course_id", form=lambda A, B: {"title": "HACK"},
                             snapshot=_cnt("Unit", "course_id", "course")),

    # SAAS-047 — the school owner's backups (the token download is a
    # string route: test_saas047_admin_backups covers it).
    "admin.backup_status": _ent("backup", "SchoolBackup", "bid", ('GET',)),
    "admin.backup_delete": _ent("backup", "SchoolBackup", "bid"),
    "admin.backup_download_prepare": _ent("backup", "SchoolBackup", "bid",
                                          form=lambda A, B: {"account_password": "wrong",
                                                             "passphrase": "p" * 14,
                                                             "passphrase_confirm": "p" * 14}),
    # SAAS-048 — restore pages (owner only).
    "admin.restore_detail": _ent("restore", "SchoolRestore", "rid", ('GET',)),
    "admin.restore_status": _ent("restore", "SchoolRestore", "rid", ('GET',)),
    "admin.restore_confirm": _ent("restore", "SchoolRestore", "rid",
                                  form=lambda A, B: {"modules": "academic", "mode": "replace",
                                                     "school_name": B["school"].name,
                                                     "account_password": "wrong"}),
    "admin.restore_undo": _ent("restore", "SchoolRestore", "rid",
                               form=lambda A, B: {"account_password": "wrong"},
                               snapshot=_cnt("SchoolRestore", "undo_of_id", "restore")),
    # SAAS-017 — mobile API (26). Each attack uses the account the
    # endpoint serves; rejection is 404 {"error": "not_found"}.
    "api.mark_notification_read": _ent("notification", "NotificationLog", "notif_id", roles=("parent",)),
    "api.parent_child_attendance": _ent("student", "Student", "student_id", ('GET',), roles=("parent",)),
    "api.parent_child_invoices": _ent("student", "Student", "student_id", ('GET',), roles=("parent",)),
    "api.parent_child_materials": _ent("student", "Student", "student_id", ('GET',), roles=("parent",)),
    "api.parent_child_results": _ent("student", "Student", "student_id", ('GET',), roles=("parent",)),
    "api.parent_child_schedule": _ent("student", "Student", "student_id", ('GET',), roles=("parent",)),
    "api.parent_pickup_release": _ent("pickup", "PickupCall", "cid", roles=("parent",)),
    "api.pickup_ack_api": _ent("pickup", "PickupCall", "cid", roles=("teacher",)),
    "api.qbank_set_state": _ent("bank_question", "BankQuestion", "qid",
                                form=lambda A, B: {"review_state": "rejected"}),
    "api.student_announcement_detail": _ent("announcement", "Announcement", "aid", ('GET',), roles=("student",)),
    "api.student_assignment_detail": _ent("assignment", "CourseAssignment", "aid", ('GET',), roles=("student",)),
    "api.student_assignment_submit": _ent("assignment", "CourseAssignment", "aid", roles=("student",),
                                          form=lambda A, B: {"body": "HACK"},
                                          snapshot=_cnt("Submission", "assignment_id", "assignment")),
    "api.student_course_detail": _ent("course", "Course", "course_id", ('GET',), roles=("student",)),
    "api.student_lesson_view": _ent("lesson", "Lesson", "lid", ('GET',), roles=("student",)),
    "api.student_quiz_attempt": _ent("quiz", "Quiz", "qid", ('GET',), roles=("student",)),
    "api.student_quiz_submit": _ent("quiz", "Quiz", "qid", roles=("student",), form=lambda A, B: {"answers": {}},
                                    snapshot=_cnt("QuizAttempt", "quiz_id", "quiz")),
    "api.student_report_card": _ent("term", "Term", "term_id", ('GET',), roles=("student",)),
    "api.teacher_announcement_delete": _ent("announcement", "Announcement", "aid", ('DELETE',), roles=("teacher",)),
    "api.teacher_assignment_detail": _ent("assignment", "CourseAssignment", "aid", ('GET', 'DELETE'),
                                          roles=("teacher",)),
    "api.teacher_assignment_grade": _ent("assignment", "CourseAssignment", "aid", roles=("teacher",),
                                         extra=lambda B: {"sid": B["student"].id},
                                         form=lambda A, B: {"score": 1},
                                         snapshot=_row("Submission", "submission")),
    "api.teacher_assignment_submissions": _ent("assignment", "CourseAssignment", "aid", ('GET',), roles=("teacher",)),
    "api.teacher_message_thread": _ent("conversation", "Conversation", "conv_id", ('GET', 'POST'), roles=("teacher",),
                                       form=lambda A, B: {"body": "HACK"},
                                       snapshot=_cnt("Message", "conversation_id", "conversation")),
    "api.teacher_quiz_stats": _ent("quiz", "Quiz", "qid", ('GET',), roles=("teacher",)),
    "api.teacher_section_schedule": _ent("section", "Section", "section_id", ('GET',), roles=("teacher",)),
    "api.teacher_template_add_questions": _ent("assess_template", "AssessmentTemplate", "tid", roles=("teacher",),
                                               form=lambda A, B: {"bank_question_ids": [B["bank_question"]]},
                                               snapshot=_cnt("AssessmentTemplateItem", "template_id",
                                                             "assess_template")),
    "api.teacher_template_detail": _ent("assess_template", "AssessmentTemplate", "tid", ('GET', 'DELETE'),
                                        roles=("teacher",)),
}


# Gaps the sweep found; each is fixed by the named ticket. Strict xfail:
# once fixed the test passes, xfail(strict) turns red, remove the line.
KNOWN_GAPS: dict[tuple[str, str], str] = {}


# ─── Allowlist ───────────────────────────────────────────────────────

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
    "superadmin.school_backup_policy":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-047 backup tests",
    "superadmin.school_restore_new":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-048 restore tests",
    "superadmin.school_restore_confirm":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-048 restore tests",
    "superadmin.school_module_set":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by the SAAS-030 console tests",
    "superadmin.school_features_set":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by tests/test_console_features.py",
    "superadmin.school_branding":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by tests/test_console_branding.py",
    "superadmin.school_branding_logo":
        "platform console (no school tenant): 404 on every school host and when "
        "resolution is off — covered by tests/test_console_branding.py",
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

ALLOWLIST: dict[str, str] = dict(_PRE_AUTH_OR_SHARED)


# ─── Form / query-string ids ─────────────────────────────────────────

_FORM_ID_RE = re.compile(
    r"request\.(?:form|args|values)\.get(?:list)?\(\s*[\"'](\w*_id)[\"']")
_JSON_ID_RE = re.compile(r"request\.(?:get_json|json)[^\n]*?[\"'](\w*_id)[\"']")
_NOT_AN_FK = {"national_id"}


_HELPER_CALL_RE = re.compile(r"(?<![\w.])(_\w+)\(")


def _view_source(fn) -> str:
    """The view's source + the same-module `_helpers` it calls (one level):
    a shared create/update helper reads the form for the view."""
    fn = inspect.unwrap(fn)
    src = inspect.getsource(fn)
    mod = inspect.getmodule(fn)
    for name in set(_HELPER_CALL_RE.findall(src)):
        helper = getattr(mod, name, None)
        if inspect.isfunction(helper) and helper.__module__ == fn.__module__:
            try:
                src += inspect.getsource(helper)
            except (OSError, TypeError):
                pass
    return src


def discover_form_id_endpoints(app) -> dict[str, list[str]]:
    out = {}
    for ep, fn in app.view_functions.items():
        try:
            src = _view_source(fn)
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


def _titled(model: str, prefix: str):
    """Rows of `model` (any school) whose title starts with B's marker —
    a copy of B's content into A shows up here."""
    def snap(B):
        from app import models as M
        cls = getattr(M, model)
        return cls.query.filter(cls.title.like(f"{prefix}-{B['school'].slug}%")).count()
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
    # SAAS-015 — LMS form ids (+ lms.quiz_submit for SAAS-016).
    "lms.announcement_new": _post(
        lambda A, B: {"title": "x", "body": "x", "section_id": B["section"].id},
        _xlink("Announcement", ("section_id", "section"))),
    "lms.assignment_edit": _in_a("aid", "assignment",
                                 form=lambda A, B: {"title": "x", "rubric_id": B["rubric"]},
                                 snapshot=_xlink("CourseAssignment", ("rubric_id", "rubric"))),
    "lms.assignment_extension_add": _in_a("aid", "assignment",
                                          form=lambda A, B: {"student_id": B["student"].id,
                                                             "new_due_at": "2027-01-01T10:00"},
                                          snapshot=_cnt("AssignmentExtension", "student_id", "student")),
    "lms.assignment_from_template": _in_a("cid", "course", methods=("GET", "POST"),
                                          form=lambda A, B: {"template_id": B["assign_template"]},
                                          snapshot=_titled("CourseAssignment", "AssignTpl")),
    "lms.assignment_new": _in_a("cid", "course",
                                form=lambda A, B: {"title": "x", "rubric_id": B["rubric"]},
                                snapshot=_xlink("CourseAssignment", ("rubric_id", "rubric"))),
    "lms.assignment_pick_from_bank": _in_a("aid", "assignment",
                                           form=lambda A, B: {"bank_ids": B["bank_question"]},
                                           snapshot=_cnt("AssignmentQuestion", "source_bank_id", "bank_question")),
    "lms.bank_home": _get_q(lambda A, B: {"subject_id": B["subject"].id, "grade_id": B["grade"].id,
                                          "lesson_id": B["lesson"], "unit_id": B["unit"]}),
    "lms.objective_new": _post(lambda A, B: {"title": "x", "lesson_id": B["lesson"]},
                               _xlink("LearningObjective", ("lesson_id", "lesson"))),
    "lms.qbank_dashboard": _get_q(lambda A, B: {"subject_id": B["subject"].id}),
    "lms.quiz_pick_from_bank": _in_a("qid", "quiz",
                                     form=lambda A, B: {"bank_ids": B["bank_question"]},
                                     snapshot=_cnt("Question", "source_bank_id", "bank_question")),
    "lms.quiz_submit": _in_a("qid", "quiz", form=lambda A, B: {"attempt_id": B["attempt"]},
                             snapshot=_row("QuizAttempt", "attempt")),
    "lms.skill_new": _post(lambda A, B: {"title": "x", "parent_id": B["skill"]},
                           _xlink("Skill", ("parent_id", "skill"))),
    "lms.taxonomy_objective_edit": _in_a("oid", "objective",
                                         form=lambda A, B: {"title": "x", "lesson_id": B["lesson"]},
                                         snapshot=_xlink("LearningObjective", ("lesson_id", "lesson"))),
    "lms.taxonomy_objective_new": _post(lambda A, B: {"title": "x", "lesson_id": B["lesson"]},
                                        _xlink("LearningObjective", ("lesson_id", "lesson"))),
    "lms.taxonomy_skill_edit": _in_a("sid", "skill",
                                     form=lambda A, B: {"title": "x", "parent_id": B["skill"]},
                                     snapshot=_xlink("Skill", ("parent_id", "skill"))),
    "lms.taxonomy_skill_new": _post(lambda A, B: {"title": "x", "parent_id": B["skill"]},
                                    _xlink("Skill", ("parent_id", "skill"))),
    "lms.template_detail": Entry(lambda B: {"tid": B["assess_template"]},
                                 mixed=lambda A, B: {"tid": A["assess_template"]},
                                 form=lambda A, B: {"subject_id": B["subject"].id}),
    "lms.template_home": _get_q(lambda A, B: {"subject_id": B["subject"].id, "grade_id": B["grade"].id}),
    "lms.template_use": _in_a("tid", "assess_template",
                              form=lambda A, B: {"section_id": B["section"].id},
                              snapshot=_cnt("CourseSection", "section_id", "section")),
    "lms.templates_gallery": _get_q(lambda A, B: {"subject_id": B["subject"].id}),
    # SAAS-015 — create/update helpers the detector now reads (_bank_save,
    # _passage_form, _employee_bind) + read-only filters.
    "lms.bank_new": _post(lambda A, B: {"prompt": "x", "kind": "short", "correct_short": "x",
                          "subject_id": B["subject"].id, "grade_id": B["grade"].id,
                          "year_id": B["year"].id, "term_id": B["term"].id,
                          "unit_id": B["unit"], "lesson_id": B["lesson"], "passage_id": B["passage"]},
                          _xlink("BankQuestion", ("subject_id", "subject"), ("grade_id", "grade"),
                           ("term_id", "term"), ("unit_id", "unit"), ("lesson_id", "lesson"),
                           ("passage_id", "passage"))),
    "lms.bank_smart_new": _post(lambda A, B: {"prompt": "x", "kind": "short", "correct_short": "x",
                          "subject_id": B["subject"].id, "grade_id": B["grade"].id,
                          "year_id": B["year"].id, "term_id": B["term"].id,
                          "unit_id": B["unit"], "lesson_id": B["lesson"], "passage_id": B["passage"]},
                                _xlink("BankQuestion", ("subject_id", "subject"), ("grade_id", "grade"),
                           ("term_id", "term"), ("unit_id", "unit"), ("lesson_id", "lesson"),
                           ("passage_id", "passage"))),
    "lms.bank_edit": _in_a("bid", "bank_question", form=lambda A, B: {"prompt": "x", "kind": "short", "correct_short": "x",
                          "subject_id": B["subject"].id, "grade_id": B["grade"].id,
                          "year_id": B["year"].id, "term_id": B["term"].id,
                          "unit_id": B["unit"], "lesson_id": B["lesson"], "passage_id": B["passage"]},
                           snapshot=_xlink("BankQuestion", ("subject_id", "subject"), ("grade_id", "grade"),
                           ("term_id", "term"), ("unit_id", "unit"), ("lesson_id", "lesson"),
                           ("passage_id", "passage"))),
    "lms.passage_new": _post(lambda A, B: {"title": "x", "subject_id": B["subject"].id,
                                           "grade_id": B["grade"].id},
                             _xlink("Passage", ("subject_id", "subject"), ("grade_id", "grade"))),
    "lms.passage_edit": _in_a("pid", "passage",
                              form=lambda A, B: {"title": "x", "subject_id": B["subject"].id,
                                                 "grade_id": B["grade"].id},
                              snapshot=_xlink("Passage", ("subject_id", "subject"), ("grade_id", "grade"))),
    "hr.employee_new": _post(lambda A, B: {"full_name": "x", "job_title": "x",
                                           "user_id": B["users"]["teacher"].id},
                             _cnt("Employee", "user_id", "teacher_user")),
    "hr.employee_edit": _in_a("employee_id", "employee",
                              form=lambda A, B: {"full_name": "x", "job_title": "x",
                                                 "user_id": B["users"]["teacher"].id},
                              snapshot=_cnt("Employee", "user_id", "teacher_user")),
    "dashboard.home": _get_q(lambda A, B: {"child_id": B["student"].id}),
    "platform.audit_log_viewer": _get_q(lambda A, B: {"user_id": B["users"]["admin"].id}),
    "platform.audit_log_export": _get_q(lambda A, B: {"user_id": B["users"]["admin"].id}),
    # SAAS-018 — form ids (15).
    "academic.bulk_transfer": _in_a("from_id", "section",
                                    form=lambda A, B: {"target_section_id": B["section"].id,
                                                       "enrollment_ids": B["enrollment"].id},
                                    snapshot=_row("Enrollment", "enrollment")),
    "academic.subject_prerequisites": _post(
        lambda A, B: {"action": "add", "subject_id": A["subject"].id,
                      "requires_subject_id": B["subject"].id},
        _cnt("SubjectPrerequisite", "requires_subject_id", "subject")),
    "admin.audit_log": _get_q(lambda A, B: {"user_id": B["users"]["admin"].id}),
    "messaging.conversation_new": _post(lambda A, B: {"recipient_id": B["users"]["teacher"].id, "body": "x"},
                                        _cnt("ConversationParticipant", "user_id", "teacher_user")),
    "nafis.cycle_edit": _in_a("cycle_id", "nafis_cycle", form=lambda A, B: {"name_ar": "x",
                                                                           "academic_year_id": B["year"].id},
                              snapshot=_xlink("NafisCycle", ("academic_year_id", "year"))),
    "nafis.cycle_new": _post(lambda A, B: {"name_ar": "x", "academic_year_id": B["year"].id},
                             _xlink("NafisCycle", ("academic_year_id", "year"))),
    "platform.room_slot_save": _in_a("room_id", "room",
                                     form=lambda A, B: {"day_id": B["day"], "period_id": B["period"],
                                                        "assignment_id": B["teacher_assignment"]},
                                     snapshot=_both(_xlink("ScheduleSlot", ("day_id", "day"), ("period_id", "period")),
                                                    _row("Assignment", "teacher_assignment"))),
    "platform.substitution_new": _post(
        lambda A, B: {"date": "2026-10-07", "schedule_slot_id": B["slot"],
                      "original_teacher_id": B["teacher"], "substitute_teacher_id": A["teacher"]},
        _xlink("SubstitutionLog", ("schedule_slot_id", "slot"), ("original_teacher_id", "teacher"))),
    "results.class_average_report": _get_q(lambda A, B: {"section_id": B["section"].id,
                                                         "subject_id": B["subject"].id,
                                                         "term_id": B["term"].id, "year_id": B["year"].id}),
    "results.components": _post(
        lambda A, B: {"term_id": A["term"].id, "subject_id": A["subject"].id, "action": "add",
                      "name": "x", "max_score": "10", "grade_id": B["grade"].id,
                      "source_type": "lms_quiz", "source_id": B["quiz"], "auto_sync": "1"},
        _both(_xlink("AssessmentComponent", ("grade_id", "grade"), ("source_id", "quiz")))),
    # ready-made component set applied in bulk: B's grade must not scope A's new components
    "results.component_templates": _post(
        lambda A, B: {"key": "year-20-final-80", "term_ids": A["term"].id, "subject_ids": A["subject"].id,
                      "grade_id": B["grade"].id, "action": "apply"},
        _xlink("AssessmentComponent", ("grade_id", "grade"))),
    "results.missing_grades_report": _get_q(lambda A, B: {"section_id": B["section"].id,
                                                          "subject_id": B["subject"].id,
                                                          "term_id": B["term"].id, "year_id": B["year"].id}),
    "results.rubric_edit": _in_a("rubric_id", "rubric", methods=("POST",),
                                 form=lambda A, B: {"title": "x", "subject_id": B["subject"].id},
                                 snapshot=_xlink("Rubric", ("subject_id", "subject"))),
    "results.rubric_new": _post(lambda A, B: {"title": "x", "subject_id": B["subject"].id},
                                _xlink("Rubric", ("subject_id", "subject"))),
    "schedule.slot_save": _in_a("section_id", "section",
                                form=lambda A, B: {"day_id": B["day"], "period_id": B["period"],
                                                   "subject_id": B["subject"].id, "teacher_id": B["teacher"],
                                                   "room_id": B["room"]},
                                snapshot=_xlink("ScheduleSlot", ("day_id", "day"), ("teacher_id", "teacher"),
                                                ("room_id", "room"))),
    "teachers.section_assignments": _in_a("section_id", "section",
                                          form=lambda A, B: {"subject_id": B["subject"].id,
                                                             "teacher_id": B["teacher"]},
                                          snapshot=_xlink("Assignment", ("teacher_id", "teacher"),
                                                          ("subject_id", "subject"))),
    # SAAS-016 — courses form ids (3).
    "courses.lesson_edit": _in_a("lesson_id", "lesson", form=lambda A, B: {"title": "x", "unit_id": B["unit"]},
                                 snapshot=_xlink("Lesson", ("unit_id", "unit"))),
    "courses.lesson_new": _in_a("course_id", "course", form=lambda A, B: {"title": "x", "unit_id": B["unit"]},
                                snapshot=_xlink("Lesson", ("unit_id", "unit"))),
    "courses.new": _post(lambda A, B: {"title": "x", "academic_year_id": B["year"].id, "grade_id": B["grade"].id,
                                       "subject_id": B["subject"].id, "term_id": B["term"].id},
                         _xlink("Course", ("academic_year_id", "year"), ("grade_id", "grade"),
                                ("subject_id", "subject"))),
    # SAAS-017 — mobile API form ids (7), as the account they serve.
    "api.qbank_questions": Entry(lambda B: {}, form=lambda A, B: {"subject_id": B["subject"].id}),
    "api.teacher_attendance_existing": Entry(lambda B: {}, roles=("teacher",),
                                             form=lambda A, B: {"section_id": B["section"].id,
                                                                "date": "2026-09-06"}),
    "api.teacher_components": Entry(lambda B: {}, roles=("teacher",),
                                    form=lambda A, B: {"subject_id": B["subject"].id, "term_id": B["term"].id}),
    "api.teacher_grades_existing": Entry(lambda B: {}, roles=("teacher",),
                                         form=lambda A, B: {"section_id": A["section"].id,
                                                            "subject_id": A["subject"].id,
                                                            "term_id": A["term"].id,
                                                            "component_id": B["component"]}),
    "api.teacher_students": Entry(lambda B: {}, roles=("teacher",),
                                  form=lambda A, B: {"section_id": B["section"].id}),
    "api.teacher_templates": Entry(lambda B: {}, methods=("GET", "POST"), roles=("teacher",),
                                   form=lambda A, B: {"title": "x", "subject_id": B["subject"].id,
                                                      "grade_id": B["grade"].id},
                                   snapshot=_xlink("AssessmentTemplate", ("subject_id", "subject"),
                                                   ("grade_id", "grade"))),
    "api.teacher_upload": Entry(lambda B: {}, methods=("POST",), roles=("teacher",),
                                form=lambda A, B: {"section_id": B["section"].id, "subject_id": B["subject"].id,
                                                   "title": "x",
                                                   "file": (io.BytesIO(b"%PDF-1.4 x"), "x.pdf")},
                                snapshot=_cnt("Material", "section_id", "section")),
    # SAAS-048 — a restore from another school's saved backup.
    "admin.restore_new": _post(lambda A, B: {"backup_id": B["backup"]},
                               _cnt("SchoolRestore", "source_backup_id", "backup")),
    # SAAS-049 — opening another school's saved backup to browse it.
    "admin.browse_home": _post(lambda A, B: {"backup_id": B["backup"]}, _row("SchoolBackup", "backup")),
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
    "superadmin.school_restore_new": "console (owner): backup_id is looked up WITH school_id = the "
                                     "school in the URL (SAAS-048) — test_saas048_restore_pages",
}


# ─── Fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def enforce_app(app, monkeypatch):
    """Enforce-mode tenancy, CSRF off so a POST is judged on isolation,
    not on a missing token (a 400 must never pass as "blocked")."""
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    return app


def _int_rules(app) -> Iterable:
    """Every route that takes a record id: `<int:…>` (api / platform) and
    `<hid:…>` (school web links carry a code, the view still gets the
    int). Dropping either would silently take routes out of the sweep."""
    for rule in app.url_map.iter_rules():
        if ("<int:" in rule.rule or "<hid:" in rule.rule)                 and (rule.methods or set()) - {"HEAD", "OPTIONS"}:
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
        "Unclassified <int:…>/<hid:…> endpoint(s) — add each to ROUTE_MATRIX "
        "(with an id fetcher for school B) or ALLOWLIST (with a reason):\n  - "
        + "\n  - ".join(f"{ep}  {path}" for ep, path in unclassified)
    )


def test_matrix_and_allowlist_do_not_overlap():
    both = sorted(set(ROUTE_MATRIX) & set(ALLOWLIST))
    assert not both, f"in both ROUTE_MATRIX and ALLOWLIST: {both}"


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
    unclassified = sorted(ep for ep in found
                          if ep not in FORM_ID_MATRIX and ep not in FORM_ID_PLATFORM)
    assert not unclassified, (
        "Endpoint(s) reading an *_id from form/query/json are unclassified — "
        "add to FORM_ID_MATRIX (or FORM_ID_PLATFORM with a reason):\n  - "
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
        login_as(c, A["users"][e.roles[0]], base_url=host(A))
        for m in e.methods:
            before = _snap(app, e, B)
            payload = e.form(A, B) if e.form else {}
            if m == "GET":
                r = c.get(url, query_string=payload, base_url=host(A))
            else:
                r = c.open(url, method=m, base_url=host(A), **body_kwargs(url, payload))
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
    allowed = [ep for ep in rules if ep in ALLOWLIST]
    form_found = discover_form_id_endpoints(app)
    form_cov = [ep for ep in form_found if ep in FORM_ID_MATRIX]
    lines = [
        "# SAAS-012 isolation coverage",
        "",
        f"- `<int:…>` / `<hid:…>` endpoints: **{total}**",
        f"- in ROUTE_MATRIX: **{len(covered)}** ({len(covered) / total:.1%})",
        f"- in ALLOWLIST (written reason): **{len(allowed)}**",
        f"- form/query-id endpoints: **{len(form_found)}**, covered **{len(form_cov)}**, "
        f"platform tables **{len(form_found) - len(form_cov)}**",
        f"- known gaps (strict xfail): **{len(KNOWN_GAPS)}**",
    ]
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
        if e.skip == "":
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
        m = "GET" if "GET" in e.methods else e.methods[0]
        r1 = c.open(build_url(app, endpoint, real, host(A)), method=m, base_url=host(A))
        r2 = c.open(build_url(app, endpoint, fake, host(A)), method=m, base_url=host(A))
    assert r1.status_code == r2.status_code, f"{endpoint}: foreign {r1.status_code} vs missing {r2.status_code}"
    from app.services.hashid import encode
    codes = {encode(v) for d in (real, fake) for v in d.values() if isinstance(v, int)}
    def norm(r):
        # the id is echoed in links / canonical URL — as a number or as
        # its link code (<hid:…> routes): mask both
        body = r.get_data(as_text=True)
        for code in codes:
            body = body.replace(code, "N")
        return re.sub(r"\d+", "N", body)
    assert norm(r1) == norm(r2), f"{endpoint}: foreign and missing pages differ"
