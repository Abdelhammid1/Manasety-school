"""Tickets «أزرار الإجراءات في قائمة الطلاب» and «تعديل حصة في الجدول»."""

from __future__ import annotations

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


# ── students list ──

def test_the_list_shows_edit_to_who_may_edit_only(sapp, world, login_as):
    A = world["A"]
    sid = A["student"].id
    edit = f"/students/{hid(sid)}/edit"
    admin = _client(sapp, login_as, A, "admin").get("/students", base_url=host(A)).get_data(as_text=True)
    assert edit in admin and "تعديل بيانات الطالب" in admin
    assert f"/students/{hid(sid)}\"" in admin                    # the arrow stays
    t = _client(sapp, login_as, A, "teacher")                     # students.view, no edit
    body = t.get("/students", base_url=host(A)).get_data(as_text=True)
    assert edit not in body
    assert t.get(edit, base_url=host(A)).status_code == 403


# ── timetable slot edit ──

def _slot(sapp, A):
    from app.extensions import db
    from app.models import ScheduleSlot
    with sapp.app_context():
        s = db.session.get(ScheduleSlot, A["slot"])
        out = (s.id, s.subject_id, s.teacher_id, s.room_id)
        db.session.remove()
    return out


def _no_room(sapp, A):
    from app.extensions import db
    from app.models import ScheduleSlot
    with sapp.app_context():
        db.session.get(ScheduleSlot, A["slot"]).room_id = None
        db.session.commit(); db.session.remove()


def test_the_card_has_an_edit_form_prefilled_and_says_no_room(sapp, world, login_as):
    A = world["A"]
    _no_room(sapp, A)
    page = _client(sapp, login_as, A, "admin").get(f"/schedule/section/{hid(A['section'].id)}",
                                                    base_url=host(A)).get_data(as_text=True)
    assert "حفظ التعديل" in page and "القاعة: غير محددة" in page
    i = page.index("حفظ التعديل")
    form = page[page.rindex("<form", 0, i):i]
    assert f'value="{A["teacher_assignment"]}" selected' in form


def test_editing_fills_the_room_in_place_and_keeps_attendance_linked(sapp, world, login_as):
    from datetime import date
    from app.extensions import db
    from app.models import Attendance, ScheduleSlot
    A = world["A"]
    _no_room(sapp, A)
    with sapp.app_context():
        att = Attendance(school_id=A["school"].id, enrollment_id=A["enrollment"].id, date=date(2026, 10, 27),
                         status="present", schedule_slot_id=A["slot"])
        db.session.add(att); db.session.commit()
        aid = att.id
        n = ScheduleSlot.query.count()
        db.session.remove()
    r = _client(sapp, login_as, A, "admin").post(
        f"/schedule/section/{hid(A['section'].id)}/slot", base_url=host(A),
        data={"day_id": A["day"], "period_id": A["period"], "assignment_id": A["teacher_assignment"],
              "room_id": A["room"]})
    assert r.status_code == 302
    sid, _subj, _t, room = _slot(sapp, A)
    assert sid == A["slot"] and room == A["room"]                  # same row, room filled
    with sapp.app_context():
        assert ScheduleSlot.query.count() == n                      # nothing added
        assert db.session.get(Attendance, aid).schedule_slot_id == A["slot"]
        db.session.remove()


def test_editing_into_a_busy_teacher_is_refused(sapp, world, login_as):
    from app.extensions import db
    from app.models import ScheduleSlot, Section
    A = world["A"]
    with sapp.app_context():              # the same teacher, same day+period, in another section
        other = Section(school_id=A["school"].id, year_id=A["year"].id, grade_id=A["grade"].id, name="ب2")
        db.session.add(other); db.session.flush()
        db.session.add(ScheduleSlot(school_id=A["school"].id, year_id=A["year"].id, section_id=other.id,
                                    day_id=A["day"], period_id=A["period"], subject_id=A["subject"].id,
                                    teacher_id=A["teacher"]))
        db.session.commit(); db.session.remove()
    before = _slot(sapp, A)
    r = _client(sapp, login_as, A, "admin").post(
        f"/schedule/section/{hid(A['section'].id)}/slot", base_url=host(A), follow_redirects=True,
        data={"day_id": A["day"], "period_id": A["period"], "assignment_id": A["teacher_assignment"]})
    assert r.status_code == 200 and "تعارض" in r.get_data(as_text=True)
    assert _slot(sapp, A) == before


@pytest.mark.parametrize("role", ["student", "parent"])
def test_without_schedule_edit_no_button_and_403(sapp, world, login_as, role):
    A = world["A"]
    c = _client(sapp, login_as, A, role)
    page = c.get(f"/schedule/section/{hid(A['section'].id)}", base_url=host(A))
    assert "حفظ التعديل" not in page.get_data(as_text=True)
    before = _slot(sapp, A)
    r = c.post(f"/schedule/section/{hid(A['section'].id)}/slot", base_url=host(A),
               data={"day_id": A["day"], "period_id": A["period"], "assignment_id": A["teacher_assignment"]})
    assert r.status_code == 403 and _slot(sapp, A) == before


def test_another_schools_section_is_refused(sapp, world, login_as):
    A, B = world["A"], world["B"]
    r = _client(sapp, login_as, A, "admin").post(
        f"/schedule/section/{hid(B['section'].id)}/slot", base_url=host(A),
        data={"day_id": A["day"], "period_id": A["period"], "assignment_id": A["teacher_assignment"]})
    assert r.status_code == 404
