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
from sqlalchemy.orm import MANYTOONE
from sqlalchemy.orm.base import NO_VALUE

from ..extensions import db

# (child_table, fk_column) pairs allowed to reference another school's
# row. Empty today; add with a reason when a real case appears.
CROSS_SCHOOL_OK: frozenset[tuple[str, str]] = frozenset()

# Platform (Super Admin) tables: they live outside every school, so they
# are neither tenant-owned nor inheriting. Some carry a school_id /
# target_school_id that POINTS at a school without belonging to it.
# Listed explicitly — a new table that is in neither this list nor the
# tenant world fails the schema gate (tests/test_saas002_schema_gate.py).
PLATFORM_TABLES: frozenset[str] = frozenset({
    "platform_users", "platform_recovery_codes", "platform_audit_logs",
    # SAAS-026
    "plans", "school_subscriptions", "school_subscription_events", "platform_settings",
    # SAAS-029
    "platform_jobs",
    # SAAS-030 — console-managed exceptions (keyed by school, never
    # written from a school host)
    "school_module_overrides", "school_feature_overrides", "school_limit_overrides",
    # SAAS-031
    "support_sessions", "support_session_events",
    # SAAS-032 — console-only, never written from a school host
    "school_slug_history", "platform_school_notes", "school_contacts", "school_tags",
    "platform_announcements",
    # SAAS-033
    "platform_invoices", "platform_invoice_lines", "platform_payments",
    # SAAS-034
    "platform_usage_snapshots", "platform_alerts",
    # SAAS-035
    "school_offboarding",
    # SAAS-036
    "platform_sessions", "platform_setup_tokens", "audit_prune_guard",
})
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


_OWNED_CACHE: dict = {}


def owned_tables() -> set[str]:
    """Tenant-owned table names. Cached: the metadata only changes when a
    model is imported (the key catches that), and this runs per flush."""
    key = (id(db.metadata), len(db.metadata.tables))
    hit = _OWNED_CACHE.get(key)
    if hit is None:
        hit = frozenset(t.name for t in db.metadata.tables.values()
                        if "school_id" in t.c and t.name != "schools"
                        and t.name not in PLATFORM_TABLES)
        _OWNED_CACHE.clear()
        _OWNED_CACHE[key] = hit
    return set(hit)


def edges() -> list[Edge]:
    owned = owned_tables()
    out = []
    for t in db.metadata.tables.values():
        if t.name not in owned:
            continue
        for fk in t.foreign_keys:
            col, parent = fk.parent.name, fk.column.table.name
            if col in _SKIP_COLUMNS or parent not in owned:
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

def _parent_school(session, cache, table, pk):
    """(found, school_id) of row `pk` in `table`. Pending objects with an
    explicit id are looked up in the session first; otherwise raw SQL,
    so the soft-delete filter can't hide a deleted parent of another
    school."""
    key = (table, pk)
    if key in cache:
        return cache[key]
    pending = cache.get("__pending__")
    if pending is None:
        # Built once per flush: only pending objects with an explicit id
        # can be referenced by id before the INSERT.
        pending = {}
        for o in session.new:
            t = getattr(inspect(o).mapper, "local_table", None)
            oid = getattr(o, "id", None)
            if t is not None and oid is not None:
                pending[(t.name, oid)] = o
        cache["__pending__"] = pending
    if key in pending:
        cache[key] = (True, _effective_school(session, cache, pending[key]))
        return cache[key]
    row = session.connection().execute(
        sa.text(f"SELECT school_id FROM {table} WHERE id = :i"), {"i": pk}).first()
    cache[key] = (False, None) if row is None else (True, row[0])
    return cache[key]


def _loaded_parent(state, column_name):
    """The object a MANYTOONE relationship over `column_name` currently
    holds (NO_VALUE when not loaded/set)."""
    for rel in state.mapper.relationships:
        if rel.direction is MANYTOONE and                 any(l.name == column_name for l, _ in rel.local_remote_pairs):
            return state.attrs[rel.key].loaded_value
    return NO_VALUE


def _column_value(state, column):
    try:
        key = state.mapper.get_property_by_column(column).key
    except Exception:  # noqa: BLE001 — column not mapped on this class
        key = column.name
    return getattr(state.obj(), key, None)


def _effective_school(session, cache, obj):
    """The school_id this row has, or will get from its column default:
    first parent with a known school (same order as inherited_school_id),
    then the current tenant. None when nothing determines it."""
    sid = getattr(obj, "school_id", None)
    if sid is not None:
        return sid
    state = inspect(obj)
    table = state.mapper.local_table
    col = table.c.get("school_id")
    if col is None:
        return None
    for parent_table, fk_col in col.info.get("tenant_parents", ()):
        parent_obj = _loaded_parent(state, fk_col)
        if parent_obj is not NO_VALUE and parent_obj is not None:
            psid = _effective_school(session, cache, parent_obj)
            if psid is not None:
                return psid
        pid = _column_value(state, table.c[fk_col])
        if pid is not None:
            found, psid = _parent_school(session, cache, parent_table, pid)
            if found and psid is not None:
                return psid
    from .tenancy import TenantNotResolved, current_school_id
    try:
        return current_school_id()
    except TenantNotResolved:
        return None


def check_instance(session, obj, cache=None) -> None:
    cache = {} if cache is None else cache
    state = inspect(obj)
    table = getattr(state.mapper, "local_table", None)
    if table is None or "school_id" not in table.c:
        return
    sid = _effective_school(session, cache, obj)
    if sid is None:
        if table.c.school_id.nullable:
            return          # shared / catalogue row
        raise TenantIntegrityError(f"{table.name}: cannot determine the row's school")
    owned = owned_tables()
    for fk in table.foreign_keys:
        col, parent = fk.parent.name, fk.column.table.name
        if col in _SKIP_COLUMNS or parent not in owned or (table.name, col) in CROSS_SCHOOL_OK:
            continue
        # Check BOTH the relationship object and the FK column: either may
        # be the stale one until the flush syncs them.
        candidates = []
        parent_obj = _loaded_parent(state, col)
        if parent_obj is not NO_VALUE and parent_obj is not None:
            candidates.append(("object", True, _effective_school(session, cache, parent_obj)))
        pid = _column_value(state, fk.parent)
        if pid is not None:
            found, psid = _parent_school(session, cache, parent, pid)
            candidates.append((pid, found, psid))
        for ref, found, psid in candidates:
            if not found:
                raise TenantIntegrityError(
                    f"{table.name}.{col} -> {parent}: parent {ref} does not exist")
            if psid is not None and int(psid) != int(sid):
                raise TenantIntegrityError(
                    f"{table.name}.{col} -> {parent}: row of school {sid} "
                    f"cannot point at a {parent} row of school {psid}")


def _before_flush(session, flush_context, instances):
    cache: dict = {}
    for obj in list(session.new) + list(session.dirty):
        if obj in session.new or session.is_modified(obj, include_collections=False):
            check_instance(session, obj, cache)


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
