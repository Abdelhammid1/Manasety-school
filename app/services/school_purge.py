"""SAAS-035 — permanent, controlled deletion of one school's data.

Refused unless EVERY condition holds (each one is tested on its own):
  - the school is archived and its retention period is over
  - a verified export exists (school_offboarding.export_verified_at)
  - two approvals from two different owners — or, when the platform has
    a single owner, one approval and 24 h between request and purge
  - the slug typed back as confirmation
  - --backup-file: a non-empty file modified within the last hour
    (the command never makes the backup itself)

Delete order comes from the foreign keys (topological, children first),
over the tenant tables only; nullable links between doomed rows are
cleared first so FK cycles (roles ↔ users) can't block it. All in one
transaction, checked before commit: the school has 0 rows everywhere and
every other school has exactly the rows it had. Any difference → rollback.
Then UPLOAD_ROOT/<id> is removed. The schools row stays as a "witness"
(platform invoices, subscriptions and audit point at it): name replaced,
contact data / settings / logo / SMTP secrets wiped, archived, purged_at
set, the slug reserved forever. Dry run is the default.
"""
from __future__ import annotations

import os
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select

from ..extensions import db

BACKUP_MAX_AGE = timedelta(hours=1)
SINGLE_OWNER_WAIT = timedelta(hours=24)
WIPE_FIELDS = ("phone", "address", "email", "website", "legal_name_ar", "legal_name_en", "logo_url",
               "license_number", "tax_number", "invoice_header_text", "invoice_footer_text",
               "invoice_policy_text", "smtp_host", "smtp_username", "smtp_password_encrypted",
               "smtp_from_name", "smtp_from_email", "blocked_message")


class PurgeRefused(RuntimeError):
    pass


def _aware(dt):
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))


def check_conditions(school, *, confirm_slug: str, backup_file: str | None, now=None) -> list[str]:
    from ..models import PlatformUser, SchoolOffboarding
    now = now or datetime.now(timezone.utc)
    problems = []
    off = SchoolOffboarding.query.filter_by(school_id=school.id).first()
    if school.status != "archived":
        problems.append("school is not archived")
    if off is None:
        problems.append("no offboarding record")
        return problems
    if off.purged_at is not None:
        problems.append("already purged")
    if off.retention_until is None or _aware(off.retention_until) > now:
        problems.append("retention period not over")
    if off.export_verified_at is None or not off.export_file:
        problems.append("no verified export (run school-export --verify)")

    def active_owner(uid):
        u = db.session.get(PlatformUser, uid) if uid else None
        return u is not None and u.is_active and u.role == "owner"

    archived = _aware(off.archived_at)
    requested = _aware(off.purge_requested_at)
    if off.purge_requested_by is None or requested is None:
        problems.append("purge not requested")
    elif archived is None or requested <= archived:
        problems.append("purge request older than the archive")
    elif not active_owner(off.purge_requested_by):
        problems.append("requesting owner is no longer an active owner")
    elif (off.approvals_required or 2) > 1:
        # fixed when requested: deactivating the other owner later can't
        # turn this into the single-owner path
        approved = _aware(off.purge_approved_at)
        if off.purge_approved_by is None or off.purge_approved_by == off.purge_requested_by \
                or approved is None or approved <= requested:
            problems.append("needs approval by a second owner")
        elif not active_owner(off.purge_approved_by):
            problems.append("approving owner is no longer an active owner")
        elif _aware(getattr(db.session.get(PlatformUser, off.purge_approved_by), "created_at", None)
                    or requested) >= requested:
            problems.append("approving owner was created after the request")
    elif now - requested < SINGLE_OWNER_WAIT:
        problems.append("single owner: 24 h must pass after the request")
    if (confirm_slug or "").strip() != school.slug:
        problems.append("confirmation slug does not match")
    if not backup_file:
        problems.append("--backup-file is required")
    else:
        p = Path(backup_file)
        try:
            st = p.stat()
            if st.st_size <= 0:
                problems.append("backup file is empty")
            if time.time() - st.st_mtime > BACKUP_MAX_AGE.total_seconds():
                problems.append("backup file is older than 1 hour")
        except OSError:
            problems.append("backup file not found")
    return problems


def _tables():
    from .school_export import tenant_tables
    return tenant_tables()


def counts(conn, tables) -> dict[str, dict[int, int]]:
    """{table: {school_id: rows}} for every tenant table."""
    out = {}
    for t in tables:
        out[t.name] = dict(conn.execute(select(t.c.school_id, func.count()).group_by(t.c.school_id)).all())
    return out


def plan(school_id: int) -> list[tuple[str, int]]:
    with db.engine.connect() as conn:
        return [(t.name, conn.execute(select(func.count()).select_from(t)
                                      .where(t.c.school_id == school_id)).scalar())
                for t in _tables()]


