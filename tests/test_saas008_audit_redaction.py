"""SAAS-008 — secrets never reach audit_logs, old rows get scrubbed,
and both viewers + the CSV export hide anything that slipped through."""

from __future__ import annotations

import importlib.util
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.services.audit import REDACTED, is_secret_field, redact

BCRYPT_RE = re.compile(r"\$2[abxy]\$\d{2}\$")
FAKE_HASH = "$2b$12$" + "x" * 53


# ─── Unit: redact() ──────────────────────────────────────────────────

def test_redact_plain_dict_keeps_key():
    out = redact({"password_hash": FAKE_HASH, "full_name": "Ali"})
    assert out == {"password_hash": REDACTED, "full_name": "Ali"}


def test_redact_nested_and_lists():
    out = redact({"a": {"smtp_password_encrypted": "zzz"},
                  "b": [{"api_token": "t"}, {"phone": "050"}]})
    assert out == {"a": {"smtp_password_encrypted": REDACTED},
                   "b": [{"api_token": REDACTED}, {"phone": "050"}]}


@pytest.mark.parametrize("name", [
    "password_hash", "PASSWORD_HASH", "Password", "new_password",
    "api_token", "API_TOKEN", "x_secret", "webhook_secret", "signing_key",
    "token", "secret",
])
def test_secret_names_detected(name):
    assert is_secret_field(name)


@pytest.mark.parametrize("name", [
    "full_name", "phone", "email", "username", "is_active",
    "failed_attempts", "keyboard_layout", "tokenized", "monkey",
])
def test_normal_names_not_detected(name):
    assert not is_secret_field(name)


def test_redact_none_is_safe():
    assert redact(None) is None
    assert redact({"password_hash": None}) == {"password_hash": REDACTED}
    assert redact({"phone": None}) == {"phone": None}


def test_redact_bcrypt_value_under_unexpected_key():
    assert redact({"note": FAKE_HASH}) == {"note": REDACTED}


def test_redact_does_not_mutate_input():
    src = {"password_hash": FAKE_HASH}
    redact(src)
    assert src["password_hash"] == FAKE_HASH


# ─── Integration: real listeners on User ─────────────────────────────

def _audit_rows(entity_id):
    from app.models import AuditLog
    return (AuditLog.query
            .filter_by(entity_type="User", entity_id=entity_id)
            .order_by(AuditLog.id).all())


def _no_bcrypt(row):
    blob = json.dumps([row.old_value, row.new_value])
    return not BCRYPT_RE.search(blob)


def test_user_create_update_delete_never_logs_hash(app, two_schools):
    from app.extensions import db
    from app.models import AuditLog, User

    A = two_schools["A"]
    with app.app_context():
        u = User(school_id=A["school"].id, role_id=A["roles"]["teacher"].id,
                 username="saas008_u", full_name="Redact Me", is_active=True)
        u.set_password("first-password-123")
        db.session.add(u); db.session.commit()
        uid = u.id
        try:
            create = _audit_rows(uid)[-1]
            assert create.action == "create"
            assert create.new_value["password_hash"] == REDACTED
            assert create.new_value["full_name"] == "Redact Me"
            assert _no_bcrypt(create)

            u.set_password("second-password-456")
            db.session.commit()
            upd = _audit_rows(uid)[-1]
            assert upd.action == "update"
            assert upd.old_value["password_hash"] == REDACTED
            assert upd.new_value["password_hash"] == REDACTED
            assert _no_bcrypt(upd)

            db.session.delete(u); db.session.commit()
            dele = _audit_rows(uid)[-1]
            assert dele.action == "delete"
            assert _no_bcrypt(dele)
            assert dele.old_value["password_hash"] == REDACTED
        finally:
            AuditLog.query.filter_by(entity_type="User", entity_id=uid).delete()
            leftover = db.session.get(User, uid)
            if leftover is not None:
                db.session.delete(leftover)
            db.session.commit()


# ─── Migration: scrubs legacy rows, deletes nothing ──────────────────

