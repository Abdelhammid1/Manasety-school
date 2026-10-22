"""SAAS-035 — export (own rows only, no secrets, manifest = counts,
--verify), the offboarding path, and the purge: every missing condition
refused on its own, a successful purge leaves 0 rows for A and B exactly
as it was (invoices / subscriptions / global tables intact, integrity
check clean), and a failure mid-delete rolls everything back."""

from __future__ import annotations

import json
import time
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

from test_saas026_subscriptions import CONSOLE, _console_client, console  # noqa: F401


@pytest.fixture
def uploads(console, tmp_path, monkeypatch):
    monkeypatch.setitem(console.config, "UPLOAD_ROOT", str(tmp_path / "up"))
    return tmp_path


@pytest.fixture
def backup(tmp_path):
    f = tmp_path / "dump.sql"
    f.write_text("-- dump")
    return str(f)


def _export(app, bundle):
    from app.services import school_export
    with app.app_context():
        return school_export.export_school(bundle["school"].id)


def test_export_contains_only_own_rows_and_no_secrets(console, two_schools, uploads):
    A, B = two_schools["A"], two_schools["B"]
    res = _export(console, A)
    with zipfile.ZipFile(res["path"]) as z:
        names = z.namelist()
        assert "manifest.json" in names and "README.md" in names and "tables/users.csv" in names
        users = z.read("tables/users.csv").decode()
        assert "password_hash" not in users.splitlines()[0]
        blob = b"".join(z.read(n) for n in names if n.startswith("tables/"))
        assert b"$2b$" not in blob                                    # no bcrypt hash anywhere
        for marker in B["markers"]:
            assert marker.encode() not in blob, marker
        assert A["markers"][2].encode() in blob
        school = json.loads(z.read("tables/schools.json"))
        assert "smtp_password_encrypted" not in school


def test_manifest_counts_and_verify(console, two_schools, uploads):
    from app.extensions import db
    from app.models import Student
    from app.services import school_export
    A = two_schools["A"]
    res = _export(console, A)
    with console.app_context():
        n = Student.query.filter_by(school_id=A["school"].id).count()
        assert res["manifest"]["tables"]["students"]["rows"] == n
        assert school_export.verify(res["path"]) == []
        db.session.add(Student(school_id=A["school"].id, permanent_code="NEW-1", full_name="late arrival"))
        db.session.commit()
        problems = school_export.verify(res["path"])
        assert any("students" in p for p in problems)
        Student.query.filter_by(permanent_code="NEW-1").delete()
        db.session.commit()


def test_export_runs_from_queue_and_marks_verified(console, two_schools, uploads):
    from app.extensions import db
    from app.models import PlatformJob, SchoolOffboarding
    from app.services import school_export
    A = two_schools["A"]["school"].id
    with console.app_context():
        db.session.add(SchoolOffboarding(school_id=A, reason="leaving"))
        db.session.add(PlatformJob(kind="school_export", status="pending", school_id=A))
        db.session.commit()
        assert school_export.run_export_queue() == 1
        job = PlatformJob.query.filter_by(kind="school_export", school_id=A).one()
        assert job.status == "succeeded" and job.result["verified"]
        assert SchoolOffboarding.query.filter_by(school_id=A).one().export_verified_at is not None
        SchoolOffboarding.query.delete()          # points at the job: first
        PlatformJob.query.delete()
        db.session.commit()


# ─── purge ───────────────────────────────────────────────────────────

