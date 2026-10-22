"""SAAS-047 — the school owner's backup page: who can reach it, the
request limits, the queue, retention, the protected download, the
console view / policy, and isolation (the id matrix is in test_saas002)."""

from __future__ import annotations

import re

import pytest

from isolation_harness import host
from test_saas026_subscriptions import CONSOLE, _console_client, console  # noqa: F401

PASS = "a long enough passphrase"
ACCOUNT_PASSWORD = "test-password-12345"     # the two_schools fixture's account password


@pytest.fixture
def bapp(app, monkeypatch, tmp_path):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setitem(app.config, "UPLOAD_ROOT", str(tmp_path / "uploads"))
    monkeypatch.setitem(app.config, "SCHOOL_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setitem(app.config, "SCHOOL_BACKUP_MIN_FREE_MB", 1)
    return app


@pytest.fixture(autouse=True)
def _clear_policy(app):
    """The policy is a platform setting keyed by school id: no test
    school's policy may outlive the test."""
    yield
    from app.extensions import db
    from app.models import PlatformSetting
    from app.services.school_backups import POLICY_KEY
    with app.app_context():
        PlatformSetting.query.filter_by(key=POLICY_KEY).delete()
        db.session.commit()
        db.session.remove()


def _client(app, login_as, bundle, role="admin"):
    c = app.test_client()
    login_as(c, bundle["users"][role], base_url=host(bundle))
    return c


def _fresh(app, bundle):
    """Drop the seeded placeholder rows: these tests make real packages."""
    from app.extensions import db
    from app.models import SchoolBackup
    with app.app_context():
        SchoolBackup.query.filter_by(school_id=bundle["school"].id).delete()
        db.session.commit()
        db.session.remove()


def _run(app):
    from app.extensions import db
    from app.services import school_backups as svc
    with app.app_context():
        n = svc.run_queue()
        db.session.remove()
    return n


def _rows(app, bundle):
    from app.extensions import db
    from app.models import SchoolBackup
    with app.app_context():
        out = [(b.id, b.status, b.file_name) for b in
               SchoolBackup.query.filter_by(school_id=bundle["school"].id).order_by(SchoolBackup.id)]
        db.session.remove()
    return out


# ─── who ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("role", ["teacher", "student", "parent"])
def test_only_the_school_owner_reaches_the_page(bapp, world, login_as, role):
    A = world["A"]
    c = _client(bapp, login_as, A, role)
    bid = A["backup"]
    for method, url in [("GET", "/admin/backups"), ("POST", "/admin/backups/new"),
                        ("GET", f"/admin/backups/{bid}/status.json"),
                        ("POST", f"/admin/backups/{bid}/delete"),
                        ("POST", f"/admin/backups/{bid}/download")]:
        r = c.open(url, method=method, base_url=host(A))
        assert r.status_code == 403, (role, url, r.status_code)
    assert len(_rows(bapp, A)) == 1


def test_owner_sees_the_page_with_own_rows_only(bapp, world, login_as):
    A, B = world["A"], world["B"]
    r = _client(bapp, login_as, A).get("/admin/backups", base_url=host(A))
    body = r.get_data(as_text=True)
    assert r.status_code == 200 and "النسخ الاحتياطي" in body
    assert not [m for m in B["markers"] if m in body]


# ─── request + queue ────────────────────────────────────────────────

def test_request_runs_from_the_queue_and_notifies_in_app(bapp, world, login_as):
    from app.extensions import db
    from app.models import AuditLog, NotificationLog, SchoolBackup
    from app.services import school_backup as engine
    A = world["A"]
    _fresh(bapp, A)
    c = _client(bapp, login_as, A)
    assert c.post("/admin/backups/new", base_url=host(A)).status_code == 302
    assert [s for _, s, _ in _rows(bapp, A)] == ["pending"]
    # a second one while the first is pending: refused
    c.post("/admin/backups/new", base_url=host(A))
    assert len(_rows(bapp, A)) == 1
    assert _run(bapp) == 1
    (bid, status, name), = _rows(bapp, A)
    assert status == "succeeded" and name.endswith(".tar.gz")
    st = c.get(f"/admin/backups/{bid}/status.json", base_url=host(A)).get_json()
    assert st["status"] == "succeeded" and st["progress"] == 100
    with bapp.app_context():
        path = engine.backups_dir(A["school"].id) / name
        assert engine.verify_package(path, expect_school_id=A["school"].id).ok
        n = NotificationLog.query.filter_by(school_id=A["school"].id, kind="school_backup").one()
        assert n.target_email is None and n.target_phone is None          # in-app only
        acts = {a.action for a in AuditLog.query.filter_by(entity_type="SchoolBackup", entity_id=bid)}
        assert {"backup_create", "backup_succeeded"} <= acts
        assert db.session.get(SchoolBackup, bid).requested_by_user_id == A["users"]["admin"].id
        db.session.remove()


def test_daily_limit_disabled_feature_and_low_disk(bapp, world, login_as, monkeypatch):
    from app.services import school_backups as svc
    A = world["A"]
    _fresh(bapp, A)
    c = _client(bapp, login_as, A)
    for _ in range(svc.DAILY_LIMIT):
        c.post("/admin/backups/new", base_url=host(A))
        _run(bapp)
    assert len(_rows(bapp, A)) == svc.DAILY_LIMIT
    r = c.post("/admin/backups/new", base_url=host(A), follow_redirects=True)
    assert "الحد الأقصى" in r.get_data(as_text=True)
    assert len(_rows(bapp, A)) == svc.DAILY_LIMIT
    _fresh(bapp, A)
    monkeypatch.setattr(svc, "disk_ok", lambda: False)
    r = c.post("/admin/backups/new", base_url=host(A), follow_redirects=True)
    assert "المساحة" in r.get_data(as_text=True) and _rows(bapp, A) == []
    monkeypatch.setattr(svc, "policy", lambda sid: {"enabled": False, "keep": 5})
    r = c.post("/admin/backups/new", base_url=host(A), follow_redirects=True)
    assert "مقفول" in r.get_data(as_text=True) and _rows(bapp, A) == []


def test_retention_keeps_the_newest(bapp, world, login_as, monkeypatch):
    from app.services import school_backup as engine
    from app.services import school_backups as svc
    A = world["A"]
    _fresh(bapp, A)
    monkeypatch.setattr(svc, "DAILY_LIMIT", 10)
    real = svc.policy
    monkeypatch.setattr(svc, "policy", lambda sid: {**real(sid), "keep": 2})
    c = _client(bapp, login_as, A)
    for _ in range(4):
        c.post("/admin/backups/new", base_url=host(A))
        _run(bapp)
    rows = _rows(bapp, A)
    assert len(rows) == 2
    with bapp.app_context():
        on_disk = sorted(p.name for p in engine.backups_dir(A["school"].id).glob("*.tar.gz"))
    assert on_disk == sorted(n for _, _, n in rows)


# ─── download ───────────────────────────────────────────────────────

def _ready(bapp, login_as, A):
    _fresh(bapp, A)
    c = _client(bapp, login_as, A)
    c.post("/admin/backups/new", base_url=host(A))
    _run(bapp)
    (bid, _, _), = _rows(bapp, A)
    return c, bid


def test_download_needs_the_account_password_and_is_encrypted(bapp, world, login_as, tmp_path):
    from app.extensions import db
    from app.models import AuditLog
    from app.services import school_backup as engine
    A = world["A"]
    c, bid = _ready(bapp, login_as, A)
    url = f"/admin/backups/{bid}/download"
    r = c.post(url, base_url=host(A), follow_redirects=True,
               data={"account_password": "wrong", "passphrase": PASS, "passphrase_confirm": PASS})
    assert "غير صحيحة" in r.get_data(as_text=True)
    r = c.post(url, base_url=host(A), follow_redirects=True,
               data={"account_password": ACCOUNT_PASSWORD, "passphrase": PASS, "passphrase_confirm": PASS + "x"})
    assert "غير مطابق" in r.get_data(as_text=True)
    r = c.post(url, base_url=host(A), follow_redirects=True,
               data={"account_password": ACCOUNT_PASSWORD, "passphrase": "short", "passphrase_confirm": "short"})
    assert "12 حرف" in r.get_data(as_text=True)
    r = c.post(url, base_url=host(A),
               data={"account_password": ACCOUNT_PASSWORD, "passphrase": PASS, "passphrase_confirm": PASS})
    assert r.status_code == 200
    link = re.search(r'href="(/admin/backups/download/[^"]+)"', r.get_data(as_text=True)).group(1)
    got = c.get(link, base_url=host(A))
    assert got.status_code == 200 and got.headers["Cache-Control"] == "no-store"
    data = got.get_data()
    got.close()
    assert data.startswith(engine.MAGIC) and PASS.encode() not in data
    out = tmp_path / "dl.mbk"
    out.write_bytes(data)
    with bapp.app_context():
        assert engine.verify_package(out, PASS, expect_school_id=A["school"].id).ok
        acts = [a.action for a in AuditLog.query.filter_by(entity_type="SchoolBackup", entity_id=bid)
                .order_by(AuditLog.id)]
        db.session.remove()
    assert "backup_download_refused" in acts and acts[-1] == "backup_downloaded"
    # single use
    assert c.get(link, base_url=host(A)).status_code == 404


def test_download_link_is_bound_to_the_user_and_expires(bapp, world, login_as, monkeypatch):
    from app.extensions import db
    from app.models import User
    A, B = world["A"], world["B"]
    c, bid = _ready(bapp, login_as, A)
    r = c.post(f"/admin/backups/{bid}/download", base_url=host(A),
               data={"account_password": ACCOUNT_PASSWORD, "passphrase": PASS, "passphrase_confirm": PASS})
    link = re.search(r'href="(/admin/backups/download/[^"]+)"', r.get_data(as_text=True)).group(1)
    # another admin of the same school
    with bapp.app_context():
        other = User(school_id=A["school"].id, role_id=A["roles"]["admin"].id, username="admin2",
                     full_name="Admin2", is_active=True)
        other.password_hash = db.session.get(User, A["users"]["admin"].id).password_hash
        db.session.add(other)
        db.session.commit()
        db.session.refresh(other)
        db.session.expunge(other)
        db.session.remove()
    c2 = bapp.test_client()
    login_as(c2, other, base_url=host(A))
    assert c2.get(link, base_url=host(A)).status_code == 404
    # B's admin, on B's host, with A's link
    cb = _client(bapp, login_as, B)
    assert cb.get(link, base_url=host(B)).status_code == 404
    # expired
    from app.services import school_backups as svc
    monkeypatch.setattr(svc, "DOWNLOAD_TTL", -1)
    assert c.get(link, base_url=host(A)).status_code == 404
    assert c.get("/admin/backups/download/not-a-token", base_url=host(A)).status_code == 404


def test_delete_removes_the_file(bapp, world, login_as):
    from app.services import school_backup as engine
    A = world["A"]
    c, bid = _ready(bapp, login_as, A)
    (_, _, name), = _rows(bapp, A)
    assert c.post(f"/admin/backups/{bid}/delete", base_url=host(A)).status_code == 302
    assert _rows(bapp, A) == []
    with bapp.app_context():
        assert not (engine.backups_dir(A["school"].id) / name).exists()


# ─── console ────────────────────────────────────────────────────────

def test_console_lists_dates_and_sizes_and_owner_sets_the_policy(console, world):
    from app.extensions import db
    from app.services import school_backups as svc
    A = world["A"]
    sid = A["school"].id
    c, _ = _console_client(console, "owner")
    page = c.get(f"/superadmin/schools/{sid}", base_url=CONSOLE)
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert "النسخ الاحتياطي للمدرسة" in body and f"Backup-{A['school'].slug}" not in body
    r = c.post(f"/superadmin/schools/{sid}/backup-policy", base_url=CONSOLE, data={"enabled": "0", "keep": "3"})
    assert r.status_code == 302
    with console.app_context():
        assert svc.policy(sid) == {"enabled": False, "keep": 3}
        db.session.remove()
    s, _ = _console_client(console, "support")
    r = s.post(f"/superadmin/schools/{sid}/backup-policy", base_url=CONSOLE, data={"enabled": "1", "keep": "9"})
    assert r.status_code in (302, 403)
    with console.app_context():
        assert svc.policy(sid) == {"enabled": False, "keep": 3}
        db.session.remove()


def test_wrong_account_passwords_lock_like_the_login(bapp, world, login_as):
    from app.extensions import db
    from app.models import User
    A = world["A"]
    c, bid = _ready(bapp, login_as, A)
    url = f"/admin/backups/{bid}/download"
    for _ in range(bapp.config["LOCKOUT_MAX_ATTEMPTS"]):
        c.post(url, base_url=host(A), data={"account_password": "wrong", "passphrase": PASS,
                                             "passphrase_confirm": PASS})
    r = c.post(url, base_url=host(A), follow_redirects=True,
               data={"account_password": ACCOUNT_PASSWORD, "passphrase": PASS, "passphrase_confirm": PASS})
    assert "مقفول" in r.get_data(as_text=True)
    with bapp.app_context():
        u = db.session.get(User, A["users"]["admin"].id)
        assert u.is_locked()
        u.locked_until, u.failed_attempts = None, 0
        db.session.commit()
        db.session.remove()


def test_prepared_downloads_are_capped(bapp, world, login_as, monkeypatch):
    from app.services import school_backup as engine
    from app.services import school_backups as svc
    A = world["A"]
    c, bid = _ready(bapp, login_as, A)
    url = f"/admin/backups/{bid}/download"
    ok = {"account_password": ACCOUNT_PASSWORD, "passphrase": PASS, "passphrase_confirm": PASS}
    for _ in range(svc.PREPARE_PER_HOUR):
        assert c.post(url, base_url=host(A), data=ok).status_code == 200
    with bapp.app_context():
        prepared = list((engine.backups_dir(A["school"].id) / "downloads").glob("*.mbk"))
    assert len(prepared) == 1                     # one prepared file per backup at a time
    r = c.post(url, base_url=host(A), data=ok, follow_redirects=True)
    assert "في الساعة" in r.get_data(as_text=True)
