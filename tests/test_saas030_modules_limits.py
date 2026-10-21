"""SAAS-030 — module catalogue, per-school module enforcement (route,
API, can(), sidebar, cron), plan limits (students, staff users, storage)
and the console screen. Two schools throughout: A changes, B never does."""

from __future__ import annotations

import io
import threading

import pytest

from isolation_harness import host
from test_saas026_subscriptions import CONSOLE, _console_client, console  # noqa: F401

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.fixture
def mapp(app, monkeypatch):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    return app


def _override(app, school_id, key, enabled):
    from app.extensions import db
    from app.models import School
    from app.services.modules import set_override
    with app.app_context():
        set_override(db.session.get(School, school_id), key, enabled, "test", None)
        db.session.commit()
        db.session.remove()


def _limits(app, school_id, **values):
    from app.extensions import db
    from app.models import SchoolLimitOverride
    with app.app_context():
        row = db.session.get(SchoolLimitOverride, school_id)
        if not values:
            if row is not None:
                db.session.delete(row)
        else:
            if row is None:
                row = SchoolLimitOverride(school_id=school_id, reason="test")
                db.session.add(row)
            for k, v in values.items():
                setattr(row, k, v)
        db.session.commit()
        db.session.remove()


@pytest.fixture(autouse=True)
def _clean_overrides(app):
    yield
    from app.extensions import db
    from app.models import SchoolLimitOverride, SchoolModuleOverride
    with app.app_context():
        SchoolModuleOverride.query.delete()
        SchoolLimitOverride.query.delete()
        db.session.commit()
        db.session.remove()


# ─── catalogue ───────────────────────────────────────────────────────

def test_every_route_belongs_to_a_module(app):
    from app.services.modules import APP_ENDPOINTS, PLATFORM_BLUEPRINTS, module_for_endpoint
    missing = sorted({r.endpoint for r in app.url_map.iter_rules()
                      if r.endpoint not in APP_ENDPOINTS and not r.endpoint.startswith("_")
                      and r.endpoint.split(".")[0] not in PLATFORM_BLUEPRINTS
                      and module_for_endpoint(r.endpoint, r.rule) is None})
    assert not missing, f"classify these in services/modules.py: {missing}"


def test_every_blueprint_is_classified(app):
    from app.services.modules import MODULES, PLATFORM_BLUEPRINTS
    known = {b for m in MODULES for b in m.blueprints} | set(PLATFORM_BLUEPRINTS) | {"api", "platform"}
    assert set(app.blueprints) <= known, sorted(set(app.blueprints) - known)


def test_core_modules_and_unknown_keys():
    from app.services.modules import BY_KEY, validate_plan_modules
    assert all(BY_KEY[k].core for k in ("core", "academic", "students"))
    assert not any(BY_KEY[k].core for k in ("finance", "hr", "lms", "nafis", "attendance",
                                            "schedule", "portal", "results"))
    with pytest.raises(ValueError):
        validate_plan_modules(["finance", "flying"])
    assert validate_plan_modules(["*", "x"]) == ["*"]


# ─── module enforcement ──────────────────────────────────────────────

