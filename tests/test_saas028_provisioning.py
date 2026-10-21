"""SAAS-028 — provision_school, starter data, first admin + setup link,
the console wizard, and the smoke crawl of a brand-new school."""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta

import pytest

from isolation_harness import host
from test_saas025_platform import CONSOLE, _login, papp, puser  # noqa: F401  (fixtures)

pytestmark = pytest.mark.usefixtures("papp")


@pytest.fixture
def created(papp):
    """Collects provisioned school ids and purges them afterwards."""
    ids: list[int] = []
    yield ids
    from app.extensions import db
    from app.models import PlatformAuditLog
    from world import purge_schools
    with papp.app_context():
        if ids:
            from app.services.platform_security import audit_prune
            with audit_prune(db.session.connection()):
                PlatformAuditLog.query.filter(PlatformAuditLog.target_school_id.in_(ids)).delete(
                    synchronize_session=False)
            db.session.commit()
            purge_schools(ids)
        db.session.remove()


def _spec(slug=None, **kw):
    from app.services.provisioning import ProvisionSpec
    from app.services.subscriptions import get_settings, internal_plan, platform_today
    plan = internal_plan()
    base = dict(name="مدرسة الاختبار", slug=f"prov-{secrets.token_hex(3)}" if slug is None else slug,
                admin_full_name="مدير الاختبار", plan_id=plan.id,
                starts_on=platform_today(get_settings()), months=12)
    base.update(kw)
    return ProvisionSpec(**base)


def _provision(papp, created, **kw):
    from app.services.provisioning import provision_school
    with papp.test_request_context(base_url=CONSOLE):
        r = provision_school(_spec(**kw), None)
    created.append(r.school_id)
    return r


def _row_counts(papp):
    from app.extensions import db
    with papp.app_context():
        out = {}
        with db.engine.connect() as conn:
            for t in db.metadata.sorted_tables:
                out[t.name] = conn.execute(db.select(db.func.count()).select_from(t)).scalar()
        db.session.remove()
        return out


# ─── service ─────────────────────────────────────────────────────────

def test_provision_creates_complete_school(papp, created):
    from app.extensions import db
    from app.models import (Account, AuditLog, BehaviorCategory, Day, PaymentMethod, Period, Role,
                            School, SchoolSubscriptionEvent, User)
    from app.services.subscriptions import current_subscription, school_state
    r = _provision(papp, created)
    assert r.setup_link.startswith(f"https://{r.slug}.manasety.ai/set-password/")
    assert r.subdomain_status in ("pending_sync", "queued")
    with papp.app_context():
        s = db.session.get(School, r.school_id)
        assert s.status == "active" and s.code and len(s.code) <= 32
        assert current_subscription(s.id) is not None and school_state(s).state == "active"
        for model in (Role, Account, Day, Period, PaymentMethod, BehaviorCategory):
            assert model.query.filter_by(school_id=s.id).count() > 0, model.__name__
        admin = User.query.filter_by(school_id=s.id, username="admin").one()
        assert admin.role.name == "admin" and admin.is_active
        assert PaymentMethod.query.filter_by(school_id=s.id).first().account_id is not None
        assert AuditLog.query.filter_by(school_id=s.id, entity_type="School").count() >= 1
        assert SchoolSubscriptionEvent.query.filter_by(school_id=s.id, kind="created").count() == 1
        db.session.remove()


def test_template_is_idempotent_and_school_scoped(papp, created, two_schools):
    from app.extensions import db
    from app.services.school_templates import apply
    from app.services.tenancy import tenant_context
    owned_before = _owned_counts(papp, two_schools)
    r = _provision(papp, created)
    # provisioning added nothing to A or B
    assert _owned_counts(papp, two_schools) == owned_before
    before = _row_counts(papp)
    with papp.app_context():
        with tenant_context(r.school_id):
            counts = apply(r.school_id)
        db.session.commit()
        db.session.remove()
    assert sum(counts.values()) == 0
    assert _row_counts(papp) == before


