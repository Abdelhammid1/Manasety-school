"""Ticket «بعذر بدون سبب» — «مستأذن بعذر» needs a reason (recommended
option): checked on the server for the whole class before anything is
saved, the reason shows when the day is reopened, and a record moved to
another status drops it."""

from __future__ import annotations

from datetime import date

import pytest

from isolation_harness import hid, host

DAY = "2026-10-27"          # a Tuesday


@pytest.fixture
def sapp(app, monkeypatch):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    return app


@pytest.fixture
def klass(sapp, two_schools):
    """School A's section with a second student (Salma)."""
    from app.extensions import db
    from app.models import Enrollment, Student
    A = two_schools["A"]
    with sapp.app_context():
        salma = Student(school_id=A["school"].id, permanent_code="PC-salma", full_name="سلمى العتيبي")
        db.session.add(salma); db.session.flush()
        e2 = Enrollment(student_id=salma.id, school_id=A["school"].id, year_id=A["year"].id,
                        grade_id=A["grade"].id, section_id=A["section"].id, status="active",
                        enrolled_at=date(2026, 9, 1))
        db.session.add(e2); db.session.commit()
        out = {"A": A, "e1": A["enrollment"].id, "e2": e2.id, "url": f"/attendance/section/{hid(A['section'].id)}/mark"}
        db.session.remove()
    return out


def _records(sapp):
    from app.extensions import db
    from app.models import Attendance
    with sapp.app_context():
        out = {a.enrollment_id: (a.status, a.excuse_reason) for a in Attendance.query.all()}
        db.session.remove()
    return out


def _admin(sapp, login_as, A):
    c = sapp.test_client()
    login_as(c, A["users"]["admin"], base_url=host(A))
    return c


@pytest.mark.parametrize("reason", ["", "    "])
def test_excused_without_a_reason_refuses_the_whole_save_and_names_the_student(sapp, klass, login_as, reason):
    A = klass["A"]
    c = _admin(sapp, login_as, A)
    r = c.post(klass["url"], base_url=host(A), data={
        "date": DAY, f"status_{klass['e1']}": "absent",
        f"status_{klass['e2']}": "excused", f"excuse_reason_{klass['e2']}": reason,
        f"note_{klass['e1']}": "kept-note"})
    body = r.get_data(as_text=True)
    assert r.status_code == 400 and "اكتب سبب العذر لـ: سلمى العتيبي" in body
    assert _records(sapp) == {}                                 # nothing saved, not even the absent one
    assert 'value="kept-note"' in body                          # the teacher's input is still there


def test_excused_with_a_reason_saves_and_shows_when_reopened(sapp, klass, login_as):
    A = klass["A"]
    c = _admin(sapp, login_as, A)
    r = c.post(klass["url"], base_url=host(A), data={
        "date": DAY, f"status_{klass['e1']}": "present",
        f"status_{klass['e2']}": "excused", f"excuse_reason_{klass['e2']}": "  مراجعة طبية  "})
    assert r.status_code == 302
    assert _records(sapp) == {klass["e1"]: ("present", None), klass["e2"]: ("excused", "مراجعة طبية")}
    page = c.get(f"{klass['url']}?date={DAY}", base_url=host(A)).get_data(as_text=True)
    assert 'value="مراجعة طبية"' in page


def test_other_statuses_need_no_reason_and_drop_an_old_one(sapp, klass, login_as):
    A = klass["A"]
    c = _admin(sapp, login_as, A)
    c.post(klass["url"], base_url=host(A), data={
        "date": DAY, f"status_{klass['e2']}": "excused", f"excuse_reason_{klass['e2']}": "سفر"})
    for status in ("present", "absent", "late"):
        r = c.post(klass["url"], base_url=host(A), data={
            "date": DAY, f"status_{klass['e2']}": status, f"excuse_reason_{klass['e2']}": "سفر"})
        assert r.status_code == 302
        assert _records(sapp)[klass["e2"]] == (status, None)


def test_a_too_long_reason_is_refused(sapp, klass, login_as):
    A = klass["A"]
    r = _admin(sapp, login_as, A).post(klass["url"], base_url=host(A), data={
        "date": DAY, f"status_{klass['e2']}": "excused", f"excuse_reason_{klass['e2']}": "x" * 256})
    assert r.status_code == 400 and "أطول من 255" in r.get_data(as_text=True)
    assert _records(sapp) == {}


def test_a_script_in_the_reason_is_shown_as_text(sapp, klass, login_as):
    A = klass["A"]
    c = _admin(sapp, login_as, A)
    c.post(klass["url"], base_url=host(A), data={
        "date": DAY, f"status_{klass['e2']}": "excused",
        f"excuse_reason_{klass['e2']}": "<script>alert(1)</script>"})
    page = c.get(f"{klass['url']}?date={DAY}", base_url=host(A)).get_data(as_text=True)
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page


def test_an_old_excused_record_without_a_reason_still_opens(sapp, klass, login_as):
    from app.extensions import db
    from app.models import Attendance
    A = klass["A"]
    with sapp.app_context():
        db.session.add(Attendance(school_id=A["school"].id, enrollment_id=klass["e2"],
                                  date=date(2026, 10, 27), status="excused"))
        db.session.commit()
        db.session.remove()
    c = _admin(sapp, login_as, A)
    assert c.get(f"{klass['url']}?date={DAY}", base_url=host(A)).status_code == 200
    r = c.post(klass["url"], base_url=host(A), data={
        "date": DAY, f"status_{klass['e2']}": "excused", f"excuse_reason_{klass['e2']}": "أضيف لاحقاً"})
    assert r.status_code == 302 and _records(sapp)[klass["e2"]] == ("excused", "أضيف لاحقاً")


@pytest.mark.parametrize("role", ["student", "parent"])
def test_without_attendance_rights_it_is_403(sapp, klass, login_as, role):
    A = klass["A"]
    c = sapp.test_client()
    login_as(c, A["users"][role], base_url=host(A))
    r = c.post(klass["url"], base_url=host(A), data={
        "date": DAY, f"status_{klass['e2']}": "excused", f"excuse_reason_{klass['e2']}": "x"})
    assert r.status_code == 403 and _records(sapp) == {}
