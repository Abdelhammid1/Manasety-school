"""Ticket C: what is turned off for a school leaves no trace on its core
pages — no number, no link, no card, no search group, no permission row
lost. Two schools: A closes things, B never does."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

import pytest
from werkzeug.exceptions import MethodNotAllowed, NotFound

from feature_links import unguarded_links
from isolation_harness import hid, host

ROLES = ("admin", "teacher", "student", "parent")


@pytest.fixture
def lapp(app, monkeypatch):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    return app


@pytest.fixture(autouse=True)
def _clean(app):
    yield
    from app.extensions import db
    from app.models import SchoolFeatureOverride, SchoolModuleOverride
    with app.app_context():
        SchoolFeatureOverride.query.delete()
        SchoolModuleOverride.query.delete()
        db.session.commit()
        db.session.remove()


def _features(app, sid, changes):
    from app.extensions import db
    from app.models import School
    from app.services.modules import set_feature_overrides
    with app.app_context():
        set_feature_overrides(db.session.get(School, sid), changes, "test", None)
        db.session.commit()
        db.session.remove()


def _module(app, sid, key, enabled):
    from app.extensions import db
    from app.models import School
    from app.services.modules import set_override
    with app.app_context():
        set_override(db.session.get(School, sid), key, enabled, "test", None)
        db.session.commit()
        db.session.remove()


def _all_off(app, sid):
    from app.services.modules import FEATURES
    _features(app, sid, {f.key: False for f in FEATURES if not f.essential})


def _client(app, login_as, bundle, role="admin"):
    c = app.test_client()
    login_as(c, bundle["users"][role], base_url=host(bundle))
    return c


# ─── the static check ───────────────────────────────────────────────

def test_no_unguarded_link_into_a_page_that_can_be_off():
    left = unguarded_links()
    assert not left, "wrap these in {% if endpoint_on('…') %}: " + \
        "; ".join(f"{t}:{n} → {e}" for t, n, e in left)


# ─── the crawler ────────────────────────────────────────────────────

HREF_RE = re.compile(r'href="([^"#]+)')


def _pages(bundle):
    sid = hid(bundle["student"].id)
    return ["/dashboard", "/students", f"/students/{sid}", f"/students/{sid}/360",
            f"/academic/sections/{hid(bundle['section'].id) if 'section' in bundle else ''}",
            "/admin/settings", "/students/promotion", "/admin/roles", "/search?q=a"]


def _dead_links(app, client, bundle):
    """Every internal href on the main pages → the feature it opens must be on."""
    from app.services.modules import feature_enabled, feature_for_endpoint
    adapter = app.url_map.bind(urlsplit(host(bundle)).netloc)
    dead = []
    for page in _pages(bundle):
        r = client.get(page, base_url=host(bundle))
        if r.status_code != 200:
            continue
        for href in set(HREF_RE.findall(r.get_data(as_text=True))):
            parts = urlsplit(href)
            if parts.scheme and parts.netloc not in ("", urlsplit(host(bundle)).netloc):
                continue
            path = parts.path or "/"
            if not path.startswith("/") or path.startswith("/static/"):
                continue
            try:
                endpoint, _ = adapter.match(path, method="GET")
            except (NotFound, MethodNotAllowed):
                continue
            with app.app_context():
                if not feature_enabled(bundle["school"].id, feature_for_endpoint(endpoint)):
                    dead.append((page, href, endpoint))
    return dead


@pytest.mark.parametrize("role", ROLES)
def test_with_every_feature_off_no_visible_link_leads_to_a_closed_page(lapp, two_schools, login_as, role):
    A = two_schools["A"]
    _all_off(lapp, A["school"].id)
    c = _client(lapp, login_as, A, role)
    assert c.get("/dashboard", base_url=host(A)).status_code == 200
    dead = _dead_links(lapp, c, A)
    assert dead == [], " | ".join(map(str, dead))


@pytest.mark.parametrize("module", ["attendance", "schedule", "results", "lms", "nafis", "finance", "hr", "portal"])
def test_one_module_off_at_a_time(lapp, two_schools, login_as, module):
    A = two_schools["A"]
    _module(lapp, A["school"].id, module, False)
    for role in ROLES:
        c = _client(lapp, login_as, A, role)
        dead = _dead_links(lapp, c, A)
        assert dead == [], role + ": " + " | ".join(map(str, dead))


# ─── the dashboard ──────────────────────────────────────────────────

def test_finance_off_no_financial_card_and_no_financial_query(lapp, two_schools, login_as, monkeypatch):
    from app.blueprints.dashboard import routes as dash
    A, B = two_schools["A"], two_schools["B"]
    _module(lapp, A["school"].id, "finance", False)
    called = []
    for name in ("_outstanding_ar", "_overdue_invoices_count", "_payments_sum", "_expenses_sum",
                 "_cash_on_hand", "_installments_due_next_7d"):
        real = getattr(dash, name)
        monkeypatch.setattr(dash, name, lambda *a, _n=name, _r=real, **k: called.append((_n, a[0])) or _r(*a, **k))
    body = _client(lapp, login_as, A).get("/dashboard", base_url=host(A)).get_data(as_text=True)
    assert [c for c in called if c[1] == A["school"].id] == []
    for text in ("أقساط خلال ٧ أيام", "فواتير متأخّرة", "الرصيد النقدي", "مصروفات هذا الشهر", "فاتورة جديدة"):
        assert text not in body, text
    body_b = _client(lapp, login_as, B).get("/dashboard", base_url=host(B)).get_data(as_text=True)
    assert "فواتير متأخّرة" in body_b and "الرصيد النقدي" in body_b


@pytest.mark.parametrize("module,text", [("attendance", "الحضور اليوم"), ("lms", "التعلم (LMS)")])
def test_attendance_and_lms_cards_go_with_their_module(lapp, two_schools, login_as, module, text):
    A = two_schools["A"]
    assert text in _client(lapp, login_as, A).get("/dashboard", base_url=host(A)).get_data(as_text=True)
    _module(lapp, A["school"].id, module, False)
    assert text not in _client(lapp, login_as, A).get("/dashboard", base_url=host(A)).get_data(as_text=True)


# ─── Student 360 ────────────────────────────────────────────────────

def test_student_360_drops_the_sections_that_are_off(lapp, two_schools, login_as):
    A = two_schools["A"]
    c = _client(lapp, login_as, A)
    url = f"/students/{hid(A['student'].id)}/360"
    full = c.get(url + ".json", base_url=host(A)).get_json()
    assert {"academic", "attendance", "financial", "behavior", "health", "documents"} <= set(full)
    _module(lapp, A["school"].id, "finance", False)
    _features(lapp, A["school"].id, {"students.health": False})
    data = c.get(url + ".json", base_url=host(A)).get_json()
    assert "financial" not in data and "health" not in data
    assert "academic" in data and data["student"]["full_name"] == full["student"]["full_name"]
    page = c.get(url, base_url=host(A)).get_data(as_text=True)
    assert "المالي" not in page and "الصحي" not in page and "الأكاديمي" in page


# ─── search ─────────────────────────────────────────────────────────

def test_search_skips_a_group_whose_feature_is_off(lapp, two_schools, login_as):
    from app.extensions import db
    from app.models.hr import Employee
    A = two_schools["A"]
    with lapp.app_context():
        db.session.add(Employee(school_id=A["school"].id, full_name="Zebulon Employee", job_title="x"))
        db.session.commit(); db.session.remove()
    c = _client(lapp, login_as, A)
    assert "الموظفون" in (c.get("/search.json?q=Zebulon", base_url=host(A)).get_json() or {}).get("groups", {}) \
        or "الموظفون" in c.get("/search?q=Zebulon", base_url=host(A)).get_data(as_text=True)
    _features(lapp, A["school"].id, {"hr.employees": False})
    assert "Zebulon Employee" not in c.get("/search?q=Zebulon", base_url=host(A)).get_data(as_text=True)
    assert "Zebulon Employee" not in c.get("/search.json?q=Zebulon", base_url=host(A)).get_data(as_text=True)


# ─── roles ──────────────────────────────────────────────────────────

def test_saving_a_role_keeps_the_permissions_of_a_closed_module(lapp, two_schools, login_as):
    from app.extensions import db
    from app.models import Role
    A = two_schools["A"]
    sid = A["school"].id
    with lapp.app_context():
        r = Role(school_id=sid, name="accountant", name_ar="محاسب", is_system=False,
                 permissions={"finance": ["view"], "students": ["view"]})
        db.session.add(r); db.session.commit(); rid = r.id
        db.session.remove()
    _module(lapp, sid, "finance", False)
    c = _client(lapp, login_as, A)
    form = c.get(f"/admin/roles/{hid(rid)}/edit", base_url=host(A)).get_data(as_text=True)
    assert 'name="perm_finance_view"' not in form and 'name="perm_students_view"' in form
    # the admin renames the role; a forged hidden row is ignored
    c.post(f"/admin/roles/{hid(rid)}/edit", base_url=host(A),
           data={"name": "accountant", "name_ar": "محاسب أول", "perm_students_view": "1",
                 "perm_finance_delete": "1"})
    _module(lapp, sid, "finance", None)
    with lapp.app_context():
        r = db.session.get(Role, rid)
        assert r.name_ar == "محاسب أول"
        assert r.permissions == {"finance": ["view"], "students": ["view"]}
        db.session.remove()


# ─── sidebar groups ─────────────────────────────────────────────────

def _sidebar(body):
    start = body.index('id="app-sidebar"')
    return body[start:body.index("</aside>", start)]


def test_quizzes_stay_in_the_sidebar_with_results_off(lapp, two_schools, login_as):
    A = two_schools["A"]
    _module(lapp, A["school"].id, "results", False)
    side = _sidebar(_client(lapp, login_as, A).get("/dashboard", base_url=host(A)).get_data(as_text=True))
    assert "/lms/quizzes" in side and "/results/grades" not in side


def test_a_student_keeps_the_timetable_with_lms_off(lapp, two_schools, login_as):
    A = two_schools["A"]
    c = _client(lapp, login_as, A, "student")
    had = "/schedule" in _sidebar(c.get("/dashboard", base_url=host(A)).get_data(as_text=True))
    _module(lapp, A["school"].id, "lms", False)
    side = _sidebar(c.get("/dashboard", base_url=host(A)).get_data(as_text=True))
    assert "/lms/" not in side and "/courses/" not in side
    if had:
        assert "/schedule" in side


def test_an_empty_group_disappears(lapp, two_schools, login_as):
    A = two_schools["A"]
    _features(lapp, A["school"].id, {"nafis.outcomes": False, "nafis.cycles": False, "nafis.gaps": False})
    side = _sidebar(_client(lapp, login_as, A).get("/dashboard", base_url=host(A)).get_data(as_text=True))
    assert 'data-group="admin-nafis"' not in side
