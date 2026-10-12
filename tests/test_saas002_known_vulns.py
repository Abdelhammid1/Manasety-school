"""SAAS-002 §4.5 — Known-vulnerability tests (R1 / R2 / R3).

Each test proves a current security hole exists and is marked
`xfail(strict=True)`. When the fix lands (SAAS-006 for R1 & R2,
SAAS-007 for R3) the test flips from xfail to pass, strict=True
makes it a FAILURE, and the committer is forced to delete the
xfail marker — the hole can never silently come back.

R1  — login is not tenant-aware. Two schools can hold the same
      username; `User.query.filter_by(username=…).first()` picks
      one at random.  Fixed by SAAS-006.
R2  — OTP / password-reset flow searches by email/phone across
      every school in the DB. Fixed by SAAS-006.
R3  — a session cookie minted on school A keeps a logged-in user
      on school B. Fixed by SAAS-006 (web) and SAAS-007 (API JWT).
"""

from __future__ import annotations

import pytest


# ─── R1 ───────────────────────────────────────────────────────────────

@pytest.mark.xfail(
    strict=True,
    reason="R1 — login still filters by username alone; see SAAS-006.",
)
def test_r1_login_is_tenant_scoped(app, two_schools):
    """A `admin / <password-of-A>` login submitted on school B's host
    MUST fail. Today it succeeds because the user lookup ignores the
    requested tenant and returns whichever admin row comes first."""
    A = two_schools["A"]
    B = two_schools["B"]
    # Give A's admin a distinct password so we can tell whose it is.
    with app.app_context():
        from app.extensions import db
        A["users"]["admin"].set_password("alpha-admin-pw-12345")
        B["users"]["admin"].set_password("beta-admin-pw-12345")
        db.session.commit()

    with app.test_client() as c:
        # Request lands on school B's host but we present A's password.
        # Correct behaviour (after SAAS-006): fail — no such credential
        # on school B. Current behaviour: succeeds because the lookup
        # finds A's admin by username.
        r = c.get("/auth/login", base_url=f"https://{B['school'].slug}.manasety.ai")
        import re
        tok = re.search(
            rb'name="csrf_token" value="([^"]+)"', r.data,
        ).group(1).decode()
        resp = c.post(
            "/auth/login",
            base_url=f"https://{B['school'].slug}.manasety.ai",
            data={
                "csrf_token": tok,
                "role_hint": "admin",
                "username": "admin",
                "password": "alpha-admin-pw-12345",
            },
        )
        # Correct behaviour: 401 (bad credentials for THIS tenant).
        assert resp.status_code == 401, (
            f"R1 fix should return 401 on cross-tenant login; got {resp.status_code}"
        )


# ─── R2 ───────────────────────────────────────────────────────────────

@pytest.mark.xfail(
    strict=True,
    reason="R2 — password-reset lookup searches every school; see SAAS-006.",
)
def test_r2_password_reset_is_tenant_scoped(app, two_schools):
    """Two schools can share an email address. A `forgot` request on
    school A must NEVER send an OTP targeted at school B's user —
    not even silently."""
    A = two_schools["A"]
    B = two_schools["B"]
    # Give both schools' admins the same email, different passwords.
    shared_email = "principal@shared.test"
    with app.app_context():
        from app.extensions import db
        A["users"]["admin"].email = shared_email
        B["users"]["admin"].email = shared_email
        A["users"]["admin"].set_password("alpha-admin-pw-12345")
        B["users"]["admin"].set_password("beta-admin-pw-12345")
        db.session.commit()

    with app.test_client() as c:
        r = c.get("/auth/forgot", base_url=f"https://{A['school'].slug}.manasety.ai")
        import re
        tok_m = re.search(rb'name="csrf_token" value="([^"]+)"', r.data)
        tok = tok_m.group(1).decode() if tok_m else ""
        resp = c.post(
            "/auth/forgot",
            base_url=f"https://{A['school'].slug}.manasety.ai",
            data={"csrf_token": tok, "channel": "email", "target": shared_email},
        )

        with c.session_transaction() as sess:
            otp_user_id = sess.get("otp_user_id")

    # Correct behaviour (post SAAS-006): the OTP must point at A's
    # user, not B's. Today it picks the first row that matches, which
    # could be either.
    assert otp_user_id == A["users"]["admin"].id, (
        f"R2 fix should scope reset to tenant A's user "
        f"({A['users']['admin'].id}); got {otp_user_id}"
    )


# ─── R3 ───────────────────────────────────────────────────────────────

@pytest.mark.xfail(
    strict=True,
    reason="R3 — a session cookie from one tenant is honoured on another; "
           "see SAAS-006. Verified by checking that A's school name is "
           "NOT returned when the same cookie is replayed on B's host.",
)
def test_r3_session_cookie_cannot_cross_tenants(app, two_schools, login_as):
    """Log in as school A's admin, then issue a request on school B's
    host with the same cookie. Must NOT render A's data on B's host —
    the fix either logs the user out, 401s, or at the very least
    scopes the response to B's school name (never A's)."""
    A = two_schools["A"]
    B = two_schools["B"]
    a_name = A["school"].name
    b_slug = B["school"].slug

    with app.test_client() as c:
        login_as(c, A["users"]["admin"])

        # Baseline: on A's host the admin dashboard renders A's name.
        r_on_a = c.get(
            "/dashboard",
            base_url=f"https://{A['school'].slug}.manasety.ai",
            follow_redirects=True,
        )
        assert r_on_a.status_code == 200, (
            f"baseline failed — admin can't open own dashboard: "
            f"{r_on_a.status_code}"
        )
        assert a_name.encode() in r_on_a.data, (
            "baseline failed — A's dashboard doesn't name school A."
        )

        # Replay the same cookie against B's host.
        r_on_b = c.get(
            "/dashboard",
            base_url=f"https://{b_slug}.manasety.ai",
            follow_redirects=True,
        )
        # Correct behaviour (post SAAS-006): A's data must NOT appear
        # in a response served on B's host. Either we're logged out
        # (redirected to /auth/login) or the response is scoped to B.
        assert a_name.encode() not in r_on_b.data, (
            f"R3 fix must stop a cookie minted on {A['school'].slug} "
            f"from rendering {A['school'].slug}'s data on "
            f"{b_slug}'s host; A's name leaked into the body."
        )
