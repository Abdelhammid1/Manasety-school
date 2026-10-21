"""Named run-once locks for CLI jobs: Postgres session advisory lock
(autocommit connection), process lock on SQLite dev/test."""
from __future__ import annotations

import hashlib
import threading
from contextlib import contextmanager

from sqlalchemy import text

from ..extensions import db

_local: dict[str, threading.Lock] = {}
_guard = threading.Lock()


class AlreadyRunning(Exception):
    pass


def _key(name: str) -> int:
    return int.from_bytes(hashlib.sha256(name.encode()).digest()[:4], "big")


@contextmanager
def named_lock(name: str):
    engine = db.engine
    if engine.dialect.name == "postgresql":
        conn = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        try:
            if not conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _key(name)}).scalar():
                raise AlreadyRunning(name)
            try:
                yield
            finally:
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _key(name)})
        finally:
            conn.close()
        return
    with _guard:
        lock = _local.setdefault(name, threading.Lock())
    if not lock.acquire(blocking=False):
        raise AlreadyRunning(name)
    try:
        yield
    finally:
        lock.release()


# ─── transaction-scoped, blocking (SAAS-033) ────────────────────────

_tx_locks: dict[str, threading.Lock] = {}


def _release_tx_locks(session, transaction):
    if transaction.parent is not None:
        return
    held = session.info.get("_tx_locks") or {}
    while held:
        _name, lock = held.popitem()
        lock.release()


def transaction_lock(name: str, timeout: float = 15) -> None:
    """Wait for `name` and hold it until the current transaction ends
    (commit, rollback or close). Postgres: pg_advisory_xact_lock; other
    databases: a process lock released by an after_transaction_end hook.
    For "read the max, write the next" sequences (invoice numbers)."""
    from sqlalchemy import event
    if db.engine.dialect.name == "postgresql":
        db.session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _key(name)})
        return
    sess = db.session()
    held = sess.info.setdefault("_tx_locks", {})
    if name in held:
        return
    if not sess.info.get("_tx_lock_listener"):
        event.listen(sess, "after_transaction_end", _release_tx_locks)
        sess.info["_tx_lock_listener"] = True
    with _guard:
        lock = _tx_locks.setdefault(name, threading.Lock())
    if not lock.acquire(timeout=timeout):
        raise AlreadyRunning(name)
    held[name] = lock
