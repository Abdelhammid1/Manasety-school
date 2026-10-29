"""BUG-007 — publish a course to sections from the course page: the link
(CourseSection) decides which students see the course in «موادي»."""

from __future__ import annotations

from datetime import date

import pytest

from isolation_harness import hid, host


@pytest.fixture
def sapp(app, monkeypatch):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    return app


def _client(sapp, login_as, user, A):
    c = sapp.test_client()
    login_as(c, user, base_url=host(A))
    return c


@pytest.fixture
def school(sapp, world):
    """School A: its course starts with NO section; section «أ» holds the
    world's student, a new section «ب» of the same grade holds Salma."""
    from app.extensions import db
    from app.models import CourseSection, Enrollment, Role, Section, Student, User
    A = world["A"]
    with sapp.app_context():
        CourseSection.query.filter_by(course_id=A["course"]).delete()
        sec_b = Section(school_id=A["school"].id, year_id=A["year"].id, grade_id=A["grade"].id,
                        name="ب-alpha", capacity=30)
        db.session.add(sec_b)
        db.session.flush()
        role = Role.query.filter_by(school_id=A["school"].id, name="student").one()
        u = User(school_id=A["school"].id, role_id=role.id, username="salma_alpha", full_name="Salma")
        u.set_password("x" * 12)
        db.session.add(u)
        db.session.flush()
        salma = Student(school_id=A["school"].id, permanent_code="PC-alpha-salma", full_name="Salma",
                        user_id=u.id)
        db.session.add(salma)
        db.session.flush()
        db.session.add(Enrollment(student_id=salma.id, section_id=sec_b.id, school_id=A["school"].id,
                                  year_id=A["year"].id, grade_id=A["grade"].id,
                                  status="active", enrolled_at=date(2026, 9, 1)))
        db.session.commit()
        out = {"A": A, "sec_a": A["section"].id, "sec_b": sec_b.id, "salma": u.id}
        db.session.remove()
    return out


def _links(sapp, course_id):
    from app.extensions import db
    from app.models import CourseSection
    with sapp.app_context():
        rows = sorted(cs.section_id for cs in CourseSection.query.filter_by(course_id=course_id))
        db.session.remove()
    return rows


def _my_subjects(c, A) -> str:
    r = c.get("/dashboard", base_url=host(A))
    assert r.status_code == 200
    return r.get_data(as_text=True)


def _salma(sapp):
    from app.extensions import db
    from app.models import User
    with sapp.app_context():
        u = User.query.filter_by(username="salma_alpha").one()
        db.session.expunge(u)
        db.session.remove()
    return u


def test_link_from_the_course_page_then_the_student_sees_it(sapp, school, login_as):
    A = school["A"]
    student = _client(sapp, login_as, A["users"]["student"], A)
    assert "Course-alpha" not in _my_subjects(student, A)       # the bug: no link, nothing shown

    admin = _client(sapp, login_as, A["users"]["admin"], A)
    page = admin.get(f"/courses/{hid(A['course'])}", base_url=host(A)).get_data(as_text=True)
    assert "الشُعب المرتبطة" in page and 'name="section_ids"' in page
    r = admin.post(f"/courses/{hid(A['course'])}/sections/link", base_url=host(A),
                   data={"section_ids": [str(school["sec_a"])]})
    assert r.status_code == 302
    assert _links(sapp, A["course"]) == [school["sec_a"]]
    page = admin.get(f"/courses/{hid(A['course'])}", base_url=host(A)).get_data(as_text=True)
    assert "فك الربط" in page

    assert "Course-alpha" in _my_subjects(student, A)
    assert student.get(f"/courses/{hid(A['course'])}", base_url=host(A)).status_code == 200
    assert student.get(f"/lms/assignments/{hid(A['assignment'])}", base_url=host(A)).status_code == 200
    # Salma is in «ب», not linked
    salma = _client(sapp, login_as, _salma(sapp), A)
    assert "Course-alpha" not in _my_subjects(salma, A)
    assert salma.get(f"/courses/{hid(A['course'])}", base_url=host(A)).status_code == 404


def test_a_second_link_of_the_same_section_is_refused_with_a_message(sapp, school, login_as):
    A = school["A"]
    admin = _client(sapp, login_as, A["users"]["admin"], A)
    url = f"/courses/{hid(A['course'])}/sections/link"
    admin.post(url, base_url=host(A), data={"section_ids": [str(school["sec_a"])]})
    r = admin.post(url, base_url=host(A), data={"section_ids": [str(school["sec_a"])]}, follow_redirects=True)
    assert "مرتبطة بالفعل" in r.get_data(as_text=True)
    assert _links(sapp, A["course"]) == [school["sec_a"]]


def test_no_section_chosen_is_an_error(sapp, school, login_as):
    A = school["A"]
    admin = _client(sapp, login_as, A["users"]["admin"], A)
    r = admin.post(f"/courses/{hid(A['course'])}/sections/link", base_url=host(A), data={},
                   follow_redirects=True)
    assert "اختر شعبة واحدة على الأقل" in r.get_data(as_text=True)
    assert _links(sapp, A["course"]) == []


def test_an_unpublished_course_stays_hidden_even_when_linked(sapp, school, login_as):
    from app.extensions import db
    from app.models import Course
    A = school["A"]
    admin = _client(sapp, login_as, A["users"]["admin"], A)
    admin.post(f"/courses/{hid(A['course'])}/sections/link", base_url=host(A),
               data={"section_ids": [str(school["sec_a"])]})
    with sapp.app_context():
        db.session.get(Course, A["course"]).is_published = False
        db.session.commit()
        db.session.remove()
    assert "المقرّر مسودة" in admin.get(f"/courses/{hid(A['course'])}", base_url=host(A)).get_data(as_text=True)
    student = _client(sapp, login_as, A["users"]["student"], A)
    assert "Course-alpha" not in _my_subjects(student, A)


