"""SAAS-017 — the mobile API: the one rejection shape, the relationship
checks (parent ↔ own children, teacher ↔ own sections), the quiz-submit
choice check and where uploads land. The cross-school matrix is in
test_saas002; the contract on A's own records in the snapshot test."""

from __future__ import annotations

import io

import pytest

from isolation_harness import host

NOT_FOUND = {"error": "not_found"}


@pytest.fixture
def papp(app, monkeypatch):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    return app


def _api(app, A, role_or_user):
    from app.services.auth_jwt import issue_token
    user = A["users"][role_or_user] if isinstance(role_or_user, str) else role_or_user
    with app.app_context():
        tok = issue_token(user)
    c = app.test_client()
    c.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {tok}"
    return c


@pytest.mark.parametrize("role,method,path", [
    ("parent", "GET", "/api/parent/child/{student}/attendance"),
    ("parent", "POST", "/api/notifications/{notification}/read"),
    ("parent", "POST", "/api/parent/pickup/{pickup}/release"),
    ("teacher", "POST", "/api/pickup/{pickup}/ack"),
    ("student", "GET", "/api/student/assignments/{assignment}"),
    ("student", "GET", "/api/student/courses/{course}"),
    ("student", "GET", "/api/student/lessons/{lesson}"),
    ("student", "GET", "/api/student/quizzes/{quiz}/attempt"),
    ("student", "GET", "/api/student/report-card/{term}"),
    ("teacher", "GET", "/api/teacher/assignments/{assignment}"),
    ("teacher", "GET", "/api/teacher/quizzes/{quiz}/stats"),
    ("teacher", "GET", "/api/teacher/messages/{conversation}"),
    ("teacher", "GET", "/api/teacher/section/{section}/schedule"),
    ("teacher", "GET", "/api/teacher/templates/{assess_template}"),
])
def test_rejection_is_exactly_not_found_for_foreign_and_missing(papp, world, role, method, path):
    A, B = world["A"], world["B"]
    ids = {k: getattr(B[k], "id", B[k]) for k in ("student", "notification", "pickup", "assignment",
                                                   "course", "lesson", "quiz", "term", "conversation",
                                                   "section", "assess_template")}
    c = _api(papp, A, role)
    for url in (path.format(**ids), path.format(**{k: 987654321 for k in ids})):
        r = c.open(url, method=method, base_url=host(A))
        assert r.status_code == 404, url
        assert r.get_json() == NOT_FOUND, url


def test_parent_sees_only_own_children_in_the_same_school(papp, world):
    """A child of school A who is not this parent's: not_found, and the
    notification about that child can't be marked read."""
    from app.extensions import db
    from app.models import NotificationLog, Student
    A = world["A"]
    with papp.app_context():
        other = Student(school_id=A["school"].id, permanent_code="PC-alpha-09", full_name="OtherKid-alpha")
        db.session.add(other)
        db.session.flush()
        n = NotificationLog(school_id=A["school"].id, student_id=other.id, kind="announcement",
                            status="sent", payload="{}")
        db.session.add(n)
        db.session.commit()
        kid, nid = other.id, n.id
        db.session.remove()
    c = _api(papp, A, "parent")
    r = c.get(f"/api/parent/child/{kid}/attendance", base_url=host(A))
    assert (r.status_code, r.get_json()) == (404, NOT_FOUND)
    r = c.post(f"/api/notifications/{nid}/read", base_url=host(A))
    assert (r.status_code, r.get_json()) == (404, NOT_FOUND)
    with papp.app_context():
        assert db.session.get(NotificationLog, nid).read_at is None
        db.session.remove()
    assert c.get(f"/api/parent/child/{A['student'].id}/attendance", base_url=host(A)).status_code == 200


def test_teacher_reads_only_the_sections_they_teach(papp, world):
    from app.extensions import db
    from app.models import Section
    A = world["A"]
    with papp.app_context():
        sec = Section(school_id=A["school"].id, year_id=A["year"].id, grade_id=A["grade"].id,
                      name="Sec9-alpha", capacity=30)
        db.session.add(sec)
        db.session.commit()
        other = sec.id
        db.session.remove()
    c = _api(papp, A, "teacher")
    for url in (f"/api/teacher/students?section_id={other}", f"/api/teacher/section/{other}/schedule"):
        r = c.get(url, base_url=host(A))
        assert r.status_code == 403, url
        assert r.get_json() == {"error": "teacher not assigned to this section"}
    for url in (f"/api/teacher/students?section_id={A['section'].id}",
                f"/api/teacher/section/{A['section'].id}/schedule"):
        assert c.get(url, base_url=host(A)).status_code == 200, url
    # The roster is not for parents / students of the school.
    r = _api(papp, A, "parent").get(f"/api/teacher/students?section_id={A['section'].id}", base_url=host(A))
    assert r.status_code == 403


