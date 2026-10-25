"""The activity log reads as Arabic sentences: no JSON, no ids, no
true/false, no \\uXXXX, no secret — and only what really changed."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pytest

from isolation_harness import host


@pytest.fixture
def dapp(app, monkeypatch):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    return app


def _page(app, login_as, bundle, role="admin", qs=""):
    c = app.test_client()
    login_as(c, bundle["users"][role], base_url=host(bundle))
    r = c.get("/admin/audit" + qs, base_url=host(bundle))
    return r.status_code, r.get_data(as_text=True)


def _edit_user(app, uid, **changes):
    from app.extensions import db
    from app.models import User
    with app.app_context():
        u = db.session.get(User, uid)
        assert u is not None
        for k, v in changes.items():
            if k == "password":
                u.set_password(v)
            else:
                setattr(u, k, v)
        db.session.commit()
        db.session.remove()


def _raw_row(app, **kw):
    from app.extensions import db
    from app.models import AuditLog
    with app.app_context():
        row = AuditLog(created_at=datetime.now(timezone.utc), **kw)
        db.session.add(row); db.session.commit()
        rid = row.id
        db.session.remove()
    return rid


def _rows(body):
    """The log rows only (the page around them has its own CSS / JS)."""
    start = body.index('<section class="flex flex-col gap-space-sm">')
    return body[start:body.index("</section>", start)]


def _no_raw(body):
    rows = _rows(body)
    for bad in ('"phone"', "role_id", "school_id", "\\u06", "[REDACTED]", "true", "false",
                "True", "False", "None", "created_at", "failed_attempts", "{\"", "$2b$"):
        assert bad not in rows, bad


def test_a_phone_change_is_one_line(dapp, two_schools, login_as):
    A = two_schools["A"]
    _edit_user(dapp, A["users"]["teacher"].id, phone="01001234567")
    status, body = _page(dapp, login_as, A)
    assert status == 200
    assert "عدّل بيانات مستخدم: Teacher-alpha" in body
    assert "رقم الهاتف" in body and "01001234567" in body
    _no_raw(body)


def test_a_role_change_shows_the_role_name(dapp, two_schools, login_as):
    from app.extensions import db
    from app.models import Role
    A = two_schools["A"]
    with dapp.app_context():
        role = db.session.get(Role, A["roles"]["admin"].id)
        assert role is not None
        role_name = role.name_ar or role.name
        db.session.remove()
    _edit_user(dapp, A["users"]["teacher"].id, role_id=A["roles"]["admin"].id)
    _, body = _page(dapp, login_as, A)
    assert "الدور الوظيفي" in body and role_name in body
    _no_raw(body)


def test_a_password_change_says_so_without_any_hash(dapp, two_schools, login_as):
    A = two_schools["A"]
    _edit_user(dapp, A["users"]["parent"].id, password="new-password-9876")
    _, body = _page(dapp, login_as, A)
    assert "تم تغيير كلمة المرور" in body
    _no_raw(body)


def test_a_login_reads_as_a_sentence_and_old_login_updates_are_hidden(dapp, two_schools, login_as):
    A = two_schools["A"]
    r = dapp.test_client().post("/auth/login", base_url=host(A),
                                data={"username": A["users"]["student"].username,
                                      "password": "test-password-12345"})
    assert r.status_code in (302, 400)        # 400 = CSRF on; the event is still the point below
    from app.services import audit
    from app.extensions import db
    from app.models import User
    with dapp.test_request_context():
        u = db.session.get(User, A["users"]["student"].id)
        audit.record_login_event(u, audit.LOGIN_OK, "web")
        db.session.commit()
        db.session.remove()
    # an old-style row: the full snapshot of a login-only update
    _raw_row(dapp, school_id=A["school"].id, action="update", entity_type="User",
             entity_id=A["users"]["student"].id, old_value={"last_login_at": None},
             new_value={"full_name": "Student-alpha", "email": "x@y.test", "last_login_at": "2026-10-24T07:14:00"})
    _, body = _page(dapp, login_as, A)
    assert "Student-alpha سجّل دخول" in body
    assert "عدّل بيانات مستخدم: Student-alpha" not in body
    rows = _rows(body)
    assert "تسجيل دخول" in rows                                # the badge, in Arabic
    assert "#" + str(A["users"]["student"].id) not in rows
    # "login" may appear only as the badge's icon name, never as text
    assert rows.count(">login<") == rows.count('text-lg">login<')


def test_a_deleted_reference_and_an_unknown_field_do_not_break_the_page(dapp, two_schools, login_as, caplog):
    A = two_schools["A"]
    _raw_row(dapp, school_id=A["school"].id, action="update", entity_type="User",
             entity_id=A["users"]["teacher"].id,
             old_value={"role_id": 999999, "favourite_colour": "أزرق"},
             new_value={"full_name": "Teacher-alpha", "role_id": 999998, "favourite_colour": "أحمر"})
    with caplog.at_level(logging.WARNING):
        status, body = _page(dapp, login_as, A)
    assert status == 200
    assert "غير متاح (محذوف)" in body
    assert "favourite_colour" in body and "أحمر" in body            # raw name, page alive
    assert any("favourite_colour" in m for m in caplog.messages)


def test_school_b_sees_none_of_school_a_and_names_stay_in_school(dapp, two_schools, login_as):
    A, B = two_schools["A"], two_schools["B"]
    _edit_user(dapp, A["users"]["teacher"].id, phone="01009998887")
    # a row of A naming B's role id: never resolved to B's role name
    _raw_row(dapp, school_id=A["school"].id, action="update", entity_type="User",
             entity_id=A["users"]["teacher"].id, old_value={"role_id": A["roles"]["admin"].id},
             new_value={"full_name": "Teacher-alpha", "role_id": B["roles"]["admin"].id})
    _, body_b = _page(dapp, login_as, B)
    assert "01009998887" not in body_b and "Teacher-alpha" not in body_b
    _, body_a = _page(dapp, login_as, A)
    assert "غير متاح (محذوف)" in body_a


def test_many_rows_cost_a_bounded_number_of_queries(dapp, two_schools, login_as):
    import sqlalchemy as sa
    from app.extensions import db
    A = two_schools["A"]
    for i in range(30):
        _edit_user(dapp, A["users"]["teacher"].id, phone=f"0100000{i:04d}")
    c = dapp.test_client()
    login_as(c, A["users"]["admin"], base_url=host(A))
    with dapp.app_context():
        engine = db.engine
    count = {"n": 0}

    def tick(*_a, **_k):
        count["n"] += 1
    sa.event.listen(engine, "before_cursor_execute", tick)
    try:
        r = c.get("/admin/audit", base_url=host(A))
    finally:
        sa.event.remove(engine, "before_cursor_execute", tick)
    assert r.status_code == 200 and r.get_data(as_text=True).count("رقم الهاتف") >= 30
    assert count["n"] < 40, count["n"]


def test_without_the_permission_it_is_still_refused(dapp, two_schools, login_as):
    from app.extensions import db
    from app.models import Role
    A = two_schools["A"]
    with dapp.app_context():
        role = db.session.get(Role, A["roles"]["teacher"].id)
        assert role is not None
        perms = dict(role.permissions or {})
        perms.pop("users", None)
        role.permissions = perms
        db.session.commit()
        db.session.remove()
    status, _ = _page(dapp, login_as, A, role="teacher")
    assert status == 403


def test_dates_read_in_arabic_in_cairo_time():
    from zoneinfo import ZoneInfo
    from app.services.audit_display import format_datetime, format_value
    utc = datetime(2026, 10, 24, 7, 14, tzinfo=timezone.utc)
    assert format_datetime(utc, ZoneInfo("Africa/Cairo")) == "24 أكتوبر 2026 – 10:14 ص"
    assert format_value("dob", "2015-03-02") == "2 مارس 2015"
    assert format_value("is_active", False) == "معطّل"
    assert format_value("is_refund", True) == "نعم"
    assert format_value("phone", None) == "—"
    assert format_value("status", "absent") == "غائب"


# ─── the school's settings, and where a login came from ─────────────

def test_a_login_says_website_or_app_and_the_device(dapp, two_schools, login_as):
    A = two_schools["A"]
    from app.services import audit
    from app.extensions import db
    from app.models import User
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/129.0 Safari/537.36")
    with dapp.test_request_context(headers={"User-Agent": ua}):
        u = db.session.get(User, A["users"]["teacher"].id)
        audit.record_login_event(u, audit.LOGIN_OK, "web")
        audit.record_login_event(u, audit.LOGIN_FAILED, "api", reason="password")
        db.session.commit()
        db.session.remove()
    rows = _rows(_page(dapp, login_as, A)[1])
    assert "الدخول من" in rows and "الموقع" in rows and "تطبيق الموبايل" in rows
    assert "Chrome على Windows" in rows
    assert "كلمة مرور غير صحيحة" in rows
    assert "من خلال" not in rows


def test_school_settings_changes_are_in_the_log(dapp, two_schools, login_as, tmp_path, monkeypatch):
    import io
    from PIL import Image
    monkeypatch.setitem(dapp.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setitem(dapp.config, "UPLOAD_ROOT", str(tmp_path / "uploads"))
    A, B = two_schools["A"], two_schools["B"]
    c = dapp.test_client()
    login_as(c, A["users"]["admin"], base_url=host(A))
    buf = io.BytesIO()
    Image.new("RGB", (40, 20), (10, 20, 30)).save(buf, "PNG")
    r = c.post("/admin/settings", base_url=host(A), content_type="multipart/form-data",
               data={"name": A["school"].name, "primary_color": "#123456", "phone": "0100000",
                     "smtp_password": "", "logo_file": (io.BytesIO(buf.getvalue()), "logo.png")},
               follow_redirects=True)
    assert r.status_code == 200
    rows = _rows(c.get("/admin/audit", base_url=host(A)).get_data(as_text=True))
    assert f"عدّل بيانات المدرسة: {A['school'].name}" in rows
    assert "اللون الأساسي" in rows and "#123456" in rows
    assert "تم رفع لوجو جديد" in rows and "/files/" not in rows
    assert "auth_epoch" not in rows
    # B's log has none of it
    assert "#123456" not in _rows(_page(dapp, login_as, B)[1])
    # saving again with nothing changed adds no row
    from app.extensions import db
    from app.models import AuditLog
    with dapp.app_context():
        n = AuditLog.query.filter_by(entity_type="School", school_id=A["school"].id).count()
        db.session.remove()
    c.post("/admin/settings", base_url=host(A), data={"name": A["school"].name, "primary_color": "#123456",
                                                     "phone": "0100000"})
    with dapp.app_context():
        assert AuditLog.query.filter_by(entity_type="School", school_id=A["school"].id).count() == n
        db.session.remove()


def test_a_console_change_is_attributed_to_the_manasety_team(dapp, two_schools, login_as):
    A = two_schools["A"]
    from app.services.audit import BY_PLATFORM
    _raw_row(dapp, school_id=A["school"].id, action="update", entity_type="School", entity_id=A["school"].id,
             old_value={"primary_color": None},
             new_value={"name": A["school"].name, "primary_color": "#0F766E", BY_PLATFORM: True})
    rows = _rows(_page(dapp, login_as, A)[1])
    assert "فريق منصتي عدّل بيانات المدرسة" in rows
    assert BY_PLATFORM not in rows
