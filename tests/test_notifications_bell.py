"""The top bar's bell opens for every role and shows the user's own
notifications only — not the school's whole outbound log."""

from __future__ import annotations

import json
import re

import pytest

from isolation_harness import host

ROLES = ("admin", "teacher", "student", "parent")


@pytest.fixture
def napp(app, monkeypatch):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    return app


@pytest.fixture
def notices(napp, two_schools):
    """A notice about school A's student (→ A's parent and the student),
    and a backup notice for A (→ A's admins)."""
    from app.extensions import db
    from app.models import NotificationLog
    A = two_schools["A"]
    with napp.app_context():
        rows = [
            NotificationLog(school_id=A["school"].id, kind="absence", student_id=A["student"].id,
                            payload=json.dumps({"title": "غياب اليوم", "message": "تم تسجيل غياب"},
                                               ensure_ascii=False)),
            NotificationLog(school_id=A["school"].id, kind="school_backup",
                            payload=json.dumps({"title": "النسخة الاحتياطية", "message": "جاهزة"},
                                               ensure_ascii=False)),
        ]
        db.session.add_all(rows); db.session.commit()
        ids = [r.id for r in rows]
        db.session.remove()
    yield
    with napp.app_context():
        NotificationLog.query.filter(NotificationLog.id.in_(ids)).delete(synchronize_session=False)
        db.session.commit()
        db.session.remove()


def _client(app, login_as, bundle, role):
    c = app.test_client()
    login_as(c, bundle["users"][role], base_url=host(bundle))
    return c


def _titles(c, bundle):
    r = c.get("/notifications.json", base_url=host(bundle))
    assert r.status_code == 200
    d = r.get_json()
    return {i["title"] for i in d["items"]}, d["count"]


@pytest.mark.parametrize("role", ROLES)
def test_the_bell_opens_for_every_role(napp, two_schools, login_as, role):
    A = two_schools["A"]
    c = _client(napp, login_as, A, role)
    page = c.get("/dashboard", base_url=host(A), follow_redirects=True).get_data(as_text=True)
    btn = re.search(r'<button[^>]*data-notif-toggle[^>]*>', page)
    assert btn and 'aria-controls="notif-panel"' in btn.group(0), role
    assert 'id="notif-panel"' in page and "/notifications.json" in page
    assert c.get("/notifications", base_url=host(A)).status_code == 200


def test_each_role_sees_only_its_own(napp, two_schools, login_as, notices):
    A, B = two_schools["A"], two_schools["B"]
    seen = {role: _titles(_client(napp, login_as, A, role), A) for role in ROLES}
    assert seen["parent"] == ({"غياب اليوم"}, 1)
    assert seen["student"] == ({"غياب اليوم"}, 1)
    assert seen["admin"] == ({"النسخة الاحتياطية"}, 1)
    assert seen["teacher"] == (set(), 0)
    assert _titles(_client(napp, login_as, B, "parent"), B) == (set(), 0)     # school B: nothing of A's
    assert _titles(_client(napp, login_as, B, "admin"), B) == (set(), 0)


def test_the_badge_counts_the_users_own_and_the_page_marks_read(napp, two_schools, login_as, notices):
    A = two_schools["A"]
    c = _client(napp, login_as, A, "parent")

    def badge():
        page = c.get("/dashboard", base_url=host(A), follow_redirects=True).get_data(as_text=True)
        m = re.search(r'data-notif-toggle.*?</button>', page, re.S)
        assert m
        n = re.search(r'bg-error text-on-error[^>]*>(\d+)<', m.group(0))
        return int(n.group(1)) if n else 0
    assert badge() == 1
    page = c.get("/notifications", base_url=host(A)).get_data(as_text=True)
    assert "غياب اليوم" in page and "تم تسجيل غياب" in page
    assert badge() == 0
    teacher = _client(napp, login_as, A, "teacher")
    page = teacher.get("/dashboard", base_url=host(A), follow_redirects=True).get_data(as_text=True)
    m = re.search(r'data-notif-toggle.*?</button>', page, re.S)
    assert m and "bg-error text-on-error" not in m.group(0)      # no school-wide count


def test_anonymous_cannot_read(napp, two_schools):
    r = napp.test_client().get("/notifications.json", base_url=host(two_schools["A"]))
    assert r.status_code in (302, 401)
