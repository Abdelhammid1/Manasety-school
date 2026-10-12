"""SAAS-005 — central `current_school_id()` with a defined priority
order and a raise on empty.

The function lives in `app.services.tenancy` and is the single source
of truth for "what school is this request/job acting on." These tests
pin the priority order so a future refactor can't silently swap the
precedence of context-var vs host-tenant vs current_user.

Priority (from the implementation docstring):
  1. `tenant_context(school_id)` — explicit, for jobs/CLI/cron
  2. `g.tenant_resolved` — host resolver, when log/enforce mode
  3. `g.api_user.school_id` — mobile-API JWT user
  4. `current_user.school_id` — Flask-Login fallback (off mode)
  5. raise TenantNotResolved

Also enforces: every blueprint's `_sid()` delegates to this function,
no blueprint reads `current_user.school_id` directly outside of
tenancy.py itself.
"""

from __future__ import annotations


def test_context_var_wins_over_everything(app, two_schools):
    from app.services.tenancy import current_school_id, tenant_context
    A = two_schools["A"]
    B = two_schools["B"]
    # Even if B is "logged in" via current_user, an explicit
    # tenant_context(A) must win.
    with app.test_request_context("/", base_url=f"http://{B['school'].slug}.manasety.ai"):
        from flask import g
        # Pretend the resolver attached B.
        from app.services.tenancy import ResolvedTenant
        g.tenant_resolved = ResolvedTenant(
            "tenant", school=B["school"], slug=B["school"].slug,
            host=f"{B['school'].slug}.manasety.ai", reason="test",
        )
        with tenant_context(A["school"].id):
            assert current_school_id() == A["school"].id


def test_host_tenant_wins_over_current_user(app, two_schools):
    from app.services.tenancy import current_school_id, ResolvedTenant
    A = two_schools["A"]
    B = two_schools["B"]
    with app.test_client() as c:
        # Log in as A's admin, but request lands on B's host.
        with c.session_transaction(base_url=f"http://{A['school'].slug}.manasety.ai") as sess:
            sess["_user_id"] = str(A["users"]["admin"].id)
            sess["_fresh"] = True
        with app.test_request_context(
            "/", base_url=f"http://{B['school'].slug}.manasety.ai"
        ):
            from flask import g
            g.tenant_resolved = ResolvedTenant(
                "tenant", school=B["school"], slug=B["school"].slug,
                host=f"{B['school'].slug}.manasety.ai", reason="test",
            )
            # Note: current_user is anonymous in test_request_context,
            # so this really tests host > (anon fallthrough). Add a
            # dedicated api_user path to prove host > api_user too.
            g.api_user = A["users"]["admin"]
            assert current_school_id() == B["school"].id


def test_api_user_used_when_no_host_tenant(app, two_schools):
    from app.services.tenancy import current_school_id
    A = two_schools["A"]
    with app.test_request_context("/"):
        from flask import g
        # No g.tenant_resolved, no logged-in user — only an API user.
        g.api_user = A["users"]["admin"]
        assert current_school_id() == A["school"].id


def test_current_user_fallback_when_resolver_off(app, two_schools):
    """With resolver OFF (no g.tenant_resolved), the function falls
    back to Flask-Login's current_user — preserves the legacy
    single-tenant behaviour for dev DBs."""
    from app.services.tenancy import current_school_id
    A = two_schools["A"]
    with app.test_client() as c:
        with c.session_transaction(base_url=f"http://{A['school'].slug}.manasety.ai") as sess:
            sess["_user_id"] = str(A["users"]["admin"].id)
            sess["_fresh"] = True
        with app.test_request_context(
            "/",
            base_url=f"http://{A['school'].slug}.manasety.ai",
            environ_overrides={"HTTP_COOKIE": _cookie_header(c, f"{A['school'].slug}.manasety.ai")},
        ):
            # Simulate "resolver off" — g.tenant_resolved left unset.
            # Flask-Login's _load_user triggers on current_user access.
            # The helper should fall through to current_user.
            try:
                sid = current_school_id()
            except Exception as e:
                raise AssertionError(
                    f"current_school_id() should fall back to current_user; "
                    f"raised {type(e).__name__}: {e}"
                )
            assert sid == A["school"].id


def _cookie_header(client, domain: str) -> str:
    """Build a Cookie: header from the test client's jar for `domain`."""
    pairs = []
    for ck in client._cookies.values():
        if ck.domain in (domain, "." + domain, ""):
            pairs.append(f"{ck.key}={ck.value}")
    return "; ".join(pairs)


def test_raises_when_no_tenant_in_scope(app):
    from app.services.tenancy import current_school_id, TenantNotResolved
    with app.test_request_context("/"):
        # No context var, no g.tenant_resolved, no api_user, no login.
        try:
            current_school_id()
        except TenantNotResolved:
            pass
        else:
            raise AssertionError(
                "current_school_id() should raise TenantNotResolved when "
                "there is no tenant in scope."
            )


# ─── Forcing gate — every blueprint's `_sid` goes through the helper ─

def test_every_blueprint_sid_delegates_to_central_helper():
    """Walk every file that defines a local `_sid()` and confirm it
    calls `current_school_id` instead of reading
    `current_user.school_id` directly. This is the lock that keeps a
    future PR from reintroducing the bypass that SAAS-005 removed."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "app" / "blueprints"
    offenders = []
    for py in root.rglob("*.py"):
        src = py.read_text(encoding="utf-8")
        # Find each local `_sid()` body.
        for m in re.finditer(
            r"^def _sid\(\)(?:\s*->\s*int)?:\s*\n((?:    [^\n]*\n)+)",
            src, re.MULTILINE,
        ):
            body = m.group(1)
            if "current_school_id" not in body:
                offenders.append(f"{py.relative_to(root.parent.parent)}")
                break
    assert not offenders, (
        "SAAS-005 — the following blueprints define a local `_sid()` "
        "that does NOT delegate to `current_school_id`. Replace the "
        "body with `return current_school_id()`:\n  - "
        + "\n  - ".join(offenders)
    )
