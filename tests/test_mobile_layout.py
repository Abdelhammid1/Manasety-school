"""Mobile layout guards (the phone pass over the whole site):
viewport + safe areas, the bottom navigation per role (only links the
user may open), the menu button wherever the sidebar is a drawer, the
platform CSS rules, and `None` never printed into a page."""

from __future__ import annotations

import re

import pytest

from isolation_harness import host


@pytest.fixture
def mapp(app, monkeypatch):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    return app


def _page(app, login_as, bundle, role, path="/dashboard"):
    c = app.test_client()
    login_as(c, bundle["users"][role], base_url=host(bundle))
    r = c.get(path, base_url=host(bundle), follow_redirects=True)
    assert r.status_code == 200, (role, path, r.status_code)
    return r.get_data(as_text=True)


def test_viewport_allows_zoom_and_uses_the_safe_areas(mapp, two_schools, login_as):
    body = _page(mapp, login_as, two_schools["A"], "admin")
    m = re.search(r'<meta name="viewport" content="([^"]+)"', body)
    assert m, "viewport meta missing"
    meta = m.group(1)
    assert "viewport-fit=cover" in meta and "width=device-width" in meta
    assert "user-scalable=no" not in meta and "maximum-scale" not in meta     # zoom stays allowed
    for rule in ("-webkit-tap-highlight-color:transparent", "@media (pointer:coarse){input,select,textarea{font-size:16px",
                 "hoverOnlyWhenSupported: true", "env(safe-area-inset-bottom", "100dvh"):
        assert rule in body, rule


@pytest.mark.parametrize("role,expected,absent", [
    ("admin", ["/students", "/attendance", "/finance"], []),
    ("teacher", ["/attendance", "/results", "/schedule"], ["/finance"]),
    ("student", ["/courses", "/lms/assignments", "/lms/quizzes"], ["/finance", "/attendance"]),
    ("parent", ["/portal/pickup", "/lms/announcements"], ["/finance/invoices"]),
])
def test_bottom_navigation_per_role(mapp, two_schools, login_as, role, expected, absent):
    body = _page(mapp, login_as, two_schools["A"], role)
    nav = re.search(r'<nav id="app-bottomnav".*?</nav>', body, re.S)
    assert nav, "bottom navigation missing"
    links = re.findall(r'href="([^"]+)"', nav.group(0))
    for prefix in expected:
        assert any(l.startswith(prefix) for l in links), (role, prefix, links)
    for prefix in absent:
        assert not any(l.startswith(prefix) for l in links), (role, prefix, links)
    assert "toggleSidebarMobile()" in nav.group(0)            # «المزيد» opens the full menu


def test_no_link_to_a_page_the_role_cannot_open(mapp, two_schools, login_as):
    """The parent's sidebar / dashboard and the teacher's sidebar used to
    link to pages answering 403 (finance invoices, subjects). The harness
    roles are broad, so take those permissions away as a real school has."""
    from app.extensions import db
    from app.models import Role
    A = two_schools["A"]
    with mapp.app_context():
        for key, module in (("parent", "finance"), ("teacher", "teachers")):
            role = db.session.get(Role, A["roles"][key].id)
            assert role is not None
            perms = dict(role.permissions or {})
            perms.pop(module, None)
            role.permissions = perms
        db.session.commit()
        db.session.remove()
    parent = _page(mapp, login_as, A, "parent")
    assert "/finance/invoices" not in parent
    teacher = _page(mapp, login_as, A, "teacher")
    assert 'href="/teachers/subjects"' not in teacher


def test_menu_button_shows_wherever_the_sidebar_is_a_drawer(mapp, two_schools, login_as):
    body = _page(mapp, login_as, two_schools["A"], "admin")
    # the sidebar hides at <=900px: the button must not be md:hidden (<768 only)
    m = re.search(r'<button[^>]*class="menu-toggle[^"]*"[^>]*>', body)
    assert m, "menu button missing"
    toggle = m.group(0)
    assert "md:hidden" not in toggle and 'aria-controls="app-sidebar"' in toggle
    assert ".menu-toggle{display:inline-flex!important}" in body
    assert 'id="sidebar-backdrop"' in body


def test_none_is_rendered_as_empty(mapp):
    with mapp.test_request_context():
        from flask import render_template_string
        assert render_template_string('<input value="{{ x }}">', x=None) == '<input value="">'
        assert render_template_string("{{ x|tojson }}", x=None) == "null"


def test_one_bottom_tab_is_current(mapp, two_schools, login_as):
    """«واجباتي» and «اختباراتي» share the lms blueprint: only the page's own
    tab is marked current."""
    body = _page(mapp, login_as, two_schools["A"], "student", "/lms/quizzes")
    m = re.search(r'<nav id="app-bottomnav".*?</nav>', body, re.S)
    assert m, "bottom navigation missing"
    current = re.findall(r'<a href="([^"]+)" aria-current="page"', m.group(0))
    assert len(current) == 1 and current[0].startswith("/lms/quizzes"), current


def test_search_lists_only_what_the_user_may_open(mapp, two_schools, login_as):
    """The search icon is on every phone's top bar: a role without the
    students / teachers / finance / payroll permission gets no such hits."""
    from app.extensions import db
    from app.models import Role, Student
    A = two_schools["A"]
    with mapp.app_context():
        role = db.session.get(Role, A["roles"]["parent"].id)
        assert role is not None
        perms = dict(role.permissions or {})
        for module in ("students", "teachers", "finance", "payroll"):
            perms.pop(module, None)
        role.permissions = perms
        stu = Student.query.filter_by(school_id=A["school"].id).first()
        assert stu is not None
        name = stu.full_name
        db.session.commit()
        db.session.remove()
    for role_key, sees in (("parent", False), ("admin", True)):
        c = mapp.test_client()
        login_as(c, A["users"][role_key], base_url=host(A))
        r = c.get("/search.json", query_string={"q": name[:4]}, base_url=host(A))
        assert r.status_code == 200
        assert ("الطلاب" in (r.get_json() or {}).get("groups", {})) is sees, role_key
