"""SAAS-025 — the ONLY way platform code reads across schools.

`platform_read_scope(action, user, school_id=None)` records the read in
platform_audit_logs, then opens a read-only window: any attempt to
write a school-owned row inside it fails the flush. The tenant guard
(SAAS-022) stays installed and untouched.

Allowed callers: app/blueprints/superadmin/ and app/services/platform*.py
(enforced by tests/test_saas025_platform.py).
"""
from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import event

from ..extensions import db

_FLAG = "platform_read_only"


class PlatformReadOnlyError(RuntimeError):
    pass


@contextmanager
def platform_read_scope(action: str, user, school_id=None, **meta):
    from .platform_auth import audit
    audit(action, user, school_id=school_id, **meta)
    db.session.commit()
    sess = db.session()
    sess.info[_FLAG] = sess.info.get(_FLAG, 0) + 1
    try:
        yield
    finally:
        sess.info[_FLAG] -= 1
        if not sess.info[_FLAG]:
            sess.info.pop(_FLAG)


def _refuse_writes(session, flush_context, instances):
    if not session.info.get(_FLAG):
        return
    from .tenant_guard import PLATFORM_TABLES
    for obj in list(session.new) + list(session.dirty) + list(session.deleted):
        table = getattr(getattr(obj, "__table__", None), "name", None)
        if table not in PLATFORM_TABLES:
            raise PlatformReadOnlyError(
                f"write to {table} inside platform_read_scope (read-only)")


def install() -> None:
    if not event.contains(db.session, "before_flush", _refuse_writes):
        event.listen(db.session, "before_flush", _refuse_writes)