def test_finance_off_for_a_only(mapp, two_schools, login_as):
    from app.services.auth_jwt import issue_token
    A, B = two_schools["A"], two_schools["B"]
    _override(mapp, A["school"].id, "finance", False)

    ca = mapp.test_client()
    login_as(ca, A["users"]["admin"], base_url=host(A))
    assert ca.get("/finance/invoices", base_url=host(A)).status_code == 404

    cb = mapp.test_client()
    login_as(cb, B["users"]["admin"], base_url=host(B))
    assert cb.get("/finance/invoices", base_url=host(B)).status_code == 200

    # sidebar: links and groups are filtered by the same helpers the
    # templates call (jinja globals, so the sidebar macros see them)
    env = mapp.jinja_env.globals
    for bundle, expected in ((A, False), (B, True)):
        with mapp.test_request_context("/", base_url=host(bundle)):
            from flask import g
            from app.services.tenancy import resolve_host
            g.tenant_resolved = resolve_host(f"{bundle['school'].slug}.manasety.ai")
            assert env["endpoint_on"]("finance.invoices_list") is expected
            assert env["module_on"]("finance") is expected
            assert env["endpoint_on"]("students.students_list") is True

    with mapp.app_context():
        tok = issue_token(A["users"]["parent"])
    r = mapp.test_client().get(f"/api/parent/child/{A['student'].id}/invoices", base_url=host(A),
                               headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403 and r.json == {"error": "module_disabled", "module": "finance"}


def test_can_follows_modules(mapp, two_schools):
    from app.extensions import db
    from app.models import User
    A, B = two_schools["A"], two_schools["B"]
    _override(mapp, A["school"].id, "finance", False)
    with mapp.app_context():
        a = db.session.get(User, A["users"]["admin"].id)
        b = db.session.get(User, B["users"]["admin"].id)
        assert a.can("finance", "view") is False and a.can("students", "view") is True
        assert b.can("finance", "view") is True
        db.session.remove()


def test_reenable_restores_everything(mapp, two_schools, login_as):
    A = two_schools["A"]
    _override(mapp, A["school"].id, "finance", False)
    _override(mapp, A["school"].id, "finance", None)      # back to the plan
    c = mapp.test_client()
    login_as(c, A["users"]["admin"], base_url=host(A))
    assert c.get("/finance/invoices", base_url=host(A)).status_code == 200


def test_core_module_cannot_be_disabled(mapp, two_schools):
    from app.services.subscriptions import SubscriptionError
    with pytest.raises(SubscriptionError):
        _override(mapp, two_schools["A"]["school"].id, "students", False)


def test_cron_skips_disabled_module(mapp, two_schools):
    from datetime import date
    from app.blueprints.cron.routes import run_school_tick
    A, B = two_schools["A"], two_schools["B"]
    _override(mapp, A["school"].id, "finance", False)
    with mapp.app_context():
        ra = run_school_tick(A["school"].id, date.today())
        rb = run_school_tick(B["school"].id, date.today())
    assert ra["skipped_modules"] == ["finance"] and "reminders" not in ra
    assert "reminders" in rb and "skipped_modules" not in rb


def test_plan_without_module_and_plan_change(mapp, two_schools):
    import secrets
    from app.extensions import db
    from app.models import Plan, School, SchoolModuleOverride
    from app.services import subscriptions as subs
    from app.services.modules import enabled_modules
    A = two_schools["A"]["school"].id
    with mapp.app_context():
        lite = Plan(code=f"lite-{secrets.token_hex(2)}", name_ar="خفيفة", modules=["attendance"],
                    billing_cycle="monthly", is_active=True)
        db.session.add(lite); db.session.flush()
        school = db.session.get(School, A)
        internal = subs.current_subscription(A).plan
        subs.change_plan(school, lite, None, "test")
        db.session.commit()
        on = enabled_modules(A)
        assert "attendance" in on and "finance" not in on and "students" in on
        # an override that just repeats the new plan disappears on the next change
        from app.services.modules import set_override
        set_override(school, "finance", True, "trial of finance", None)
        db.session.commit()
        subs.change_plan(school, internal, None, "back")
        db.session.commit()
        assert SchoolModuleOverride.query.filter_by(school_id=A).count() == 0
        db.session.remove()


# ─── limits ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("used,warn,blocked", [(89, False, False), (90, True, False),
                                               (100, True, True), (101, True, True)])
def test_student_limit_levels(mapp, two_schools, monkeypatch, used, warn, blocked):
    """Limit 100: 89 % nothing, 90 % warning, 100 % / 101 % (after a
    downgrade) adding one more is refused."""
    from app.services import limits
    from app.services.tenancy import tenant_context
    A = two_schools["A"]["school"].id
    monkeypatch.setattr(limits, "school_usage",
                        lambda sid, with_storage=True: limits.Usage(students=used, users=0, storage_bytes=0))
    _limits(mapp, A, max_students=100)
    with mapp.app_context(), tenant_context(A):
        r = {x["kind"]: x for x in limits.limit_report(A)}["students"]
        assert r["warn"] is warn and r["full"] is (used >= 100)
        if blocked:
            with pytest.raises(limits.LimitReached) as e:
                limits.check_and_reserve(A, "students")
            assert "وصلت للحد الأقصى للباقة (100)" in str(e.value)
            assert e.value.api_body()["error"] == "limit_reached"
        else:
            limits.check_and_reserve(A, "students")
        from app.extensions import db
        db.session.rollback()
        db.session.remove()


