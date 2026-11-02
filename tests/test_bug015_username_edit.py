"""BUG-015 — the username can be corrected from «تعديل مستخدم» (it was
readonly and the route ignored it): unique inside the school, never
altered, login follows the new name, the links to the user stay."""

from __future__ import annotations

import pytest

from isolation_harness import hid, host

PASSWORD = "Test-Only-Pass-123"


@pytest.fixture
def uapp(app, monkeypatch):
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    return app


@pytest.fixture
def sara(uapp, two_schools):
    """An accountant of school A (the ticket's acc.sara), one more user
    holding a name, and the same name in school B."""
    from app.extensions import db
    from app.models import Role, User
    A, B = two_schools["A"], two_schools["B"]
    with uapp.app_context():
        role = Role(school_id=A["school"].id, name="accountant", name_ar="محاسب", permissions={})
        role_b = Role(school_id=B["school"].id, name="accountant", name_ar="محاسب", permissions={})
        db.session.add_all([role, role_b])
        db.session.flush()
        u = User(school_id=A["school"].id, role_id=role.id, username="acc.sara", full_name="Sara", is_active=True)
        other = User(school_id=A["school"].id, role_id=role.id, username="acc.taken", full_name="Other", is_active=True)
        far = User(school_id=B["school"].id, role_id=role_b.id, username="acc.beta", full_name="Beta", is_active=True)
        for x in (u, other, far):
            x.set_password(PASSWORD)
        db.session.add_all([u, other, far])
        db.session.commit()
        out = {"A": A, "B": B, "id": u.id, "role": role.id, "far": far.id}
        db.session.remove()
    return out


def _admin(app, login_as, A, role="admin"):
    c = app.test_client()
    login_as(c, A["users"][role], base_url=host(A))
    return c


def _form(s, username, **over):
    return {"username": username, "full_name": "Sara", "role_id": str(s["role"]), "is_active": "1", **over}


def _name(app, uid):
    from app.extensions import db
    from app.models import User
    with app.app_context():
        out = db.session.get(User, uid).username
        db.session.remove()
    return out


def _login(app, A, username):
    r = app.test_client().post("/auth/login", base_url=host(A),
                               data={"username": username, "password": PASSWORD})
    return r.status_code == 302 and "/login" not in r.headers.get("Location", "")


def test_rename_saves_shows_and_login_follows(uapp, sara, login_as):
    A = sara["A"]
    c = _admin(uapp, login_as, A)
    url = f"/admin/users/{hid(sara['id'])}/edit"
    page = c.get(url, base_url=host(A)).get_data(as_text=True)
    i = page.index('name="username"')
    assert "readonly" not in page[i:page.index(">", i)]
    r = c.post(url, base_url=host(A), data=_form(sara, "  acc.sara2  "), follow_redirects=True)
    body = r.get_data(as_text=True)
    assert "تم تحديث المستخدم" in body and "acc.sara2" in body
    assert _name(uapp, sara["id"]) == "acc.sara2"
    assert "acc.sara2" in c.get(url, base_url=host(A)).get_data(as_text=True).split("</h1>")[0]
    assert _login(uapp, A, "acc.sara2") and not _login(uapp, A, "acc.sara")


@pytest.mark.parametrize("value,message", [
    ("", "الحقل مطلوب"), ("    ", "الحقل مطلوب"), ("acc.taken", "مستخدم لحساب آخر"),
    ("x" * 65, "طويل جدًا"), ("__manasety_x", "محجوز"),
])
def test_bad_names_are_refused_nothing_changes_and_the_input_is_kept(uapp, sara, login_as, value, message):
    from app.extensions import db
    from app.models import User
    A = sara["A"]
    r = _admin(uapp, login_as, A).post(f"/admin/users/{hid(sara['id'])}/edit", base_url=host(A),
                                       data=_form(sara, value, full_name="Changed Name"))
    body = r.get_data(as_text=True)
    assert r.status_code == 400 and message in body
    assert 'value="Changed Name"' in body                       # what was typed stays
    with uapp.app_context():
        u = db.session.get(User, sara["id"])
        assert (u.username, u.full_name) == ("acc.sara", "Sara")   # nothing saved
        db.session.remove()


def test_a_short_password_refuses_the_rename_too(uapp, sara, login_as):
    A = sara["A"]
    r = _admin(uapp, login_as, A).post(f"/admin/users/{hid(sara['id'])}/edit", base_url=host(A),
                                       data=_form(sara, "acc.new", password="short"))
    assert r.status_code == 400 and _name(uapp, sara["id"]) == "acc.sara"


def test_a_name_used_in_another_school_is_allowed(uapp, sara, login_as):
    """Uniqueness is inside the school, as at creation."""
    A = sara["A"]
    r = _admin(uapp, login_as, A).post(f"/admin/users/{hid(sara['id'])}/edit", base_url=host(A),
                                       data=_form(sara, "acc.beta"))
    assert r.status_code == 302 and _name(uapp, sara["id"]) == "acc.beta"


def test_saving_other_fields_keeps_the_name(uapp, sara, login_as):
    from app.extensions import db
    from app.models import User
    A = sara["A"]
    r = _admin(uapp, login_as, A).post(f"/admin/users/{hid(sara['id'])}/edit", base_url=host(A),
                                       data=_form(sara, "acc.sara", full_name="Sara Ali"))
    assert r.status_code == 302
    with uapp.app_context():
        u = db.session.get(User, sara["id"])
        assert (u.username, u.full_name) == ("acc.sara", "Sara Ali")
        db.session.remove()


def test_the_rename_is_in_the_activity_log(uapp, sara, login_as):
    from app.extensions import db
    from app.models import AuditLog
    A = sara["A"]
    _admin(uapp, login_as, A).post(f"/admin/users/{hid(sara['id'])}/edit", base_url=host(A),
                                   data=_form(sara, "acc.logged"))
    with uapp.app_context():
        row = (AuditLog.query.filter_by(entity_type="User", entity_id=sara["id"], action="update")
               .order_by(AuditLog.id.desc()).first())
        assert row.old_value["username"] == "acc.sara" and row.new_value["username"] == "acc.logged"
        db.session.remove()


@pytest.mark.parametrize("role", ["teacher", "student", "parent"])
def test_without_users_edit_it_is_403(uapp, sara, login_as, role):
    A = sara["A"]
    r = _admin(uapp, login_as, A, role).post(f"/admin/users/{hid(sara['id'])}/edit", base_url=host(A),
                                             data=_form(sara, "hacked"))
    assert r.status_code == 403 and _name(uapp, sara["id"]) == "acc.sara"


def test_another_schools_user_is_404(uapp, sara, login_as):
    A = sara["A"]
    r = _admin(uapp, login_as, A).post(f"/admin/users/{hid(sara['far'])}/edit", base_url=host(A),
                                       data=_form(sara, "hacked"))
    assert r.status_code == 404 and _name(uapp, sara["far"]) == "acc.beta"


def test_creating_a_user_still_works(uapp, sara, login_as):
    A = sara["A"]
    r = _admin(uapp, login_as, A).post("/admin/users/new", base_url=host(A), data={
        "username": "acc.fresh", "full_name": "Fresh", "role_id": str(sara["role"]),
        "password": PASSWORD, "is_active": "1"})
    assert r.status_code == 302 and _login(uapp, A, "acc.fresh")
