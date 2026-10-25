"""Console → a school's modules AND pages in one tree, one reason, one
save (owner only). One event + one audit line per save; no override row
that equals a default; a refused save changes nothing."""

from __future__ import annotations

import pytest

from isolation_harness import host
from test_saas026_subscriptions import CONSOLE, _console_client, console  # noqa: F401


@pytest.fixture
def capp(console):
    console.config["WTF_CSRF_ENABLED"] = False
    return console


@pytest.fixture(autouse=True)
def _clean(console):
    yield
    from app.extensions import db
    from app.models import SchoolFeatureOverride, SchoolModuleOverride
    with console.app_context():
        SchoolFeatureOverride.query.delete()
        SchoolModuleOverride.query.delete()
        db.session.commit()
        db.session.remove()


def _form(app, sid, **changes):
    """What the page would post: every toggleable module as it is, every
    editable page with its stored state — then `changes` on top.
    module_x="off" / feature_x=False|True / reason="…"."""
    from app.extensions import db
    from app.services.modules import feature_sources
    with app.app_context():
        tree = feature_sources(sid)
        db.session.remove()
    data: dict = {"known": []}
    for m in tree:
        if not m["module"].core:
            data[f"module_{m['module'].key}"] = ("on" if m["override"].enabled else "off") if m["override"] else "plan"
        if not m["enabled"]:
            continue
        for f in m["features"]:
            if f["source"] == "essential":
                continue
            key = f["feature"].key
            data["known"].append(key)
            if f["stored"]:
                data[f"feature_{key}"] = "1"
    for k, v in changes.items():
        if k.startswith("feature_"):
            if v:
                data[k] = "1"
            else:
                data.pop(k, None)
        else:
            data[k] = v
    return data


def _save(c, sid, data):
    return c.post(f"/superadmin/schools/{sid}/features", base_url=CONSOLE, data=data, follow_redirects=True)


def test_the_owner_sees_the_whole_tree(capp, two_schools):
    from app.services.modules import FEATURES, MODULES
    sid = two_schools["A"]["school"].id
    c, _ = _console_client(capp, "owner")
    page = c.get(f"/superadmin/schools/{sid}", base_url=CONSOLE).get_data(as_text=True)
    assert all(m.label_ar in page for m in MODULES)
    assert all(f'id="f_{f.key}"' in page for f in FEATURES)
    assert f"/superadmin/schools/{sid}/features" in page and 'name="module_finance"' in page


def test_two_modules_and_three_pages_in_one_save(capp, two_schools, login_as):
    from app.extensions import db
    from app.models import PlatformAuditLog, SchoolFeatureOverride, SchoolModuleOverride, SchoolSubscriptionEvent
    from app.services.modules import feature_enabled, module_enabled
    A, B = two_schools["A"], two_schools["B"]
    sid = A["school"].id
    c, _ = _console_client(capp, "owner")
    data = _form(capp, sid, module_hr="off", module_nafis="off",
                 **{"feature_students.behavior": False, "feature_lms.ai": True, "feature_finance.budgets": False},
                 reason="باقة مخصصة")
    body = _save(c, sid, data).get_data(as_text=True)
    assert "تم تعديل 2 وحدة و3 صفحة" in body
    with capp.app_context():
        assert not module_enabled(sid, "hr") and not module_enabled(sid, "nafis")
        assert not feature_enabled(sid, "finance.budgets") and not feature_enabled(sid, "students.behavior")
        assert feature_enabled(sid, "lms.ai")
        assert feature_enabled(B["school"].id, "finance.budgets") and module_enabled(B["school"].id, "hr")
        ev = SchoolSubscriptionEvent.query.filter(SchoolSubscriptionEvent.school_id == sid,
                                                  SchoolSubscriptionEvent.kind.in_(("module_override",
                                                                                    "feature_override"))).all()
        assert len(ev) == 1 and ev[0].reason == "باقة مخصصة" and "hr:off" in ev[0].to_value
        audit = PlatformAuditLog.query.filter(PlatformAuditLog.action.in_(("module_override",
                                                                           "feature_override"))).all()
        assert len(audit) == 1
        assert audit[0].meta["modules"]["hr"] == {"before": "plan", "after": "off"}
        assert audit[0].meta["changes"]["finance.budgets"] == {"before": True, "after": False}
        assert SchoolModuleOverride.query.filter_by(school_id=sid).count() == 2
        assert {o.feature_key for o in SchoolFeatureOverride.query.filter_by(school_id=sid)} == \
            {"finance.budgets", "students.behavior", "lms.ai"}
        db.session.remove()
    # the school's admin: 404 and no link, at once
    ca = capp.test_client()
    login_as(ca, A["users"]["admin"], base_url=host(A))
    assert ca.get("/finance/budgets", base_url=host(A)).status_code == 404
    assert "/finance/budgets" not in ca.get("/finance/invoices", base_url=host(A)).get_data(as_text=True)
    # the change shows under "آخر التغييرات"
    page = c.get(f"/superadmin/schools/{sid}", base_url=CONSOLE).get_data(as_text=True)
    assert "آخر التغييرات" in page and "باقة مخصصة" in page