def test_bulk_import_refused_whole(mapp, two_schools, login_as):
    """An import bigger than the remaining slots imports nothing."""
    from app.extensions import db
    from app.models import Student
    from app.services.limits import school_usage
    A = two_schools["A"]
    sid = A["school"].id
    with mapp.app_context():
        n = school_usage(sid).students
        db.session.remove()
    _limits(mapp, sid, max_students=n + 1)
    c = mapp.test_client()
    login_as(c, A["users"]["admin"], base_url=host(A))
    rows = [{"n": i, "status": "ok", "reason": None,
             "data": {"full_name": f"bulk {i}", "national_id": None}} for i in range(3)]
    with c.session_transaction(base_url=host(A)) as s:
        s["import_pending"] = {"entity": "students", "rows": rows}
    r = c.post("/platform/imports/commit", base_url=host(A), follow_redirects=True)
    assert "لم يتم استيراد أي صف".encode() in r.data and "المتبقي 1".encode() in r.data
    with mapp.app_context():
        assert Student.query.filter(Student.school_id == sid, Student.full_name.like("bulk %")).count() == 0
        db.session.remove()


def test_over_limit_school_keeps_working(mapp, two_schools, login_as):
    """After a downgrade below current usage nothing is disabled."""
    A = two_schools["A"]
    _limits(mapp, A["school"].id, max_students=0, max_users=0)
    c = mapp.test_client()
    login_as(c, A["users"]["admin"], base_url=host(A))
    assert c.get("/students", base_url=host(A), follow_redirects=True).status_code == 200


def test_staff_user_limit_web(mapp, two_schools, login_as):
    from app.extensions import db
    from app.models import Role, User
    A = two_schools["A"]
    _limits(mapp, A["school"].id, max_users=0)
    with mapp.app_context():
        rid = Role.query.filter_by(school_id=A["school"].id, name="admin").first().id
        db.session.remove()
    c = mapp.test_client()
    login_as(c, A["users"]["admin"], base_url=host(A))
    r = c.post("/admin/users/new", base_url=host(A), data={
        "username": "lim-user", "full_name": "x", "password": "long-enough-1", "role_id": rid,
        "is_active": "1"})
    assert "وصلت للحد الأقصى للباقة".encode() in r.data
    with mapp.app_context():
        assert User.query.filter_by(school_id=A["school"].id, username="lim-user").first() is None
        db.session.remove()


def test_parents_and_students_are_not_staff(mapp, two_schools):
    from app.services.limits import school_usage
    from app.extensions import db
    from app.models import Role, User
    A = two_schools["A"]["school"].id
    with mapp.app_context():
        staff = (User.query.join(Role, Role.id == User.role_id)
                 .filter(User.school_id == A, User.is_active.is_(True),
                         Role.name.notin_(("student", "parent"))).count())
        assert school_usage(A).users == staff
        db.session.remove()


def test_concurrent_last_slot_only_one_wins(mapp, two_schools):
    from app.extensions import db
    from app.models import Student
    from app.services.limits import LimitReached, check_and_reserve, school_usage
    from app.services.tenancy import tenant_context
    A = two_schools["A"]["school"].id
    with mapp.app_context():
        n = school_usage(A).students
        db.session.remove()
    _limits(mapp, A, max_students=n + 1)
    results, barrier = [], threading.Barrier(2)

    def worker(i):
        with mapp.app_context(), tenant_context(A):
            try:
                barrier.wait()
                check_and_reserve(A, "students")
                db.session.add(Student(school_id=A, permanent_code=f"RACE-{i}", full_name=f"race {i}"))
                db.session.commit()
                results.append("ok")
            except LimitReached:
                db.session.rollback()
                results.append("limit")
            finally:
                db.session.remove()

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(30)
    assert sorted(results) == ["limit", "ok"], results


def test_storage_limit_on_upload(mapp, two_schools, tmp_path, monkeypatch):
    from werkzeug.datastructures import FileStorage
    from app.services import file_storage as fs
    from app.services.tenancy import tenant_context
    monkeypatch.setitem(mapp.config, "UPLOAD_ROOT", str(tmp_path))
    A = two_schools["A"]["school"].id
    _limits(mapp, A, max_storage_mb=0)
    with mapp.test_request_context(base_url=host(two_schools["A"])), tenant_context(A):
        f = FileStorage(stream=io.BytesIO(PNG), filename="a.png")
        with pytest.raises(fs.StorageLimitRejected) as e:
            fs.save(f, "logo", A)
        assert e.value.api_body["error"] == "limit_reached" and e.value.api_body["limit"] == "storage"
    _limits(mapp, A)
    with mapp.test_request_context(base_url=host(two_schools["A"])), tenant_context(A):
        assert fs.save(FileStorage(stream=io.BytesIO(PNG), filename="a.png"), "logo", A).startswith("/files/")


