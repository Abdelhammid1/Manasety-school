"""SAAS-015 — the LMS / courses pages still open on school A's own records
after the switch to owned_or_404 (the cross-school attacks are in
test_saas002)."""

from __future__ import annotations

import pytest

from isolation_harness import build_url, host
from test_saas002_route_isolation import ROUTE_MATRIX

OWN_PAGES = sorted(
    ep for ep, e in ROUTE_MATRIX.items()
    if ep.startswith(("lms.", "courses.")) and e.methods == ("GET",)
)


@pytest.fixture
def sapp(app, monkeypatch):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    return app


def test_there_are_own_pages_to_check():
    assert len(OWN_PAGES) >= 10


@pytest.mark.parametrize("endpoint", OWN_PAGES)
def test_own_page_opens(sapp, world, login_as, endpoint):
    A, B = world["A"], world["B"]
    entry = ROUTE_MATRIX[endpoint]
    role = entry.roles[-1]
    c = sapp.test_client()
    login_as(c, A["users"][role], base_url=host(A))
    url = build_url(sapp, endpoint, entry.ids(A), host(A))
    r = c.get(url, base_url=host(A))
    assert r.status_code == 200, f"{endpoint} as {role}: {url} -> {r.status_code}"
    assert not [m for m in B["markers"] if m in r.get_data(as_text=True)]
