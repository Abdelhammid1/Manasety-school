"""Academic forms (years, terms, grades, sections): every bad input is one
clear Arabic message with the typed values kept — never a 500 / 404 / 403
— and a good input saves as before. Plus BUG-001: a year name (2026-2027)
inside an Arabic message keeps its order (Unicode isolates)."""

from __future__ import annotations

import pytest

from isolation_harness import hid, host

ISO_L, ISO_R = "⁦", "⁩"


@pytest.fixture
def vapp(app, monkeypatch):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    return app


def _c(app, login_as, bundle):
    c = app.test_client()
    login_as(c, bundle["users"]["admin"], base_url=host(bundle))
    return c


def _post(c, bundle, url, data):
    import html
    r = c.post(url, base_url=host(bundle), data=data, follow_redirects=True)
    return r.status_code, html.unescape(r.get_data(as_text=True))     # messages hold "…" (escaped in HTML)


def _count(app, model_name, **where):
    from app import models
    from app.extensions import db
    with app.app_context():
        n = getattr(models, model_name).query.execution_options(include_deleted=True).filter_by(**where).count()
        db.session.remove()
    return n


# ─── terms ──────────────────────────────────────────────────────────

def _term_form(**over):
    base = {"name": "الفصل الدراسي الثاني", "order_index": "2", "start_date": "2027-02-01",
            "end_date": "2027-06-10", "weight": "50", "status_mode": "auto"}
    return {**base, **over}


@pytest.mark.parametrize("over,message", [
    ({"weight": "60"}, "مجموع أوزان الفترات لا يجب أن يتجاوز 100% (الحالي بعد التعديل: 110%"),
    ({"weight": "abc"}, "الوزن يجب أن يكون رقمًا بين 0 و100"),
    ({"weight": "-5"}, "الوزن يجب أن يكون رقمًا بين 0 و100"),
    ({"weight": ""}, "الوزن يجب أن يكون رقمًا بين 0 و100"),
    ({"order_index": "1"}, "ترتيب الفترة (1) مستخدم بالفعل في فترة \"Term1-alpha\""),
    ({"order_index": "0"}, "ترتيب الفترة يجب أن يكون رقمًا صحيحًا 1 أو أكبر"),
    ({"order_index": "x"}, "ترتيب الفترة يجب أن يكون رقمًا صحيحًا 1 أو أكبر"),
    ({"name": "  "}, "اسم الفترة الدراسية مطلوب"),
    ({"start_date": "bad"}, "تاريخ البداية غير صحيح"),
    ({"end_date": "2027-01-01", "start_date": "2027-02-01"}, "تاريخ النهاية يجب أن يكون بعد تاريخ البداية"),
])
def test_a_bad_term_is_a_message_and_keeps_the_input(vapp, two_schools, login_as, over, message):
    A = two_schools["A"]
    c = _c(vapp, login_as, A)
    before = _count(vapp, "Term", year_id=A["year"].id)
    status, body = _post(c, A, f"/academic/years/{hid(A['year'].id)}/terms/new", _term_form(**over))
    assert status == 200 and message in body
    assert 'value="الفصل الدراسي الثاني"' in body or over.get("name")      # typed values stay
    assert _count(vapp, "Term", year_id=A["year"].id) == before


def test_a_good_term_saves_and_editing_skips_itself(vapp, two_schools, login_as):
    A = two_schools["A"]
    c = _c(vapp, login_as, A)
    status, body = _post(c, A, f"/academic/years/{hid(A['year'].id)}/terms/new", _term_form())
    assert status == 200 and "مجموع الأوزان = 100%" in body
    # edit the first term keeping its own order: allowed; raising its weight past 100: refused
    t1 = hid(A["term"].id)
    keep = {"name": "Term1-alpha", "order_index": "1", "start_date": "2026-09-01", "end_date": "2027-01-31",
            "weight": "50", "status_mode": "auto"}
    status, body = _post(c, A, f"/academic/terms/{t1}/edit", keep)
    assert "تم تعديل الفترة الدراسية" in body
    status, body = _post(c, A, f"/academic/terms/{t1}/edit", {**keep, "weight": "70", "name": "معدّل"})
    assert status == 200 and "الحالي بعد التعديل: 120%" in body and 'value="معدّل"' in body