# ─── console ─────────────────────────────────────────────────────────

def test_console_module_toggle_roles_and_reason(console, two_schools):
    sid = two_schools["A"]["school"].id
    owner, _ = _console_client(console, "owner")
    r = owner.post(f"/superadmin/schools/{sid}/modules", base_url=CONSOLE,
                   data={"module": "hr", "state": "off", "reason": ""}, follow_redirects=True)
    assert "السبب مطلوب".encode() in r.data
    owner.post(f"/superadmin/schools/{sid}/modules", base_url=CONSOLE,
               data={"module": "hr", "state": "off", "reason": "unpaid add-on"})
    from app.services.modules import module_enabled
    with console.app_context():
        assert module_enabled(sid, "hr") is False
        assert module_enabled(two_schools["B"]["school"].id, "hr") is True
    for role in ("support", "finance"):
        c, _ = _console_client(console, role)
        assert c.post(f"/superadmin/schools/{sid}/modules", base_url=CONSOLE,
                      data={"module": "hr", "state": "on", "reason": "x"}).status_code == 403
    sup, _ = _console_client(console, "support")
    page = sup.get(f"/superadmin/schools/{sid}", base_url=CONSOLE)
    assert page.status_code == 200 and "الموديولات".encode() in page.data
    assert b"school_module_set" not in page.data and f"/schools/{sid}/modules".encode() not in page.data


def test_console_limits_finance_can_edit(console, two_schools):
    from app.extensions import db
    from app.models import SchoolLimitOverride
    sid = two_schools["A"]["school"].id
    fin, _ = _console_client(console, "finance")
    r = fin.post(f"/superadmin/schools/{sid}/limits", base_url=CONSOLE,
                 data={"max_students": "500", "reason": "contract"})
    assert r.status_code == 302
    with console.app_context():
        assert db.session.get(SchoolLimitOverride, sid).max_students == 500
        db.session.remove()
    sup, _ = _console_client(console, "support")
    assert sup.post(f"/superadmin/schools/{sid}/limits", base_url=CONSOLE,
                    data={"max_students": "1", "reason": "x"}).status_code == 403


def test_api_module_gate_without_tenant_host(app, two_schools, monkeypatch):
    """Security review: with host resolution off, the bearer's own school
    still decides."""
    from app.services.auth_jwt import issue_token
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "off")
    A = two_schools["A"]
    _override(app, A["school"].id, "finance", False)
    with app.app_context():
        tok = issue_token(A["users"]["parent"])
    r = app.test_client().get(f"/api/parent/child/{A['student'].id}/invoices",
                              headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403 and r.json == {"error": "module_disabled", "module": "finance"}


def test_non_staff_role_names_cannot_hide_staff(mapp, two_schools, login_as):
    """Security review: a custom role named parent/student (or the parent
    role given staff permissions) would hide staff from the user limit."""
    from app.extensions import db
    from app.models import Role
    A = two_schools["A"]
    c = mapp.test_client()
    login_as(c, A["users"]["admin"], base_url=host(A))
    parent_id = A["roles"]["parent"].id
    r = c.post("/admin/roles/new", base_url=host(A),
               data={"name": "student", "name_ar": "x", "perm_students_view": "on"})
    assert "محجوز".encode() in r.data
    with mapp.app_context():
        before = db.session.get(Role, parent_id).permissions
        db.session.remove()
    r = c.post(f"/admin/roles/{parent_id}/edit", base_url=host(A),
               data={"name": "parent", "name_ar": "ولي أمر", "perm_users_add": "on",
                     "perm_portal_view": "on"})
    assert "يقتصر على صلاحيات البوابة".encode() in r.data
    with mapp.app_context():
        assert db.session.get(Role, parent_id).permissions == before
        db.session.remove()
    teacher_id = A["roles"]["teacher"].id
    r = c.post(f"/admin/roles/{teacher_id}/edit", base_url=host(A),
               data={"name": "parent", "name_ar": "x"})
    assert "محجوز".encode() in r.data
