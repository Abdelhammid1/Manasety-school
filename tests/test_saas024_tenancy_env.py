"""SAAS-024 — tenancy hosts from the environment, and `log` mode is
observe-only for platform-host logins."""

from __future__ import annotations

import logging

import pytest

from app.config import (
    _resolve_base_domain, _resolve_legacy_hosts, _resolve_platform_hosts,
    _resolve_tenancy_hosts,
)


# ─── Env parsing ─────────────────────────────────────────────────────

def test_unset_env_keeps_current_defaults():
    base, platform, legacy = _resolve_tenancy_hosts({})
    assert base == "manasety.ai"
    assert platform == ["console.manasety.ai"]
    # SAAS-038: no legacy alias unless the environment sets one.
    assert legacy == {}


def test_empty_platform_hosts_means_none():
    assert _resolve_platform_hosts({"PLATFORM_HOSTS": ""}) == []
    assert _resolve_platform_hosts({"PLATFORM_HOSTS": " , "}) == []


def test_values_are_parsed_and_normalised():
    env = {"BASE_DOMAIN": "Example.TEST", "PLATFORM_HOSTS": "ops.example.test, admin.example.test",
           "LEGACY_HOSTS": "old.manasety.ai=demo, LMS.manasety.ai=Demo"}
    base, platform, legacy = _resolve_tenancy_hosts(env)
    assert base == "example.test"
    assert platform == ["ops.example.test", "admin.example.test"]
    assert legacy == {"old.manasety.ai": "demo", "lms.manasety.ai": "demo"}


def test_empty_legacy_hosts_means_none():
    assert _resolve_legacy_hosts({"LEGACY_HOSTS": ""}) == {}


@pytest.mark.parametrize("env, needle", [
    ({"LEGACY_HOSTS": "old.manasety.ai"}, "host=slug"),
    ({"LEGACY_HOSTS": "old.manasety.ai=-bad-"}, "not a valid slug"),
    ({"LEGACY_HOSTS": "old.manasety.ai=Has Space"}, "not a valid slug"),
    ({"LEGACY_HOSTS": "bad host!=demo"}, "not a valid host"),
    ({"PLATFORM_HOSTS": "lms.manasety.ai:8080"}, "not a valid host"),
    ({"PLATFORM_HOSTS": "https://lms.manasety.ai"}, "not a valid host"),
    ({"BASE_DOMAIN": ""}, "not a valid host"),
    ({"BASE_DOMAIN": "under_score.ai"}, "not a valid host"),
    ({"PLATFORM_HOSTS": "lms.manasety.ai", "LEGACY_HOSTS": "lms.manasety.ai=demo"},
     "both PLATFORM_HOSTS and LEGACY_HOSTS"),
])
def test_bad_values_refuse_to_boot(env, needle):
    with pytest.raises(RuntimeError, match=needle):
        _resolve_tenancy_hosts(env)


def test_base_domain_default():
    assert _resolve_base_domain({}) == "manasety.ai"


# ─── Modes × host kinds ──────────────────────────────────────────────

@pytest.fixture
def hosts_app(app, two_schools, monkeypatch):
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setitem(app.config, "PLATFORM_HOSTS", ["console.manasety.ai"])
    monkeypatch.setitem(app.config, "LEGACY_HOSTS", {"old.manasety.ai": "alpha"})
    return app


HOSTS = {
    "tenant": "http://alpha.manasety.ai",
    "platform": "http://console.manasety.ai",
    "legacy": "http://old.manasety.ai",
    "unknown": "http://nosuch.manasety.ai",
}


@pytest.mark.parametrize("mode", ["off", "log", "enforce"])
@pytest.mark.parametrize("kind", sorted(HOSTS))
def test_login_page_per_mode_and_host(hosts_app, monkeypatch, mode, kind):
    monkeypatch.setitem(hosts_app.config, "TENANT_RESOLUTION_MODE", mode)
    with hosts_app.test_client() as c:
        status = c.get("/auth/login", base_url=HOSTS[kind]).status_code
    expected = 404 if (mode == "enforce" and kind == "unknown") else 200
    assert status == expected, (mode, kind, status)


def _login(c, base_url, username, password="test-password-12345"):
    return c.post("/auth/login", base_url=base_url,
                  data={"username": username, "password": password})


def test_platform_login_in_log_mode_is_not_blocked(hosts_app, monkeypatch, caplog):
    monkeypatch.setitem(hosts_app.config, "TENANT_RESOLUTION_MODE", "log")
    with caplog.at_level(logging.WARNING):
        with hosts_app.test_client() as c:
            r = _login(c, HOSTS["platform"], "t_alpha")
    assert r.status_code == 302, r.status_code
    assert any("would reject platform login" in m for m in caplog.messages)


def test_platform_login_in_enforce_mode_is_blocked(hosts_app, monkeypatch):
    monkeypatch.setitem(hosts_app.config, "TENANT_RESOLUTION_MODE", "enforce")
    with hosts_app.test_client() as c:
        r = _login(c, HOSTS["platform"], "t_alpha")
    assert r.status_code == 401


def test_legacy_host_resolves_and_logs_in_under_enforce(hosts_app, monkeypatch):
    """The production plan: lms.manasety.ai as a legacy alias of the demo
    school, so demo users keep logging in there under enforce."""
    monkeypatch.setitem(hosts_app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(hosts_app.config, "PLATFORM_HOSTS", [])
    monkeypatch.setitem(hosts_app.config, "LEGACY_HOSTS", {"lms.manasety.ai": "alpha"})
    with hosts_app.test_client() as c:
        assert _login(c, "http://lms.manasety.ai", "t_alpha").status_code == 302
        # and a beta user can't log in through alpha's alias
    with hosts_app.test_client() as c:
        assert _login(c, "http://lms.manasety.ai", "t_beta").status_code == 401


def test_tenant_host_login_is_tenant_scoped_in_log_mode(hosts_app, monkeypatch):
    monkeypatch.setitem(hosts_app.config, "TENANT_RESOLUTION_MODE", "log")
    with hosts_app.test_client() as c:
        assert _login(c, HOSTS["tenant"], "t_beta").status_code == 401
    with hosts_app.test_client() as c:
        assert _login(c, HOSTS["tenant"], "t_alpha").status_code == 302


def test_mobile_api_on_legacy_host_under_enforce(hosts_app, monkeypatch):
    """Regression: the mobile API keeps working on a legacy alias host."""
    monkeypatch.setitem(hosts_app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(hosts_app.config, "LEGACY_HOSTS", {"lms.manasety.ai": "alpha"})
    with hosts_app.test_client() as c:
        r = c.post("/api/auth/login", base_url="http://lms.manasety.ai",
                   json={"username": "t_alpha", "password": "test-password-12345"})
    assert r.status_code == 200, (r.status_code, r.get_data(as_text=True)[:200])