def test_back_to_the_default_removes_the_exception(capp, two_schools):
    from app.extensions import db
    from app.models import SchoolFeatureOverride
    sid = two_schools["A"]["school"].id
    c, _ = _console_client(capp, "owner")
    _save(c, sid, _form(capp, sid, **{"feature_finance.budgets": False}, reason="x"))
    _save(c, sid, _form(capp, sid, **{"feature_finance.budgets": True}, reason="رجوع"))
    with capp.app_context():
        assert SchoolFeatureOverride.query.filter_by(school_id=sid).count() == 0
        db.session.remove()


def test_without_a_reason_nothing_changes_and_the_choices_stay(capp, two_schools):
    from app.extensions import db
    from app.models import SchoolFeatureOverride, SchoolModuleOverride
    sid = two_schools["A"]["school"].id
    c, _ = _console_client(capp, "owner")
    body = _save(c, sid, _form(capp, sid, module_hr="off", **{"feature_finance.budgets": False,
                                                              "feature_lms.ai": True}, reason="")).get_data(as_text=True)
    assert "لم يُحفظ أي تغيير" in body
    with capp.app_context():
        assert SchoolModuleOverride.query.filter_by(school_id=sid).count() == 0
        assert SchoolFeatureOverride.query.filter_by(school_id=sid).count() == 0
        db.session.remove()
    # the page shows what was chosen, not the stored state
    assert 'id="f_lms.ai" name="feature_lms.ai" value="1" data-module="lms" checked' in body
    assert 'id="f_finance.budgets" name="feature_finance.budgets" value="1" data-module="finance" >' in body
    assert '<option value="off" selected>' in body


@pytest.mark.parametrize("extra", [{"known": ["core.users"]}, {"known": ["finance.nope"]},
                                   {"module_students": "off"}])
def test_essential_or_unknown_keys_refuse_the_whole_save(capp, two_schools, extra):
    from app.extensions import db
    from app.models import SchoolFeatureOverride, SchoolModuleOverride
    sid = two_schools["A"]["school"].id
    c, _ = _console_client(capp, "owner")
    data = _form(capp, sid, module_hr="off", **{"feature_finance.budgets": False}, reason="x")
    for k, v in extra.items():
        data[k] = data.get(k, []) + v if isinstance(v, list) else v
    _save(c, sid, data)
    with capp.app_context():
        assert SchoolModuleOverride.query.filter_by(school_id=sid).count() == 0
        assert SchoolFeatureOverride.query.filter_by(school_id=sid).count() == 0
        db.session.remove()


def test_a_closed_module_keeps_its_pages_and_they_are_not_editable(capp, two_schools, login_as):
    from app.extensions import db
    from app.models import SchoolFeatureOverride
    A = two_schools["A"]
    sid = A["school"].id
    c, _ = _console_client(capp, "owner")
    _save(c, sid, _form(capp, sid, **{"feature_finance.budgets": False}, reason="x"))
    _save(c, sid, _form(capp, sid, module_finance="off", reason="إيقاف المالية"))
    page = c.get(f"/superadmin/schools/{sid}", base_url=CONSOLE).get_data(as_text=True)
    assert 'id="f_finance.reports" disabled' in page and 'name="feature_finance.reports"' not in page
    # the closed module's pages were not sent, so the stored page state stays
    with capp.app_context():
        assert SchoolFeatureOverride.query.filter_by(school_id=sid, feature_key="finance.budgets").one().enabled is False
        db.session.remove()
    _save(c, sid, _form(capp, sid, module_finance="plan", reason="رجوع المالية"))
    ca = capp.test_client()
    login_as(ca, A["users"]["admin"], base_url=host(A))
    assert ca.get("/finance/reports", base_url=host(A)).status_code == 200
    assert ca.get("/finance/budgets", base_url=host(A)).status_code == 404


@pytest.mark.parametrize("role", ["finance", "support"])
def test_other_roles_read_only(capp, two_schools, role):
    sid = two_schools["A"]["school"].id
    c, _ = _console_client(capp, role)
    page = c.get(f"/superadmin/schools/{sid}", base_url=CONSOLE).get_data(as_text=True)
    assert "الموديولات والصفحات" in page and 'id="f_finance.budgets" disabled' in page
    assert f"/superadmin/schools/{sid}/features" not in page
    assert c.post(f"/superadmin/schools/{sid}/features", base_url=CONSOLE,
                  data={"module_hr": "off", "reason": "x"}).status_code == 403


def test_school_users_and_visitors_never_reach_it(capp, two_schools, login_as):
    A = two_schools["A"]
    sc = capp.test_client()
    login_as(sc, A["users"]["admin"], base_url=host(A))
    for base in (host(A), CONSOLE):
        r = sc.post(f"/superadmin/schools/{A['school'].id}/features", base_url=base, data={"module_hr": "off", "reason": "x"})
        assert r.status_code in (302, 401, 403, 404)
    r = capp.test_client().post(f"/superadmin/schools/{A['school'].id}/features", base_url=CONSOLE,
                                data={"module_hr": "off", "reason": "x"})
    assert r.status_code in (302, 401, 403)
