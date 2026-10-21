"""SAAS-035 — export everything a school owns, as a zip:

  tables/<table>.csv   every table with a school_id (found from
                       db.metadata, not a hand-written list), only this
                       school's rows, secret columns left out
  files/…              a copy of UPLOAD_ROOT/<school_id>
  manifest.json        {table: {rows, sha256}} + files + meta
  README.md            the columns of each table

Read in one transaction (REPEATABLE READ on Postgres) inside
platform_read_scope(), so the manifest's counts are the data at one
instant. Run from the CLI or the job queue — never inside a web request.
The zip lives under UPLOAD_ROOT/_platform/exports (mode 600) and is
deleted after EXPORT_TTL_DAYS.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from ..extensions import db

EXPORT_TTL_DAYS = 7


def exports_dir() -> Path:
    from .file_storage import upload_root
    d = Path(upload_root()) / "_platform" / "exports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def tenant_tables():
    """Tables a school owns (school_id column), platform tables excluded."""
    from .tenant_guard import PLATFORM_TABLES
    return [t for t in db.metadata.sorted_tables
            if "school_id" in t.c and t.name not in PLATFORM_TABLES and t.name != "schools"]


def link_tables():
    """[(table, fk)] for tables WITHOUT a school_id whose FK points at a
    tenant table (subject_grades …). Their rows belong to whoever owns
    the parent row; the export and the purge both cover them."""
    from .tenant_guard import PLATFORM_TABLES
    tenant = {t.name for t in tenant_tables()}
    out = []
    for t in db.metadata.sorted_tables:
        if "school_id" in t.c or t.name in PLATFORM_TABLES or t.name == "schools":
            continue
        fks = [fk for fk in t.foreign_keys if fk.column.table.name in tenant]
        if fks:
            out.append((t, fks))
    return out


def _link_where(table, fks, school_id):
    from sqlalchemy import or_
    return or_(*[fk.parent.in_(select(fk.column.table.c[fk.column.name])
                               .where(fk.column.table.c.school_id == school_id)) for fk in fks])


def link_count(conn, table, fks, school_id) -> int:
    from sqlalchemy import func
    return conn.execute(select(func.count()).select_from(table)
                        .where(_link_where(table, fks, school_id))).scalar()


def exported_columns(table):
    from .audit import is_secret_field
    return [c for c in table.c if not is_secret_field(c.name)]


def _csv(conn, table, school_id, where=None) -> tuple[bytes, int]:
    cols = exported_columns(table)
    cond = table.c.school_id == school_id if where is None else where
    order = list(table.primary_key.columns) or cols[:1]
    rows = conn.execute(select(*cols).where(cond).order_by(*order)).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([c.name for c in cols])
    for r in rows:
        w.writerow(["" if v is None else (v.isoformat() if hasattr(v, "isoformat") else v) for v in r])
    return buf.getvalue().encode("utf-8"), len(rows)


def _school_row(conn, school_id):
    from ..models import School
    t = School.__table__
    cols = exported_columns(t)
    r = conn.execute(select(*cols).where(t.c.id == school_id)).first()
    return {c.name: (v.isoformat() if hasattr(v, "isoformat") else v) for c, v in zip(cols, r)}


def export_school(school_id: int, user=None) -> dict:
    """Write the zip; returns {path, manifest}."""
    from ..models import School
    school = db.session.get(School, school_id)
    if school is None:
        raise ValueError("unknown school")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = exports_dir() / f"{school.slug}-{school.id}-{stamp}.zip"
    manifest = {"school_id": school.id, "slug": school.slug, "created_at": stamp, "tables": {}, "files": []}
    readme = [f"# تصدير {school.name}\n", "كل ملف CSV فيه صفوف المدرسة دي بس. الأعمدة السرية مستبعدة.\n"]
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        _write_zip(os.fdopen(fd, "wb"), school, manifest, readme, user)
    except BaseException:
        Path(path).unlink(missing_ok=True)
        raise
    return {"path": str(path), "manifest": manifest}


def _write_zip(fh, school, manifest, readme, user):
    from .file_storage import upload_root
    from .platform_scope import platform_read_scope
    with platform_read_scope("school_export_read", user, school_id=school.id):
        with db.engine.connect() as conn:
            if conn.dialect.name == "postgresql":
                conn = conn.execution_options(isolation_level="REPEATABLE READ")
            with conn.begin(), fh, zipfile.ZipFile(fh, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr("tables/schools.json", json.dumps(_school_row(conn, school.id),
                                                             ensure_ascii=False, indent=1, default=str))
                for t in tenant_tables():
                    data, n = _csv(conn, t, school.id)
                    z.writestr(f"tables/{t.name}.csv", data)
                    manifest["tables"][t.name] = {"rows": n, "sha256": hashlib.sha256(data).hexdigest()}
                    readme.append(f"\n## {t.name} ({n})\n" + ", ".join(c.name for c in exported_columns(t)) + "\n")
                for t, fks in link_tables():
                    data, n = _csv(conn, t, school.id, where=_link_where(t, fks, school.id))
                    z.writestr(f"tables/{t.name}.csv", data)
                    manifest["tables"][t.name] = {"rows": n, "sha256": hashlib.sha256(data).hexdigest(),
                                                  "link": True}
                root = Path(upload_root()) / str(school.id)
                if root.is_dir():
                    real_root = root.resolve()
                    for f in sorted(root.rglob("*")):
                        # 7. never follow a symlink out of the school's folder
                        if f.is_symlink() or not f.resolve().is_relative_to(real_root):
                            continue
                        if f.is_file():
                            rel = f.relative_to(root).as_posix()
                            z.write(f, f"files/{rel}")
                            manifest["files"].append({"path": rel, "bytes": f.stat().st_size})
                z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
                z.writestr("README.md", "".join(readme))


def verify(path: str, *, school_id: int | None = None, conn=None) -> list[str]:
    """Re-count the school's rows (tenant AND link tables) and compare with
    the manifest and the CSV checksums. [] = verified."""
    from sqlalchemy import func
    from .platform_scope import platform_read_scope
    problems = []
    try:
        z = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile):
        return ["export file missing or unreadable"]
    with z:
        manifest = json.loads(z.read("manifest.json"))
        sid = manifest["school_id"]
        if school_id is not None and sid != school_id:
            return ["export belongs to another school"]
        for name, meta in manifest["tables"].items():
            data = z.read(f"tables/{name}.csv")
            if hashlib.sha256(data).hexdigest() != meta["sha256"]:
                problems.append(f"{name}: checksum mismatch")

    def check(c):
        for t in tenant_tables():
            want = manifest["tables"].get(t.name, {}).get("rows")
            have = c.execute(select(func.count()).select_from(t).where(t.c.school_id == sid)).scalar()
            if want is None:
                problems.append(f"{t.name}: missing from the manifest")
            elif have != want:
                problems.append(f"{t.name}: {have} rows now, {want} in the manifest")
        for t, fks in link_tables():
            want = manifest["tables"].get(t.name, {}).get("rows")
            have = link_count(c, t, fks, sid)
            if want is None:
                problems.append(f"{t.name}: missing from the manifest")
            elif have != want:
                problems.append(f"{t.name}: {have} rows now, {want} in the manifest")
    if conn is not None:
        check(conn)
    else:
        with platform_read_scope("school_export_verify", None, school_id=sid):
            with db.engine.connect() as c:
                check(c)
    return problems


def prune_old_exports(days: int = EXPORT_TTL_DAYS) -> int:
    from ..models import SchoolOffboarding
    keep = {r.export_file for r in SchoolOffboarding.query.filter(SchoolOffboarding.purged_at.is_(None))
            if r.export_file}
    cutoff = datetime.now().timestamp() - days * 86400
    n = 0
    for f in exports_dir().glob("*.zip"):
        if f.name not in keep and f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)
            n += 1
    return n


def run_export_queue() -> int:
    """`flask school-export --from-queue`: run every pending export job."""
    from ..models import PlatformJob
    from .audit import redact
    jobs = PlatformJob.query.filter_by(kind="school_export", status="pending").all()
    for j in jobs:
        j.status, j.started_at = "running", datetime.now(timezone.utc)
        db.session.commit()
        try:
            res = export_school(j.school_id)
            problems = verify(res["path"])
            j.status = "succeeded" if not problems else "failed"
            j.result = {"file": Path(res["path"]).name, "verified": not problems,
                        "tables": len(res["manifest"]["tables"])}
            j.log = redact("\n".join(problems)) if problems else None
            if not problems:
                mark_verified(j.school_id, j.id, Path(res["path"]).name)
        except Exception as e:  # noqa: BLE001
            db.session.rollback()
            j.status, j.log = "failed", f"{type(e).__name__}"
        j.finished_at = datetime.now(timezone.utc)
        db.session.commit()
    prune_old_exports()
    return len(jobs)


def mark_verified(school_id: int, job_id: int | None, file_name: str | None) -> None:
    from ..models import SchoolOffboarding
    row = SchoolOffboarding.query.filter_by(school_id=school_id).first()
    if row is not None:
        row.export_job_id = job_id
        row.export_file = file_name
        row.export_verified_at = datetime.now(timezone.utc)
