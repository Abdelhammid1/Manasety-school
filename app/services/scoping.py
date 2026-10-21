"""Isolation sweep (SAAS-013B..017) — the one way a view loads a row by an
id that came from the URL, the form or a JSON body.

    owned_or_404(Student, student_id)          -> the row, or 404
    owned_many_or_404(Invoice, invoice_ids)    -> all rows, or 404 if ANY
                                                  id is missing / foreign

A foreign id and a missing id get exactly the same 404 (no enumeration:
same status, same body). Soft-deleted rows count as missing unless
`include_deleted=True`.
"""
from __future__ import annotations

from typing import Iterable

from flask import abort


def _sid() -> int:
    from .tenancy import current_school_id
    return int(current_school_id())


def _query(model, include_deleted: bool):
    q = model.query
    if not include_deleted and hasattr(model, "deleted_at"):
        q = q.filter(model.deleted_at.is_(None))
    return q


def owned_or_404(model, oid, *, include_deleted: bool = False):
    """The `model` row with this id in the current school, else 404."""
    try:
        oid = int(oid)
    except (TypeError, ValueError):
        abort(404)
    obj = _query(model, include_deleted).filter(model.id == oid, model.school_id == _sid()).first()
    if obj is None:
        abort(404)
    return obj


def owned_or_none(model, oid, *, include_deleted: bool = False):
    """Same check for an OPTIONAL id: None when empty, 404 when foreign."""
    if oid in (None, "", 0):
        return None
    return owned_or_404(model, oid, include_deleted=include_deleted)


def owned_many_or_404(model, ids: Iterable, *, include_deleted: bool = False) -> list:
    """Every id must belong to the current school — one foreign id and the
    whole request is a 404, before anything is written (no partial work)."""
    try:
        wanted = {int(i) for i in ids if i not in (None, "")}
    except (TypeError, ValueError):
        abort(404)
    if not wanted:
        return []
    rows = _query(model, include_deleted).filter(model.id.in_(wanted), model.school_id == _sid()).all()
    if len(rows) != len(wanted):
        abort(404)
    by_id = {r.id: r for r in rows}
    return [by_id[i] for i in sorted(wanted)]