def _ready(app, bundle, owners=2, **overrides):
    """Make A purge-ready (with a real, verified export); returns the
    platform user ids used."""
    from pathlib import Path
    from app.extensions import db
    from app.models import PlatformUser, School, SchoolOffboarding
    from app.services import school_export
    import secrets
    with app.app_context():
        export_file = Path(school_export.export_school(bundle["school"].id)["path"]).name
        PlatformUser.query.filter_by(role="owner").update({"is_active": False})
        ids = []
        for i in range(owners):
            u = PlatformUser(email=f"o{i}-{secrets.token_hex(3)}@manasety.test", full_name="o",
                             role="owner", is_active=True,
                             created_at=datetime.now(timezone.utc) - timedelta(days=365))
            u.set_password(secrets.token_urlsafe(16))
            db.session.add(u); db.session.flush(); ids.append(u.id)
        s = db.session.get(School, bundle["school"].id)
        s.status = "archived"
        now = datetime.now(timezone.utc)
        row = SchoolOffboarding(school_id=s.id, reason="leaving", requested_at=now - timedelta(days=100),
                                export_verified_at=now - timedelta(days=99), export_file=export_file,
                                archived_at=now - timedelta(days=95),
                                retention_until=now - timedelta(days=1), purge_requested_by=ids[0],
                                purge_requested_at=now - timedelta(days=2),
                                approvals_required=2 if owners > 1 else 1,
                                purge_approved_by=ids[1] if owners > 1 else None,
                                purge_approved_at=now - timedelta(days=1) if owners > 1 else None)
        for k, v in overrides.items():
            setattr(row, k, v)
        db.session.add(row)
        db.session.commit()
        db.session.remove()
    return ids


@pytest.fixture
def purge_world(console, two_schools, uploads):
    yield
    from app.extensions import db
    from app.models import PlatformUser, School, SchoolOffboarding
    with console.app_context():
        SchoolOffboarding.query.delete()
        PlatformUser.query.filter_by(role="owner").update({"is_active": True})
        for k, slug in (("A", "alpha"), ("B", "beta")):
            s = db.session.get(School, two_schools[k]["school"].id)
            if s is not None:
                s.status, s.slug = "active", slug
        db.session.commit()
        db.session.remove()


def _purge(app, bundle, backup, execute=True, confirm=None):
    from app.extensions import db
    from app.models import School
    from app.services import school_purge
    with app.app_context():
        s = db.session.get(School, bundle["school"].id)
        return school_purge.purge(s, confirm_slug=confirm or s.slug, backup_file=backup, execute=execute)


@pytest.mark.parametrize("override,expected", [
    ({"export_verified_at": None}, "no verified export"),
    ({"retention_until": datetime.now(timezone.utc) + timedelta(days=5)}, "retention"),
    ({"purge_requested_by": None}, "purge not requested"),
    ({"purge_approved_by": None}, "second owner"),
])
def test_purge_refuses_each_missing_condition(console, two_schools, purge_world, backup, override, expected):
    _ready(console, two_schools["A"], **override)
    rep = _purge(console, two_schools["A"], backup)
    assert not rep["executed"] and any(expected in p for p in rep["problems"]), rep["problems"]


def test_purge_refuses_bad_confirm_backup_and_status(console, two_schools, purge_world, backup, tmp_path):
    import os
    from app.extensions import db
    from app.models import School
    A = two_schools["A"]
    _ready(console, A)
    assert "confirmation slug does not match" in _purge(console, A, backup, confirm="wrong")["problems"]
    assert "--backup-file is required" in _purge(console, A, None)["problems"]
    empty = tmp_path / "empty.sql"
    empty.write_text("")
    assert "backup file is empty" in _purge(console, A, str(empty))["problems"]
    old = time.time() - 2 * 3600
    os.utime(backup, (old, old))
    assert "backup file is older than 1 hour" in _purge(console, A, backup)["problems"]
    with console.app_context():
        db.session.get(School, A["school"].id).status = "suspended"
        db.session.commit()
    assert "school is not archived" in _purge(console, A, str(tmp_path / "x"))["problems"]


def test_single_owner_needs_24h(console, two_schools, purge_world, backup):
    A = two_schools["A"]
    _ready(console, A, owners=1, purge_requested_at=datetime.now(timezone.utc) - timedelta(hours=2))
    assert any("24 h" in p for p in _purge(console, A, backup)["problems"])


def test_dry_run_is_default_and_deletes_nothing(console, two_schools, purge_world, backup):
    from app.models import Student
    A = two_schools["A"]
    _ready(console, A)
    rep = _purge(console, A, backup, execute=False)
    assert not rep["executed"] and dict(rep["plan"])["students"] >= 1
    with console.app_context():
        assert Student.query.filter_by(school_id=A["school"].id).count() >= 1


