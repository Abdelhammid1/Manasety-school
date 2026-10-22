"""SAAS-046 — the school backup package: format, export, encryption and
verify_package (runs on SQLite and on PostgreSQL)."""

from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile

import pytest


@pytest.fixture
def bapp(app, monkeypatch, tmp_path):
    monkeypatch.setitem(app.config, "UPLOAD_ROOT", str(tmp_path / "uploads"))
    monkeypatch.setitem(app.config, "SCHOOL_BACKUP_DIR", str(tmp_path / "backups"))
    return app


@pytest.fixture
def uploads(bapp, world, tmp_path):
    """One upload per school, under the storage's <school_id>/ folder."""
    out = {}
    for side in ("A", "B"):
        sid = world[side]["school"].id
        d = tmp_path / "uploads" / str(sid) / "materials" / "1"
        d.mkdir(parents=True)
        (d / f"note-{side}.pdf").write_bytes(f"%PDF-1.4 {side}".encode())
        out[side] = f"materials/1/note-{side}.pdf"
    return out


def _export(app, bundle, **kw):
    from app.extensions import db
    from app.services import school_backup as sb
    with app.app_context():
        res = sb.export_school(bundle["school"].id, **kw)
        db.session.remove()
    return res


def _verify(app, path, passphrase=None, **kw):
    from app.services import school_backup as sb
    with app.app_context():
        return sb.verify_package(path, passphrase, **kw)


def _members(path) -> dict[str, bytes]:
    with tarfile.open(path, "r:gz") as t:
        return {m.name: t.extractfile(m).read() for m in t.getmembers()}


def _rewrite(path, members: dict[str, bytes], *, resum: bool) -> None:
    """Write `members` back as a package; resum=True recomputes the
    checksums like an attacker who knows the format would."""
    if resum:
        members = dict(members)
        members.pop("checksums.sha256", None)
        sums = "".join(f"{hashlib.sha256(b).hexdigest()}  {n}\n" for n, b in sorted(members.items()))
        members["checksums.sha256"] = sums.encode()
    os.remove(path)
    with tarfile.open(path, "w:gz") as t:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))


# ─── coverage ───────────────────────────────────────────────────────

def test_every_school_table_is_backed_up_or_excluded_with_a_reason(bapp):
    from app.services import school_backup as sb
    with bapp.app_context():
        assert sb.unclassified_tables() == []
        assert all(len(why) > 15 for why in sb.BACKUP_EXCLUDED.values())
        names = {t.name for t in sb.backup_tables()}
    assert {"students", "invoices", "journal_lines", "lms_quiz_attempts", "users"} <= names
    assert not names & {"schools", "school_subscriptions", "platform_jobs", "support_sessions",
                        "device_tokens", "account_setup_tokens"}


def test_a_new_school_table_is_picked_up_without_a_list(bapp):
    """Discovery is by school_id column: a new tenant table is in the next
    backup automatically (excluding one needs a written reason)."""
    from sqlalchemy import Column, Integer, Table
    from app.extensions import db
    from app.services import school_backup as sb
    ghost = Table("ghost_records", db.metadata, Column("id", Integer, primary_key=True),
                  Column("school_id", Integer))
    try:
        with bapp.app_context():
            assert "ghost_records" in {t.name for t in sb.backup_tables()}
            assert sb.unclassified_tables() == []
    finally:
        db.metadata.remove(ghost)


def test_the_package_holds_exactly_the_discovered_tables(bapp, world):
    from app.services import school_backup as sb
    res = _export(bapp, world["A"])
    with bapp.app_context():
        assert set(res.manifest["tables"]) == {t.name for t in sb.backup_tables()}


# ─── round trip + isolation ─────────────────────────────────────────

def test_round_trip_counts_match_the_database(bapp, world, uploads):
    from sqlalchemy import func, select
    from app.extensions import db
    from app.services import school_backup as sb
    A = world["A"]
    res = _export(bapp, A)
    rep = _verify(bapp, res.path)
    assert rep.ok, rep.problems
    assert rep.school_id == A["school"].id and rep.slug == A["school"].slug
    with bapp.app_context():
        for t in sb.backup_tables():
            cond = t.c.school_id == A["school"].id
            extra = sb._row_filter(t)
            if extra is not None:
                cond = cond & extra
            live = db.session.execute(select(func.count()).select_from(t).where(cond)).scalar()
            assert rep.tables[t.name] == live == res.manifest["tables"][t.name]["rows"], t.name
        db.session.remove()
    assert sum(rep.tables.values()) > 50
    assert [f["path"] for f in res.manifest["files"]] == [uploads["A"]]
    assert oct(os.stat(res.path).st_mode & 0o777) in ("0o600", "0o666")   # 0o666 = Windows