def _owned_counts(papp, two_schools):
    """{table: rows owned by A or B} over every table with school_id."""
    from app.extensions import db
    ids = [two_schools["A"]["school"].id, two_schools["B"]["school"].id]
    with papp.app_context():
        with db.engine.connect() as conn:
            out = {t.name: conn.execute(db.select(db.func.count()).select_from(t)
                                        .where(t.c.school_id.in_(ids))).scalar()
                   for t in db.metadata.sorted_tables if "school_id" in t.c}
        db.session.remove()
    return out


def test_two_schools_in_a_row(papp, created):
    a = _provision(papp, created)
    b = _provision(papp, created)
    assert a.school_id != b.school_id and a.slug != b.slug


@pytest.mark.parametrize("slug,msg", [
    ("console", "محجوز"), ("www", "محجوز"), ("-bad", "يسمح"), ("", "مطلوب"),
])
def test_bad_slugs_refused(papp, slug, msg):
    from app.services.provisioning import ProvisionError, provision_school
    with papp.test_request_context(base_url=CONSOLE):
        with pytest.raises(ProvisionError, match=msg):
            provision_school(_spec(slug=slug), None)


def test_duplicate_and_case_insensitive_slug(papp, created):
    from app.services.provisioning import ProvisionError, provision_school
    r = _provision(papp, created)
    with papp.test_request_context(base_url=CONSOLE):
        with pytest.raises(ProvisionError, match="مستخدم"):
            provision_school(_spec(slug=r.slug), None)
        with pytest.raises(ProvisionError, match="مستخدم"):
            provision_school(_spec(slug=r.slug.upper()), None)


def test_code_gets_suffix_when_taken(papp, created):
    from app.extensions import db
    from app.models import School
    a = _provision(papp, created, slug=f"dup{secrets.token_hex(2)}")
    with papp.app_context():
        code_a = db.session.get(School, a.school_id).code
        db.session.remove()
    b = _provision(papp, created, slug=code_a.lower() + "-x")
    with papp.app_context():
        assert db.session.get(School, b.school_id).code != code_a
        db.session.remove()


@pytest.mark.parametrize("step", ["_create_subscription", "_apply_template", "_create_admin",
                                  "_record_events", "_after_create"])
def test_failure_in_any_step_leaves_nothing(papp, monkeypatch, step):
    from app.services import provisioning as prov
    before = _row_counts(papp)
    real = getattr(prov, step)

    def boom(*a, **kw):
        real(*a, **kw)              # do the step's writes, then fail
        raise RuntimeError("injected")
    monkeypatch.setattr(prov, step, boom)
    with papp.test_request_context(base_url=CONSOLE):
        with pytest.raises(RuntimeError):
            prov.provision_school(_spec(), None)
    assert _row_counts(papp) == before


def test_dry_run_writes_nothing(papp):
    from app.services.provisioning import provision_school
    before = _row_counts(papp)
    with papp.test_request_context(base_url=CONSOLE):
        r = provision_school(_spec(), None, dry_run=True)
    assert r.school_id is None and r.setup_link is None and r.plan
    assert _row_counts(papp) == before


# ─── first admin + set-password ──────────────────────────────────────

def _token(link):
    return link.rsplit("/", 1)[1]


