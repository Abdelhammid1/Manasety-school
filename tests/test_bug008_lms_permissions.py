"""BUG-008 — every staff-side LMS route (question management, bank,
templates, grading, analytics, taxonomy …) needs lms.edit on the server.
A student gets 403 on all of them (GET and POST) and nothing changes in
the database; the teacher keeps working; the student's own routes (take,
submit, result, autosave …) stay open to them."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from isolation_harness import build_url, hid, host, rule_for

# The routes a student uses: they keep their own checks (enrolment,
# ownership of the attempt …) — tested in test_saas016.
STUDENT_SIDE = {
    "lms.assignments_home", "lms.quizzes_home", "lms.announcements_home",
    "lms.assignment_detail", "lms.assignment_submit",
    "lms.quiz_take", "lms.quiz_submit", "lms.quiz_result",
    "lms.attempt_tab_switch", "lms.attempt_flag", "lms.attempt_autosave",
    "courses.list_courses", "courses.detail", "courses.lesson_view",
}


@pytest.fixture
def sapp(app, monkeypatch):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    return app


def _client(sapp, login_as, A, role):
    c = sapp.test_client()
    login_as(c, A["users"][role], base_url=host(A))
    return c


def _id(v):
    return getattr(v, "id", v)


def _arg(endpoint: str, arg: str, A: dict):
    """The right row of school A for one URL argument of an endpoint."""
    name = endpoint.split(".", 1)[1]
    if arg == "aid":
        return A["announcement"] if name.startswith("announcement") else A["assignment"]
    if arg == "qid":
        if name in ("quiz_question_update", "quiz_question_delete", "quiz_question_new_version"):
            return A["question"]
        if name.startswith("assignment_question_") and name != "assignment_question_add":
            return A["assignment_question"]
        return A["quiz"]
    if arg == "cid":
        return A["collection"] if name == "collection_add" else A["course"]
    if arg == "tid":
        return {"template_delete": A["assign_template"],
                "feedback_template_delete": A["feedback_template"]}.get(name, A["assess_template"])
    if arg == "sid":
        return A["skill"] if "skill" in name else A["submission"]
    return {
        "iid": A["template_item"], "bid": A["bank_question"], "oid": A["objective"],
        "pid": A["passage"], "attempt_id": A["attempt"], "submission_id": A["submission"],
        "student_id": A["student"], "section_id": A["section"], "course_id": A["course"],
        "lesson_id": A["lesson"], "unit_id": A["unit"], "grade_id": A["grade"],
        "term_id": A["term"], "subject_id": A["subject"], "link_id": A["course_section"],
    }[arg]


def _staff_routes(sapp, A):
    """[(endpoint, method, url)] of every lms.* / courses.* route that is
    not a student's own."""
    from app.extensions import db
    from app.models import CourseSection
    with sapp.app_context():
        A = {**A, "course_section": CourseSection.query.filter_by(course_id=A["course"]).first().id}
        db.session.remove()
    out = []
    for endpoint in sorted({r.endpoint for r in sapp.url_map.iter_rules()
                            if r.endpoint.startswith(("lms.", "courses."))}):
        if endpoint in STUDENT_SIDE:
            continue
        rule = rule_for(sapp, endpoint)
        url = build_url(sapp, endpoint, {a: _id(_arg(endpoint, a, A)) for a in rule.arguments},
                        host(A))
        for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            out.append((endpoint, method, url))
    return out


_LMS_TABLES = (
    "lms_questions", "lms_choices", "lms_assignment_questions", "lms_assignment_choices",
    "lms_bank_questions", "lms_course_assignments", "lms_quizzes", "lms_courses",
    "lms_course_sections", "lms_submissions", "lms_assessment_template_items",
)


def _snapshot(sapp):
    from app.extensions import db
    out = {}
    with sapp.app_context():
        meta = db.metadata
        for name in _LMS_TABLES:
            t = meta.tables.get(name)
            if t is None:
                continue
            out[name] = [tuple(r) for r in db.session.execute(select(t).order_by(*t.primary_key.columns))]
        db.session.remove()
    return out