def _load_migration():
    path = next(Path(__file__).parents[1].glob(
        "migrations/versions/*_saas008_redact_audit_secrets.py"))
    spec = importlib.util.spec_from_file_location("saas008_mig", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _insert_leaky(school_id, marker, n=1):
    from app.extensions import db
    from app.models import AuditLog
    ids = []
    for i in range(n):
        res = db.session.execute(AuditLog.__table__.insert().values(
            school_id=school_id, user_id=None, action="update",
            entity_type="User", entity_id=900000 + i,
            old_value={"password_hash": FAKE_HASH, "full_name": marker},
            new_value={"password_hash": FAKE_HASH, "full_name": marker},
            created_at=datetime.now(timezone.utc),
        ))
        ids.append(res.inserted_primary_key[0])
    db.session.commit()
    return ids


def test_migration_scrubs_without_deleting(app, two_schools):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import func
    from app.extensions import db
    from app.models import AuditLog

    mig = _load_migration()
    A = two_schools["A"]
    with app.app_context():
        ids = _insert_leaky(A["school"].id, "saas008-mig", n=3)
        try:
            before = db.session.query(func.count(AuditLog.id)).scalar()
            with db.engine.begin() as conn:
                with Operations.context(MigrationContext.configure(conn)):
                    mig.upgrade()
            db.session.expire_all()
            after = db.session.query(func.count(AuditLog.id)).scalar()
            assert after == before
            for row in AuditLog.query.filter(AuditLog.id.in_(ids)):
                assert row.old_value["password_hash"] == REDACTED
                assert row.new_value["password_hash"] == REDACTED
                assert row.new_value["full_name"] == "saas008-mig"
            # Whole table: no bcrypt string survives anywhere.
            for row in AuditLog.query.yield_per(500):
                assert _no_bcrypt(row), row.id
        finally:
            AuditLog.query.filter(AuditLog.id.in_(ids)).delete(
                synchronize_session=False)
            db.session.commit()


# ─── Viewers + CSV export ────────────────────────────────────────────

@pytest.fixture
def leaky_rows(app, two_schools):
    from app.extensions import db
    from app.models import AuditLog, Role
    A = two_schools["A"]
    role_id = A["roles"]["admin"].id

    def _set_perms(perms):
        role = db.session.get(Role, role_id)
        assert role is not None
        role.permissions = perms
        db.session.commit()

    with app.app_context():
        own = _insert_leaky(A["school"].id, "saas008-own")
        orphan = _insert_leaky(None, "saas008-orphan")
        _set_perms({"users": ["view"], "platform_admin": ["view"]})
        db.session.remove()
    # two_schools yields inside its own app context, which test-client
    # requests reuse; drop its cached Role so requests see the new perms.
    db.session.expire_all()
    yield A
    with app.app_context():
        AuditLog.query.filter(AuditLog.id.in_(own + orphan)).delete(
            synchronize_session=False)
        _set_perms({})
        db.session.remove()


@pytest.mark.parametrize("path", [
    "/admin/audit",
    "/platform/audit-log",
    "/platform/audit-log/export.csv",
])
def test_viewers_hide_legacy_hash(app, leaky_rows, login_as, path):
    A = leaky_rows
    host = f"http://{A['school'].slug}.manasety.ai"
    with app.test_client() as c:
        login_as(c, A["users"]["admin"], base_url=host)
        r = c.get(path, base_url=host)
        assert r.status_code == 200, r.status_code
        body = r.get_data(as_text=True)
        assert FAKE_HASH not in body
        assert not BCRYPT_RE.search(body)


def test_admin_viewer_hides_null_school_rows(app, leaky_rows, login_as):
    A = leaky_rows
    host = f"http://{A['school'].slug}.manasety.ai"
    with app.test_client() as c:
        login_as(c, A["users"]["admin"], base_url=host)
        body = c.get("/admin/audit", base_url=host).get_data(as_text=True)
        assert "saas008-own" in body
        assert "saas008-orphan" not in body


@pytest.mark.parametrize("path", [
    "/admin/audit",
    "/platform/audit-log",
    "/platform/audit-log/export.csv",
])
def test_viewers_forbidden_without_permission(app, leaky_rows, login_as, path):
    A = leaky_rows
    host = f"http://{A['school'].slug}.manasety.ai"
    with app.test_client() as c:
        login_as(c, A["users"]["teacher"], base_url=host)
        assert c.get(path, base_url=host).status_code == 403


def test_password_change_still_visible_in_diff():
    from app.blueprints.platform.audit_viewer import _compute_diff
    old = redact({"password_hash": FAKE_HASH})
    new = redact({"password_hash": FAKE_HASH + "y", "full_name": "x"})
    assert "password_hash" in _compute_diff(old, new)