def test_setup_link_once_then_login_on_own_host_only(papp, created, two_schools):
    r = _provision(papp, created)
    h = f"http://{r.slug}.manasety.ai"
    c = papp.test_client()
    g = c.get(f"/set-password/{_token(r.setup_link)}", base_url=h)
    assert g.status_code == 302 and g.headers["Location"].endswith("/set-password")
    assert c.get("/set-password", base_url=h).status_code == 200
    pw = secrets.token_urlsafe(12)
    assert c.post("/set-password", base_url=h, data={"password": "short", "confirm": "short"}).status_code == 200
    p = c.post("/set-password", base_url=h, data={"password": pw, "confirm": pw})
    assert p.status_code == 302 and "/auth/login" in p.headers["Location"]
    # single use
    assert papp.test_client().get(f"/set-password/{_token(r.setup_link)}", base_url=h).status_code == 404
    # logs in on its own host
    ok = papp.test_client().post("/auth/login", base_url=h, data={"username": "admin", "password": pw})
    assert ok.status_code == 302 and "/auth/login" not in ok.headers["Location"]
    # …and not on school A's host
    A = two_schools["A"]
    bad = papp.test_client().post("/auth/login", base_url=host(A), data={"username": "admin", "password": pw})
    assert bad.status_code == 401


def test_setup_link_refused_on_other_host_and_after_expiry(papp, created, two_schools):
    from app.extensions import db
    from app.models import AccountSetupToken
    r = _provision(papp, created)
    tok = _token(r.setup_link)
    A = two_schools["A"]
    assert papp.test_client().get(f"/set-password/{tok}", base_url=host(A)).status_code == 404
    with papp.app_context():
        row = AccountSetupToken.query.filter_by(school_id=r.school_id).one()
        assert row.expires_at - datetime.utcnow() <= timedelta(hours=72)
        row.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.session.commit()
        db.session.remove()
    assert papp.test_client().get(f"/set-password/{tok}", base_url=f"http://{r.slug}.manasety.ai").status_code == 404


def test_token_never_stored_or_logged(papp, created, caplog):
    from app.extensions import db
    r = _provision(papp, created)
    tok = _token(r.setup_link)
    assert tok not in caplog.text
    with papp.app_context():
        with db.engine.connect() as conn:
            for t in ("audit_logs", "platform_audit_logs", "school_subscription_events",
                      "account_setup_tokens", "users"):
                rows = conn.execute(db.text(f"SELECT * FROM {t}")).all()
                assert tok not in repr(rows), t
        db.session.remove()


# ─── smoke crawl ─────────────────────────────────────────────────────

SCHOOL_BLUEPRINT_SKIP = ("superadmin.", "cron.", "static", "api.", "account.", "auth.")


def test_smoke_crawl_new_school(papp, created, login_as):
    """A brand-new school: the admin opens every argument-less GET page
    of the school app — zero 500s."""
    from app.extensions import db
    from app.models import User
    r = _provision(papp, created)
    with papp.app_context():
        admin = User.query.filter_by(school_id=r.school_id, username="admin").one()
        db.session.expunge(admin)
        db.session.remove()
    c = papp.test_client()
    h = f"http://{r.slug}.manasety.ai"
    login_as(c, admin, base_url=h)
    errors, seen = [], 0
    for rule in papp.url_map.iter_rules():
        if rule.arguments or "GET" not in (rule.methods or ()) or rule.endpoint.startswith(SCHOOL_BLUEPRINT_SKIP):
            continue
        if re.search(r"(export|download|pdf|xlsx|csv|print)", rule.rule):
            continue
        resp = c.get(rule.rule, base_url=h)
        seen += 1
        if resp.status_code >= 500:
            errors.append((rule.endpoint, rule.rule, resp.status_code))
    assert seen > 40
    assert not errors, errors


# ─── wizard ──────────────────────────────────────────────────────────

def _wizard(c, slug):
    steps = [
        ("school", {"name": "مدرسة الويزارد", "name_en": "Wizard School", "slug": slug}),
        ("settings", {"currency": "EGP", "currency_symbol": "ج.م", "fiscal_year_start_month": "9",
                      "invoice_prefix": "INV", "default_tax_rate": "0", "attendance_mode": "daily"}),
        ("subscription", {"plan_id": "", "starts_on": "", "term": "months", "months": "12"}),
        ("admin", {"admin_full_name": "مدير", "admin_username": "admin"}),
    ]
    return steps