def test_an_order_held_by_a_deleted_term_is_explained_not_a_500(vapp, two_schools, login_as):
    from app.extensions import db
    from app.models import Term
    A = two_schools["A"]
    with vapp.app_context():
        from datetime import date
        t = Term(school_id=A["school"].id, year_id=A["year"].id, name="محذوفة", order_index=5,
                 start_date=date(2027, 7, 1), end_date=date(2027, 7, 20), weight=0)
        db.session.add(t); db.session.flush()
        t.soft_delete(None); db.session.commit(); db.session.remove()
    c = _c(vapp, login_as, A)
    status, body = _post(c, A, f"/academic/years/{hid(A['year'].id)}/terms/new",
                         _term_form(order_index="5", weight="10"))
    assert status == 200 and "مستخدم بالفعل في فترة \"محذوفة\"" in body and "المحذوفات" in body


# ─── grades ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("data,message", [
    ({"name": "G1-alpha", "order_index": "7"}, "اسم الصف \"G1-alpha\" موجود بالفعل"),
    ({"name": "الصف الثاني", "order_index": "1"}, "ترتيب الصف (1) مستخدم بالفعل في صف \"G1-alpha\""),
    ({"name": "الصف الثاني", "order_index": "-3"}, "ترتيب الصف يجب أن يكون رقمًا صحيحًا 1 أو أكبر"),
    ({"name": "الصف الثاني", "order_index": "abc"}, "ترتيب الصف يجب أن يكون رقمًا صحيحًا 1 أو أكبر"),
    ({"name": "", "order_index": "7"}, "اسم الصف مطلوب"),
])
def test_a_bad_grade_is_a_message(vapp, two_schools, login_as, data, message):
    A = two_schools["A"]
    c = _c(vapp, login_as, A)
    before = _count(vapp, "Grade", school_id=A["school"].id)
    status, body = _post(c, A, "/academic/grades/new", data)
    assert status == 200 and message in body
    assert _count(vapp, "Grade", school_id=A["school"].id) == before


def test_grades_save_and_edit_keeps_its_own_name_and_order(vapp, two_schools, login_as):
    A = two_schools["A"]
    c = _c(vapp, login_as, A)
    _, body = _post(c, A, "/academic/grades/new", {"name": "الصف الثاني", "order_index": "2"})
    assert "تم إضافة الصف" in body
    _, body = _post(c, A, f"/academic/grades/{hid(A['grade'].id)}/edit",
                    {"name": "G1-alpha", "order_index": "1", "stage": ""})
    assert "تم تحديث الصف" in body
    _, body = _post(c, A, f"/academic/grades/{hid(A['grade'].id)}/edit", {"name": "الصف الثاني", "order_index": "1"})
    assert "اسم الصف \"الصف الثاني\" موجود بالفعل" in body
    # another school's names don't count
    B = two_schools["B"]
    _, body = _post(_c(vapp, login_as, B), B, "/academic/grades/new", {"name": "G1-alpha", "order_index": "2"})
    assert "تم إضافة الصف" in body


# ─── sections ───────────────────────────────────────────────────────

def test_sections_duplicate_missing_grade_and_capacity(vapp, two_schools, login_as):
    A = two_schools["A"]
    c = _c(vapp, login_as, A)
    gid = str(A["grade"].id)
    status, body = _post(c, A, "/academic/sections/new", {"grade_id": gid, "name": "Sec-alpha", "capacity": "30"})
    assert status == 200 and "يوجد فصل بنفس الاسم \"Sec-alpha\" في هذا الصف لهذه السنة الدراسية" in body
    status, body = _post(c, A, "/academic/sections/new", {"grade_id": "999999", "name": "ب", "capacity": "30"})
    assert status == 200 and "الصف المختار غير موجود، برجاء إعادة الاختيار" in body
    status, body = _post(c, A, "/academic/sections/new", {"grade_id": gid, "name": "ب", "capacity": "abc"})
    assert status == 200 and "سعة الفصل يجب أن يكون رقمًا صحيحًا 1 أو أكبر" in body and 'value="ب"' in body
    _, body = _post(c, A, "/academic/sections/new", {"grade_id": gid, "name": "ب", "capacity": "25"})
    assert "تم إضافة الفصل" in body
    # editing: its own name is fine; another section's name isn't
    sec = hid(A["section"].id)
    _, body = _post(c, A, f"/academic/sections/{sec}/edit", {"name": "Sec-alpha", "capacity": "30"})
    assert "تم تعديل الفصل" in body
    status, body = _post(c, A, f"/academic/sections/{sec}/edit", {"name": "ب", "capacity": "30"})
    assert status == 200 and "يوجد فصل بنفس الاسم \"ب\"" in body
    status, body = _post(c, A, f"/academic/sections/{sec}/edit", {"name": "Sec-alpha", "capacity": "0"})
    assert status == 200 and "سعة الفصل" in body


