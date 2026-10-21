"""SAAS-004 — host-based tenant resolution + TenantContext.

Three slices:
1. `normalize_host` as a pure string transform (table-driven).
2. `resolve_host` end-to-end with a live Flask app + DB fixture
   that seeds two schools (demo active, susp suspended, arch archived).
3. The `before_request` hook in all three modes (off / log / enforce).
4. TenantContext ContextVar isolation across threads.
"""

from __future__ import annotations

import os
import sys
import threading
from contextvars import copy_context

import pytest


# ─── Isolate from the project's load_dotenv like SAAS-001 did ────────

def _fresh_app(**env):
    """Return a brand-new Flask app whose config was imported under
    the given env. We let load_dotenv run so DATABASE_URL etc. load,
    but we manually set APP_ENV / SECRET_KEY in os.environ so dotenv's
    `override=False` leaves our values alone."""
    for mod in ("app.config", "app"):
        sys.modules.pop(mod, None)
    keys = list(env.keys()) + ["APP_ENV"]
    old = {k: os.environ.get(k) for k in keys}
    try:
        for k, v in env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        import importlib
        app_mod = importlib.import_module("app")
        app = app_mod.create_app()
        # Apply tenancy config AFTER create_app so tests can set them
        # per-case without constructing a dedicated Config subclass.
        app.config["BASE_DOMAIN"] = env.get("BASE_DOMAIN", "manasety.ai")
        app.config["PLATFORM_HOSTS"] = env.get(
            "PLATFORM_HOSTS", ["console.manasety.ai"],
        )
        app.config["LEGACY_HOSTS"] = env.get(
            "LEGACY_HOSTS", {"lms.manasety.ai": "demo"},
        )
        app.config["TENANT_RESOLUTION_MODE"] = env.get(
            "TENANT_RESOLUTION_MODE", "off",
        )
        return app
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ─── 1. normalize_host ───────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("demo.manasety.ai",         "demo.manasety.ai"),
    ("DEMO.Manasety.AI",         "demo.manasety.ai"),
    ("demo.manasety.ai:443",     "demo.manasety.ai"),
    ("demo.manasety.ai.",        "demo.manasety.ai"),   # trailing dot
    ("  demo.manasety.ai  ",     "demo.manasety.ai"),
    ("",                         ""),
    (None,                       ""),
    (":443",                     ""),                   # port only
    ("host:not-a-number",        ""),
    ("[::1]",                    ""),                   # IPv6 literal
    ("evil ai",                  ""),                   # space
    ("中文.manasety.ai",          ""),                   # non-ASCII
])
def test_normalize_host(raw, expected):
    app = _fresh_app(APP_ENV="testing", SECRET_KEY=None)
    with app.app_context():
        from app.services.tenancy import normalize_host
        assert normalize_host(raw) == expected


# ─── 2. resolve_host — uses the DB fixture ───────────────────────────

@pytest.fixture
def app_with_schools():
    """Seed three schools: demo (active), susp (suspended), arch
    (archived). Seeds `demo` too — the old fixture relied on the
    dev SQLite having one, which is no longer the case after
    SAAS-002's DB guard forced tests onto a throwaway test DB."""
    app = _fresh_app(APP_ENV="testing", SECRET_KEY=None)
    with app.app_context():
        from app.extensions import db
        from app.models import School
        extras = []
        for slug, status in [("demo", "active"), ("susp", "suspended"), ("arch", "archived")]:
            if not School.query.filter_by(slug=slug).first():
                s = School(
                    code=f"TEST-{slug}", name=f"test-{slug}",
                    slug=slug, status=status,
                )
                db.session.add(s)
                db.session.flush()
                if status == "active":
                    from world import give_subscription
                    give_subscription(s)
                extras.append(s)
        db.session.commit()
        ids = [s.id for s in extras]
        yield app
        from world import purge_schools
        purge_schools(ids)
        db.session.remove()


def test_resolve_tenant_host(app_with_schools):
    with app_with_schools.app_context():
        from app.services.tenancy import resolve_host
        r = resolve_host("demo.manasety.ai")
        assert r.kind == "tenant"
        assert r.slug == "demo"
        assert r.school is not None


def test_resolve_platform_host(app_with_schools):
    with app_with_schools.app_context():
        from app.services.tenancy import resolve_host
        r = resolve_host("console.manasety.ai")
        assert r.kind == "platform"
        assert r.school is None
        assert r.is_platform is True


def test_resolve_unknown_slug(app_with_schools):
    with app_with_schools.app_context():
        from app.services.tenancy import resolve_host
        r = resolve_host("ghost.manasety.ai")
        assert r.kind == "unknown"


def test_resolve_suspended_school(app_with_schools):
    with app_with_schools.app_context():
        from app.services.tenancy import resolve_host
        r = resolve_host("susp.manasety.ai")
        assert r.kind == "suspended"
        assert r.school is not None


def test_resolve_archived_school_looks_like_unknown(app_with_schools):
    """Never disclose whether a slug exists but is archived."""
    with app_with_schools.app_context():
        from app.services.tenancy import resolve_host
        r = resolve_host("arch.manasety.ai")
        assert r.kind == "unknown"