def _delete_rows(conn, school_id, tables):
    names = {t.name for t in tables}
    # 1. clear nullable links between rows that are about to go (cycles)
    for t in tables:
        for fk in t.foreign_keys:
            parent = fk.column.table
            if parent.name in names and fk.parent.nullable and "school_id" in parent.c:
                ids = select(parent.c[fk.column.name]).where(parent.c.school_id == school_id)
                conn.execute(t.update().where(t.c.school_id == school_id, fk.parent.in_(ids))
                             .values({fk.parent.name: None}))
    # 2. link tables without a school_id of their own (subject_grades …):
    #    their rows point at doomed rows
    from .tenant_guard import PLATFORM_TABLES
    for t in reversed(db.metadata.sorted_tables):
        if "school_id" in t.c or t.name in PLATFORM_TABLES or t.name == "schools":
            continue
        for fk in t.foreign_keys:
            parent = fk.column.table
            if parent.name in names:
                ids = select(parent.c[fk.column.name]).where(parent.c.school_id == school_id)
                conn.execute(t.delete().where(fk.parent.in_(ids)))
    # 3. children first (reverse dependency order)
    for t in reversed(tables):
        conn.execute(t.delete().where(t.c.school_id == school_id))


def _witness(conn, school):
    from ..models import School
    t = School.__table__
    values = {f: None for f in WIPE_FIELDS if f in t.c and t.c[f].nullable}
    values.update(name=f"[مدرسة محذوفة #{school.id}]", status="archived", is_active=False)
    conn.execute(t.update().where(t.c.id == school.id).values(values))


def purge(school, *, confirm_slug: str, backup_file: str | None, execute: bool = False,
          user=None) -> dict:
    """Dry run by default: returns the plan. With execute=True, deletes."""
    from ..models import SchoolOffboarding
    from .file_storage import upload_root
    from .platform_auth import audit
    from .tenant_guard import integrity_report
    problems = check_conditions(school, confirm_slug=confirm_slug, backup_file=backup_file)
    report = {"plan": plan(school.id), "problems": problems, "executed": False}
    if problems or not execute:
        return report
    tables = _tables()
    sid = school.id
    db.session.commit()                    # nothing pending on the ORM side
    with db.engine.connect() as conn:
        if conn.dialect.name == "postgresql":
            conn = conn.execution_options(isolation_level="REPEATABLE READ")
        tx = conn.begin()
        try:
            from .school_export import exports_dir, link_count, link_tables, verify
            if conn.dialect.name == "postgresql":
                from ..models import School
                conn.execute(select(School.__table__.c.id).where(School.__table__.c.id == sid).with_for_update())
                conn.execute(select(SchoolOffboarding.__table__.c.id)
                             .where(SchoolOffboarding.__table__.c.school_id == sid).with_for_update())
            off = SchoolOffboarding.query.filter_by(school_id=sid).first()
            # what's about to go must be exactly what was exported
            stale = verify(str(exports_dir() / (off.export_file or "-")), school_id=sid, conn=conn)
            if stale:
                raise PurgeRefused("export no longer matches the data: " + "; ".join(stale[:5]))
            links = link_tables()
            link_before = {t.name: (conn.execute(select(func.count()).select_from(t)).scalar(),
                                    link_count(conn, t, fks, sid)) for t, fks in links}
            before = counts(conn, tables)
            _delete_rows(conn, sid, tables)
            after = counts(conn, tables)
            for t, fks in links:
                total, mine = link_before[t.name]
                if conn.execute(select(func.count()).select_from(t)).scalar() != total - mine:
                    raise PurgeRefused(f"safety check failed: {t.name} lost rows of another school")
            leftover = {n: c.get(sid, 0) for n, c in after.items() if c.get(sid, 0)}
            changed = {n for n in before
                       if {k: v for k, v in before[n].items() if k != sid}
                       != {k: v for k, v in after[n].items() if k != sid}}
            if leftover or changed:
                raise PurgeRefused(f"safety check failed: leftover={leftover} other_schools_changed={sorted(changed)}")
            if any(integrity_report(conn).values()):
                raise PurgeRefused("tenant integrity check failed after delete")
            _witness(conn, school)
            off_t = SchoolOffboarding.__table__
            conn.execute(off_t.update().where(off_t.c.school_id == sid)
                         .values(purged_at=datetime.now(timezone.utc)))
            tx.commit()
        except Exception:
            tx.rollback()
            raise
    folder = Path(upload_root()) / str(sid)
    if folder.is_dir():
        shutil.rmtree(folder)
    db.session.expire_all()
    audit("school_purged", user, school_id=sid, tables=len(tables),
          rows=sum(n for _, n in report["plan"]))
    db.session.commit()
    report["executed"] = True
    return report