def _all_counts(app, sid):
    from sqlalchemy import func, select
    from app.extensions import db
    from app.services.school_export import tenant_tables
    with app.app_context():
        with db.engine.connect() as conn:
            return {t.name: conn.execute(select(func.count()).select_from(t)
                                         .where(t.c.school_id == sid)).scalar() for t in tenant_tables()}


def test_purge_success(console, two_schools, purge_world, backup, uploads):
    from app.extensions import db
    from app.models import (PlatformInvoice, School, SchoolOffboarding, SchoolSubscription)
    from app.services import billing
    from app.services.tenant_guard import integrity_report
    A, B = two_schools["A"], two_schools["B"]
    folder = uploads / "up" / str(A["school"].id)
    folder.mkdir(parents=True)
    (folder / "x.pdf").write_bytes(b"%PDF")
    with console.app_context():
        inv = billing.create_invoice(db.session.get(School, A["school"].id), None, currency="EGP",
                                     lines=[{"description": "x", "qty": 1, "unit_price": 10}])
        db.session.commit()
        inv_id = inv.id
        from app.models.nafis import LearningOutcome
        global_before = LearningOutcome.query.count()
        db.session.remove()
    _ready(console, A)
    b_before = _all_counts(console, B["school"].id)
    rep = _purge(console, A, backup)
    assert rep["executed"] and not rep["problems"]
    assert all(n == 0 for n in _all_counts(console, A["school"].id).values())
    assert _all_counts(console, B["school"].id) == b_before
    assert not folder.exists()
    with console.app_context():
        s = db.session.get(School, A["school"].id)
        assert s.name == f"[مدرسة محذوفة #{s.id}]" and s.status == "archived" and s.slug == "alpha"
        assert s.smtp_password_encrypted is None and s.phone is None
        assert db.session.get(PlatformInvoice, inv_id) is not None
        assert SchoolSubscription.query.filter_by(school_id=s.id).count() >= 1
        assert SchoolOffboarding.query.filter_by(school_id=s.id).one().purged_at is not None
        assert not any(integrity_report().values())
        from app.models.nafis import LearningOutcome
        assert LearningOutcome.query.count() == global_before
        from app.models import PlatformInvoiceLine
        PlatformInvoiceLine.query.filter_by(invoice_id=inv_id).delete()     # lines first (FK)
        PlatformInvoice.query.filter_by(id=inv_id).delete()
        db.session.commit()
        db.session.remove()


def test_failure_mid_delete_rolls_back(console, two_schools, purge_world, backup, monkeypatch):
    from app.services import school_purge
    A = two_schools["A"]
    _ready(console, A)
    before = _all_counts(console, A["school"].id)
    real = school_purge._witness

    def boom(conn, school):
        raise RuntimeError("disk on fire")
    monkeypatch.setattr(school_purge, "_witness", boom)
    with pytest.raises(RuntimeError):
        _purge(console, A, backup)
    assert _all_counts(console, A["school"].id) == before
    monkeypatch.setattr(school_purge, "_witness", real)


# ─── console path ────────────────────────────────────────────────────

def test_console_path_and_roles(console, two_schools, purge_world):
    from app.extensions import db
    from app.models import PlatformJob, SchoolOffboarding
    A = two_schools["A"]["school"]
    c, uid = _console_client(console, "owner")
    with c.session_transaction(base_url=CONSOLE) as s:
        s["sa_totp_at"] = time.time()
    base = f"/superadmin/schools/{A.id}/offboarding"
    assert c.get(base, base_url=CONSOLE).status_code == 200
    c.post(f"{base}/start", base_url=CONSOLE, data={"reason": "contract ended"})
    c.post(f"{base}/export", base_url=CONSOLE, data={"reason": "hand-over"})
    r = c.post(f"{base}/request_purge", base_url=CONSOLE, data={"reason": "x", "confirm_slug": A.slug})
    with console.app_context():
        row = SchoolOffboarding.query.filter_by(school_id=A.id).one()
        assert row.purge_requested_by is None                    # no verified export yet
        assert PlatformJob.query.filter_by(kind="school_export", school_id=A.id, status="pending").count() == 1
        PlatformJob.query.delete()
        db.session.commit()
    sup, _ = _console_client(console, "support")
    assert sup.get(base, base_url=CONSOLE).status_code == 403
    # never a delete button on the web
    page = c.get(base, base_url=CONSOLE).data.decode()
    assert "school-purge" in page and "/purge" not in page.replace("request_purge", "").replace("approve_purge", "")