def test_wizard_end_to_end_and_double_submit(papp, puser, created):
    from app.extensions import db
    from app.models import School
    from app.services.subscriptions import internal_plan
    with papp.app_context():
        pid = internal_plan().id
        db.session.commit()
        db.session.remove()
    info = puser("owner")
    c = papp.test_client()
    _login(c, info)
    slug = f"wiz-{secrets.token_hex(3)}"
    assert c.get("/superadmin/schools/new", base_url=CONSOLE).status_code == 200
    # can't skip ahead
    assert c.get("/superadmin/schools/new?step=review", base_url=CONSOLE).status_code == 302
    for step, data in _wizard(c, slug):
        if step == "subscription":
            data["plan_id"] = str(pid)
        r = c.post(f"/superadmin/schools/new/{step}", base_url=CONSOLE, data=data)
        assert r.status_code == 302, (step, r.data[:300])
    # going back keeps the fields
    back = c.post("/superadmin/schools/new/admin", base_url=CONSOLE,
                  data={"admin_full_name": "مدير", "admin_username": "admin", "nav": "back"})
    assert back.status_code == 302
    page = c.get("/superadmin/schools/new?step=school", base_url=CONSOLE)
    assert slug.encode() in page.data
    review = c.get("/superadmin/schools/new?step=review", base_url=CONSOLE)
    assert review.status_code == 200
    nonce = re.search(rb'name="nonce" value="([^"]+)"', review.data).group(1).decode()
    first = c.post("/superadmin/schools/new/create", base_url=CONSOLE, data={"nonce": nonce})
    assert first.status_code == 200 and b"/set-password/" in first.data
    second = c.post("/superadmin/schools/new/create", base_url=CONSOLE, data={"nonce": nonce})
    assert second.status_code == 302 and b"/set-password/" not in second.data
    with papp.app_context():
        rows = School.query.filter_by(slug=slug).all()
        assert len(rows) == 1
        created.append(rows[0].id)
        db.session.remove()


def test_wizard_validates_server_side(papp, puser):
    info = puser("owner")
    c = papp.test_client()
    _login(c, info)
    r = c.post("/superadmin/schools/new/school", base_url=CONSOLE, data={"name": "x", "slug": "console"})
    assert r.status_code == 400 and "محجوز".encode() in r.data
    r = c.post("/superadmin/schools/new/school", base_url=CONSOLE, data={"name": "", "slug": "fine-slug"})
    assert r.status_code == 400


@pytest.mark.parametrize("role", ["support", "finance"])
def test_only_owner_can_create(papp, puser, role):
    info = puser(role)
    c = papp.test_client()
    _login(c, info)
    assert c.get("/superadmin/schools/new", base_url=CONSOLE).status_code == 403
    assert c.post("/superadmin/schools/new/create", base_url=CONSOLE, data={"nonce": "x"}).status_code == 403
    assert c.get("/superadmin/schools/slug-check?slug=abc", base_url=CONSOLE).status_code == 403


def test_slug_check_endpoint_and_rate_limit(papp, puser, monkeypatch):
    from app.blueprints.superadmin import onboarding
    monkeypatch.setattr(onboarding, "SLUG_CHECKS_PER_MINUTE", 3)
    info = puser("owner")
    c = papp.test_client()
    _login(c, info)
    j = c.get("/superadmin/schools/slug-check?slug=console", base_url=CONSOLE).json
    assert j["ok"] is False and "محجوز" in j["message"]
    assert c.get("/superadmin/schools/slug-check?slug=free-one", base_url=CONSOLE).json["ok"] is True
    c.get("/superadmin/schools/slug-check?slug=a1", base_url=CONSOLE)
    assert c.get("/superadmin/schools/slug-check?slug=a2", base_url=CONSOLE).status_code == 429


def test_wizard_not_reachable_from_school_host(papp, two_schools):
    A = two_schools["A"]
    assert papp.test_client().get("/superadmin/schools/new", base_url=host(A)).status_code == 404
