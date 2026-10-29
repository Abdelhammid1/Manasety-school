"""Ticket «ولي الأمر — في قائمة الطلاب» — the column shows the linked
guardian (primary, else the first linked), falls back to the old
parent_name, «—» only with neither; search finds a student by the linked
guardian's name; one query for the whole page."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import event

from isolation_harness import host


@pytest.fixture
def sapp(app, monkeypatch):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    return app


@pytest.fixture
def kids(sapp, two_schools):
    """Two brothers linked to «أبو العتيبي» (existing guardian, primary for
    one, plus a non-primary aunt), a legacy student with parent_name only,
    and one with nothing."""
    from app.extensions import db
    from app.models import Guardian, Student, StudentGuardian
    A = two_schools["A"]
    sid = A["school"].id
    with sapp.app_context():
        father = Guardian(school_id=sid, full_name="أبو العتيبي", phone="0500000001")
        aunt = Guardian(school_id=sid, full_name="خالة سلمى")
        db.session.add_all([father, aunt]); db.session.flush()
        out = {}
        for code, name in (("K1", "سلمى العتيبي"), ("K2", "يوسف العتيبي"), ("K3", "قديم"), ("K4", "بدون")):
            st = Student(school_id=sid, permanent_code=code, full_name=name)
            if code == "K3":
                st.parent_name = "اسم قديم"
            db.session.add(st); db.session.flush()
            out[code] = st.id
        # Salma: aunt linked first (not primary), father primary
        db.session.add(StudentGuardian(student_id=out["K1"], guardian_id=aunt.id, is_primary=False))
        db.session.add(StudentGuardian(student_id=out["K1"], guardian_id=father.id, is_primary=True))
        db.session.add(StudentGuardian(student_id=out["K2"], guardian_id=father.id, is_primary=False))
        db.session.commit()
        db.session.remove()
    return out


def _row(body, name):
    i = body.index(name)
    return body[i:i + 1500]


def test_the_column_shows_the_linked_guardian_then_parent_name_then_dash(sapp, two_schools, login_as, kids):
    A = two_schools["A"]
    c = sapp.test_client()
    login_as(c, A["users"]["admin"], base_url=host(A))
    body = c.get("/students", base_url=host(A)).get_data(as_text=True)
    assert "أبو العتيبي" in _row(body, "سلمى العتيبي")          # primary wins over the first link
    assert "خالة سلمى" not in _row(body, "سلمى العتيبي")
    assert "أبو العتيبي" in _row(body, "يوسف العتيبي")          # the only link, not primary
    assert "اسم قديم" in _row(body, ">قديم<")
    bare = _row(body, ">بدون<")
    assert "—" in bare and "أبو العتيبي" not in bare


def test_search_by_the_linked_guardian_finds_the_children(sapp, two_schools, login_as, kids):
    A = two_schools["A"]
    c = sapp.test_client()
    login_as(c, A["users"]["admin"], base_url=host(A))
    body = c.get("/students?q=أبو العتيبي", base_url=host(A)).get_data(as_text=True)
    assert "سلمى العتيبي" in body and "يوسف العتيبي" in body and ">قديم<" not in body
    body = c.get("/students?q=اسم قديم", base_url=host(A)).get_data(as_text=True)
    assert ">قديم<" in body


def test_the_query_count_does_not_grow_with_the_rows(sapp, two_schools, login_as):
    from app.extensions import db
    from app.models import Enrollment, Guardian, Student, StudentGuardian
    A = two_schools["A"]
    c = sapp.test_client()
    login_as(c, A["users"]["admin"], base_url=host(A))

    def add(n):
        with sapp.app_context():
            for i in range(n):
                g = Guardian(school_id=A["school"].id, full_name=f"G{i}-{n}")
                st = Student(school_id=A["school"].id, permanent_code=f"Q{n}-{i}", full_name=f"S{n}-{i}")
                db.session.add_all([g, st]); db.session.flush()
                db.session.add(StudentGuardian(student_id=st.id, guardian_id=g.id, is_primary=True))
                db.session.add(Enrollment(student_id=st.id, school_id=A["school"].id, year_id=A["year"].id,
                                          grade_id=A["grade"].id, section_id=A["section"].id,
                                          status="active", enrolled_at=date(2026, 9, 1)))
            db.session.commit()
            db.session.remove()

    def count():
        """Statements that read the guardians — the column's cost."""
        with sapp.app_context():
            engine = db.engine
        n = {"q": 0}

        def on(_conn, _cur, statement, *_a, **_k):
            if "guardians" in statement:
                n["q"] += 1
        event.listen(engine, "before_cursor_execute", on)
        try:
            assert c.get("/students", base_url=host(A)).status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", on)
        return n["q"]

    add(5)
    small = count()
    add(30)
    assert count() == small <= 2         # one for the column (+ none per row)


def test_the_section_page_shows_the_linked_guardian_too(sapp, two_schools, login_as, kids):
    from app.extensions import db
    from app.models import Enrollment
    A = two_schools["A"]
    with sapp.app_context():
        db.session.add(Enrollment(student_id=kids["K1"], school_id=A["school"].id, year_id=A["year"].id,
                                  grade_id=A["grade"].id, section_id=A["section"].id,
                                  status="active", enrolled_at=date(2026, 9, 1)))
        db.session.commit()
        db.session.remove()
    from isolation_harness import hid
    c = sapp.test_client()
    login_as(c, A["users"]["admin"], base_url=host(A))
    body = c.get(f"/academic/sections/{hid(A['section'].id)}", base_url=host(A)).get_data(as_text=True)
    assert "أبو العتيبي" in _row(body, "سلمى العتيبي")
