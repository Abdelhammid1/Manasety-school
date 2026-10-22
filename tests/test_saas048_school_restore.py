"""SAAS-048 — restoring a school (whole or by module) safely: the engine
(services/school_restore.py). Runs on SQLite and on PostgreSQL."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile

import pytest

from isolation_harness import host

ALL_BUT_ACCOUNTS = ["settings", "academic", "students", "attendance", "lms", "results", "schedule",
                    "finance", "hr", "messaging"]


@pytest.fixture
def rapp(app, monkeypatch, tmp_path):
    monkeypatch.setitem(app.config, "UPLOAD_ROOT", str(tmp_path / "uploads"))
    monkeypatch.setitem(app.config, "SCHOOL_BACKUP_DIR", str(tmp_path / "backups"))
    return app


def _export(app, bundle):
    from app.extensions import db
    from app.services import school_backup as sb
    with app.app_context():
        res = sb.export_school(bundle["school"].id)
        db.session.remove()
    return res.path


def _state(app, bundle) -> dict:
    """Every restorable row of the school, by table (secrets left out)."""
    import sqlalchemy as sa
    from app.extensions import db
    from app.services import school_backup as sb
    from app.services import school_restore as sr
    sid = bundle["school"].id
    out = {}
    with app.app_context():
        conn = db.session.connection()
        for t in sb.backup_tables():
            if t.name in sr.NEVER_RESTORED:
                continue
            cols = sb.backup_columns(t)
            rows = conn.execute(sa.select(*cols).where(t.c.school_id == sid)).all()
            out[t.name] = sorted(tuple(str(v) for v in r) for r in rows)
        db.session.remove()
    return out


def _school_row(app, bundle):
    from app.extensions import db
    from app.models import School
    with app.app_context():
        s = db.session.get(School, bundle["school"].id)
        out = (s.slug, s.status, s.smtp_host, s.notify_channels, s.auth_epoch, s.name)
        db.session.remove()
    return out


def _restore(app, bundle, path, modules=ALL_BUT_ACCOUNTS, mode="replace", **kw):
    from app.extensions import db
    from app.services import school_restore as sr
    with app.app_context():
        try:
            return sr.run_restore(bundle["school"].id, path, modules, mode, **kw)
        finally:
            db.session.remove()


def _mutate(app, bundle):
    """Edits after the backup: a renamed subject, a new subject, a deleted note."""
    from app.extensions import db
    from app.models import StudentNote, Subject
    with app.app_context():
        s = db.session.get(Subject, bundle["subject"].id)
        s.name = "Renamed-after-backup"
        db.session.add(Subject(school_id=bundle["school"].id, name="New-after-backup"))
        note = StudentNote.query.filter_by(school_id=bundle["school"].id).first()
        if note:
            db.session.delete(note)
        db.session.commit()
        db.session.remove()


# ─── modules ────────────────────────────────────────────────────────

def test_every_table_is_in_a_module_or_never_restored(rapp):
    from app.services import school_restore as sr
    with rapp.app_context():
        assert sr.unmapped_tables() == []
    assert all(len(why) > 15 for why in sr.NEVER_RESTORED.values())


def test_dependencies_are_added_with_a_reason_but_never_accounts(rapp):
    from app.services import school_restore as sr
    with rapp.app_context():
        mods, added = sr.with_dependencies(["attendance"])
        assert mods.index("academic") < mods.index("students") < mods.index("attendance")
        assert set(added) == {"students", "academic"} and all(added.values())
        mods, _ = sr.with_dependencies(["messaging", "lms"])
        assert "accounts" not in mods
        with pytest.raises(sr.RestoreError):
            sr.with_dependencies(["no_such_module"])


# ─── refusals ───────────────────────────────────────────────────────

def test_package_of_b_is_refused_on_a_and_nothing_changes(rapp, world):
    from app.services import school_restore as sr
    A, B = world["A"], world["B"]
    pkg_b = _export(rapp, B)
    before = _state(rapp, A)
    with pytest.raises(sr.RestoreError):
        _restore(rapp, A, pkg_b)
    assert _state(rapp, A) == before


def test_tampered_package_is_refused(rapp, world):
    from app.services import school_restore as sr
    A, B = world["A"], world["B"]
    path = _export(rapp, A)
    with tarfile.open(path, "r:gz") as t:
        members = {m.name: t.extractfile(m).read() for m in t.getmembers()}
    manifest = json.loads(members["manifest.json"])
    cols = manifest["tables"]["subjects"]["columns"]
    from app.services import school_backup as sb
    row = [None] * len(cols)
    row[cols.index("id")], row[cols.index("school_id")], row[cols.index("name")] = 999991, B["school"].id, "X"
    members["data/subjects.copy"] += sb.copy_line(row).encode()
    manifest["tables"]["subjects"]["rows"] += 1
    members["manifest.json"] = json.dumps(manifest).encode()
    members.pop("checksums.sha256")
    members["checksums.sha256"] = "".join(f"{hashlib.sha256(b).hexdigest()}  {n}\n"
                                          for n, b in members.items()).encode()
    path.unlink()
    with tarfile.open(path, "w:gz") as t:
        for n, b in members.items():
            info = tarfile.TarInfo(n)
            info.size = len(b)
            t.addfile(info, io.BytesIO(b))
    before = _state(rapp, A)
    with pytest.raises(sr.RestoreError):
        _restore(rapp, A, path)
    assert _state(rapp, A) == before


# ─── replace ────────────────────────────────────────────────────────

def test_full_replace_brings_back_the_package_and_b_is_untouched(rapp, world):
    A, B = world["A"], world["B"]
    path = _export(rapp, A)
    snapshot = _state(rapp, A)
    b_before = _state(rapp, B)
    school_before = _school_row(rapp, A)
    _mutate(rapp, A)
    assert _state(rapp, A) != snapshot
    out = _restore(rapp, A, path)
    assert _state(rapp, A) == snapshot
    assert _state(rapp, B) == b_before
    assert _school_row(rapp, A) == school_before
    assert out["restore_point_backup_id"]


def test_failure_midway_rolls_everything_back(rapp, world):
    from app.services import school_restore as sr
    A = world["A"]
    path = _export(rapp, A)
    _mutate(rapp, A)
    before = _state(rapp, A)
    with pytest.raises(sr.RestoreError):
        _restore(rapp, A, path, fail_after="students")
    assert _state(rapp, A) == before
    with rapp.app_context():
        assert not sr.in_maintenance(A["school"].id)


def test_unbalanced_journal_in_the_package_is_rolled_back(rapp, world):
    """Checksums recomputed by an attacker: verify passes, the post-write
    ledger check refuses and nothing stays written."""
    from app.services import school_backup as sb
    from app.services import school_restore as sr
    A = world["A"]
    path = _export(rapp, A)
    with tarfile.open(path, "r:gz") as t:
        members = {m.name: t.extractfile(m).read() for m in t.getmembers()}
    manifest = json.loads(members["manifest.json"])
    cols = manifest["tables"]["journal_lines"]["columns"]
    lines = members["data/journal_lines.copy"].decode().splitlines()
    assert lines, "the world fixture posts journal entries"
    vals = sb.parse_copy_line(lines[0])
    vals[cols.index("debit")] = "999999.00"
    vals[cols.index("credit")] = "0.00"
    lines[0] = sb.copy_line(vals).rstrip("\n")
    members["data/journal_lines.copy"] = ("\n".join(lines) + "\n").encode()
    manifest["tables"]["journal_lines"]["sha256"] = hashlib.sha256(members["data/journal_lines.copy"]).hexdigest()
    members["manifest.json"] = json.dumps(manifest).encode()
    members.pop("checksums.sha256")
    members["checksums.sha256"] = "".join(f"{hashlib.sha256(b).hexdigest()}  {n}\n"
                                          for n, b in members.items()).encode()
    path.unlink()
    with tarfile.open(path, "w:gz") as t:
        for n, b in members.items():
            info = tarfile.TarInfo(n)
            info.size = len(b)
            t.addfile(info, io.BytesIO(b))
    before = _state(rapp, A)
    with pytest.raises(sr.RestoreError, match="متوازنة"):
        _restore(rapp, A, path, modules=["finance"])
    assert _state(rapp, A) == before


def test_a_chart_of_accounts_with_sub_accounts_restores(rapp, world):
    """accounts.parent_id points into its own table: the orphan check
    must look for the parent among the other rows, not the row itself."""
    from app.extensions import db
    from app.models import Account
    A = world["A"]
    sid = A["school"].id
    with rapp.app_context():
        top = Account(school_id=sid, code="T-900", name="Top", type="asset")
        db.session.add(top); db.session.flush()
        db.session.add(Account(school_id=sid, code="T-901", name="Child", type="asset", parent_id=top.id))
        db.session.commit()
        db.session.remove()
    path = _export(rapp, A)
    snapshot = _state(rapp, A)
    _restore(rapp, A, path, modules=["finance"])
    assert _state(rapp, A) == snapshot
    with rapp.app_context():
        child = Account.query.filter_by(school_id=sid, code="T-901").one()
        assert child.parent is not None and child.parent.code == "T-900"
        db.session.remove()


def test_the_acting_admin_and_the_school_row_are_protected(rapp, world):
    """Accounts chosen explicitly: the admin running it keeps password and
    role; plan / slug / SMTP / status never move."""
    from app.extensions import db
    from app.models import Role, School, User
    A = world["A"]
    path = _export(rapp, A)
    admin_id = A["users"]["admin"].id
    with rapp.app_context():
        u = db.session.get(User, admin_id)
        u.password_hash = "changed-after-backup"
        u.full_name = "Admin renamed after backup"
        role = db.session.get(Role, u.role_id)
        role.permissions = {"everything": True} if hasattr(role, "permissions") else None
        s = db.session.get(School, A["school"].id)
        s.smtp_host = "smtp.after-backup.test"
        db.session.commit()
        expect_role = db.session.get(Role, u.role_id).permissions if hasattr(role, "permissions") else None
        db.session.remove()
    school_before = _school_row(rapp, A)
    _restore(rapp, A, path, modules=ALL_BUT_ACCOUNTS + ["accounts"], actor_user_id=admin_id)
    with rapp.app_context():
        u = db.session.get(User, admin_id)
        assert u.password_hash == "changed-after-backup"
        assert u.full_name == "Admin renamed after backup"
        if expect_role is not None:
            assert db.session.get(Role, u.role_id).permissions == expect_role
        db.session.remove()
    assert _school_row(rapp, A) == school_before


def test_a_deleted_user_comes_back_without_a_usable_password(rapp, world):
    from app.extensions import db
    from app.models import User
    A = world["A"]
    path = _export(rapp, A)
    with rapp.app_context():
        u = User(school_id=A["school"].id, role_id=A["roles"]["teacher"].id, username="gone_later",
                 full_name="Gone-Later", is_active=True)
        u.set_password("old-secret-password-1")
        db.session.add(u)
        db.session.commit()
        db.session.remove()
    path = _export(rapp, A)                          # the package now has gone_later
    with rapp.app_context():
        User.query.filter_by(username="gone_later").delete()
        db.session.commit()
        db.session.remove()
    _restore(rapp, A, path, modules=["accounts"], actor_user_id=A["users"]["admin"].id)
    with rapp.app_context():
        back = User.query.filter_by(username="gone_later").one()
        assert back.password_hash and not back.check_password("old-secret-password-1")
        # an existing account keeps its own password
        assert db.session.get(User, A["users"]["teacher"].id).check_password("test-password-12345")
        db.session.remove()


# ─── add missing ────────────────────────────────────────────────────

def test_add_missing_only_adds_what_is_gone(rapp, world):
    from app.extensions import db
    from app.models import Subject
    A = world["A"]
    with rapp.app_context():
        extra = Subject(school_id=A["school"].id, name="Will-be-deleted")
        db.session.add(extra)
        db.session.commit()
        extra_id = extra.id
        db.session.remove()
    path = _export(rapp, A)
    with rapp.app_context():
        # Newer row first: SQLite would otherwise reuse the deleted id (a
        # clash add_missing skips and reports — Postgres never reuses ids).
        db.session.add(Subject(school_id=A["school"].id, name="Newer-than-backup"))
        db.session.flush()
        # a real delete (the ORM's delete is a soft delete: the row stays)
        db.session.execute(Subject.__table__.delete().where(Subject.__table__.c.id == extra_id))
        s = db.session.get(Subject, A["subject"].id)
        s.name = "Edited-after-backup"
        db.session.commit()
        db.session.remove()
    out = _restore(rapp, A, path, modules=["academic"], mode="add_missing")
    with rapp.app_context():
        names = {s.name for s in Subject.query.filter_by(school_id=A["school"].id)}
        db.session.remove()
    assert {"Will-be-deleted", "Edited-after-backup", "Newer-than-backup"} <= names
    assert out["inserted"]["subjects"] == 1 and out["skipped"]["subjects"] >= 1


# ─── undo ───────────────────────────────────────────────────────────

def test_undo_returns_to_the_state_before_the_restore(rapp, world):
    from app.extensions import db
    from app.models import SchoolBackup
    from app.services import school_backup as sb
    A = world["A"]
    path = _export(rapp, A)
    _mutate(rapp, A)
    before_restore = _state(rapp, A)
    out = _restore(rapp, A, path)
    assert _state(rapp, A) != before_restore
    with rapp.app_context():
        point = db.session.get(SchoolBackup, out["restore_point_backup_id"])
        assert point.kind == "restore_point"
        point_path = sb.backups_dir(A["school"].id) / point.file_name
        db.session.remove()
    _restore(rapp, A, point_path, take_restore_point=False)
    assert _state(rapp, A) == before_restore


# ─── maintenance ────────────────────────────────────────────────────

def test_maintenance_closes_only_that_school(rapp, world, login_as, monkeypatch):
    from app.services import school_restore as sr
    monkeypatch.setitem(rapp.config, "TENANT_RESOLUTION_MODE", "enforce")
    A, B = world["A"], world["B"]
    with rapp.app_context():
        sr._maintenance_set(A["school"].id, True)
    try:
        ca, cb = rapp.test_client(), rapp.test_client()
        login_as(ca, A["users"]["admin"], base_url=host(A))
        login_as(cb, B["users"]["admin"], base_url=host(B))
        assert ca.get("/dashboard", base_url=host(A)).status_code == 503
        r = ca.get("/api/me", base_url=host(A))
        assert r.status_code == 503 and r.get_json()["error"] == "maintenance"
        assert cb.get("/dashboard", base_url=host(B)).status_code in (200, 302)
    finally:
        with rapp.app_context():
            sr._maintenance_set(A["school"].id, False)
    assert rapp.test_client().get("/auth/login", base_url=host(A)).status_code == 200


def test_every_foreign_key_is_deferrable(rapp):
    """A restore defers them inside its own transaction; a new FK that
    isn't deferrable would make a module's replace fail midway."""
    from app.extensions import db
    bad = [f"{t.name}.{fk.name or [c.name for c in fk.columns]}" for t in db.metadata.tables.values()
           for fk in t.foreign_key_constraints if not fk.deferrable or fk.initially != "IMMEDIATE"]
    assert bad == []