# ─── security-review follow-ups ──────────────────────────────────────

def test_purge_refuses_when_data_changed_after_export(console, two_schools, purge_world, backup):
    from app.extensions import db
    from app.models import Student
    A = two_schools["A"]
    _ready(console, A)
    with console.app_context():
        db.session.add(Student(school_id=A["school"].id, permanent_code="AFTER-1", full_name="after export"))
        db.session.commit()
    from app.services import school_purge
    with pytest.raises(school_purge.PurgeRefused, match="export no longer matches"):
        _purge(console, A, backup)
    assert _all_counts(console, A["school"].id)["students"] >= 1


def test_every_table_the_purge_touches_is_exported(console, two_schools, uploads):
    """Tenant tables and link tables (no school_id, FK to a tenant table —
    none today since SAAS-019, but a future one is covered) all land in
    the manifest."""
    from app.services import school_export
    res = _export(console, two_schools["A"])
    touched = {t.name for t in school_export.tenant_tables()} | {t.name for t, _ in school_export.link_tables()}
    assert touched <= set(res["manifest"]["tables"])


def test_deactivating_second_owner_does_not_unlock_single_owner_path(console, two_schools, purge_world, backup):
    from app.extensions import db
    from app.models import PlatformUser
    A = two_schools["A"]
    ids = _ready(console, A, purge_approved_by=None, purge_approved_at=None)
    with console.app_context():
        db.session.get(PlatformUser, ids[1]).is_active = False
        db.session.commit()
    rep = _purge(console, A, backup)
    assert any("second owner" in p for p in rep["problems"])


def test_unarchive_resets_offboarding(console, two_schools, purge_world):
    from app.extensions import db
    from app.models import SchoolOffboarding
    A = two_schools["A"]
    _ready(console, A)
    c, _ = _console_client(console, "owner")
    with c.session_transaction(base_url=CONSOLE) as s:
        s["sa_totp_at"] = time.time()
    with console.app_context():
        from app.models import PlatformUser
        PlatformUser.query.filter_by(role="owner").update({"is_active": True})
        db.session.commit()
    c.post(f"/superadmin/schools/{A['school'].id}/lifecycle/unarchive", base_url=CONSOLE,
           data={"reason": "came back", "confirm_slug": A["school"].slug})
    with console.app_context():
        row = SchoolOffboarding.query.filter_by(school_id=A["school"].id).one()
        assert row.retention_until is None and row.purge_approved_by is None and row.export_verified_at is None


def test_export_skips_symlinks_out_of_the_school(console, two_schools, uploads, tmp_path, monkeypatch):
    import os
    A = two_schools["A"]
    folder = uploads / "up" / str(A["school"].id)
    folder.mkdir(parents=True)
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET")
    link = folder / "link.txt"
    try:
        os.symlink(secret, link)
    except (OSError, NotImplementedError):
        # no symlink privilege (Windows): simulate one so the rule is
        # still exercised — never a skipped test
        import pathlib
        link.write_text("TOP-SECRET")
        real = pathlib.Path.is_symlink
        monkeypatch.setattr(pathlib.Path, "is_symlink", lambda self: self == link or real(self))
    res = _export(console, A)
    with zipfile.ZipFile(res["path"]) as z:
        assert not any(n.startswith("files/link") for n in z.namelist())


def test_hash_columns_are_secret():
    from app.services.audit import is_secret_field
    assert is_secret_field("token_hash") and is_secret_field("code_hash") and is_secret_field("password_hash")


# ─── post-commit security review ─────────────────────────────────────

