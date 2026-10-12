"""SAAS-001 — SECRET_KEY mandatory in production + explicit cookie flags.

Tests import `app.config` under a controlled os.environ. load_dotenv()
runs at config module import and would re-inject SECRET_KEY from the
project's .env, so we also patch it to a no-op for the duration of
the import. We never print the actual key value — the error message
must only name the problem.
"""

from __future__ import annotations

import importlib
import os
import sys
from unittest.mock import patch

import pytest


# ─── Helpers ──────────────────────────────────────────────────────────

def _reload_config(**env):
    """Reload `app.config` with a scoped environment. Returns the
    fresh module (which raises at import time on hard failures).

    `load_dotenv` is monkeypatched to a no-op so the project's .env
    can't silently reinject SECRET_KEY into the test environment."""
    for mod in ("app.config", "app"):
        sys.modules.pop(mod, None)
    old = {k: os.environ.get(k) for k in ("APP_ENV", "SECRET_KEY", "JWT_SIGNING_KEY")}
    try:
        for k, v in env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        # SAAS-007 — a production boot now needs JWT_SIGNING_KEY as
        # well. These SAAS-001 tests only probe SECRET_KEY rules, so
        # inject a passing JWT key unless the test overrode it.
        if "JWT_SIGNING_KEY" not in env and os.environ.get("APP_ENV") not in ("development", "testing"):
            os.environ["JWT_SIGNING_KEY"] = "j" * 48
        with patch("dotenv.load_dotenv", lambda *a, **k: False):
            return importlib.import_module("app.config")
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        for mod in ("app.config", "app"):
            sys.modules.pop(mod, None)


def _make_app_with(**env):
    """Reload Config with scoped env then build the Flask app.
    Same load_dotenv guard as _reload_config."""
    for mod in ("app.config", "app"):
        sys.modules.pop(mod, None)
    old = {k: os.environ.get(k) for k in ("APP_ENV", "SECRET_KEY", "JWT_SIGNING_KEY")}
    try:
        for k, v in env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        # SAAS-007 — fulfill the JWT key requirement for prod boots.
        if "JWT_SIGNING_KEY" not in env and os.environ.get("APP_ENV") not in ("development", "testing"):
            os.environ["JWT_SIGNING_KEY"] = "j" * 48
        with patch("dotenv.load_dotenv", lambda *a, **k: False):
            app_mod = importlib.import_module("app")
            return app_mod.create_app()
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        for mod in ("app.config", "app"):
            sys.modules.pop(mod, None)


# ─── SECRET_KEY validation (unit) ─────────────────────────────────────

def test_production_missing_secret_key_raises():
    with pytest.raises(RuntimeError) as e:
        _reload_config(APP_ENV="production", SECRET_KEY=None)
    msg = str(e.value)
    assert "SECRET_KEY" in msg
    # Must not leak any key material
    assert "dev-secret-change-me" not in msg


def test_production_default_secret_key_raises():
    with pytest.raises(RuntimeError) as e:
        _reload_config(APP_ENV="production", SECRET_KEY="dev-secret-change-me")
    assert "dev-secret-change-me" not in str(e.value)


def test_production_short_secret_key_raises():
    short = "x" * 10
    with pytest.raises(RuntimeError) as e:
        _reload_config(APP_ENV="production", SECRET_KEY=short)
    # Error names the problem but doesn't echo the key itself
    assert short not in str(e.value)
    assert "32" in str(e.value)


def test_production_valid_secret_key_boots():
    mod = _reload_config(
        APP_ENV="production",
        SECRET_KEY="a" * 48,
    )
    assert mod.Config.SECRET_KEY == "a" * 48


def test_development_missing_key_uses_fallback():
    mod = _reload_config(APP_ENV="development", SECRET_KEY=None)
    assert mod.Config.SECRET_KEY == "dev-secret-change-me"


def test_testing_missing_key_uses_fallback():
    mod = _reload_config(APP_ENV="testing", SECRET_KEY=None)
    assert mod.Config.SECRET_KEY == "dev-secret-change-me"


# ─── Cookie flags (integration via Flask test client) ─────────────────

def test_cookies_prod_are_hardened():
    app = _make_app_with(APP_ENV="production", SECRET_KEY="z" * 48)
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert app.config["REMEMBER_COOKIE_HTTPONLY"] is True
    assert app.config["REMEMBER_COOKIE_SAMESITE"] == "Lax"
    assert app.config["REMEMBER_COOKIE_SECURE"] is True
    # D5 — host-only, must not be set
    assert app.config.get("SESSION_COOKIE_DOMAIN") in (None, "")
    assert app.config.get("SERVER_NAME") in (None, "")


def test_cookies_dev_drop_secure():
    app = _make_app_with(APP_ENV="development", SECRET_KEY=None)
    # Secure flag off in dev so http://localhost sends the cookie
    assert app.config["SESSION_COOKIE_SECURE"] is False
    assert app.config["REMEMBER_COOKIE_SECURE"] is False
    # The other flags must stay on even in dev
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"


def test_login_sets_hardened_session_cookie():
    """End-to-end: hit /auth/login (GET) over HTTPS in production
    mode and check the Set-Cookie header carries the flags the
    ticket demands. Flask skips `Secure` on non-TLS requests even
    when the config has it on, so the test request must be https."""
    app = _make_app_with(APP_ENV="production", SECRET_KEY="q" * 48)
    with app.test_client() as c:
        r = c.get("/auth/login", base_url="https://demo.manasety.ai")
        set_cookie = r.headers.getlist("Set-Cookie")
        session_lines = [s for s in set_cookie if s.lower().startswith("session=")]
        assert session_lines, "no session cookie emitted on login GET"
        header = session_lines[0]
        assert "HttpOnly" in header
        assert "Secure" in header
        assert "SameSite=Lax" in header
        # D5 — no Domain=
        assert "Domain=" not in header
