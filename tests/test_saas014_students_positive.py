"""SAAS-014 — the students / attendance / portal endpoints still work on
school A's own records (the cross-school attacks are in test_saas002)."""

from __future__ import annotations

import pytest

from isolation_harness import host


@pytest.fixture
def sapp(app, monkeypatch):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    return app


@pytest.mark.parametrize("path", [
    "/students/{student}/360", "/students/{student}/360.json", "/students/{student}/siblings.json",
    "/students/{student}/documents", "/students/{student}/health", "/students/{student}/behavior",
    "/students/{student}/id-card", "/students/guardians/{guardian}",
    "/attendance/reports/student/{student}", "/attendance/reports/section/{section}",
])
def test_own_pages_open(sapp, world, login_as, path):
    A = world["A"]
    c = sapp.test_client()
    login_as(c, A["users"]["admin"], base_url=host(A))
    url = path.format(student=A["student"].id, guardian=A["guardian"], section=A["section"].id)
    r = c.get(url, base_url=host(A))
    assert r.status_code == 200, f"{url}: {r.status_code}"
    assert not [m for m in world["B"]["markers"] if m in r.get_data(as_text=True)]


def test_own_writes_work(sapp, world, login_as):
    from app.extensions import db
    from app.models import StudentNote, User
    from app.models.student import student_tag_links as links
    A = world["A"]
    c = sapp.test_client()
    login_as(c, A["users"]["admin"], base_url=host(A))
    sid = A["student"].id
    with sapp.app_context():
        notes = StudentNote.query.filter_by(student_id=sid).count()
        db.session.remove()
    assert c.post(f"/students/{sid}/notes/add", base_url=host(A), data={"body": "ملاحظة A"}).status_code in (200, 302)
    assert c.post(f"/students/{sid}/tags/attach", base_url=host(A),
                  data={"tag_id": A["student_tag"]}).status_code in (200, 302)
    with sapp.app_context():
        assert StudentNote.query.filter_by(student_id=sid).count() == notes + 1
        assert db.session.execute(links.select().where(links.c.student_id == sid,
                                                       links.c.tag_id == A["student_tag"])).first()
        before = db.session.get(User, A["student_user"]).is_active
        db.session.remove()
    assert c.post(f"/students/{sid}/account/toggle", base_url=host(A)).status_code in (200, 302)
    with sapp.app_context():
        u = db.session.get(User, A["student_user"])
        assert u.is_active is (not before)
        u.is_active = before
        db.session.commit()
        db.session.remove()


def test_parent_picked_in_the_form_must_be_of_this_school(sapp, world, login_as):
    """Fixed in this ticket: student_edit / student_new took parent_user_id
    from the form unchecked (the tenant guard stopped the write, as a 500)."""
    A, B = world["A"], world["B"]
    c = sapp.test_client()
    login_as(c, A["users"]["admin"], base_url=host(A))
    r = c.post(f"/students/{A['student'].id}/edit", base_url=host(A),
               data={"full_name": "x", "parent_user_id": B["parent_user"]})
    assert r.status_code == 404
    r = c.post(f"/students/{A['student'].id}/edit", base_url=host(A),
               data={"full_name": A["student"].full_name, "parent_user_id": A["parent_user"]})
    assert r.status_code in (200, 302)
