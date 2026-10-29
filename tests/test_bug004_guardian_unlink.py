"""BUG-004 — «إلغاء الربط» on the student page: the unlink form was nested
inside the permissions form, so the browser dropped it and the button
saved the permissions instead. It is now a form of its own, reached with
form="…"; no page keeps a form inside a form."""

from __future__ import annotations

from datetime import date
from html.parser import HTMLParser

import pytest

from isolation_harness import hid, host


@pytest.fixture
def sapp(app, monkeypatch):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    return app


def _client(sapp, login_as, A, role):
    c = sapp.test_client()
    login_as(c, A["users"][role], base_url=host(A))
    return c


class _Forms(HTMLParser):
    """How the browser sees the forms: nesting depth, and each submit
    button's target (its form="" attribute, else the enclosing form)."""

    def __init__(self):
        super().__init__()
        self.stack, self.nested, self.forms, self.buttons = [], 0, {}, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            if self.stack:
                self.nested += 1
            self.stack.append(a)
            if a.get("id"):
                self.forms[a["id"]] = a
        elif tag == "button":
            self.buttons.append((a, self.stack[-1] if self.stack else None))

    def handle_endtag(self, tag):
        if tag == "form" and self.stack:
            self.stack.pop()

    def handle_data(self, data):
        if self.buttons and data.strip():
            a, target = self.buttons[-1]
            a.setdefault("_text", "")
            a["_text"] += data.strip()


def _parse(html):
    p = _Forms()
    p.feed(html)
    # form="id" wins over the enclosing form, wherever that form is
    p.buttons = [(a, p.forms.get(a["form"]) if a.get("form") else t) for a, t in p.buttons]
    return p


@pytest.fixture
def family(sapp, world):
    """School A: the world's student and a brother share one guardian; the
    student also has a second guardian."""
    from app.extensions import db
    from app.models import Enrollment, Guardian, Student, StudentGuardian
    A = world["A"]
    with sapp.app_context():
        link = db.session.get(StudentGuardian, A["guardian_link"])
        brother = Student(school_id=A["school"].id, permanent_code="PC-alpha-bro", full_name="Youssef")
        db.session.add(brother)
        db.session.flush()
        db.session.add(Enrollment(student_id=brother.id, section_id=A["section"].id, school_id=A["school"].id,
                                  year_id=A["year"].id, grade_id=A["grade"].id, status="active",
                                  enrolled_at=date(2026, 9, 1)))
        bro_link = StudentGuardian(student_id=brother.id, guardian_id=link.guardian_id)
        mother = Guardian(school_id=A["school"].id, full_name="Mother-alpha")
        db.session.add_all([bro_link, mother])
        db.session.flush()
        mother_link = StudentGuardian(student_id=link.student_id, guardian_id=mother.id)
        db.session.add(mother_link)
        db.session.commit()
        out = {"A": A, "link": link.id, "student": link.student_id, "guardian": link.guardian_id,
               "brother_link": bro_link.id, "mother_link": mother_link.id}
        db.session.remove()
    return out


def _links(sapp):
    from app.extensions import db
    from app.models import StudentGuardian
    with sapp.app_context():
        ids = {sg.id for sg in StudentGuardian.query.all()}
        db.session.remove()
    return ids


def test_the_student_page_has_no_nested_form_and_the_button_targets_unlink(sapp, family, login_as):
    A = family["A"]
    c = _client(sapp, login_as, A, "admin")
    html = c.get(f"/students/{hid(family['student'])}", base_url=host(A)).get_data(as_text=True)
    p = _parse(html)
    assert p.nested == 0
    unlink = [(a, t) for a, t in p.buttons if "إلغاء الربط" in a.get("_text", "")]
    assert len(unlink) == 2                                     # one per guardian
    for _a, target in unlink:
        assert target is not None and "/delete" in target["action"] and target["method"] == "post"
    save = [(a, t) for a, t in p.buttons if "حفظ الصلاحيات" in a.get("_text", "")]
    assert save and all("/update" in t["action"] for _a, t in save)


def test_unlinking_from_the_student_page_removes_only_that_link(sapp, family, login_as):
    from app.extensions import db
    from app.models import Guardian, Student
    A = family["A"]
    c = _client(sapp, login_as, A, "admin")
    before = _links(sapp)
    r = c.post(f"/students/guardian-links/{hid(family['link'])}/delete", base_url=host(A),
               follow_redirects=True)
    body = r.get_data(as_text=True)
    assert r.status_code == 200 and "تم إلغاء ربط ولي الأمر بالطالب" in body
    assert r.request.path == f"/students/{hid(family['student'])}"       # back on the student page
    assert _links(sapp) == before - {family["link"]}            # brother + mother links stay
    with sapp.app_context():
        assert db.session.get(Guardian, family["guardian"]) is not None
        assert db.session.get(Student, family["student"]) is not None
        db.session.remove()
    g = c.get(f"/students/guardians/{hid(family['guardian'])}", base_url=host(A)).get_data(as_text=True)
    assert "Youssef" in g


@pytest.mark.parametrize("role", ["teacher", "student", "parent"])
def test_a_role_without_students_edit_gets_403(sapp, family, login_as, role):
    A = family["A"]
    c = _client(sapp, login_as, A, role)
    before = _links(sapp)
    r = c.post(f"/students/guardian-links/{hid(family['link'])}/delete", base_url=host(A))
    assert r.status_code == 403
    assert _links(sapp) == before


def test_without_a_csrf_token_the_unlink_is_refused(sapp, family, login_as, monkeypatch):
    A = family["A"]
    c = _client(sapp, login_as, A, "admin")
    monkeypatch.setitem(sapp.config, "WTF_CSRF_ENABLED", True)
    before = _links(sapp)
    r = c.post(f"/students/guardian-links/{hid(family['link'])}/delete", base_url=host(A))
    assert r.status_code in (400, 403)
    assert _links(sapp) == before


def test_another_schools_link_is_refused(sapp, family, world, login_as):
    A, B = family["A"], world["B"]
    c = _client(sapp, login_as, A, "admin")
    before = _links(sapp)
    r = c.post(f"/students/guardian-links/{hid(B['guardian_link'])}/delete", base_url=host(A))
    assert r.status_code == 404
    assert _links(sapp) == before


def test_no_other_edit_page_nests_a_delete_form(sapp, world, login_as):
    """The same mistake on the lesson / assignment / quiz edit pages: the
    delete button sat in a form inside the edit form."""
    A = world["A"]
    c = _client(sapp, login_as, A, "admin")
    for url in (f"/courses/lessons/{hid(A['lesson'])}/edit",
                f"/lms/assignments/{hid(A['assignment'])}/edit",
                f"/lms/quizzes/{hid(A['quiz'])}/edit"):
        r = c.get(url, base_url=host(A))
        assert r.status_code == 200, url
        p = _parse(r.get_data(as_text=True))
        assert p.nested == 0, url
        delete = [t for a, t in p.buttons if a.get("form") == "delete-form"]
        assert delete and "/delete" in delete[0]["action"], url
