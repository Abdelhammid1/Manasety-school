"""Features inside modules: every web route of a school module belongs to
exactly one feature; a feature is on = its module is on AND (the school's
override, else its default). Essential features never turn off. Two
schools throughout: A changes, B never does."""

from __future__ import annotations

import itertools
from datetime import date

import pytest

from isolation_harness import hid, host
from test_saas026_subscriptions import CONSOLE, _console_client, console  # noqa: F401

APPROVED_ESSENTIAL = {
    "core.auth", "core.dashboard", "core.users", "core.roles", "core.settings", "core.support_log",
    "core.ai_usage", "academic.structure", "students.records", "students.guardians",
}


@pytest.fixture
def fapp(app, monkeypatch):
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


def _features(app, sid, changes, reason="test"):
    from app.extensions import db
    from app.models import School
    from app.services.modules import set_feature_overrides
    with app.app_context():
        out = set_feature_overrides(db.session.get(School, sid), changes, reason, None)
        db.session.commit()
        db.session.remove()
    return out


def _module(app, sid, key, enabled):
    from app.extensions import db
    from app.models import School
    from app.services.modules import set_override
    with app.app_context():
        set_override(db.session.get(School, sid), key, enabled, "test", None)
        db.session.commit()
        db.session.remove()


def _admin(app, login_as, bundle, role="admin"):
    c = app.test_client()
    login_as(c, bundle["users"][role], base_url=host(bundle))
    return c


# ─── the catalogue ──────────────────────────────────────────────────

def test_every_web_route_has_exactly_one_feature(app):
    from app.services.modules import (APP_ENDPOINTS, BY_KEY, FEATURES, PLATFORM_BLUEPRINTS,
                                      feature_for_endpoint, module_for_endpoint)
    web = {r.endpoint for r in app.url_map.iter_rules()
           if r.endpoint not in APP_ENDPOINTS and not r.endpoint.startswith("_")
           and r.endpoint.split(".")[0] not in PLATFORM_BLUEPRINTS | {"api"}}
    missing = sorted(e for e in web if feature_for_endpoint(e) is None)
    assert not missing, f"routes without a feature (add them to FEATURES): {missing}"
    seen: dict[str, str] = {}
    twice = []
    for f in FEATURES:
        for ep in f.endpoints:
            if ep in seen:
                twice.append((ep, seen[ep], f.key))
            seen[ep] = f.key
    assert not twice, f"routes in two features: {twice}"
    assert all(f.module in BY_KEY for f in FEATURES)
    # a feature's routes are in its own module, and every listed route exists
    assert not [e for e in seen if e not in web], "a feature lists a route that doesn't exist"
    wrong = [(e, k) for e, k in seen.items() if module_for_endpoint(e, "") != k.split(".")[0]]
    assert not wrong, f"routes listed under another module's feature: {wrong}"


def test_the_catalogue_is_the_approved_one():
    from app.services.modules import ESSENTIAL_FEATURES, FEATURES, FEATURES_BY_KEY
    assert len(FEATURES) == 69 and len(FEATURES_BY_KEY) == 69
    assert ESSENTIAL_FEATURES == APPROVED_ESSENTIAL
    assert [f.key for f in FEATURES if not f.default_on] == ["lms.ai"]


@pytest.mark.parametrize("module_on,override,default_on,essential",
                         list(itertools.product([True, False], [True, False, None], [True, False], [True, False])))
def test_the_rule_for_every_cell(fapp, two_schools, monkeypatch, module_on, override, default_on, essential):
    """on = essential OR (module on AND (override if any, else default))."""
    from app.extensions import db
    from app.models import SchoolFeatureOverride
    from app.services import modules
    A = two_schools["A"]
    sid = A["school"].id
    key = "finance.budgets"
    f = modules.FEATURES_BY_KEY[key]
    fake = modules.Feature(f.key, f.label_ar, f.endpoints, essential=essential, default_on=default_on)
    monkeypatch.setitem(modules.FEATURES_BY_KEY, key, fake)
    monkeypatch.setattr(modules, "FEATURES", tuple(fake if x.key == key else x for x in modules.FEATURES))
    if not module_on:
        _module(fapp, sid, "finance", False)
    if override is not None:
        with fapp.app_context():
            db.session.add(SchoolFeatureOverride(school_id=sid, feature_key=key, enabled=override, reason="t"))
            db.session.commit(); db.session.remove()
    expected = essential or (module_on and (override if override is not None else default_on))
    with fapp.app_context():
        assert modules.feature_enabled(sid, key) is expected
        db.session.remove()


def test_unknown_none_and_platform():
    from app.services.modules import feature_enabled
    assert feature_enabled(1, None) is True
    assert feature_enabled(None, "finance.budgets") is True          # a platform user
    assert feature_enabled(1, "finance.nope") is False