def test_resolve_fails_closed_on_unknown_status(app_with_schools):
    """Security review (2026-10-12) — if `status` ever drifts to a
    value the resolver doesn't recognise (future `trial`, half-
    applied migration, hand-edited row), it MUST NOT be treated as
    active. Fail closed and look like `unknown`."""
    with app_with_schools.app_context():
        from app.extensions import db
        from app.models import School
        from app.services.tenancy import resolve_host
        s = School.query.filter_by(slug="susp").first()
        original = s.status
        try:
            s.status = "trial"            # a value never defined in SCHOOL_STATUSES
            db.session.commit()
            r = resolve_host("susp.manasety.ai")
            assert r.kind == "unknown"    # fail-closed, not "tenant"
            assert r.school is None
        finally:
            s.status = original
            db.session.commit()


def test_resolve_rejects_multi_level_subdomain(app_with_schools):
    with app_with_schools.app_context():
        from app.services.tenancy import resolve_host
        r = resolve_host("a.b.manasety.ai")
        assert r.kind == "unknown"


def test_resolve_rejects_spoof_suffix(app_with_schools):
    """`demo.manasety.ai.evil.com` must NOT match BASE_DOMAIN."""
    with app_with_schools.app_context():
        from app.services.tenancy import resolve_host
        r = resolve_host("demo.manasety.ai.evil.com")
        assert r.kind == "unknown"


def test_legacy_host_maps_to_demo(app_with_schools):
    with app_with_schools.app_context():
        from app.services.tenancy import resolve_host
        r = resolve_host("lms.manasety.ai")
        assert r.kind == "tenant"
        assert r.slug == "demo"
        assert r.reason.startswith("legacy_map")


# ─── 3. Modes (off / log / enforce) ──────────────────────────────────

def test_mode_off_passes_everything_through():
    app = _fresh_app(
        APP_ENV="testing", SECRET_KEY=None,
        TENANT_RESOLUTION_MODE="off",
    )
    with app.test_client() as c:
        r = c.get("/auth/login", base_url="https://ghost.manasety.ai")
        # Login page renders despite unknown host.
        assert r.status_code == 200


def test_mode_log_does_not_block():
    app = _fresh_app(
        APP_ENV="testing", SECRET_KEY=None,
        TENANT_RESOLUTION_MODE="log",
    )
    with app.test_client() as c:
        r = c.get("/auth/login", base_url="https://ghost.manasety.ai")
        assert r.status_code == 200  # logs but doesn't 404


def test_mode_enforce_404s_unknown():
    app = _fresh_app(
        APP_ENV="testing", SECRET_KEY=None,
        TENANT_RESOLUTION_MODE="enforce",
    )
    with app.test_client() as c:
        r = c.get("/auth/login", base_url="https://ghost.manasety.ai")
        assert r.status_code == 404


def test_mode_enforce_404s_malformed():
    app = _fresh_app(
        APP_ENV="testing", SECRET_KEY=None,
        TENANT_RESOLUTION_MODE="enforce",
    )
    with app.test_client() as c:
        r = c.get("/auth/login", base_url="https://evil.com")
        assert r.status_code == 404


def test_mode_enforce_lets_tenant_through(app_with_schools):
    """Dev-sqlite demo tenant must pass under enforce."""
    app_with_schools.config["TENANT_RESOLUTION_MODE"] = "enforce"
    with app_with_schools.test_client() as c:
        r = c.get("/auth/login", base_url="https://demo.manasety.ai")
        assert r.status_code == 200


def test_mode_enforce_403s_suspended(app_with_schools):
    app_with_schools.config["TENANT_RESOLUTION_MODE"] = "enforce"
    with app_with_schools.test_client() as c:
        r = c.get("/auth/login", base_url="https://susp.manasety.ai")
        assert r.status_code == 403
        assert b"\xd9\x85\xd9\x88\xd9\x82\xd9\x88\xd9\x81" in r.data  # "موقوف"


# ─── 4. TenantContext ─────────────────────────────────────────────────

def test_tenant_context_sets_and_restores():
    app = _fresh_app(APP_ENV="testing", SECRET_KEY=None)
    with app.app_context():
        from app.services.tenancy import (
            tenant_context, current_tenant_id, TenantNotResolved,
        )
        with pytest.raises(TenantNotResolved):
            current_tenant_id()
        with tenant_context(7):
            assert current_tenant_id() == 7
            with tenant_context(42):
                assert current_tenant_id() == 42
            assert current_tenant_id() == 7
        with pytest.raises(TenantNotResolved):
            current_tenant_id()


def test_tenant_context_isolates_across_threads():
    """One thread's `tenant_context(1)` must NOT leak into another
    thread's `tenant_context(2)`."""
    app = _fresh_app(APP_ENV="testing", SECRET_KEY=None)
    with app.app_context():
        from app.services.tenancy import tenant_context, current_tenant_id

        seen: dict[int, int] = {}
        barrier = threading.Barrier(2)

        def worker(tid: int) -> None:
            def run_in_ctx() -> None:
                with app.app_context():
                    with tenant_context(tid):
                        barrier.wait()  # both threads enter at once
                        seen[tid] = current_tenant_id()
            copy_context().run(run_in_ctx)

        t1 = threading.Thread(target=worker, args=(1,))
        t2 = threading.Thread(target=worker, args=(2,))
        t1.start(); t2.start()
        t1.join();  t2.join()
        assert seen == {1: 1, 2: 2}
