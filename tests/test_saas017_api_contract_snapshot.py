"""SAAS-017 — the mobile API contract on school A's own records stays
exactly as it was: every status code and the JSON shape (keys and value
types, not values) of the 33 isolation-sweep endpoints.

The snapshot in fixtures/api_contract_saas017.json was recorded on the
code BEFORE the SAAS-017 changes. Rewrite it only on purpose:

    SAAS017_WRITE_SNAPSHOT=1 pytest tests/test_saas017_api_contract_snapshot.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from isolation_harness import host

SNAPSHOT = Path(__file__).parent / "fixtures" / "api_contract_saas017.json"


def shape(v):
    if isinstance(v, dict):
        return {k: shape(x) for k, x in sorted(v.items())}
    if isinstance(v, list):
        return [shape(v[0])] if v else []
    if v is None:
        return "null"
    return type(v).__name__


@pytest.fixture
def papp(app, monkeypatch):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    return app


def _calls(A, extra):
    """(name, role, method, path, json). Read-only calls first, writes
    after, deletes last — one client session walks them in order."""
    a, s = A, extra
    return [
        ("parent_child_attendance", "parent", "GET", f"/api/parent/child/{a['student'].id}/attendance", None),
        ("parent_child_invoices", "parent", "GET", f"/api/parent/child/{a['student'].id}/invoices", None),
        ("parent_child_materials", "parent", "GET", f"/api/parent/child/{a['student'].id}/materials", None),
        ("parent_child_results", "parent", "GET", f"/api/parent/child/{a['student'].id}/results", None),
        ("parent_child_schedule", "parent", "GET", f"/api/parent/child/{a['student'].id}/schedule", None),
        ("student_announcement_detail", "student", "GET", f"/api/student/announcements/{a['announcement']}", None),
        ("student_assignment_detail", "student", "GET", f"/api/student/assignments/{a['assignment']}", None),
        ("student_course_detail", "student", "GET", f"/api/student/courses/{a['course']}", None),
        ("student_lesson_view", "student", "GET", f"/api/student/lessons/{a['lesson']}", None),
        ("student_quiz_attempt", "student", "GET", f"/api/student/quizzes/{a['quiz']}/attempt", None),
        ("student_report_card", "student", "GET", f"/api/student/report-card/{a['term'].id}", None),
        ("teacher_assignment_detail", "teacher", "GET", f"/api/teacher/assignments/{a['assignment']}", None),
        ("teacher_assignment_submissions", "teacher", "GET",
         f"/api/teacher/assignments/{a['assignment']}/submissions", None),
        ("teacher_quiz_stats", "teacher", "GET", f"/api/teacher/quizzes/{a['quiz']}/stats", None),
        ("teacher_section_schedule", "teacher", "GET", f"/api/teacher/section/{a['section'].id}/schedule", None),
        ("teacher_template_detail", "teacher", "GET", f"/api/teacher/templates/{a['assess_template']}", None),
        ("teacher_message_thread", "teacher", "GET", f"/api/teacher/messages/{a['conversation']}", None),
        ("teacher_components", "teacher", "GET",
         f"/api/teacher/components?subject_id={a['subject'].id}&term_id={a['term'].id}", None),
        ("teacher_grades_existing", "teacher", "GET",
         f"/api/teacher/grades?section_id={a['section'].id}&subject_id={a['subject'].id}"
         f"&term_id={a['term'].id}&component_id={s['component']}", None),
        ("teacher_attendance_existing", "teacher", "GET",
         f"/api/teacher/attendance?section_id={a['section'].id}&date=2026-09-06", None),
        ("teacher_students", "teacher", "GET", f"/api/teacher/students?section_id={a['section'].id}", None),
        ("teacher_templates", "teacher", "GET", f"/api/teacher/templates?subject_id={a['subject'].id}", None),
        ("qbank_questions", "admin", "GET", f"/api/admin/question_bank/questions?subject_id={a['subject'].id}",
         None),
        # writes
        ("mark_notification_read", "parent", "POST", f"/api/notifications/{s['notification']}/read", None),
        ("qbank_set_state", "admin", "POST", f"/api/admin/question_bank/questions/{a['bank_question']}/state",
         {"review_state": "approved"}),
        ("student_assignment_submit", "student", "POST", f"/api/student/assignments/{a['assignment']}/submit",
         {"body": "حل", "answers": {}}),
        ("student_quiz_submit", "student", "POST", f"/api/student/quizzes/{a['quiz']}/submit",
         {"answers": {str(a["question"]): a["choice"]}}),
        ("teacher_assignment_grade", "teacher", "POST",
         f"/api/teacher/assignments/{a['assignment']}/submissions/{a['student'].id}/grade",
         {"score": 5, "feedback": "جيد"}),
        ("teacher_message_thread_post", "teacher", "POST", f"/api/teacher/messages/{a['conversation']}",
         {"body": "رسالة"}),
        ("teacher_template_add_questions", "teacher", "POST",
         f"/api/teacher/templates/{a['assess_template']}/questions", {"bank_question_ids": [a["bank_question"]]}),
        ("teacher_templates_post", "teacher", "POST", "/api/teacher/templates",
         {"title": "قالب", "subject_id": a["subject"].id, "grade_id": a["grade"].id}),
        ("pickup_ack_api", "teacher", "POST", f"/api/pickup/{a['pickup']}/ack", None),
        ("parent_pickup_release", "parent", "POST", f"/api/parent/pickup/{a['pickup']}/release", None),
        # deletes
        ("teacher_announcement_delete", "teacher", "DELETE", f"/api/teacher/announcements/{a['announcement']}",
         None),
        ("teacher_template_detail_delete", "teacher", "DELETE", f"/api/teacher/templates/{a['assess_template']}",
         None),
        ("teacher_assignment_detail_delete", "teacher", "DELETE", f"/api/teacher/assignments/{a['assignment']}",
         None),
    ]


def _prepare(app, A):
    """A's own records the calls need: the teacher teaches A's section,
    one component, one notification for A's child, the pickup targets
    A's teacher."""
    from app.extensions import db
    from app.models import AssessmentComponent, NotificationLog, PickupCall
    with app.app_context():
        comp = AssessmentComponent(school_id=A["school"].id, term_id=A["term"].id,
                                   subject_id=A["subject"].id, name="Comp-alpha", max_score=10)
        notif = NotificationLog(school_id=A["school"].id, student_id=A["student"].id,
                                kind="announcement", status="sent", payload="{}")
        db.session.add_all([comp, notif])
        call = db.session.get(PickupCall, A["pickup"])
        call.teacher_user_id = A["users"]["teacher"].id
        call.parent_user_id = A["users"]["parent"].id
        db.session.commit()
        out = {"component": comp.id, "notification": notif.id}
        db.session.remove()
    return out


def _tokens(app, A):
    from app.services.auth_jwt import issue_token
    with app.app_context():
        return {r: issue_token(A["users"][r]) for r in ("admin", "teacher", "parent", "student")}


def record(app, A):
    extra = _prepare(app, A)
    tokens = _tokens(app, A)
    out = {}
    with app.test_client() as c:
        for name, role, method, path, body in _calls(A, extra):
            r = c.open(path, method=method, json=body, base_url=host(A),
                       headers={"Authorization": f"Bearer {tokens[role]}"})
            data = r.get_json(silent=True)
            out[name] = {"status": r.status_code, "shape": shape(data)}
    return out


def test_api_contract_on_own_records_is_unchanged(papp, world):
    got = record(papp, world["A"])
    if os.environ.get("SAAS017_WRITE_SNAPSHOT") == "1":
        SNAPSHOT.write_text(json.dumps(got, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                            encoding="utf-8")
        pytest.fail("snapshot rewritten — rerun without SAAS017_WRITE_SNAPSHOT")
    want = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert sorted(got) == sorted(want)
    diffs = {k: (want[k], got[k]) for k in want if want[k] != got[k]}
    assert not diffs, json.dumps(diffs, ensure_ascii=False, indent=1)