# ─── enforcement ────────────────────────────────────────────────────

def test_a_page_off_for_a_only(fapp, two_schools, login_as):
    A, B = two_schools["A"], two_schools["B"]
    _features(fapp, A["school"].id, {"finance.budgets": False})
    ca, cb = _admin(fapp, login_as, A), _admin(fapp, login_as, B)
    assert ca.get("/finance/budgets", base_url=host(A)).status_code == 404
    assert cb.get("/finance/budgets", base_url=host(B)).status_code == 200
    assert ca.get("/finance/invoices", base_url=host(A)).status_code == 200      # the rest of finance
    page_a = ca.get("/finance/invoices", base_url=host(A)).get_data(as_text=True)
    page_b = cb.get("/finance/invoices", base_url=host(B)).get_data(as_text=True)
    assert "/finance/budgets" not in page_a and "/finance/budgets" in page_b
    env = fapp.jinja_env.globals
    for bundle, expected in ((A, False), (B, True)):
        with fapp.test_request_context("/", base_url=host(bundle)):
            from flask import g
            from app.services.tenancy import resolve_host
            g.tenant_resolved = resolve_host(f"{bundle['school'].slug}.manasety.ai")
            assert env["endpoint_on"]("finance.budgets_home") is expected
            assert env["feature_on"]("finance.budgets") is expected
            assert env["endpoint_on"]("finance.invoices_list") is True


def test_behavior_off_inside_a_core_module(fapp, two_schools, login_as):
    A, B = two_schools["A"], two_schools["B"]
    _features(fapp, A["school"].id, {"students.behavior": False})
    ca, cb = _admin(fapp, login_as, A), _admin(fapp, login_as, B)
    assert ca.get(f"/students/{hid(A['student'].id)}/behavior", base_url=host(A)).status_code == 404
    assert cb.get(f"/students/{hid(B['student'].id)}/behavior", base_url=host(B)).status_code == 200
    detail = ca.get(f"/students/{hid(A['student'].id)}", base_url=host(A))
    assert detail.status_code == 200


def test_a_module_off_wins_and_coming_back_restores_the_pages(fapp, two_schools, login_as):
    A = two_schools["A"]
    sid = A["school"].id
    _module(fapp, sid, "finance", False)
    _features(fapp, sid, {"finance.reports": True, "finance.budgets": False})
    c = _admin(fapp, login_as, A)
    assert c.get("/finance/reports", base_url=host(A)).status_code == 404
    _module(fapp, sid, "finance", None)
    assert c.get("/finance/reports", base_url=host(A)).status_code == 200
    assert c.get("/finance/budgets", base_url=host(A)).status_code == 404     # its stored state


def test_reenabling_a_page_shows_its_data_again(fapp, two_schools, login_as):
    from app.extensions import db
    from app.models import CostCenter
    A = two_schools["A"]
    sid = A["school"].id
    with fapp.app_context():
        db.session.add(CostCenter(school_id=sid, code="CC-77", name="مركز الاختبار"))
        db.session.commit(); db.session.remove()
    _features(fapp, sid, {"finance.accounting": False})
    c = _admin(fapp, login_as, A)
    assert c.get("/finance/cost-centers", base_url=host(A)).status_code == 404
    _features(fapp, sid, {"finance.accounting": None})
    assert "مركز الاختبار" in c.get("/finance/cost-centers", base_url=host(A)).get_data(as_text=True)


def test_the_platform_user_is_never_gated(console, two_schools):
    A = two_schools["A"]
    _features(console, A["school"].id, {"finance.budgets": False, "core.audit": False})
    c, _ = _console_client(console, "owner")
    assert c.get(f"/superadmin/schools/{A['school'].id}", base_url=CONSOLE).status_code == 200


# ─── set_feature_overrides ──────────────────────────────────────────

@pytest.mark.parametrize("changes,reason", [
    ({"finance.budgets": False, "core.users": False}, "x"),      # one essential refuses both
    ({"finance.budgets": False, "finance.nope": False}, "x"),    # unknown
    ({"finance.budgets": False}, "   "),                          # no reason
])
def test_refused_changes_write_nothing(fapp, two_schools, changes, reason):
    from app.extensions import db
    from app.models import PlatformAuditLog, SchoolFeatureOverride, SchoolSubscriptionEvent
    from app.services.subscriptions import SubscriptionError
    sid = two_schools["A"]["school"].id
    with pytest.raises(SubscriptionError):
        _features(fapp, sid, changes, reason)
    with fapp.app_context():
        assert SchoolFeatureOverride.query.filter_by(school_id=sid).count() == 0
        assert SchoolSubscriptionEvent.query.filter_by(school_id=sid, kind="feature_override").count() == 0
        assert PlatformAuditLog.query.filter_by(action="feature_override").count() == 0
        db.session.remove()


