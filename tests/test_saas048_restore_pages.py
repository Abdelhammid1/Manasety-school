"""SAAS-048 — the restore pages (school owner) and the console's restore
on behalf: preview → confirm (school name + password) → run → undo."""

from __future__ import annotations

import io

import pytest

from isolation_harness import host
from test_saas026_subscriptions import CONSOLE, _console_client, console  # noqa: F401

ACCOUNT_PASSWORD = "test-password-12345"     # the two_schools fixture's account password
PASS = "a long enough passphrase"


@pytest.fixture
def rapp(app, monkeypatch, tmp_path):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setitem(app.config, "UPLOAD_ROOT", str(tmp_path / "uploads"))
    monkeypatch.setitem(app.config, "SCHOOL_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setitem(app.config, "SCHOOL_BACKUP_MIN_FREE_MB", 1)
    return app


def _client(app, login_as, bundle, role="admin"):
    c = app.test_client()
    login_as(c, bundle["users"][role], base_url=host(bundle))
    return c


def _queue(app):
    from app.extensions import db
    from app.services import school_restore as sr
    with app.app_context():
        n = sr.run_queue()
        db.session.remove()
    return n


def _saved_backup(app, bundle):
    """A real package for the school's seeded backup row."""
    from app.extensions import db
    from app.models import SchoolBackup, SchoolRestore
    from app.services import school_backup as sb
    with app.app_context():
        SchoolRestore.query.filter_by(school_id=bundle["school"].id).delete()
        res = sb.export_school(bundle["school"].id)
        b = db.session.get(SchoolBackup, bundle["backup"])
        b.file_name, b.size_bytes = res.path.name, res.bytes
        db.session.commit()
        db.session.remove()
    return bundle["backup"], res.path


def _restore_row(app, rid):
    from app.extensions import db
    from app.models import SchoolRestore
    with app.app_context():
        r = db.session.get(SchoolRestore, rid)
        out = (r.status, r.error, r.modules, r.mode, r.restore_point_backup_id)
        db.session.remove()
    return out


def _latest(app, bundle):
    from app.extensions import db
    from app.models import SchoolRestore
    with app.app_context():
        r = (SchoolRestore.query.filter_by(school_id=bundle["school"].id)
             .order_by(SchoolRestore.id.desc()).first())
        rid = r.id if r else None
        db.session.remove()
    return rid


def _subject_name(app, bundle):
    from app.extensions import db
    from app.models import Subject
    with app.app_context():
        n = db.session.get(Subject, bundle["subject"].id).name
        db.session.remove()
    return n


def _rename_subject(app, bundle, name):
    from app.extensions import db
    from app.models import Subject
    with app.app_context():
        db.session.get(Subject, bundle["subject"].id).name = name
        db.session.commit()
        db.session.remove()


@pytest.mark.parametrize("role", ["teacher", "student", "parent"])
def test_only_the_owner_reaches_restore(rapp, world, login_as, role):
    A = world["A"]
    c = _client(rapp, login_as, A, role)
    rid = A["restore"]
    for method, url in [("GET", "/admin/backups/restore"), ("POST", "/admin/backups/restore/new"),
                        ("GET", f"/admin/backups/restore/{rid}"),
                        ("GET", f"/admin/backups/restore/{rid}/status.json"),
                        ("POST", f"/admin/backups/restore/{rid}/confirm"),
                        ("POST", f"/admin/backups/restore/{rid}/undo")]:
        assert c.open(url, method=method, base_url=host(A)).status_code == 403, (role, url)


def test_full_flow_preview_confirm_run_undo(rapp, world, login_as):
    A = world["A"]
    bid, _ = _saved_backup(rapp, A)
    original = _subject_name(rapp, A)
    _rename_subject(rapp, A, "Renamed-after-backup")
    c = _client(rapp, login_as, A)
    assert c.post("/admin/backups/restore/new", base_url=host(A), data={"backup_id": bid}).status_code == 302
    rid = _latest(rapp, A)
    assert _restore_row(rapp, rid)[0] == "pending_preview"
    _queue(rapp)
    assert _restore_row(rapp, rid)[0] == "previewed"
    page = c.get(f"/admin/backups/restore/{rid}", base_url=host(A)).get_data(as_text=True)
    assert "الأساسيات الأكاديمية" in page and "تأكيد الاسترجاع" in page
    url = f"/admin/backups/restore/{rid}/confirm"
    form = {"modules": ["academic"], "mode": "replace", "school_name": A["school"].name,
            "account_password": ACCOUNT_PASSWORD}
    r = c.post(url, base_url=host(A), data={**form, "school_name": "wrong name"}, follow_redirects=True)
    assert "مش مطابق" in r.get_data(as_text=True) and _restore_row(rapp, rid)[0] == "previewed"
    r = c.post(url, base_url=host(A), data={**form, "account_password": "wrong"}, follow_redirects=True)
    assert "غير صحيحة" in r.get_data(as_text=True) and _restore_row(rapp, rid)[0] == "previewed"
    assert c.post(url, base_url=host(A), data=form).status_code == 302
    status, _, modules, mode, _ = _restore_row(rapp, rid)
    assert (status, modules, mode) == ("confirmed", ["academic"], "replace")
    _queue(rapp)
    status, error, _, _, point = _restore_row(rapp, rid)
    assert status == "succeeded", error
    assert _subject_name(rapp, A) == original and point
    # undo → back to the renamed state
    r = c.post(f"/admin/backups/restore/{rid}/undo", base_url=host(A),
               data={"account_password": ACCOUNT_PASSWORD})
    assert r.status_code == 302
    uid = _latest(rapp, A)
    assert uid != rid and _restore_row(rapp, uid)[0] == "confirmed"
    _queue(rapp)
    assert _restore_row(rapp, uid)[0] == "succeeded"
    assert _subject_name(rapp, A) == "Renamed-after-backup"


def test_upload_encrypted_package_and_b_package_refused(rapp, world, login_as, tmp_path):
    from app.extensions import db
    from app.models import SchoolRestore
    from app.services import school_backup as sb
    A, B = world["A"], world["B"]
    _, path_a = _saved_backup(rapp, A)
    _, path_b = _saved_backup(rapp, B)
    enc_a, enc_b = tmp_path / "a.mbk", tmp_path / "b.mbk"
    sb.encrypt_file(path_a, enc_a, PASS)
    sb.encrypt_file(path_b, enc_b, PASS)
    c = _client(rapp, login_as, A)
    r = c.post("/admin/backups/restore/new", base_url=host(A), follow_redirects=True,
               data={"package": (io.BytesIO(enc_b.read_bytes()), "b.mbk"), "passphrase": PASS},
               content_type="multipart/form-data")
    assert "مرفوضة" in r.get_data(as_text=True)
    r = c.post("/admin/backups/restore/new", base_url=host(A), follow_redirects=True,
               data={"package": (io.BytesIO(enc_a.read_bytes()), "a.mbk"), "passphrase": "wrong passphrase!"},
               content_type="multipart/form-data")
    assert "كلمة المرور غير صحيحة" in r.get_data(as_text=True)
    with rapp.app_context():
        assert SchoolRestore.query.filter_by(school_id=A["school"].id).count() == 0
        db.session.remove()
    r = c.post("/admin/backups/restore/new", base_url=host(A),
               data={"package": (io.BytesIO(enc_a.read_bytes()), "a.mbk"), "passphrase": PASS},
               content_type="multipart/form-data")
    assert r.status_code == 302
    rid = _latest(rapp, A)
    _queue(rapp)
    assert _restore_row(rapp, rid)[0] == "previewed"


def test_console_restores_on_behalf_with_a_reason(console, world, monkeypatch, tmp_path):
    from app.extensions import db
    from app.models import PlatformAuditLog
    monkeypatch.setitem(console.config, "UPLOAD_ROOT", str(tmp_path / "uploads"))
    monkeypatch.setitem(console.config, "SCHOOL_BACKUP_DIR", str(tmp_path / "backups"))
    A = world["A"]
    bid, _ = _saved_backup(console, A)
    original = _subject_name(console, A)
    _rename_subject(console, A, "Renamed-after-backup")
    sid = A["school"].id
    s, _ = _console_client(console, "support")
    assert s.post(f"/superadmin/schools/{sid}/restore", base_url=CONSOLE,
                  data={"backup_id": bid, "reason": "طلب المدرسة"}).status_code in (302, 403)
    assert _latest(console, A) is None
    c, _ = _console_client(console, "owner")
    c.post(f"/superadmin/schools/{sid}/restore", base_url=CONSOLE, data={"backup_id": bid, "reason": ""})
    assert _latest(console, A) is None                     # reason is required
    c.post(f"/superadmin/schools/{sid}/restore", base_url=CONSOLE,
           data={"backup_id": bid, "reason": "طلب المدرسة بالتليفون"})
    rid = _latest(console, A)
    _queue(console)
    r = c.post(f"/superadmin/schools/{sid}/restore/{rid}/confirm", base_url=CONSOLE,
               data={"modules": ["academic"], "mode": "replace", "school_name": A["school"].name,
                     "reason": "طلب المدرسة بالتليفون"})
    assert r.status_code == 302 and _restore_row(console, rid)[0] == "confirmed"
    _queue(console)
    assert _restore_row(console, rid)[0] == "succeeded"
    assert _subject_name(console, A) == original
    with console.app_context():
        acts = {a.action for a in PlatformAuditLog.query.filter_by(target_school_id=sid)}
        db.session.remove()
    assert {"school_restore_requested", "school_restore_confirmed"} <= acts