def test_package_of_a_holds_nothing_of_b(bapp, world, uploads):
    from app.services import school_backup as sb
    A, B = world["A"], world["B"]
    res = _export(bapp, A)
    members = _members(res.path)
    blob = b"".join(members.values()).decode("utf-8", "replace")
    assert not [m for m in B["markers"] if m in blob]
    assert f"files/{uploads['B']}" not in members
    for name, meta in res.manifest["tables"].items():
        at = meta["columns"].index("school_id")
        for line in members[f"data/{name}.copy"].decode().splitlines():
            assert sb.parse_copy_line(line)[at] == str(A["school"].id), name
    school = json.loads(members["school.json"])
    assert not set(school) & sb.SCHOOL_ROW_EXCLUDED


def test_platform_support_accounts_are_never_in_a_package(bapp, world):
    from app.extensions import db
    from app.models import User
    A = world["A"]
    with bapp.app_context():
        u = User(school_id=A["school"].id, role_id=A["roles"]["admin"].id, username="support-x",
                 full_name="Support-ghost", is_active=True, is_platform_support=True)
        u.password_hash = "x"
        db.session.add(u)
        db.session.commit()
        db.session.remove()
    res = _export(bapp, A)
    assert b"Support-ghost" not in _members(res.path)["data/users.copy"]


# ─── tampering ──────────────────────────────────────────────────────

