"""SAAS-007 — mobile-API JWT: tenant binding + split signing key.

Three security properties pinned here:

  1. The JWT_SIGNING_KEY is distinct from SECRET_KEY in production.
     A leak of the session key must not grant the ability to forge
     API tokens, and vice versa.

  2. A token minted for school A must not authenticate a request
     served on school B's host, even if the token itself is valid
     and the user is active.

  3. The legacy host `lms.manasety.ai` continues to work for the
     mobile apps that bake it into their configs — it resolves to
     the `demo` tenant via LEGACY_HOSTS.
"""

from __future__ import annotations

import pytest


# ─── 1. Split signing key ────────────────────────────────────────────
# Unit-test the resolver function directly. Reloading sys.modules
# contaminates the session-scoped `app` fixture for everyone else;
# testing the pure function is both faster and side-effect-free.

def test_jwt_signing_key_defaults_to_secret_in_dev(monkeypatch):
    """APP_ENV=testing allows JWT_SIGNING_KEY to fall back to
    SECRET_KEY so a single-server loopback dev setup still works
    without an extra env var."""
    monkeypatch.delenv("JWT_SIGNING_KEY", raising=False)
    import app.config as cfg
    # Call the resolver as if APP_ENV were testing.
    monkeypatch.setattr(cfg, "APP_ENV", "testing")
    key = cfg._resolve_jwt_signing_key(session_key="x" * 64)
    assert key == "x" * 64


def test_jwt_signing_key_missing_in_prod_refuses_boot(monkeypatch):
    monkeypatch.delenv("JWT_SIGNING_KEY", raising=False)
    import app.config as cfg
    monkeypatch.setattr(cfg, "APP_ENV", "production")
    with pytest.raises(RuntimeError, match="JWT_SIGNING_KEY"):
        cfg._resolve_jwt_signing_key(session_key="s" * 64)


def test_jwt_signing_key_identical_to_secret_in_prod_refuses_boot(monkeypatch):
    shared = "x" * 64
    monkeypatch.setenv("JWT_SIGNING_KEY", shared)
    import app.config as cfg
    monkeypatch.setattr(cfg, "APP_ENV", "production")
    with pytest.raises(RuntimeError, match="identical to SECRET_KEY"):
        cfg._resolve_jwt_signing_key(session_key=shared)


def test_jwt_signing_key_too_short_in_prod_refuses_boot(monkeypatch):
    monkeypatch.setenv("JWT_SIGNING_KEY", "short")
    import app.config as cfg
    monkeypatch.setattr(cfg, "APP_ENV", "production")
    with pytest.raises(RuntimeError, match="JWT_SIGNING_KEY"):
        cfg._resolve_jwt_signing_key(session_key="s" * 64)


# ─── 2. Tenant binding on /api/* ─────────────────────────────────────

def test_token_binds_school_claim(app, two_schools):
    """A freshly minted token carries the school_id of its user."""
    import jwt
    from app.services.auth_jwt import issue_token
    A = two_schools["A"]
    with app.app_context():
        tok = issue_token(A["users"]["admin"])
        payload = jwt.decode(
            tok, app.config["JWT_SIGNING_KEY"], algorithms=["HS256"],
        )
    assert payload["school"] == A["school"].id
    assert payload["school_slug"] == A["school"].slug
    assert payload["sub"] == A["users"]["admin"].id
    assert payload["iss"] == "manasety-api"


def test_api_rejects_cross_tenant_token(app, two_schools):
    """A token minted for school A, replayed against school B's host,
    is rejected with 401. The user and the token are both valid in
    isolation — only the host mismatch fails."""
    from app.services.auth_jwt import issue_token
    A = two_schools["A"]
    B = two_schools["B"]
    with app.app_context():
        token_for_a = issue_token(A["users"]["admin"])

    with app.test_client() as c:
        r = c.get(
            "/api/me",
            base_url=f"http://{B['school'].slug}.manasety.ai",
            headers={"Authorization": f"Bearer {token_for_a}"},
        )
        assert r.status_code == 401, (
            f"SAAS-007 — cross-tenant JWT replay must be rejected on "
            f"the host of school B; got {r.status_code}"
        )


def test_api_accepts_same_tenant_token(app, two_schools):
    """Baseline: a token minted for A, used on A's host, still works."""
    from app.services.auth_jwt import issue_token
    A = two_schools["A"]
    with app.app_context():
        token_for_a = issue_token(A["users"]["admin"])

    with app.test_client() as c:
        r = c.get(
            "/api/me",
            base_url=f"http://{A['school'].slug}.manasety.ai",
            headers={"Authorization": f"Bearer {token_for_a}"},
        )
        assert r.status_code != 401, (
            f"baseline — same-tenant token should authenticate; got 401."
        )


def test_token_signed_with_secret_key_fails_when_split(app, two_schools):
    """A token signed with SECRET_KEY (not JWT_SIGNING_KEY) must fail
    verification when the two keys are different."""
    from datetime import datetime, timedelta
    import jwt
    A = two_schools["A"]
    original = app.config["JWT_SIGNING_KEY"]
    try:
        app.config["JWT_SIGNING_KEY"] = "x" * 64  # distinct from SECRET_KEY
        payload = {
            "sub": A["users"]["admin"].id,
            "school": A["school"].id,
            "school_slug": A["school"].slug,
            "exp": datetime.utcnow() + timedelta(hours=1),
            "iat": datetime.utcnow(),
            "iss": "manasety-api",
        }
        bad_token = jwt.encode(payload, app.config["SECRET_KEY"], algorithm="HS256")
        with app.test_client() as c:
            r = c.get(
                "/api/me",
                base_url=f"http://{A['school'].slug}.manasety.ai",
                headers={"Authorization": f"Bearer {bad_token}"},
            )
            assert r.status_code == 401, (
                f"SAAS-007 — a token signed with SECRET_KEY instead of "
                f"JWT_SIGNING_KEY must be rejected; got {r.status_code}"
            )
    finally:
        app.config["JWT_SIGNING_KEY"] = original


# ─── 3. Legacy host stays live ───────────────────────────────────────

def test_legacy_school_host_resolves_to_demo(app):
    """lms.manasety.ai must stay mapped to the `demo` tenant so
    mobile apps that hardcode the URL keep working. If the demo
    tenant doesn't exist in the test DB that's fine — the mapping
    itself (resolver reason=legacy_map) is what we assert."""
    from app.services.tenancy import resolve_host
    # Must run inside an app context to read config.
    with app.app_context():
        r = resolve_host("lms.manasety.ai")
    # Either we hit demo (reason starts with legacy_map) OR demo
    # isn't present and we end at the "unknown" branch with the
    # same reason prefix. In both cases the mapping worked.
    assert r.reason.startswith("legacy_map"), (
        f"legacy host mapping dropped — got reason={r.reason!r} "
        f"kind={r.kind!r}"
    )
