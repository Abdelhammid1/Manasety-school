"""SAAS-036 — console hardening.

- platform_sessions: the console cookie only carries a session id; every
  request checks the row (not revoked, same user). A user sees and ends
  their own sessions; an owner ends anyone's. Password change, TOTP
  reset and deactivation end all of a user's sessions.
- Immutable audit: DB triggers refuse UPDATE / DELETE on
  platform_audit_logs and support_session_events. The only way past
  them is audit_prune(), used by the 24-month retention command.
- Optional IP allow-list (PLATFORM_ALLOWED_IPS) for the console host.
- Login notices: a new IP / browser → mail to that user.
"""
from __future__ import annotations

import hashlib
import ipaddress
import secrets
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from flask import current_app, request, session

from ..extensions import db

IMMUTABLE_TABLES = ("platform_audit_logs", "support_session_events")
AUDIT_RETENTION_MONTHS = 24
SEEN_EVERY = timedelta(seconds=60)
INVITE_TTL = timedelta(hours=72)


def utcnow():
    return datetime.now(timezone.utc)


# ─── server-side console sessions ───────────────────────────────────

def open_session(user) -> None:
    """Called at the end of a successful console login."""
    from ..models import PlatformSession
    ua = (request.headers.get("User-Agent") or "")[:255] or None
    known = PlatformSession.query.filter_by(platform_user_id=user.id, ip=request.remote_addr,
                                            user_agent=ua).first() is not None
    row = PlatformSession(id=uuid.uuid4().hex, platform_user_id=user.id, ip=request.remote_addr,
                          user_agent=ua, created_at=utcnow(), last_seen_at=utcnow())
    db.session.add(row)
    session["sa_sid"] = row.id
    if not known:
        _notice_new_login(user, row)


def check_session(user) -> bool:
    from ..models import PlatformSession
    sid = session.get("sa_sid")
    row = db.session.get(PlatformSession, sid) if sid else None
    if row is None or row.revoked_at is not None or row.platform_user_id != user.id:
        return False
    now = utcnow()
    last = row.last_seen_at if row.last_seen_at.tzinfo else row.last_seen_at.replace(tzinfo=timezone.utc)
    if now - last > SEEN_EVERY:
        row.last_seen_at = now
        db.session.commit()
    return True


def revoke_sessions(user_id: int, *, except_sid: str | None = None) -> int:
    from ..models import PlatformSession
    q = PlatformSession.query.filter(PlatformSession.platform_user_id == user_id,
                                     PlatformSession.revoked_at.is_(None))
    if except_sid:
        q = q.filter(PlatformSession.id != except_sid)
    return q.update({"revoked_at": utcnow()}, synchronize_session=False)


def _notice_new_login(user, row) -> None:
    from . import platform_mailer
    if not platform_mailer.is_configured():
        return
    try:
        platform_mailer.send(user.email, "منصتي — دخول جديد للوحة",
                             f"تم تسجيل دخول لحسابك من عنوان {row.ip} ومتصفح جديد. "
                             "لو مش إنت، غيّر كلمة المرور وأنهِ جلساتك فورًا.")
    except platform_mailer.PlatformMailError:
        pass


# ─── immutable audit ────────────────────────────────────────────────

_PG_FN = """
CREATE OR REPLACE FUNCTION manasety_audit_immutable() RETURNS trigger AS $$
BEGIN
  IF current_setting('manasety.audit_prune', true) = 'on' AND TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'audit rows are immutable (%)', TG_TABLE_NAME;
END $$ LANGUAGE plpgsql;
"""


def trigger_ddl(dialect: str, table: str) -> list[str]:
    if dialect == "postgresql":
        return [_PG_FN,
                f"DROP TRIGGER IF EXISTS {table}_immutable ON {table};",
                f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
                f"FOR EACH ROW EXECUTE FUNCTION manasety_audit_immutable();"]
    # SQLite: a delete is allowed only while audit_prune() has a row in
    # the guard table (there are no session variables).
    return ["CREATE TABLE IF NOT EXISTS audit_prune_guard (id INTEGER PRIMARY KEY)",
            f"CREATE TRIGGER IF NOT EXISTS {table}_no_update BEFORE UPDATE ON {table} "
            f"BEGIN SELECT RAISE(ABORT, 'audit rows are immutable'); END;",
            f"CREATE TRIGGER IF NOT EXISTS {table}_no_delete BEFORE DELETE ON {table} "
            f"WHEN (SELECT COUNT(*) FROM audit_prune_guard) = 0 "
            f"BEGIN SELECT RAISE(ABORT, 'audit rows are immutable'); END;"]


