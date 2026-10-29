"""Ticket «مادة بدون صفوف» — a subject needs at least one grade (new and
edit, checked on the server); terms stay optional; ids must be this
school's; the form keeps what was typed; old unlinked subjects still open
and are flagged on the list."""

from __future__ import annotations

import pytest

from isolation_harness import hid, host


@pytest.fixture
def sapp(app, monkeypatch):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    return app


def _client(sapp, login_as, A, role="admin"):
    c = sapp.test_client()
    login_as(c, A["users"][role], base_url=host(A))
    return c


def _subjects(sapp, sid):
    from app.extensions import db
    from app.models import Subject
    with sapp.app_context():
        out = {s.name: (sorted(g.id for g in s.grades), sorted(t.id for t in s.terms), s.code)
               for s in Subject.query.filter_by(school_id=sid)}
        db.session.remove()
    return out


def test_new_subject_without_a_grade_is_refused_and_the_form_keeps_the_input(sapp, two_schools, login_as):
    A = two_schools["A"]
    c = _client(sapp, login_as, A)
    before = _subjects(sapp, A["school"].id)
    r = c.post("/teachers/subjects/new", base_url=host(A),
               data={"name": "مادة اختبار 2", "code": "TST003", "term_ids": [str(A["term"].id)]})
    body = r.get_data(as_text=True)
    assert r.status_code == 400 and "اختر صفاً دراسياً واحداً على الأقل" in body
    assert 'value="مادة اختبار 2"' in body and 'value="TST003"' in body
    assert _subjects(sapp, A["school"].id) == before


def test_a_complete_subject_saves_with_grade_term_and_code(sapp, two_schools, login_as):
    A = two_schools["A"]
    c = _client(sapp, login_as, A)
    r = c.post("/teachers/subjects/new", base_url=host(A),
               data={"name": "علوم", "code": "SCI1", "grade_ids": [str(A["grade"].id)],
                     "term_ids": [str(A["term"].id)]})
    assert r.status_code == 302
    assert _subjects(sapp, A["school"].id)["علوم"] == ([A["grade"].id], [A["term"].id], "SCI1")
    # a term is required too once the school has terms (decision)
    r = c.post("/teachers/subjects/new", base_url=host(A),
               data={"name": "فنون", "grade_ids": [str(A["grade"].id)]})
    assert r.status_code == 400 and "فصلاً دراسياً" in r.get_data(as_text=True)
    assert "فنون" not in _subjects(sapp, A["school"].id)


def test_a_school_without_terms_can_still_save_a_subject(sapp, two_schools, login_as):
    from app.extensions import db
    from app.models import Term
    A = two_schools["A"]
    with sapp.app_context():
        for t in Term.query.filter_by(school_id=A["school"].id):
            t.soft_delete()
        db.session.commit(); db.session.remove()
    r = _client(sapp, login_as, A).post("/teachers/subjects/new", base_url=host(A),
                                         data={"name": "فنون", "grade_ids": [str(A["grade"].id)]})
    assert r.status_code == 302 and _subjects(sapp, A["school"].id)["فنون"][1] == []


def test_edit_cannot_remove_every_grade_and_keeps_the_code(sapp, two_schools, login_as):
    from app.extensions import db
    from app.models import Subject
    A = two_schools["A"]
    with sapp.app_context():
        s = Subject.query.filter_by(school_id=A["school"].id).first()
        s.code = "KEEP1"
        db.session.commit()
        sid, name = s.id, s.name
        db.session.remove()
    c = _client(sapp, login_as, A)
    page = c.get(f"/teachers/subjects/{hid(sid)}/edit", base_url=host(A)).get_data(as_text=True)
    assert 'value="KEEP1"' in page                     # the form carries the code now
    before = _subjects(sapp, A["school"].id)[name]
    r = c.post(f"/teachers/subjects/{hid(sid)}/edit", base_url=host(A),
               data={"name": name, "code": "KEEP1", "term_ids": [str(A["term"].id)]})
    assert r.status_code == 400 and "واحداً على الأقل" in r.get_data(as_text=True)
    assert _subjects(sapp, A["school"].id)[name] == before


