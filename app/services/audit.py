"""Ticket 6 — Audit trail service.

Attaches SQLAlchemy event listeners on the sensitive tables listed
below and writes an AuditLog row for every INSERT / UPDATE / DELETE.
Runs entirely in Flask request context so it picks up the current
user + IP + user-agent automatically.

Intentionally NOT installed on every table — the trade-off is that
low-value tables (session logs, cache, etc.) would drown the audit
log. Add a class here when a new sensitive model appears.
"""
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import event, inspect
from flask import has_request_context, request
from flask_login import current_user

from ..extensions import db
from ..models import (
    GradeEntry, YearResult, Attendance, Enrollment,
    Student, Guardian, Invoice, Payment, User, Role, Assignment,
    PassRule, AuditLog,
)


# The set of models we watch. Keep small — see docstring.
_WATCHED = [
    GradeEntry, YearResult, Attendance, Enrollment,
    Student, Guardian, Invoice, Payment, User, Role, Assignment,
    PassRule,
]


def _serialize(obj):
    """JSON-safe snapshot of the mapped columns of `obj`. Skips
    relationships (they'd blow up the row size) and normalises Decimal
    to str so the JSON encoder stops complaining."""
    if obj is None:
        return None
    out = {}
    for col in inspect(obj.__class__).columns:
        v = getattr(obj, col.key, None)
        if isinstance(v, Decimal):
            out[col.key] = str(v)
        elif isinstance(v, datetime):
            out[col.key] = v.isoformat()
        elif hasattr(v, "isoformat"):
            out[col.key] = v.isoformat()
        else:
            out[col.key] = v
    return out


def _record(connection, action, target, before=None):
    """Insert an audit row inline via the same connection the model
    event fired on. Writing on the raw connection avoids re-entering
    the ORM (and re-triggering our listeners for AuditLog itself),
    and it participates in the same transaction — a rollback wipes
    the audit row alongside the change it was tracking."""
    entity_type = target.__class__.__name__
    entity_id = getattr(target, "id", None)
    school_id = getattr(target, "school_id", None)
    user_id = getattr(current_user, "id", None) if has_request_context() else None
    ip = None
    ua = None
    if has_request_context():
        try:
            ip = request.remote_addr
            ua = (request.user_agent.string or "")[:255] if request.user_agent else None
        except Exception:
            pass
    connection.execute(AuditLog.__table__.insert().values(
        school_id=school_id, user_id=user_id,
        action=action, entity_type=entity_type, entity_id=entity_id,
        old_value=before,
        new_value=_serialize(target) if action != "delete" else None,
        ip_address=ip, user_agent=ua,
        created_at=datetime.now(timezone.utc),
    ))


def _snap_before(mapper, connection, target):
    """Called on after_update; captures the pre-image via the SQLAlchemy
    inspector so we can log old→new."""
    state = inspect(target)
    old = {}
    for attr in state.attrs:
        hist = attr.history
        if hist.has_changes():
            # deleted holds the pre-image if the attribute changed.
            old[attr.key] = (hist.deleted[0] if hist.deleted else None)
    return old or None


def _register(model):
    @event.listens_for(model, "after_insert")
    def _ai(mapper, connection, target):
        _record(connection, "create", target)

    @event.listens_for(model, "after_update")
    def _au(mapper, connection, target):
        pre = _snap_before(mapper, connection, target)
        # decimals / dates in `pre` still need normalising
        clean = {}
        for k, v in (pre or {}).items():
            if isinstance(v, Decimal): clean[k] = str(v)
            elif hasattr(v, "isoformat"): clean[k] = v.isoformat()
            else: clean[k] = v
        _record(connection, "update", target, before=clean or None)

    @event.listens_for(model, "after_delete")
    def _ad(mapper, connection, target):
        _record(connection, "delete", target, before=_serialize(target))


def install():
    """Called from app factory once per process."""
    for m in _WATCHED:
        _register(m)