def test_quiz_submit_scores_only_this_questions_choices(papp, world):
    """Before SAAS-017 any correct choice id — of another question or
    another school — scored the points."""
    from app.extensions import db
    from app.models import Answer, Choice, Question
    A, B = world["A"], world["B"]
    with papp.app_context():
        q2 = Question(quiz_id=A["quiz"], prompt="س٢", kind="mcq", points=1)
        db.session.add(q2)
        db.session.flush()
        right2 = Choice(question_id=q2.id, label="صح", is_correct=True)
        db.session.add(right2)
        db.session.commit()
        q2_id, right2_id = q2.id, right2.id
        db.session.remove()
    c = _api(papp, A, "student")
    # q1 answered with q2's correct choice, q2 with B's correct choice.
    r = c.post(f"/api/student/quizzes/{A['quiz']}/submit", base_url=host(A),
               json={"answers": {str(A["question"]): right2_id, str(q2_id): B["choice"]}})
    assert r.status_code == 200
    assert r.get_json()["awarded"] == 0
    with papp.app_context():
        aid = r.get_json()["attempt_id"]
        assert [a.choice_id for a in Answer.query.filter_by(attempt_id=aid).all()] == [None, None]
        db.session.remove()
    r = c.post(f"/api/student/quizzes/{A['quiz']}/submit", base_url=host(A),
               json={"answers": {str(A["question"]): A["choice"], str(q2_id): right2_id}})
    assert r.get_json()["awarded"] == 2


def test_teacher_upload_lands_under_the_schools_folder(papp, world, tmp_path, monkeypatch):
    from app.extensions import db
    from app.models import Material
    A = world["A"]
    monkeypatch.setitem(papp.config, "UPLOAD_ROOT", str(tmp_path))
    c = _api(papp, A, "teacher")
    r = c.post("/api/teacher/upload", base_url=host(A), data={
        "section_id": A["section"].id, "subject_id": A["subject"].id, "title": "ملف",
        "file": (io.BytesIO(b"%PDF-1.4 x"), "x.pdf")})
    assert r.status_code == 201, r.get_data(as_text=True)
    with papp.app_context():
        m = Material.query.filter_by(school_id=A["school"].id, title="ملف").one()
        key = m.file_path.split("/files/", 1)[1]
        db.session.remove()
    assert key.startswith(f"{A['school'].id}/materials/{A['section'].id}/")
    assert (tmp_path / key).is_file()
    assert not list(tmp_path.glob(f"{world['B']['school'].id}/**/*.pdf"))


def test_student_reaches_only_courses_published_to_their_section(papp, world):
    """Same school, published course, but not published to the student's
    section (or the student has no active enrollment): not_found, as on
    the web (lms._assert_can_view_course_item)."""
    from app.extensions import db
    from app.models import Course, CourseAssignment, Enrollment, Lesson, Quiz
    A = world["A"]
    with papp.app_context():
        other = Course(school_id=A["school"].id, academic_year_id=A["year"].id, grade_id=A["grade"].id,
                       subject_id=A["subject"].id, title="Hidden-alpha", is_published=True)
        db.session.add(other)
        db.session.flush()
        lesson = Lesson(course_id=other.id, title="HiddenL-alpha", body="x")
        quiz = Quiz(course_id=other.id, title="HiddenQ-alpha", is_published=True)
        asg = CourseAssignment(course_id=other.id, title="HiddenA-alpha", is_published=True)
        db.session.add_all([lesson, quiz, asg])
        db.session.commit()
        ids = {"course": other.id, "lesson": lesson.id, "quiz": quiz.id, "assignment": asg.id}
        db.session.remove()
    calls = [("GET", "/api/student/courses/{course}", None),
             ("GET", "/api/student/lessons/{lesson}", None),
             ("GET", "/api/student/assignments/{assignment}", None),
             ("POST", "/api/student/assignments/{assignment}/submit", {"body": "x"}),
             ("GET", "/api/student/quizzes/{quiz}/attempt", None),
             ("POST", "/api/student/quizzes/{quiz}/submit", {"answers": {}})]
    c = _api(papp, A, "student")
    for method, path, body in calls:
        r = c.open(path.format(**ids), method=method, json=body, base_url=host(A))
        assert (r.status_code, r.get_json()) == (404, NOT_FOUND), path
        assert "Hidden" not in r.get_data(as_text=True)
    # A's own course (published to the student's section) still opens …
    assert c.get(f"/api/student/courses/{A['course']}", base_url=host(A)).status_code == 200
    # … and fails closed once the student has no active enrollment.
    with papp.app_context():
        e = db.session.get(Enrollment, A["enrollment"].id)
        e.status = "withdrawn"
        db.session.commit()
        db.session.remove()
    try:
        r = c.get(f"/api/student/courses/{A['course']}", base_url=host(A))
        assert (r.status_code, r.get_json()) == (404, NOT_FOUND)
    finally:
        with papp.app_context():
            db.session.get(Enrollment, A["enrollment"].id).status = "active"
            db.session.commit()
            db.session.remove()