def test_csv_formula_cells_are_escaped(console, two_schools, uploads):
    import csv
    import io
    from app.extensions import db
    from app.models import Student
    A = two_schools["A"]
    with console.app_context():
        db.session.add(Student(school_id=A["school"].id, permanent_code="FX-1",
                               full_name='=HYPERLINK("http://x.test","a")'))
        db.session.commit()
        db.session.remove()
    res = _export(console, A)
    with zipfile.ZipFile(res["path"]) as z:
        rows = list(csv.reader(io.StringIO(z.read("tables/students.csv").decode("utf-8"))))
        assert json.loads(z.read("manifest.json"))["csv_formula_escape"] == "'"
    names = [r[rows[0].index("full_name")] for r in rows[1:]]
    assert "'=HYPERLINK(\"http://x.test\",\"a\")" in names
    assert not any(n.startswith(("=", "+", "-", "@")) for n in names)


def test_purge_refuses_an_edit_after_export_with_the_same_count(console, two_schools, purge_world, backup):
    from app.extensions import db
    from app.models import Student
    from app.services import school_purge
    A = two_schools["A"]
    _ready(console, A)
    with console.app_context():
        st = Student.query.filter_by(school_id=A["school"].id).first()
        st.full_name = "renamed after the export"
        db.session.commit()
        db.session.remove()
    with pytest.raises(school_purge.PurgeRefused, match="rows changed since the export"):
        _purge(console, A, backup)
    assert _all_counts(console, A["school"].id)["students"] >= 1


def test_approvals_required_cannot_be_lowered_first(console):
    from app.blueprints.superadmin.offboarding import approvals_required
    from app.extensions import db
    from app.models import PlatformAuditLog, PlatformUser
    import secrets
    now = datetime.now(timezone.utc)
    with console.app_context():
        db.session.begin_nested()
        try:
            PlatformUser.query.update({"role": "support"})
            keep = PlatformUser(email=f"solo-{secrets.token_hex(3)}@manasety.test", full_name="o",
                                role="owner", is_active=True)
            keep.set_password(secrets.token_urlsafe(16))
            db.session.add(keep)
            db.session.flush()
            assert approvals_required(now) == 1                    # really one owner
            other = PlatformUser(email=f"o2-{secrets.token_hex(3)}@manasety.test", full_name="o",
                                 role="owner", is_active=False)
            other.set_password(secrets.token_urlsafe(16))
            db.session.add(other)
            db.session.flush()
            assert approvals_required(now) == 2                    # a deactivated owner counts
            other.role = "support"
            db.session.flush()
            assert approvals_required(now) == 1
            db.session.add(PlatformAuditLog(action="platform_user_role", platform_user_id=keep.id,
                                            meta={"target_user_id": other.id, "role": "support",
                                                  "old_role": "owner"}, created_at=now))
            db.session.flush()
            assert approvals_required(now) == 2                    # demoted in the last 30 days
            assert approvals_required(now + timedelta(days=31)) == 1
        finally:
            db.session.rollback()
            db.session.remove()


def test_approver_must_predate_the_request(console, two_schools, purge_world, backup):
    from app.extensions import db
    from app.models import PlatformUser, SchoolOffboarding
    A = two_schools["A"]
    ids = _ready(console, A)
    # the purge itself refuses an approver made after the request
    with console.app_context():
        db.session.get(PlatformUser, ids[1]).created_at = datetime.now(timezone.utc)
        db.session.commit()
        db.session.remove()
    rep = _purge(console, A, backup, execute=False)
    assert any("created after the request" in p for p in rep["problems"])
    # and the console won't record such an approval
    with console.app_context():
        row = SchoolOffboarding.query.filter_by(school_id=A["school"].id).one()
        row.purge_approved_by = row.purge_approved_at = None
        db.session.commit()
        db.session.remove()
    c, uid = _console_client(console, "owner")             # created just now
    with c.session_transaction(base_url=CONSOLE) as s:
        s["sa_totp_at"] = time.time()
    c.post(f"/superadmin/schools/{A['school'].id}/offboarding/approve_purge", base_url=CONSOLE,
           data={"reason": "ok", "confirm_slug": A["school"].slug})
    with console.app_context():
        assert SchoolOffboarding.query.filter_by(school_id=A["school"].id).one().purge_approved_by is None
