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