def install_triggers(app) -> None:
    """Create the triggers whenever the tables are created (create_all in
    dev / tests); the migration does it on real databases."""
    from sqlalchemy import event, text

    def _after_create(target, connection, **kw):
        for stmt in trigger_ddl(connection.dialect.name, target.name):
            connection.execute(text(stmt))

    md = db.metadata
    for name in IMMUTABLE_TABLES:
        t = md.tables.get(name)
        if t is not None and not event.contains(t, "after_create", _after_create):
            event.listen(t, "after_create", _after_create)


@contextmanager
def audit_prune(conn=None):
    """The one sanctioned way to DELETE audit rows (retention only)."""
    from sqlalchemy import text
    own = conn is None
    conn = conn or db.engine.connect()
    tx = conn.begin() if own else None
    sqlite = conn.dialect.name != "postgresql"
    try:
        if not sqlite:
            conn.execute(text("SET LOCAL manasety.audit_prune = 'on'"))
        else:
            conn.execute(text("INSERT INTO audit_prune_guard (id) VALUES (1)"))
        try:
            yield conn
        finally:
            if sqlite:
                conn.execute(text("DELETE FROM audit_prune_guard"))
        if tx is not None:
            tx.commit()
    except Exception:
        if tx is not None:
            tx.rollback()
        raise
    finally:
        if own:
            conn.close()


def prune_audit(months: int = AUDIT_RETENTION_MONTHS) -> dict:
    from sqlalchemy import text
    cutoff = utcnow() - timedelta(days=30 * months)
    out = {}
    with audit_prune() as conn:
        out["platform_audit_logs"] = conn.execute(
            text("DELETE FROM platform_audit_logs WHERE created_at < :c"), {"c": cutoff}).rowcount
        out["support_session_events"] = conn.execute(
            text("DELETE FROM support_session_events WHERE ts < :c"), {"c": cutoff}).rowcount
    return out


# ─── IP allow-list ──────────────────────────────────────────────────

def parse_allowed_ips(raw: str | None):
    if not raw or not raw.strip():
        return None
    return [ipaddress.ip_network(p.strip(), strict=False) for p in raw.split(",") if p.strip()]


def ip_allowed(ip: str | None) -> bool:
    nets = current_app.config.get("PLATFORM_ALLOWED_IPS")
    if not nets:
        return True
    try:
        addr = ipaddress.ip_address(ip or "")
    except ValueError:
        return False
    return any(addr in n for n in nets)


# ─── platform-user invites / resets (one-time links) ────────────────

def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def issue_setup_link(user, *, purpose: str) -> str:
    """A one-time console link to set a password (invite or reset). Older
    links of the user die. Returns the raw token (shown once)."""
    from ..models import PlatformSetupToken
    PlatformSetupToken.query.filter(PlatformSetupToken.platform_user_id == user.id,
                                    PlatformSetupToken.used_at.is_(None)) \
        .update({"used_at": utcnow()}, synchronize_session=False)
    raw = secrets.token_urlsafe(32)
    db.session.add(PlatformSetupToken(platform_user_id=user.id, token_hash=hash_token(raw),
                                      purpose=purpose, expires_at=utcnow() + INVITE_TTL))
    return raw


def redeem_setup_link(raw: str):
    return redeem_setup_hash(hash_token(raw or ""))


def redeem_setup_hash(token_hash: str | None):
    from ..models import PlatformSetupToken
    if not token_hash:
        return None
    row = PlatformSetupToken.query.filter_by(token_hash=token_hash).first()
    if row is None or row.used_at is not None:
        return None
    exp = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    if exp < utcnow() or row.user is None or not row.user.is_active:
        return None
    return row


def claim_setup_token(token_id: int) -> bool:
    """Mark the link used only if nobody else did first (one UPDATE)."""
    from ..models import PlatformSetupToken
    n = PlatformSetupToken.query.filter(PlatformSetupToken.id == token_id,
                                        PlatformSetupToken.used_at.is_(None)) \
        .update({"used_at": utcnow()}, synchronize_session=False)
    return n == 1


def active_owner_count(exclude_id: int | None = None) -> int:
    from ..models import PlatformUser
    q = PlatformUser.query.filter_by(role="owner", is_active=True)
    if exclude_id is not None:
        q = q.filter(PlatformUser.id != exclude_id)
    return q.count()
