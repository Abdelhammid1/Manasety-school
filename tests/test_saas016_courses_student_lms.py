"""SAAS-016 — courses + the student LMS path: attempt ownership inside one
school, ids inside the payloads, the autosave query budget, and A's own
flows still working (the cross-school matrix is in test_saas002)."""

from __future__ import annotations

import pytest
from sqlalchemy import event

from isolation_harness import host, hid


@pytest.fixture
def sapp(app, monkeypatch):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    return app


def _client(sapp, login_as, A, role):
    c = sapp.test_client()
    login_as(c, A["users"][role], base_url=host(A))
    return c


@pytest.fixture
def classmate_attempt(sapp, world):
    """A second student of school A (no portal account) with an open
    attempt on A's quiz."""
    from app.extensions import db
    from app.models import QuizAttempt, Student
    A = world["A"]
    with sapp.app_context():
        mate = Student(school_id=A["school"].id, permanent_code="PC-alpha-02", full_name="Classmate-alpha")
        db.session.add(mate)
        db.session.flush()
        att = QuizAttempt(quiz_id=A["quiz"], student_id=mate.id)
        db.session.add(att)
        db.session.commit()
        aid = att.id
        db.session.remove()
    return aid


@pytest.mark.parametrize("path,data", [
    ("/lms/quizzes/attempts/{a}/autosave", {"question_id": "{q}", "choice_id": "{c}"}),
    ("/lms/quizzes/attempts/{a}/flag", {"question_id": "{q}"}),
    ("/lms/quizzes/attempts/{a}/tab-switch", {}),
])
def test_a_student_cannot_write_a_classmates_attempt(sapp, world, login_as, classmate_attempt,
                                                     path, data):
    from sqlalchemy import select
    from app.extensions import db
    from app.models import QuizAttempt
    A = world["A"]
    fmt = {"a": classmate_attempt, "q": A["question"], "c": A["choice"]}
    with sapp.app_context():
        t = QuizAttempt.__table__
        before = dict(db.session.execute(select(t).where(t.c.id == classmate_attempt)).mappings().one())
        db.session.remove()
    c = _client(sapp, login_as, A, "student")
    r = c.post(path.format(a=hid(classmate_attempt)), base_url=host(A), data={k: v.format(**fmt) for k, v in data.items()})
    assert r.status_code == 403
    with sapp.app_context():
        after = dict(db.session.execute(select(t).where(t.c.id == classmate_attempt)).mappings().one())
        db.session.remove()
    assert after == before


def test_a_student_cannot_submit_or_read_a_classmates_attempt(sapp, world, login_as, classmate_attempt):
    A = world["A"]
    c = _client(sapp, login_as, A, "student")
    r = c.post(f"/lms/quizzes/{hid(A['quiz'])}/submit", base_url=host(A),
               data={"attempt_id": classmate_attempt})
    assert r.status_code == 403
    assert c.get(f"/lms/quizzes/result/{hid(classmate_attempt)}", base_url=host(A)).status_code == 403


def test_autosave_refuses_a_choice_of_another_question(sapp, world, login_as):
    from app.extensions import db
    from app.models import Answer
    A, B = world["A"], world["B"]
    c = _client(sapp, login_as, A, "student")
    url = f"/lms/quizzes/attempts/{hid(A['attempt'])}/autosave"
    r = c.post(url, base_url=host(A), data={"question_id": A["question"], "choice_id": B["choice"]})
    assert r.status_code == 400
    r = c.post(url, base_url=host(A), data={"question_id": A["question"], "choice_id": A["choice"]})
    assert r.status_code == 200 and r.get_json() == {"saved": True}
    with sapp.app_context():
        ans = Answer.query.filter_by(attempt_id=A["attempt"], question_id=A["question"]).one()
        assert ans.choice_id == A["choice"]
        db.session.remove()


def test_quiz_submit_never_stores_a_foreign_choice(sapp, world, login_as):
    from app.extensions import db
    from app.models import Answer, QuizAttempt
    A, B = world["A"], world["B"]
    c = _client(sapp, login_as, A, "student")
    r = c.post(f"/lms/quizzes/{hid(A['quiz'])}/submit", base_url=host(A),
               data={"attempt_id": A["attempt"], f"q_{A['question']}": B["choice"]})
    assert r.status_code in (200, 302)
    with sapp.app_context():
        ans = Answer.query.filter_by(attempt_id=A["attempt"], question_id=A["question"]).one()
        assert ans.choice_id is None and ans.is_correct is False
        assert db.session.get(QuizAttempt, A["attempt"]).submitted_at is not None
        db.session.remove()