def test_a_student_gets_403_on_every_staff_lms_route_and_nothing_changes(sapp, world, login_as):
    from app.extensions import db
    from app.models import SchoolFeatureOverride
    A = world["A"]
    with sapp.app_context():                        # the AI routes 404 while the feature is off
        db.session.add(SchoolFeatureOverride(school_id=A["school"].id, feature_key="lms.ai",
                                             enabled=True, reason="test"))
        db.session.commit()
        db.session.remove()
    routes = _staff_routes(sapp, A)
    assert len(routes) > 60                         # the sweep really covers the blueprint
    before = _snapshot(sapp)
    c = _client(sapp, login_as, A, "student")
    wrong = []
    for endpoint, method, url in routes:
        r = c.open(url, method=method, base_url=host(A),
                   data={"prompt": "x", "bank_ids": [str(A["bank_question"])], "state": "approved",
                         "title": "x", "body": "x", "points": "1"})
        if r.status_code != 403:
            wrong.append((endpoint, method, r.status_code))
    assert wrong == [], wrong
    assert _snapshot(sapp) == before


def test_the_question_page_shows_no_answers_to_a_student(sapp, world, login_as):
    A = world["A"]
    c = _client(sapp, login_as, A, "student")
    for url in (f"/lms/assignments/{hid(A['assignment'])}/questions",
                f"/lms/quizzes/{hid(A['quiz'])}/questions"):
        r = c.get(url, base_url=host(A))
        body = r.get_data(as_text=True)
        assert r.status_code == 403
        assert "QuizQ-alpha" not in body and "AssignQ-alpha" not in body and "Choice-alpha" not in body


def test_a_logged_out_visitor_never_reaches_the_question_pages(sapp, world):
    A = world["A"]
    c = sapp.test_client()
    r = c.get(f"/lms/assignments/{hid(A['assignment'])}/questions", base_url=host(A))
    assert r.status_code in (302, 401)
    assert "AssignQ-alpha" not in r.get_data(as_text=True)


def test_the_teacher_manages_assignment_and_quiz_questions(sapp, world, login_as):
    from app.extensions import db
    from app.models import AssignmentQuestion, BankChoice, BankQuestion, Question
    A = world["A"]
    with sapp.app_context():
        bq = db.session.get(BankQuestion, A["bank_question"])
        bq.review_state, bq.kind = "approved", "mcq"
        db.session.add(BankChoice(question_id=bq.id, order_index=1, label="b1", is_correct=True))
        db.session.commit()
        db.session.remove()
    c = _client(sapp, login_as, A, "teacher")
    h = host(A)

    asg = hid(A["assignment"])
    assert c.get(f"/lms/assignments/{asg}/questions", base_url=h).status_code == 200
    assert c.post(f"/lms/assignments/{asg}/questions/add", base_url=h,
                  data={"kind": "mcq", "prompt": "new-a", "points": "2"}).status_code == 302
    with sapp.app_context():
        new = AssignmentQuestion.query.filter_by(prompt="new-a").one()
        nid = new.id
        db.session.remove()
    assert c.post(f"/lms/assignment-questions/{hid(nid)}/update", base_url=h,
                  data={"prompt": "edited-a", "points": "3"}).status_code == 302
    assert c.post(f"/lms/assignments/{asg}/pick", base_url=h,
                  data={"bank_ids": [str(A["bank_question"])]}).status_code == 302
    assert c.post(f"/lms/assignment-questions/{hid(nid)}/delete", base_url=h).status_code == 302
    with sapp.app_context():
        assert AssignmentQuestion.query.filter_by(prompt="edited-a").count() == 0
        assert AssignmentQuestion.query.filter_by(assignment_id=A["assignment"],
                                                  source_bank_id=A["bank_question"]).count() == 1
        db.session.remove()

    quiz = hid(A["quiz"])
    assert c.get(f"/lms/quizzes/{quiz}/questions", base_url=h).status_code == 200
    assert c.post(f"/lms/quizzes/{quiz}/questions/add", base_url=h,
                  data={"kind": "tf", "prompt": "new-q", "points": "1"}).status_code == 302
    with sapp.app_context():
        qid = Question.query.filter_by(prompt="new-q").one().id
        db.session.remove()
    assert c.post(f"/lms/questions/{hid(qid)}/update", base_url=h,
                  data={"prompt": "edited-q", "points": "1"}).status_code == 302
    assert c.post(f"/lms/quizzes/{quiz}/pick", base_url=h,
                  data={"bank_ids": [str(A["bank_question"])]}).status_code == 302
    assert c.post(f"/lms/questions/{hid(qid)}/delete", base_url=h).status_code == 302
    with sapp.app_context():
        assert Question.query.filter_by(prompt="edited-q").count() == 0
        assert Question.query.filter_by(quiz_id=A["quiz"], source_bank_id=A["bank_question"]).count() == 1
        db.session.remove()