def test_unlinking_hides_the_course_and_keeps_the_submissions(sapp, school, login_as):
    from app.extensions import db
    from app.models import CourseSection, Submission
    A = school["A"]
    admin = _client(sapp, login_as, A["users"]["admin"], A)
    admin.post(f"/courses/{hid(A['course'])}/sections/link", base_url=host(A),
               data={"section_ids": [str(school["sec_a"]), str(school["sec_b"])]})
    assert _links(sapp, A["course"]) == sorted([school["sec_a"], school["sec_b"]])
    with sapp.app_context():
        link = CourseSection.query.filter_by(course_id=A["course"], section_id=school["sec_a"]).one().id
        subs = Submission.query.count()
        db.session.remove()
    r = admin.post(f"/courses/{hid(A['course'])}/sections/{hid(link)}/unlink", base_url=host(A))
    assert r.status_code == 302
    assert _links(sapp, A["course"]) == [school["sec_b"]]
    with sapp.app_context():
        assert Submission.query.count() == subs
        db.session.remove()
    student = _client(sapp, login_as, A["users"]["student"], A)
    assert "Course-alpha" not in _my_subjects(student, A)
    salma = _client(sapp, login_as, _salma(sapp), A)
    assert "Course-alpha" in _my_subjects(salma, A)
    # the same unlink again (another tab): a message, not an error
    r = admin.post(f"/courses/{hid(A['course'])}/sections/{hid(link)}/unlink", base_url=host(A),
                   follow_redirects=True)
    assert r.status_code == 200 and "غير موجود" in r.get_data(as_text=True)


@pytest.mark.parametrize("role", ["student", "parent"])
def test_a_student_or_parent_cannot_link_or_unlink(sapp, school, login_as, role):
    from app.extensions import db
    from app.models import CourseSection
    A = school["A"]
    with sapp.app_context():
        db.session.add(CourseSection(course_id=A["course"], section_id=school["sec_b"], is_published=True))
        db.session.commit()
        link = CourseSection.query.filter_by(course_id=A["course"]).one().id
        db.session.remove()
    c = _client(sapp, login_as, A["users"][role], A)
    assert c.post(f"/courses/{hid(A['course'])}/sections/link", base_url=host(A),
                  data={"section_ids": [str(school["sec_a"])]}).status_code == 403
    assert c.post(f"/courses/{hid(A['course'])}/sections/{hid(link)}/unlink",
                  base_url=host(A)).status_code == 403
    assert _links(sapp, A["course"]) == [school["sec_b"]]


def test_another_schools_section_or_course_is_refused(sapp, school, world, login_as):
    A, B = school["A"], world["B"]
    admin = _client(sapp, login_as, A["users"]["admin"], A)
    r = admin.post(f"/courses/{hid(A['course'])}/sections/link", base_url=host(A),
                   data={"section_ids": [str(B["section"].id)]}, follow_redirects=True)
    assert "غير متاحة" in r.get_data(as_text=True)
    assert _links(sapp, A["course"]) == []
    r = admin.post(f"/courses/{hid(B['course'])}/sections/link", base_url=host(A),
                   data={"section_ids": [str(school["sec_a"])]})
    assert r.status_code == 404
    assert _links(sapp, B["course"]) == [B["section"].id]


def test_a_deleted_section_does_not_break_the_pages(sapp, school, login_as):
    from app.extensions import db
    from app.models import Section
    A = school["A"]
    admin = _client(sapp, login_as, A["users"]["admin"], A)
    admin.post(f"/courses/{hid(A['course'])}/sections/link", base_url=host(A),
               data={"section_ids": [str(school["sec_b"])]})
    with sapp.app_context():
        db.session.get(Section, school["sec_b"]).soft_delete()
        db.session.commit()
        db.session.remove()
    page = admin.get(f"/courses/{hid(A['course'])}", base_url=host(A))
    assert page.status_code == 200 and "شعبة محذوفة" in page.get_data(as_text=True)
    salma = _client(sapp, login_as, _salma(sapp), A)
    assert salma.get("/dashboard", base_url=host(A)).status_code == 200


def test_link_and_unlink_are_in_the_activity_log(sapp, school, login_as):
    from app.extensions import db
    from app.models import AuditLog
    A = school["A"]
    with sapp.app_context():
        seen = AuditLog.query.count() and max(r.id for r in AuditLog.query.all())
        db.session.remove()
    admin = _client(sapp, login_as, A["users"]["admin"], A)
    admin.post(f"/courses/{hid(A['course'])}/sections/link", base_url=host(A),
               data={"section_ids": [str(school["sec_a"])]})
    with sapp.app_context():
        link = AuditLog.query.filter(AuditLog.id > seen, AuditLog.entity_type == "CourseSection").one()
        assert link.action == "create" and link.school_id == A["school"].id
        lid = link.entity_id
        db.session.remove()
    admin.post(f"/courses/{hid(A['course'])}/sections/{hid(lid)}/unlink", base_url=host(A))
    with sapp.app_context():
        assert AuditLog.query.filter(AuditLog.id > seen, AuditLog.entity_type == "CourseSection",
                                     AuditLog.action == "delete").count() == 1
        db.session.remove()
