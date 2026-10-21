"""SAAS-030 — plan limits (students, staff users, storage).

Effective limit = school_limit_overrides value if set, else the plan's,
else unlimited. Enforced only when something is ADDED: nothing is ever
deleted or disabled, even if a school sits above its limit after a
downgrade.

Counting (single definition, reused by SAAS-034):
  students — no enrollment yet, or whose latest enrollment isn't
             withdrawn / transferred / graduated
  users    — active users whose role is neither student nor parent; the
             platform support user (SAAS-031) is never counted
  storage  — bytes under UPLOAD_ROOT/<school_id>

Race safety: check_and_reserve() locks the school row (SELECT … FOR
UPDATE on Postgres; a process lock held until commit/rollback on SQLite)
so two concurrent requests can't both take the last slot.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import event, func

from ..extensions import db

KINDS = ("students", "users", "storage")
WARN_RATIO = 0.9
NON_STAFF_ROLES = ("student", "parent")
MB = 1024 * 1024
LABELS_AR = {"students": "الطلاب", "users": "المستخدمين", "storage": "التخزين"}


class LimitReached(Exception):
    def __init__(self, kind: str, limit: int, remaining: int = 0):
        self.kind, self.limit, self.remaining = kind, limit, remaining
        shown = f"{limit} MB" if kind == "storage" else str(limit)
        super().__init__(f"وصلت للحد الأقصى للباقة ({shown}). تواصل مع الدعم للترقية.")

    def api_body(self):
        return {"error": "limit_reached", "limit": self.kind, "message_ar": str(self)}


@dataclass
class Usage:
    students: int
    users: int
    storage_bytes: int

    @property
    def storage_mb(self) -> float:
        return self.storage_bytes / MB

    def value(self, kind):
        return {"students": self.students, "users": self.users,
                "storage": self.storage_mb}[kind]


def storage_bytes(school_id: int) -> int:
    from .file_storage import upload_root
    root = Path(upload_root()) / str(int(school_id))
    total = 0
    if root.is_dir():
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                try:
                    total += (Path(dirpath) / f).stat().st_size
                except OSError:
                    pass
    return total


def _staff_users_query(school_id: int):
    from ..models import Role, User
    q = (db.session.query(func.count(User.id)).join(Role, Role.id == User.role_id)
         .filter(User.school_id == school_id, User.is_active.is_(True),
                 Role.name.notin_(NON_STAFF_ROLES)))
    if hasattr(User, "is_platform_support"):
        q = q.filter(User.is_platform_support.is_(False))
    return q


INACTIVE_ENROLLMENT = ("withdrawn", "transferred", "graduated")


def active_students(school_id: int) -> int:
    from sqlalchemy import or_, select
    from ..models import Enrollment, Student
    latest = (select(Enrollment.student_id, func.max(Enrollment.id).label("eid"))
              .where(Enrollment.school_id == school_id)
              .group_by(Enrollment.student_id).subquery())
    n = (db.session.query(func.count(Student.id))
         .outerjoin(latest, latest.c.student_id == Student.id)
         .outerjoin(Enrollment, Enrollment.id == latest.c.eid)
         .filter(Student.school_id == school_id,
                 or_(Enrollment.id.is_(None), Enrollment.status.notin_(INACTIVE_ENROLLMENT)))
         .scalar())
    return int(n or 0)


def school_usage(school_id: int, *, with_storage: bool = True) -> Usage:
    students = active_students(school_id)
    return Usage(students=int(students or 0), users=int(_staff_users_query(school_id).scalar() or 0),
                 storage_bytes=storage_bytes(school_id) if with_storage else 0)


def effective_limits(school_id: int) -> dict[str, int | None]:
    from ..models import SchoolLimitOverride
    from .subscriptions import current_subscription
    sub = current_subscription(school_id)
    plan = sub.plan if sub is not None else None
    out = {"students": getattr(plan, "max_students", None), "users": getattr(plan, "max_users", None),
           "storage": getattr(plan, "max_storage_mb", None)}
    o = db.session.get(SchoolLimitOverride, school_id)
    if o is not None:
        for kind, col in (("students", "max_students"), ("users", "max_users"),
                          ("storage", "max_storage_mb")):
            if getattr(o, col) is not None:
                out[kind] = getattr(o, col)
    return out


def limit_report(school_id: int) -> list[dict]:
    """[{kind, label, used, limit, ratio, warn, full}] for banners / console."""
    usage, limits = school_usage(school_id), effective_limits(school_id)
    rows = []
    for kind in KINDS:
        lim, used = limits[kind], usage.value(kind)
        ratio = (used / lim) if lim else None
        rows.append({"kind": kind, "label": LABELS_AR[kind], "used": used, "limit": lim,
                     "ratio": ratio, "warn": ratio is not None and ratio >= WARN_RATIO,
                     "full": ratio is not None and ratio >= 1})
    return rows


# ─── locking ────────────────────────────────────────────────────────

_proc_locks: dict[int, threading.Lock] = {}
_proc_guard = threading.Lock()


def _release_held(session, transaction):
    """The outermost transaction ended (commit, rollback or close at
    request teardown): free every school slot lock this session holds."""
    if transaction.parent is not None:
        return
    held = session.info.get("_limit_locks") or {}
    while held:
        _sid, lock = held.popitem()
        lock.release()


def _lock_school(school_id: int) -> None:
    from ..models import School
    if db.engine.dialect.name == "postgresql":
        # Row lock, held by the database until this transaction ends.
        # FOR NO KEY UPDATE: serialises check_and_reserve callers but,
        # unlike FOR UPDATE, doesn't block the FOR KEY SHARE every insert
        # with a school_id FK takes (audit: stalls + deadlocks)
        db.session.query(School.id).filter(School.id == school_id) \
            .with_for_update(key_share=True).one()
        return
    sess = db.session()
    held = sess.info.setdefault("_limit_locks", {})
    if school_id in held:
        return
    if not sess.info.get("_limit_listener"):
        event.listen(sess, "after_transaction_end", _release_held)
        sess.info["_limit_listener"] = True
    with _proc_guard:
        lock = _proc_locks.setdefault(school_id, threading.Lock())
    if not lock.acquire(timeout=15):
        raise RuntimeError("limit lock timeout")
    held[school_id] = lock


def check_and_reserve(school_id: int, kind: str, adding: int | float = 1) -> None:
    """Raise LimitReached unless `adding` more fits. Takes the school
    lock first; it is released when the caller's transaction ends."""
    lim = effective_limits(school_id)[kind]
    if lim is None:
        return
    _lock_school(school_id)
    usage = school_usage(school_id, with_storage=(kind == "storage"))
    used = usage.value(kind)
    if used + adding > lim:
        remaining = max(int(lim - used), 0)
        raise LimitReached(kind, lim, remaining)


def is_staff_role(role) -> bool:
    return getattr(role, "name", None) not in NON_STAFF_ROLES