def test_a_role_without_lms_edit_gets_403(sapp, world, login_as):
    """A staff role that can see students but has no lms.edit (e.g. شؤون
    طلاب) cannot touch the questions either."""
    from app.extensions import db
    from app.models import Role
    A = world["A"]
    with sapp.app_context():
        role = db.session.get(Role, A["users"]["teacher"].role_id)
        role.permissions = {"students": ["view"], "lms": ["view"]}
        db.session.commit()
        db.session.remove()
    c = _client(sapp, login_as, A, "teacher")
    assert c.get(f"/lms/assignments/{hid(A['assignment'])}/questions", base_url=host(A)).status_code == 403
    assert c.post(f"/lms/assignment-questions/{hid(A['assignment_question'])}/delete",
                  base_url=host(A)).status_code == 403


def test_another_schools_assignment_is_refused(sapp, world, login_as):
    A, B = world["A"], world["B"]
    c = _client(sapp, login_as, A, "teacher")
    for url in (f"/lms/assignments/{hid(B['assignment'])}/questions",
                f"/lms/quizzes/{hid(B['quiz'])}/questions"):
        r = c.get(url, base_url=host(A))
        assert r.status_code in (403, 404)
        assert "AssignQ-beta" not in r.get_data(as_text=True)
    r = c.post(f"/lms/assignment-questions/{hid(B['assignment_question'])}/delete", base_url=host(A))
    assert r.status_code in (403, 404)


def test_the_mastery_reports_are_staff_only(sapp, world, login_as):
    A = world["A"]
    for role, code in (("student", 403), ("parent", 403), ("teacher", 200), ("admin", 200)):
        c = _client(sapp, login_as, A, role)
        assert c.get(f"/lms/reports/student/{hid(A['student'].id)}", base_url=host(A)).status_code == code
        assert c.get(f"/lms/reports/section/{hid(A['section'].id)}", base_url=host(A)).status_code == code


def test_the_api_question_bank_refuses_a_student_token(sapp, world, login_as):
    from app.extensions import db
    from app.models import BankQuestion
    from app.services.auth_jwt import issue_token
    A = world["A"]
    with sapp.app_context():
        before = db.session.get(BankQuestion, A["bank_question"]).review_state
        tokens = {r: issue_token(A["users"][r]) for r in ("student", "teacher")}
        db.session.remove()
    c = sapp.test_client()
    auth = {"Authorization": f"Bearer {tokens['student']}"}
    for path in ("/api/admin/question_bank/dashboard", "/api/admin/question_bank/questions"):
        assert c.get(path, base_url=host(A), headers=auth).status_code == 403
    r = c.post(f"/api/admin/question_bank/questions/{A['bank_question']}/state", base_url=host(A),
               headers=auth, json={"review_state": "rejected"})
    assert r.status_code == 403
    with sapp.app_context():
        assert db.session.get(BankQuestion, A["bank_question"]).review_state == before
        db.session.remove()
    teacher = {"Authorization": f"Bearer {tokens['teacher']}"}
    assert c.get("/api/admin/question_bank/questions", base_url=host(A), headers=teacher).status_code == 200


def test_a_refused_attempt_is_logged(sapp, world, login_as, caplog):
    A = world["A"]
    c = _client(sapp, login_as, A, "student")
    with caplog.at_level("WARNING"):
        c.get(f"/lms/assignments/{hid(A['assignment'])}/questions", base_url=host(A))
    assert any("permission denied" in r.getMessage() and "lms.edit" in r.getMessage()
               for r in caplog.records)
