"""Shared helpers for generating Student.permanent_code.

Historically this lived only inside students/routes.py; the bulk
import (platform/imports.py) needed the same logic. Extracted to a
service so both callers stay consistent.

Two entry points:
- `next_permanent_code(school)` — one-shot generation with a
  SELECT ... FOR UPDATE lock on the school row (per-request path).
- `PermanentCodeAllocator(school)` — batch allocator that computes
  the current max ONCE, then hands out sequential codes with an
  in-memory counter. Used by imports_commit so a 300-row file
  doesn't hit the DB 300 times.
"""

from typing import Optional

from ..extensions import db
from ..models import School, Student


def _prefix_for(school: School) -> str:
    base = (school.code or "SCH")
    return f"{base}-"


def _max_suffix(school_id: int, prefix: str) -> int:
    codes = (
        db.session.query(Student.permanent_code)
        .filter(Student.school_id == school_id,
                Student.permanent_code.like(f"{prefix}%"))
        .all()
    )
    max_n = 0
    for (code,) in codes:
        try:
            n = int(code[len(prefix):])
            if n > max_n:
                max_n = n
        except (ValueError, TypeError):
            continue
    return max_n


def next_permanent_code(school: Optional[School] = None,
                        *, school_id: Optional[int] = None) -> str:
    """One-shot next code with FOR UPDATE lock on the school row.

    Callers that already loaded the School can pass it in; the lock
    is still acquired via a re-query so we know the row is held for
    the current transaction until commit."""
    sid = school.id if school is not None else school_id
    if sid is None:
        raise ValueError("school or school_id required")
    locked = (
        db.session.query(School)
        .filter_by(id=sid)
        .with_for_update()
        .first()
    )
    if locked is None:
        raise ValueError("school not found")
    prefix = _prefix_for(locked)
    n = _max_suffix(sid, prefix) + 1
    return f"{prefix}{n:05d}"


class PermanentCodeAllocator:
    """Batch allocator — computes the current max once, then hands
    out sequential codes with an in-memory counter.

    Ticket B1 use case: imports_commit iterates hundreds of rows;
    calling `next_permanent_code` per row would MAX-scan every time.
    """
    def __init__(self, school: School):
        # Take the same FOR UPDATE lock so the whole batch is
        # serialized against other admissions running at the same
        # moment.
        locked = (
            db.session.query(School)
            .filter_by(id=school.id)
            .with_for_update()
            .first()
        )
        if locked is None:
            raise ValueError("school not found")
        self._school_id = locked.id
        self._prefix = _prefix_for(locked)
        self._next = _max_suffix(self._school_id, self._prefix) + 1

    def take(self) -> str:
        code = f"{self._prefix}{self._next:05d}"
        self._next += 1
        return code
