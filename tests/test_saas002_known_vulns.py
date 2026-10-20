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


# ─── R1 ───────────────────────────────────────────────────────────────

def test_r1_login_is_tenant_scoped(app, two_schools):
    """A `admin / <password-of-A>` login submitted on school B's host
    MUST fail. Today it succeeds because the user lookup ignores the
    requested tenant and returns whichever admin row comes first."""
    A = two_schools["A"]
    B = two_schools["B"]
    # Give A's admin a distinct password so we can tell whose it is.
    with app.app_context():
        from app.extensions import db
        from app.models import User
        a_admin = db.session.get(User, A["users"]["admin"].id)
        b_admin = db.session.get(User, B["users"]["admin"].id)
        a_admin.set_password("alpha-admin-pw-12345")
        b_admin.set_password("beta-admin-pw-12345")
        db.session.commit()

    with app.test_client() as c:
        # Request lands on school B's host but we present A's password.
        # Correct behaviour (after SAAS-006): fail — no such credential
        # on school B. Current behaviour: succeeds because the lookup
        # finds A's admin by username.
        r = c.get("/auth/login", base_url=f"http://{B['school'].slug}.manasety.ai")
        import re
        tok = re.search(
            rb'name="csrf_token" value="([^"]+)"', r.data,
        ).group(1).decode()
        resp = c.post(
            "/auth/login",
            base_url=f"http://{B['school'].slug}.manasety.ai",
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
        from app.models import User
        a_admin = db.session.get(User, A["users"]["admin"].id)
        b_admin = db.session.get(User, B["users"]["admin"].id)
        a_admin.email = shared_email
        b_admin.email = shared_email
        a_admin.set_password("alpha-admin-pw-12345")
        b_admin.set_password("beta-admin-pw-12345")
        db.session.commit()
        expected_user_id = A["users"]["admin"].id

    tenant_host = f"http://{A['school'].slug}.manasety.ai"
    with app.test_client() as c:
        r = c.get("/auth/forgot", base_url=tenant_host)
        import re
        tok_m = re.search(rb'name="csrf_token" value="([^"]+)"', r.data)
        tok = tok_m.group(1).decode() if tok_m else ""
        resp = c.post(
            "/auth/forgot",
            base_url=tenant_host,
            data={"csrf_token": tok, "channel": "email", "target": shared_email},
        )

        # Must pass base_url so the test client reads the session cookie
        # scoped to the tenant host (not the default localhost cookie jar).
        with c.session_transaction(base_url=tenant_host) as sess:
            otp_user_id = sess.get("otp_user_id")

    # Correct behaviour (post SAAS-006): the OTP must point at A's
    # user, not B's. Pre-fix: picks the first row that matches, which
    # could be either.
    assert otp_user_id == expected_user_id, (
        f"R2 fix should scope reset to tenant A's user "
        f"({expected_user_id}); got {otp_user_id}"
    )


# ─── R3 ───────────────────────────────────────────────────────────────

def test_r3_session_cookie_cannot_cross_tenants(app, two_schools, login_as):
    """Log in as school A's admin, then issue a request on school B's
    host with the same cookie. Must NOT render A's data on B's host —
    the fix either logs the user out, 401s, or at the very least
    scopes the response to B's school name (never A's)."""
    A = two_schools["A"]
    B = two_schools["B"]
    a_host = f"http://{A['school'].slug}.manasety.ai"
    b_host = f"http://{B['school'].slug}.manasety.ai"

    with app.test_client() as c:
        # Mint the session on A's host so Werkzeug stores the cookie
        # under alpha.manasety.ai. R3 then forces the SAME cookie onto
        # B's host via explicit cookie copy.
        login_as(c, A["users"]["admin"], base_url=a_host)

        # Baseline: on A's host, admin can hit /dashboard (200).
        r_on_a = c.get(
            "/dashboard",
            base_url=a_host,
            follow_redirects=False,
        )
        assert r_on_a.status_code == 200, (
            f"baseline failed — admin can't open own dashboard: "
            f"{r_on_a.status_code}"
        )

        # Replay the same session cookie against B's host. We copy the
        # cookie onto beta's host explicitly, otherwise the test client
        # would send no cookie at all (it's scoped to alpha).
        session_cookie = c.get_cookie("session", domain=f"{A['school'].slug}.manasety.ai")
        assert session_cookie is not None, "no session cookie minted on A"
        c.set_cookie(
            "session", session_cookie.value,
            domain=f"{B['school'].slug}.manasety.ai",
        )

        r_on_b = c.get(
            "/dashboard",
            base_url=b_host,
            follow_redirects=False,
        )
        # Correct behaviour (post SAAS-006): the cross-tenant kill hook
        # logs the user out and 302s them to /auth/login on B's host
        # (or 401/403 if a stricter denial is wired later). Anything
        # that renders A's dashboard HTML (200 to /dashboard) is a leak.
        assert r_on_b.status_code in (302, 401, 403), (
            f"R3 fix should log the user out or deny the request on "
            f"the foreign tenant; got {r_on_b.status_code}"
        )
        # The redirect must land on the login page, not back into any
        # authenticated surface.
        if r_on_b.status_code == 302:
            assert "/auth/login" in (r_on_b.headers.get("Location") or ""), (
                f"R3 fix should redirect to /auth/login on cross-tenant "
                f"replay; got Location={r_on_b.headers.get('Location')}"
            )