def test_a_change_writes_rows_one_event_and_one_audit(fapp, two_schools):
    from app.extensions import db
    from app.models import PlatformAuditLog, SchoolFeatureOverride, SchoolSubscriptionEvent
    sid = two_schools["A"]["school"].id
    diff = _features(fapp, sid, {"finance.budgets": False, "lms.ai": True, "finance.reports": True}, "عقد مخصص")
    assert diff == {"finance.budgets": (True, False), "lms.ai": (False, True)}    # reports = its default
    with fapp.app_context():
        rows = {o.feature_key: o.enabled for o in SchoolFeatureOverride.query.filter_by(school_id=sid)}
        assert rows == {"finance.budgets": False, "lms.ai": True}
        ev = SchoolSubscriptionEvent.query.filter_by(school_id=sid, kind="feature_override").all()
        assert len(ev) == 1 and ev[0].reason == "عقد مخصص"
        audit = PlatformAuditLog.query.filter_by(action="feature_override").all()
        assert len(audit) == 1 and audit[0].meta["changes"]["finance.budgets"] == {"before": True, "after": False}
        db.session.remove()
    # back to the default removes the row; no row equals a default
    _features(fapp, sid, {"finance.budgets": None, "lms.ai": False})
    with fapp.app_context():
        assert SchoolFeatureOverride.query.filter_by(school_id=sid).count() == 0
        db.session.remove()


# ─── AI and cron ────────────────────────────────────────────────────

def test_no_ai_feature_no_deepseek_call_and_no_button(fapp, two_schools, login_as, monkeypatch):
    from app.services import deepseek
    calls = []
    monkeypatch.setattr(deepseek, "is_configured", lambda: True)
    monkeypatch.setattr(deepseek, "suggest_blueprint_mix", lambda *a, **k: calls.append(a) or {})
    monkeypatch.setattr(deepseek, "review_pending_questions", lambda *a, **k: calls.append(a) or [])
    A, B = two_schools["A"], two_schools["B"]
    _features(fapp, B["school"].id, {"lms.ai": True})
    ca, cb = _admin(fapp, login_as, A), _admin(fapp, login_as, B)
    assert ca.post("/lms/exams/blueprint/ai-suggest", base_url=host(A), json={}).status_code == 404
    assert ca.post("/lms/bank/ai-review", base_url=host(A)).status_code == 404
    assert calls == []
    assert 'id="ai-suggest"' not in ca.get("/lms/exams/blueprint/new", base_url=host(A)).get_data(as_text=True)
    assert 'id="ai-suggest"' in cb.get("/lms/exams/blueprint/new", base_url=host(B)).get_data(as_text=True)


def test_new_schools_have_ai_off_and_the_migration_keeps_existing_ones_on():
    import importlib.util
    import pathlib
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    import alembic.op as op_mod
    from app.services.modules import FEATURES_BY_KEY
    assert FEATURES_BY_KEY["lms.ai"].default_on is False
    spec = importlib.util.spec_from_file_location(
        "m", pathlib.Path(__file__).parent.parent / "migrations/versions/g8b0c2d4e6f8_school_feature_overrides.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    eng = sa.create_engine("sqlite://")
    with eng.begin() as conn:
        conn.execute(sa.text("CREATE TABLE schools (id INTEGER PRIMARY KEY)"))
        conn.execute(sa.text("CREATE TABLE platform_users (id INTEGER PRIMARY KEY)"))
        conn.execute(sa.text("INSERT INTO schools VALUES (1),(2),(3)"))
        op_mod._proxy = Operations(MigrationContext.configure(conn))
        mod.upgrade(); mod.upgrade()                                # twice: no duplicate
        rows = conn.execute(sa.text("SELECT school_id, feature_key, enabled, reason FROM school_feature_overrides "
                                    "ORDER BY school_id")).all()
        assert [(r[0], r[1], bool(r[2])) for r in rows] == [(1, "lms.ai", True), (2, "lms.ai", True),
                                                             (3, "lms.ai", True)]
        assert rows[0][3] == "الوضع قبل هذه التذكرة"
        mod.downgrade()
        assert "school_feature_overrides" not in sa.inspect(conn).get_table_names()


def test_cron_skips_only_the_features_that_are_off(fapp, two_schools):
    from app.blueprints.cron.routes import run_school_tick
    A, B = two_schools["A"], two_schools["B"]
    _features(fapp, A["school"].id, {"attendance.risk": False, "finance.recurring": False})
    with fapp.app_context():
        ra = run_school_tick(A["school"].id, date.today())
        rb = run_school_tick(B["school"].id, date.today())
    assert "risk_scores_updated" not in ra and "recurring" not in ra and "reminders" in ra
    assert sorted(ra["skipped_features"]) == ["attendance.risk", "finance.recurring"]
    assert "risk_scores_updated" in rb and "recurring" in rb and "skipped_features" not in rb
