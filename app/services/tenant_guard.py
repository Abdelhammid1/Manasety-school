"""SAAS-022 — keep every row in the same school as its parents.

Two layers:
  * `install(app)` registers a `before_flush` listener: for every new or
    changed ORM instance that has a school_id, each FK to another
    school-owned table must point at a row of the SAME school, otherwise
    the whole flush fails with TenantIntegrityError.
  * `integrity_report()` (CLI: `flask tenant-integrity-check`) scans
    every such FK edge in SQL — it catches what the ORM listener cannot
    see: raw SQL, bulk Query.update(), connection.execute() (e.g. the
    audit writer in services/audit.py, which is deliberately outside
    the ORM).

Edges that legitimately cross schools are listed in CROSS_SCHOOL_OK.
Parents whose school_id is NULL (shared catalogs, decision D4) are
never a violation.
"""
from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy import event, inspect

from ..extensions import db

# (child_table, fk_column) pairs allowed to reference another school's
# row. Empty today; add with a reason when a real case appears.
CROSS_SCHOOL_OK: frozenset[tuple[str, str]] = frozenset()
# school_id is the tenant itself; deleted_by_id is soft-delete
# bookkeeping (who pressed delete), not ownership.
_SKIP_COLUMNS = {"school_id", "deleted_by_id"}


class TenantIntegrityError(RuntimeError):
    """A row would link to a parent of another school."""


@dataclass(frozen=True)
class Edge:
    child: str
    column: str
    parent: str


def owned_tables() -> set[str]:
    return {t.name for t in db.metadata.tables.values()
            if "school_id" in t.c and t.name != "schools"}


def edges() -> list[Edge]:
    owned = owned_tables()
    out = []
    for t in db.metadata.tables.values():
        if t.name not in owned:
            continue
        for fk in t.foreign_keys:
            col, parent = fk.parent.name, fk.column.table.name
            if col in _SKIP_COLUMNS or parent not in owned or parent == t.name:
                continue
            if (t.name, col) in CROSS_SCHOOL_OK:
                continue
            out.append(Edge(t.name, col, parent))
    return out


# ─── SQL integrity scan ─────────────────────────────────────────────

def integrity_report(conn=None) -> dict[str, int]:
    """{ "child.column -> parent": violations } for every edge."""
    conn = conn or db.session.connection()
    report = {}
    for e in edges():
        n = conn.execute(sa.text(
            f"SELECT COUNT(*) FROM {e.child} c JOIN {e.parent} p ON p.id = c.{e.column} "
            f"WHERE p.school_id IS NOT NULL AND c.school_id IS NOT NULL "
            f"AND p.school_id != c.school_id")).scalar()
        report[f"{e.child}.{e.column} -> {e.parent}"] = int(n or 0)
    return report


# ─── ORM flush guard ────────────────────────────────────────────────

def _mapper_for_table(name):
    for m in db.Model.registry.mappers:  # type: ignore[attr-defined]
        if getattr(m, "local_table", None) is not None and m.local_table.name == name:
            return m.class_
    return None


def _parent_school(session, table, pk):
    cls = _mapper_for_table(table)
    if cls is not None:
        obj = session.get(cls, pk)
        return getattr(obj, "school_id", None) if obj is not None else None
    return session.execute(sa.text(f"SELECT school_id FROM {table} WHERE id = :i"),
                           {"i": pk}).scalar()


def _effective_school(session, obj, table):
    sid = getattr(obj, "school_id", None)
    if sid is not None:
        return sid
    # Not set yet: the inherited_school_id default will copy it from the
    # first parent present at INSERT time — predict the same value.
    col = table.c.school_id
    for parent_table, fk_col in col.info.get("tenant_parents", ()):
        pid = getattr(obj, fk_col, None)
        if pid is not None:
            return _parent_school(session, parent_table, pid)
    return None


def check_instance(session, obj) -> None:
    table = getattr(inspect(obj).mapper, "local_table", None)
    if table is None or "school_id" not in table.c:
        return
    owned = owned_tables()
    sid = _effective_school(session, obj, table)
    if sid is None:
        return
    for fk in table.foreign_keys:
        col, parent = fk.parent.name, fk.column.table.name
        if col in _SKIP_COLUMNS or parent not in owned or (table.name, col) in CROSS_SCHOOL_OK:
            continue
        try:
            attr = inspect(obj).mapper.get_property_by_column(fk.parent).key
        except Exception:  # noqa: BLE001 — column not mapped on this class
            attr = col
        pid = getattr(obj, attr, None)
        if pid is None:
            continue
        psid = _parent_school(session, parent, pid)
        if psid is not None and int(psid) != int(sid):
            raise TenantIntegrityError(
                f"{table.name}.{col} -> {parent}: row of school {sid} "
                f"cannot point at a {parent} row of school {psid}")


def _before_flush(session, flush_context, instances):
    for obj in list(session.new) + list(session.dirty):
        if session.is_modified(obj, include_collections=False) or obj in session.new:
            check_instance(session, obj)


def install(app) -> None:
    # Bound to THIS db's session factory, not the global Session class,
    # so a re-imported app (tests) never runs a stale listener.
    if not event.contains(db.session, "before_flush", _before_flush):
        event.listen(db.session, "before_flush", _before_flush)

    @app.cli.command("tenant-integrity-check")
    def _cli():
        """Count cross-school FK links; exit 1 when any exist."""
        import sys
        import click
        report = integrity_report()
        bad = {k: v for k, v in report.items() if v}
        for k, v in sorted(report.items()):
            if v:
                click.echo(f"VIOLATION {k}: {v}")
        click.echo(f"checked {len(report)} edges, {sum(bad.values())} violation(s)")
        sys.exit(1 if bad else 0)