def _count_queries(sapp, fn):
    from app.extensions import db
    with sapp.app_context():
        engine = db.engine
    n = {"q": 0}

    def on_exec(*_a, **_k):
        n["q"] += 1
    event.listen(engine, "before_cursor_execute", on_exec)
    try:
        fn()
    finally:
        event.remove(engine, "before_cursor_execute", on_exec)
    return n["q"]


def test_autosave_query_count_stays_within_one_extra_query(sapp, world, login_as):
    """The ticket's budget: the ownership / choice checks add at most one
    query to an autosave. Measured with this test (whole request, session
    and tenant checks included):

        before SAAS-015/016 (get_or_404, no choice check): mcq=12 text=15
        after  (owned_or_404 + choice belongs to question): mcq=13 text=15
        + the features gate (2026-10-25): one read of the school's page
          overrides per request (cached in g): mcq=14 text=16
    """
    from app.extensions import db
    from app.models import Question
    A = world["A"]
    with sapp.app_context():
        q2 = Question(quiz_id=A["quiz"], prompt="نص", kind="short", points=1)
        db.session.add(q2)
        db.session.commit()
        q2_id = q2.id
        db.session.remove()
    c = _client(sapp, login_as, A, "student")
    url = f"/lms/quizzes/attempts/{hid(A['attempt'])}/autosave"
    # Warm both paths once (first-request lazy loads are not the budget).
    c.post(url, base_url=host(A), data={"question_id": A["question"], "choice_id": A["choice"]})
    c.post(url, base_url=host(A), data={"question_id": q2_id, "text": "x"})
    mcq = _count_queries(sapp, lambda: c.post(url, base_url=host(A), data={
        "question_id": A["question"], "choice_id": A["choice"]}))
    text = _count_queries(sapp, lambda: c.post(url, base_url=host(A), data={
        "question_id": q2_id, "text": "y"}))
    print(f"\n[SAAS-016] autosave SQL statements: mcq={mcq} text={text}")
    assert mcq <= 12 + 1 + 1 and text <= 15 + 1, (mcq, text)


def test_lesson_unit_must_be_a_unit_of_the_same_course(sapp, world, login_as):
    from app.extensions import db
    from app.models import Course, Lesson, Unit
    A = world["A"]
    with sapp.app_context():
        other = Course(school_id=A["school"].id, academic_year_id=A["year"].id, grade_id=A["grade"].id,
                       subject_id=A["subject"].id, title="Course2-alpha")
        db.session.add(other)
        db.session.flush()
        u2 = Unit(course_id=other.id, title="Unit2-alpha")
        db.session.add(u2)
        db.session.commit()
        u2_id = u2.id
        db.session.remove()
    c = _client(sapp, login_as, A, "admin")
    assert c.post(f"/courses/lessons/{hid(A['lesson'])}/edit", base_url=host(A),
                  data={"title": "درس", "unit_id": u2_id}).status_code == 404
    assert c.post(f"/courses/lessons/{hid(A['lesson'])}/edit", base_url=host(A),
                  data={"title": "درس", "unit_id": A["unit"]}).status_code in (200, 302)
    assert c.post(f"/courses/{hid(A['course'])}/lessons/new", base_url=host(A),
                  data={"title": "درس جديد", "unit_id": A["unit"]}).status_code in (200, 302)
    with sapp.app_context():
        assert db.session.get(Lesson, A["lesson"]).unit_id == A["unit"]
        assert Lesson.query.filter_by(title="درس جديد").one().unit_id == A["unit"]
        db.session.remove()


@pytest.mark.parametrize("path", ["/courses/{course}", "/courses/lessons/{lesson}"])
def test_own_course_pages_open_for_the_student(sapp, world, login_as, path):
    A, B = world["A"], world["B"]
    c = _client(sapp, login_as, A, "admin")
    r = c.get(path.format(course=hid(A["course"]), lesson=hid(A["lesson"])), base_url=host(A))
    assert r.status_code == 200
    assert not [m for m in B["markers"] if m in r.get_data(as_text=True)]