# ─── years ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("data,message", [
    ({"name": "TY-alpha", "start_date": "2027-09-01", "end_date": "2028-06-01", "status": "closed"},
     f"السنة الدراسية \"{ISO_L}TY-alpha{ISO_R}\" موجودة بالفعل"),
    ({"name": "2027-2028", "start_date": "2028-06-01", "end_date": "2027-09-01", "status": "closed"},
     "تاريخ النهاية يجب أن يكون بعد تاريخ البداية"),
    ({"name": "2027-2028", "start_date": "", "end_date": "2028-06-01", "status": "closed"}, "تاريخ البداية مطلوب"),
    ({"name": "2027-2028", "start_date": "1/9/2027", "end_date": "2028-06-01", "status": "closed"},
     "تاريخ البداية غير صحيح"),
    ({"name": "", "start_date": "2027-09-01", "end_date": "2028-06-01", "status": "closed"},
     "اسم السنة الدراسية مطلوب"),
])
def test_a_bad_year_is_a_message(vapp, two_schools, login_as, data, message):
    A = two_schools["A"]
    c = _c(vapp, login_as, A)
    before = _count(vapp, "AcademicYear", school_id=A["school"].id)
    status, body = _post(c, A, "/academic/years/new", data)
    assert status == 200 and message in body
    assert _count(vapp, "AcademicYear", school_id=A["school"].id) == before


def test_the_year_name_keeps_its_order_in_messages_and_the_form(vapp, two_schools, login_as):
    """BUG-001 — 2026-2027 must not read as 2027-2026 inside the Arabic sentence."""
    from app.extensions import db
    from app.models import AcademicYear
    A = two_schools["A"]
    with vapp.app_context():
        db.session.get(AcademicYear, A["year"].id).name = "2026-2027"
        db.session.commit(); db.session.remove()
    c = _c(vapp, login_as, A)
    status, body = _post(c, A, "/academic/years/new",
                         {"name": "2027-2028", "start_date": "2027-09-01", "end_date": "2028-06-01",
                          "status": "active"})
    assert status == 200 and f"يوجد سنة نشطة ({ISO_L}2026-2027{ISO_R})" in body
    assert 'value="2027-2028"' in body and 'value="2027-09-01"' in body
    # the rollover message, on a good save
    _, body = _post(c, A, "/academic/years/new",
                    {"name": "2027-2028", "start_date": "2027-09-01", "end_date": "2028-06-01",
                     "status": "closed", "rollover_from": str(A["year"].id)})
    assert f"فصل من {ISO_L}2026-2027{ISO_R}" in body


def test_a_good_year_edit_saves(vapp, two_schools, login_as):
    A = two_schools["A"]
    c = _c(vapp, login_as, A)
    _, body = _post(c, A, f"/academic/years/{hid(A['year'].id)}/edit",
                    {"name": "TY-alpha", "start_date": "2026-09-01", "end_date": "2027-06-20", "status": "active"})
    assert "تم حفظ التعديلات" in body
    B = two_schools["B"]
    _, body = _post(_c(vapp, login_as, B), B, "/academic/years/new",
                    {"name": "TY-alpha", "start_date": "2027-09-01", "end_date": "2028-06-01", "status": "closed"})
    assert "تم إنشاء السنة الدراسية" in body                           # another school's name doesn't count


def test_a_database_refusal_is_a_message_not_a_500(vapp, two_schools, login_as, monkeypatch):
    """The safety net: a unique violation the checks didn't see (a save at
    the same moment) is rolled back and explained."""
    from app.blueprints.academic import validation
    A = two_schools["A"]
    monkeypatch.setattr(validation, "clash", lambda *a, **k: None)      # the check "misses" it
    c = _c(vapp, login_as, A)
    status, body = _post(c, A, "/academic/grades/new", {"name": "G1-alpha", "order_index": "9"})
    assert status == 200 and "تعذّر حفظ الصف" in body
    assert "IntegrityError" not in body and "UNIQUE" not in body


def test_an_empty_capacity_on_edit_keeps_the_current_one(vapp, two_schools, login_as):
    """Review: as before the validation ticket — renaming a section with
    the capacity left empty keeps its capacity."""
    from app.extensions import db
    from app.models import Section
    A = two_schools["A"]
    c = _c(vapp, login_as, A)
    _, body = _post(c, A, f"/academic/sections/{hid(A['section'].id)}/edit", {"name": "Sec-renamed", "capacity": ""})
    assert "تم تعديل الفصل" in body
    with vapp.app_context():
        s = db.session.get(Section, A["section"].id)
        assert (s.name, s.capacity) == ("Sec-renamed", 30)
        db.session.remove()