def test_one_changed_byte_in_any_member_fails(bapp, world, uploads):
    res = _export(bapp, world["A"])
    members = _members(res.path)
    for name in ("data/students.copy", "school.json", "manifest.json", f"files/{uploads['A']}"):
        tampered = dict(members)
        data = bytearray(tampered[name])
        data[len(data) // 2] ^= 0x01
        tampered[name] = bytes(data)
        _rewrite(res.path, tampered, resum=False)
        rep = _verify(bapp, res.path)
        assert not rep.ok and rep.problems, name
    _rewrite(res.path, members, resum=False)
    assert _verify(bapp, res.path).ok


def test_a_foreign_row_refuses_the_whole_package(bapp, world):
    """Even with recomputed checksums and counts: one row of school B
    inside A's package = the package is refused (not the row skipped)."""
    from app.services import school_backup as sb
    A, B = world["A"], world["B"]
    res = _export(bapp, A)
    members = _members(res.path)
    manifest = json.loads(members["manifest.json"])
    cols = manifest["tables"]["subjects"]["columns"]
    row = [None] * len(cols)
    row[cols.index("id")] = 999999
    row[cols.index("school_id")] = B["school"].id
    row[cols.index("name")] = "Injected"
    members["data/subjects.copy"] += sb.copy_line(row).encode()
    manifest["tables"]["subjects"]["rows"] += 1
    manifest["tables"]["subjects"]["sha256"] = hashlib.sha256(members["data/subjects.copy"]).hexdigest()
    members["manifest.json"] = json.dumps(manifest).encode()
    _rewrite(res.path, members, resum=True)
    rep = _verify(bapp, res.path)
    assert not rep.ok
    assert any("مدرسة أخرى" in p for p in rep.problems)


def test_a_table_outside_the_allowlist_is_refused(bapp, world):
    res = _export(bapp, world["A"])
    members = _members(res.path)
    manifest = json.loads(members["manifest.json"])
    manifest["tables"]["platform_jobs"] = {"rows": 0, "columns": ["id", "school_id"], "sha256": ""}
    members["data/platform_jobs.copy"] = b""
    members["manifest.json"] = json.dumps(manifest).encode()
    _rewrite(res.path, members, resum=True)
    rep = _verify(bapp, res.path)
    assert not rep.ok and any("platform_jobs" in p for p in rep.problems)


@pytest.mark.parametrize("bad", ["../evil.txt", "/etc/passwd", "files/../../x", "data\\x.copy"])
def test_unsafe_member_paths_are_refused(bapp, world, bad):
    res = _export(bapp, world["A"])
    members = _members(res.path)
    members[bad] = b"x"
    _rewrite(res.path, members, resum=True)
    assert not _verify(bapp, res.path).ok


def test_a_package_from_a_newer_schema_is_refused(bapp, world):
    from app.services import school_backup as sb
    with bapp.app_context():
        if sb.known_revisions() is None:
            pytest.fail("migrations not found — the revision check can't run")
    res = _export(bapp, world["A"])
    members = _members(res.path)
    manifest = json.loads(members["manifest.json"])
    manifest["alembic_version"] = "ffffffffffff"
    members["manifest.json"] = json.dumps(manifest).encode()
    _rewrite(res.path, members, resum=True)
    rep = _verify(bapp, res.path)
    assert not rep.ok and any("أحدث" in p for p in rep.problems)


def test_package_for_another_school_is_refused_when_expected(bapp, world):
    res = _export(bapp, world["A"])
    assert _verify(bapp, res.path, expect_school_id=world["A"]["school"].id).ok
    rep = _verify(bapp, res.path, expect_school_id=world["B"]["school"].id)
    assert not rep.ok and any("مدرسة أخرى" in p for p in rep.problems)


def test_garbage_is_refused_cleanly(bapp, tmp_path):
    p = tmp_path / "x.tar.gz"
    p.write_bytes(b"not a package at all")
    rep = _verify(bapp, p)
    assert not rep.ok and rep.problems


# ─── encryption ─────────────────────────────────────────────────────

PASS = "correct horse battery"


def test_encrypted_round_trip_and_wrong_passphrase(bapp, world, tmp_path):
    from app.services import school_backup as sb
    res = _export(bapp, world["A"])
    enc = tmp_path / "a.mbk"
    sb.encrypt_file(res.path, enc, PASS)
    assert sb.is_encrypted(enc) and not sb.is_encrypted(res.path)
    assert _verify(bapp, enc, PASS).ok
    bad = _verify(bapp, enc, "wrong passphrase!!")
    assert not bad.ok and bad.problems == [sb._BAD_PASS]
    assert not _verify(bapp, enc, None).ok
    # Truncated / bit-flipped / chunk dropped: the same generic message.
    raw = enc.read_bytes()
    for name, data in (("cut", raw[:-40]), ("flip", raw[:200] + bytes([raw[200] ^ 1]) + raw[201:]),
                       ("header", raw[:20])):
        p = tmp_path / f"{name}.mbk"
        p.write_bytes(data)
        rep = _verify(bapp, p, PASS)
        assert not rep.ok and rep.problems == [sb._BAD_PASS], name
    # nothing decrypted is left behind
    assert not list(tmp_path.glob("mnst-verify-*"))


def test_passphrase_must_be_long_enough(bapp, world, tmp_path):
    from app.services import school_backup as sb
    res = _export(bapp, world["A"])
    with pytest.raises(sb.BackupError):
        sb.encrypt_file(res.path, tmp_path / "x.mbk", "short")
    assert not (tmp_path / "x.mbk").exists()


def test_copy_format_round_trip():
    from datetime import date, datetime
    from decimal import Decimal
    from app.services import school_backup as sb
    vals = [None, True, 12, Decimal("10.50"), "سطر\tتاب\nسطر\\مائل\r", date(2026, 9, 1),
            datetime(2026, 9, 1, 8, 30), {"a": [1, "ب"]}, b"\x00\xff", r"\N"]
    back = sb.parse_copy_line(sb.copy_line(vals))
    assert back == [None, "t", "12", "10.50", "سطر\tتاب\nسطر\\مائل\r", "2026-09-01",
                    "2026-09-01 08:30:00", '{"a": [1, "ب"]}', "\\x00ff", r"\N"]


# ─── CLI + job ──────────────────────────────────────────────────────

def test_cli_encrypted_backup_and_verify(bapp, world, tmp_path, monkeypatch):
    monkeypatch.setenv("BK_PASS", PASS)
    out = tmp_path / "a.mbk"
    r = bapp.test_cli_runner().invoke(args=["school-backup", "--school", world["A"]["school"].slug,
                                            "--out", str(out), "--encrypt", "--passphrase-env", "BK_PASS"])
    assert r.exit_code == 0, r.output
    body = json.loads(r.output[r.output.index("{"):])
    assert body["encrypted"] and body["rows"] > 50
    assert not list(tmp_path.glob("*.plain.tar.gz"))
    assert PASS not in r.output
    v = bapp.test_cli_runner().invoke(args=["school-backup-verify", str(out), "--passphrase-env", "BK_PASS",
                                            "--school", world["A"]["school"].slug])
    assert v.exit_code == 0, v.output
    v = bapp.test_cli_runner().invoke(args=["school-backup-verify", str(out), "--passphrase-env", "BK_PASS",
                                            "--school", world["B"]["school"].slug])
    assert v.exit_code == 1


def test_backup_job_runs_from_the_queue(bapp, world):
    from app.extensions import db
    from app.models import PlatformJob
    from app.services import school_backup as sb
    A = world["A"]
    with bapp.app_context():
        job = PlatformJob(kind="school_backup", status="pending", school_id=A["school"].id)
        db.session.add(job)
        db.session.commit()
        jid = job.id
        assert sb.run_backup_queue() == 1
        job = db.session.get(PlatformJob, jid)
        assert job.status == "succeeded", job.result
        assert job.result["progress"] == 100 and job.result["file"].endswith(".tar.gz")
        path = sb.backups_dir(A["school"].id) / job.result["file"]
        assert sb.verify_package(path, expect_school_id=A["school"].id).ok
        db.session.delete(job)
        db.session.commit()
        db.session.remove()


def test_no_secret_column_leaves_the_server(bapp, world):
    """Password hashes, TOTP secrets and tokens are never in a package
    (security review of 10fdd41)."""
    from app.services.audit import is_secret_field
    res = _export(bapp, world["A"])
    for name, meta in res.manifest["tables"].items():
        assert not [c for c in meta["columns"] if is_secret_field(c)], name
    assert "password_hash" not in res.manifest["tables"]["users"]["columns"]
    blob = b"".join(_members(res.path).values())
    assert b"$2b$" not in blob and b"$2a$" not in blob


def test_a_package_carrying_a_secret_column_is_refused(bapp, world):
    res = _export(bapp, world["A"])
    members = _members(res.path)
    manifest = json.loads(members["manifest.json"])
    meta = manifest["tables"]["users"]
    meta["columns"].append("password_hash")
    members["data/users.copy"] = b"".join(line + b"\tx\n" for line in members["data/users.copy"].splitlines())
    meta["sha256"] = hashlib.sha256(members["data/users.copy"]).hexdigest()
    members["manifest.json"] = json.dumps(manifest).encode()
    _rewrite(res.path, members, resum=True)
    rep = _verify(bapp, res.path)
    assert not rep.ok and any("users" in p for p in rep.problems)


def test_school_json_is_an_allowlist(bapp, world):
    """Only settings the admin can already edit travel; a package whose
    school.json carries anything else is refused (security review)."""
    from app.services import school_backup as sb
    res = _export(bapp, world["A"])
    members = _members(res.path)
    school = json.loads(members["school.json"])
    assert set(school) <= sb.SCHOOL_ROW_RESTORABLE
    for extra in ({"notify_on_support_access": False}, {"approval_threshold": 0}, {"auth_epoch": 0},
                  {"smtp_host": "evil.test"}, {"status": "active"}):
        tampered = dict(members)
        tampered["school.json"] = json.dumps({**school, **extra}).encode()
        _rewrite(res.path, tampered, resum=True)
        rep = _verify(bapp, res.path)
        assert not rep.ok and any("غير مسموحة" in p for p in rep.problems), extra


def test_a_package_with_a_support_account_is_refused(bapp, world):
    """Real exports never carry platform support accounts (security review)."""
    from app.services import school_backup as sb
    res = _export(bapp, world["A"])
    members = _members(res.path)
    manifest = json.loads(members["manifest.json"])
    cols = manifest["tables"]["users"]["columns"]
    line = members["data/users.copy"].decode().splitlines()[0]
    vals = sb.parse_copy_line(line)
    vals[cols.index("id")] = "999777"
    vals[cols.index("username")] = "ghost_support"
    vals[cols.index("is_platform_support")] = "t"
    members["data/users.copy"] += sb.copy_line(vals).encode()
    manifest["tables"]["users"]["rows"] += 1
    members["manifest.json"] = json.dumps(manifest).encode()
    _rewrite(res.path, members, resum=True)
    rep = _verify(bapp, res.path)
    assert not rep.ok and any("حساب دعم" in p for p in rep.problems)


def test_unpacked_size_is_capped(bapp, world, monkeypatch):
    """A small file must not unpack into a huge one (security review)."""
    res = _export(bapp, world["A"])
    monkeypatch.setitem(bapp.config, "SCHOOL_BACKUP_MAX_UNPACKED_MB", 0)
    members = _members(res.path)
    members["data/students.copy"] += b"x" * (2 * 1024 * 1024)       # 2 MB, compresses to almost nothing
    _rewrite(res.path, members, resum=True)
    monkeypatch.setitem(bapp.config, "SCHOOL_BACKUP_MAX_UNPACKED_MB", 1)
    rep = _verify(bapp, res.path)
    assert not rep.ok and any("فك الضغط" in p for p in rep.problems)