@pytest.mark.parametrize("field", ["grade_ids", "term_ids"])
def test_another_schools_grade_or_term_is_refused(sapp, two_schools, login_as, field):
    A, B = two_schools["A"], two_schools["B"]
    c = _client(sapp, login_as, A)
    data = {"name": "خارجية", "grade_ids": [str(A["grade"].id)], "term_ids": [str(A["term"].id)]}
    data[field] = [str((B["grade"] if field == "grade_ids" else B["term"]).id)]
    r = c.post("/teachers/subjects/new", base_url=host(A), data=data)
    assert r.status_code == 400 and "غير موجود" in r.get_data(as_text=True)
    assert "خارجية" not in _subjects(sapp, A["school"].id)


def test_a_deleted_grade_is_refused(sapp, two_schools, login_as):
    from app.extensions import db
    from app.models import Grade
    A = two_schools["A"]
    with sapp.app_context():
        g = Grade(school_id=A["school"].id, name="محذوف", order_index=9)
        db.session.add(g); db.session.flush()
        g.soft_delete()
        db.session.commit()
        gid = g.id
        db.session.remove()
    r = _client(sapp, login_as, A).post("/teachers/subjects/new", base_url=host(A),
                                         data={"name": "قديمة", "grade_ids": [str(gid)]})
    assert r.status_code == 400 and "قديمة" not in _subjects(sapp, A["school"].id)


def test_a_duplicate_name_is_a_message_not_a_500(sapp, two_schools, login_as):
    A = two_schools["A"]
    existing = next(iter(_subjects(sapp, A["school"].id)))
    r = _client(sapp, login_as, A).post("/teachers/subjects/new", base_url=host(A),
                                         data={"name": existing, "grade_ids": [str(A["grade"].id)],
                                               "term_ids": [str(A["term"].id)]})
    assert r.status_code == 400 and "توجد مادة بنفس الاسم" in r.get_data(as_text=True)


def test_an_old_unlinked_subject_opens_and_is_flagged_on_the_list(sapp, two_schools, login_as):
    from app.extensions import db
    from app.models import Subject
    A = two_schools["A"]
    with sapp.app_context():
        s = Subject(school_id=A["school"].id, name="يتيمة")
        db.session.add(s); db.session.commit()
        sid = s.id
        db.session.remove()
    c = _client(sapp, login_as, A)
    body = c.get("/teachers/subjects", base_url=host(A)).get_data(as_text=True)
    assert "غير مرتبطة بأي صف" in body and "يتيمة" in body
    assert c.get(f"/teachers/subjects/{hid(sid)}/edit", base_url=host(A)).status_code == 200
    r = c.post(f"/teachers/subjects/{hid(sid)}/edit", base_url=host(A),
               data={"name": "يتيمة", "grade_ids": [str(A["grade"].id)], "term_ids": [str(A["term"].id)]})
    assert r.status_code == 302 and _subjects(sapp, A["school"].id)["يتيمة"][0] == [A["grade"].id]


@pytest.mark.parametrize("role", ["student", "parent"])
def test_without_teachers_add_the_form_is_403(sapp, two_schools, login_as, role):
    A = two_schools["A"]
    r = _client(sapp, login_as, A, role).post("/teachers/subjects/new", base_url=host(A),
                                               data={"name": "x", "grade_ids": [str(A["grade"].id)]})
    assert r.status_code == 403


def test_a_subject_with_a_grade_but_no_term_is_flagged(sapp, two_schools, login_as):
    from app.extensions import db
    from app.models import Grade, Subject
    A = two_schools["A"]
    with sapp.app_context():
        s = Subject(school_id=A["school"].id, name="بلا-ترم")
        s.grades = [db.session.get(Grade, A["grade"].id)]
        db.session.add(s); db.session.commit(); db.session.remove()
    body = _client(sapp, login_as, A).get("/teachers/subjects", base_url=host(A)).get_data(as_text=True)
    i = body.index("بدون فصل دراسي")
    assert "بلا-ترم" in body[i:i + 600]
