"""BUG-016 / BUG-017 — a staff role outside admin / teacher / parent / student
(accountant first) had an empty sidebar, and its dashboard offered buttons
that end in 403. Now both show exactly the pages the role can open: the
check is the routes' own (can_open reads require_permission). Route
protection is unchanged."""

from __future__ import annotations

import re
from html import unescape

import pytest

from app.services.school_templates.default import ROLES, role_permissions
from isolation_harness import host


@pytest.fixture
def napp(app, monkeypatch):
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    return app


def _user_with_default_role(app, A, name):
    """A user of the role exactly as a new school gets it."""
    from app.extensions import db
    from app.models import Role, User
    spec = next(r for r in ROLES if r[0] == name)
    with app.app_context():
        role = Role.query.filter_by(school_id=A["school"].id, name=name).first()
        if role is None:
            role = Role(school_id=A["school"].id, name=name, name_ar=spec[1], is_system=spec[2])
            db.session.add(role)
        role.permissions = role_permissions(spec[3])
        db.session.flush()
        u = User(school_id=A["school"].id, role_id=role.id, username=f"nav.{name}", full_name=name, is_active=True)
        u.set_password("Test-Only-Pass-123")
        db.session.add(u)
        db.session.commit()
        db.session.refresh(u)
        db.session.expunge(u)
        db.session.remove()
    return u


def _client(app, login_as, user, A):
    c = app.test_client()
    login_as(c, user, base_url=host(A))
    return c


def _nav_links(html):
    i = html.index('aria-label="التنقل الرئيسي"')
    return [unescape(h) for h in re.findall(r'href="(/[^"]*)"', html[i:html.index("</nav>", i)])]


def _main_links(html):
    i = html.index("<main")
    return {unescape(h) for h in re.findall(r'<a[^>]+href="(/[^"#]*)"', html[i:html.index("</main>", i)])}


FINANCE = ["/finance/invoices", "/finance/reports", "/finance/expenses", "/finance/dashboard"]


def test_the_accountant_sidebar_shows_the_finance_pages_only(napp, world, login_as):
    A = world["A"]
    c = _client(napp, login_as, _user_with_default_role(napp, A, "accountant"), A)
    body = c.get("/dashboard", base_url=host(A)).get_data(as_text=True)
    links = _nav_links(body)
    for page in FINANCE:
        assert any(x.startswith(page) for x in links), page
    for page in ("/hr/", "/admin/users", "/admin/settings", "/students", "/academic/", "/attendance"):
        assert not any(x.startswith(page) for x in links), page


@pytest.mark.parametrize("role", ["accountant", "student_affairs", "warehouse"])
def test_every_sidebar_link_of_a_staff_role_opens(napp, world, login_as, role):
    A = world["A"]
    c = _client(napp, login_as, _user_with_default_role(napp, A, role), A)
    links = _nav_links(c.get("/dashboard", base_url=host(A)).get_data(as_text=True))
    assert links                                        # never an empty menu
    bad = [(x, s) for x in links if (s := c.get(x, base_url=host(A)).status_code) >= 400]
    assert bad == []


@pytest.mark.parametrize("role", ["accountant", "student_affairs", "warehouse"])
def test_no_dashboard_link_of_a_staff_role_ends_in_403(napp, world, login_as, role):
    A = world["A"]
    c = _client(napp, login_as, _user_with_default_role(napp, A, role), A)
    links = _main_links(c.get("/dashboard", base_url=host(A)).get_data(as_text=True))
    bad = [(x, s) for x in sorted(links) if (s := c.get(x, base_url=host(A)).status_code) >= 400]
    assert bad == []


def test_the_accountant_quick_actions_are_his_own(napp, world, login_as):
    A = world["A"]
    c = _client(napp, login_as, _user_with_default_role(napp, A, "accountant"), A)
    body = c.get("/dashboard", base_url=host(A)).get_data(as_text=True)
    main = body[body.index("<main"):body.index("</main>")]
    for label in ("فاتورة جديدة", "مصروف جديد", "التقارير المالية"):
        assert label in main
    for label in ("طالب جديد", "مستخدم جديد", "رصد الحضور", "صرف رواتب", "الفصول التي لم تُرصَد بعد"):
        assert label not in main


@pytest.mark.parametrize("path", ["/students/new", "/admin/users/new", "/hr/payroll/new", "/attendance"])
def test_the_hidden_pages_stay_403_for_the_accountant(napp, world, login_as, path):
    A = world["A"]
    c = _client(napp, login_as, _user_with_default_role(napp, A, "accountant"), A)
    assert c.get(path, base_url=host(A)).status_code == 403


def test_the_mobile_bar_only_offers_what_opens(napp, world, login_as):
    A = world["A"]
    c = _client(napp, login_as, _user_with_default_role(napp, A, "accountant"), A)
    body = c.get("/dashboard", base_url=host(A)).get_data(as_text=True)
    i = body.index('id="app-bottomnav"')
    bar = body[i:body.index("</nav>", i)]
    links = re.findall(r'href="(/[^"]*)"', bar)
    assert "/dashboard" in links and any(x.startswith("/finance") for x in links)
    assert "المزيد" in bar                              # opens the same sidebar
    assert all(c.get(x, base_url=host(A)).status_code < 400 for x in links)


def test_the_admin_keeps_everything(napp, world, login_as):
    A = world["A"]
    c = _client(napp, login_as, A["users"]["admin"], A)
    body = c.get("/dashboard", base_url=host(A)).get_data(as_text=True)
    main = body[body.index("<main"):body.index("</main>")]
    for label in ("فاتورة جديدة", "مصروف جديد", "طالب جديد", "مستخدم جديد", "رصد الحضور",
                  "التقارير المالية", "صرف رواتب"):
        assert label in main
    links = _nav_links(body)
    for page in ("/hr/", "/admin/users", "/students", "/academic/", "/attendance", "/finance/invoices", "/lms/"):
        assert any(x.startswith(page) for x in links), page


@pytest.mark.parametrize("role,expected", [
    ("teacher", "لوحة المعلم"), ("parent", "صفحة ولي الأمر"), ("student", "صفحتي"),
])
def test_the_other_roles_keep_their_own_sidebar(napp, world, login_as, role, expected):
    A = world["A"]
    c = _client(napp, login_as, A["users"][role], A)
    body = c.get("/dashboard", base_url=host(A)).get_data(as_text=True)
    i = body.index('aria-label="التنقل الرئيسي"')
    nav = body[i:body.index("</nav>", i)]
    assert expected in nav and "لوحة التحكم" not in nav and "الموارد البشرية" not in nav


def test_can_open_reads_the_routes_own_declaration(napp):
    """Every require_permission route exposes what it needs — a stacked
    login_required keeps it, so the link and the route can't drift."""
    views = napp.view_functions
    assert ("finance", "edit") in views["finance.invoice_new"].required_permissions
    assert ("students", "add") in views["students.student_new"].required_permissions
    assert ("lms", "edit") in views["lms.assignment_questions"].required_permissions
