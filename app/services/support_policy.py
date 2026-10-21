"""SAAS-031 — support sessions: a platform staff member sees a school
exactly as its admin does, without knowing any password, time-boxed,
read-only by default, every request recorded.

Hand-off between hosts (cookies are host-only, D5):
  console  → SupportSession row + a 60-second token signed with
             SUPPORT_SESSION_KEY, bound to (session id, school id) and a
             one-time nonce (stored as a hash, burned on first use)
  school   → /_support/enter?t=<token>: verify signature, age, nonce and
             that the token's school is the school this host resolves
             to; clear any session; log in the school's support user.

Every request in the session re-checks the row (ended / expired / idle
/ wrong host) — not auth_epoch, so support can inspect a suspended
school. Read-only refuses every write and forces the flush guard to
enforce. Write mode (owner, fresh TOTP, type the school's name, 30 min
max, not for suspended / expired / grace schools) still refuses the
FORBIDDEN_ENDPOINTS below.
"""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone

from flask import current_app, g, request, session

from ..extensions import db

SUPPORT_USERNAME = "__manasety_support__"
SUPPORT_FULL_NAME = "دعم منصتي"
TOKEN_MAX_AGE = 60
DEFAULT_MINUTES = 30
MAX_MINUTES = 120
WRITE_MAX_MINUTES = 30
IDLE_MINUTES = 15
STEP_UP_SECONDS = 600
MIN_REASON = 10
MODES = ("read_only", "write")
_SESSION_KEY = "support_sid"

# Refused even in write mode. Endpoint names: a renamed route that drops
# out of this list fails tests/test_saas031_support.py (every entry must
# exist). Final list to be confirmed with Abdelhamid.
FORBIDDEN_ENDPOINTS = frozenset({
    # setting or resetting any user's password
    "students.guardian_account_reset_password",
    "students.student_account_reset_password",
    "teachers.teacher_account_reset_password",
    "admin.user_new", "admin.user_edit",
    # SMTP and other secrets (the school settings form carries SMTP)
    "admin.school_settings", "admin.smtp_test",
    # bulk import
    "platform.imports_preview", "platform.imports_commit", "finance.bank_rec_import",
    # closing a year (the period lock the accounting relies on)
    "academic.year_close",
})
# Any write-mode form carrying a credential or a login identity is
# refused too (security review: create/edit forms elsewhere set an
# account password; changing a login e-mail enables a reset).
CREDENTIAL_FIELD_RE = re.compile(r"password|passwd|username|(^|_)email$|otp|token|secret", re.I)


def credential_fields(form) -> list[str]:
    return sorted(k for k in form.keys() if k != "csrf_token" and CREDENTIAL_FIELD_RE.search(k))


# Writes always allowed inside a support session (ending it).
ALWAYS_ALLOWED = frozenset({"support.end", "auth.logout"})
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def utcnow():
    return datetime.now(timezone.utc)


def _aware(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ─── the support user ────────────────────────────────────────────────

def ensure_support_user(school):
    """The school's one support identity (admin permissions, unusable
    password). Caller commits."""
    from ..models import Role, User
    u = (User.query.execution_options(include_support=True)
         .filter_by(school_id=school.id, is_platform_support=True).first())
    if u is not None:
        return u
    role = Role.query.filter_by(school_id=school.id, name="admin").first()
    if role is None:
        raise RuntimeError(f"school {school.id} has no admin role")
    u = User(school_id=school.id, role_id=role.id, username=SUPPORT_USERNAME,
             full_name=SUPPORT_FULL_NAME, is_active=True, is_platform_support=True)
    u.set_password(secrets.token_urlsafe(48))
    db.session.add(u)
    db.session.flush()
    return u


# ─── tokens ──────────────────────────────────────────────────────────

def _serializer():
    from itsdangerous import URLSafeTimedSerializer
    return URLSafeTimedSerializer(current_app.config["SUPPORT_SESSION_KEY"], salt="support-enter")


def _hash(nonce: str) -> str:
    return hashlib.sha256(nonce.encode()).hexdigest()


def issue_token(row) -> str:
    nonce = secrets.token_urlsafe(24)
    row.nonce_hash = _hash(nonce)
    return _serializer().dumps({"sid": row.id, "school": row.school_id, "n": nonce})


class SupportError(ValueError):
    """Arabic, shown on the console."""


def start(platform_user, school, *, mode: str, reason: str, minutes: int | None = None,
          confirm_name: str = ""):
    """Validate and open a support session. Returns (row, token). Caller
    commits. Step-up TOTP is checked by the view (it owns the session)."""
    from ..models import SupportSession
    from .platform_auth import audit
    from .subscriptions import school_state
    reason = (reason or "").strip()
    if platform_user.role not in ("owner", "support"):
        raise SupportError("دورك لا يسمح بالدخول كدعم.")
    if mode not in MODES:
        raise SupportError("وضع غير معروف.")
    if len(reason) < MIN_REASON:
        raise SupportError(f"اكتب سببًا واضحًا (على الأقل {MIN_REASON} حروف).")
    if school.status == "archived":
        raise SupportError("المدرسة مؤرشفة.")
    minutes = int(minutes or DEFAULT_MINUTES)
    if not 1 <= minutes <= MAX_MINUTES:
        raise SupportError(f"المدة من 1 إلى {MAX_MINUTES} دقيقة.")
    if mode == "write":
        if platform_user.role != "owner":
            raise SupportError("وضع الكتابة لدور owner فقط.")
        if (confirm_name or "").strip() != school.name.strip():
            raise SupportError("اكتب اسم المدرسة بالظبط لتأكيد وضع الكتابة.")
        if school_state(school).state not in ("active", "trial"):
            raise SupportError("وضع الكتابة غير متاح لمدرسة موقوفة أو منتهية أو في فترة السماح.")
        minutes = min(minutes, WRITE_MAX_MINUTES)
    ensure_support_user(school)
    now = utcnow()
    # one active session per staff member: starting a new one ends the old
    for old in SupportSession.query.filter_by(platform_user_id=platform_user.id, ended_at=None):
        _end(old, "replaced")
    row = SupportSession(platform_user_id=platform_user.id, school_id=school.id, mode=mode,
                         reason=reason, started_at=now, expires_at=now + timedelta(minutes=minutes),
                         last_seen_at=now, ip=request.remote_addr if request else None,
                         user_agent=((request.user_agent.string or "")[:255] if request else None))
    db.session.add(row)
    db.session.flush()
    token = issue_token(row)
    audit("support_session_started", platform_user, school_id=school.id, support_session_id=row.id,
          mode=mode, minutes=minutes, reason=reason)
    _notify_school(school, row)
    return row, token


def _end(row, why: str):
    from .platform_auth import audit
    if row.ended_at is None:
        row.ended_at = utcnow()
        row.end_reason = why
        audit("support_session_ended", None if why else None, school_id=row.school_id,
              support_session_id=row.id, end_reason=why, platform_user_id=row.platform_user_id)


RESERVED_USERNAME_PREFIX = "__"


def username_reserved(username: str) -> bool:
    """`__…` usernames belong to the platform (the support user)."""
    return (username or "").strip().startswith(RESERVED_USERNAME_PREFIX)


def end_for_platform_user(platform_user_id: int, why: str) -> int:
    from ..models import SupportSession
    rows = SupportSession.query.filter_by(platform_user_id=platform_user_id, ended_at=None).all()
    for r in rows:
        _end(r, why)
    return len(rows)


def revoke(row, by_user):
    from .platform_auth import audit
    _end(row, "revoked")
    audit("support_session_revoked", by_user, school_id=row.school_id, support_session_id=row.id)


def redeem(token: str, school_id: int):
    """Token → live SupportSession, or None. Burns the nonce."""
    from itsdangerous import BadSignature, SignatureExpired
    from ..models import SupportSession
    try:
        data = _serializer().loads(token or "", max_age=TOKEN_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    try:
        sid, school, nonce = int(data["sid"]), int(data["school"]), str(data["n"])
    except (KeyError, TypeError, ValueError):
        return None
    if school != int(school_id):
        return None
    row = db.session.get(SupportSession, sid)
    if row is None or row.school_id != school or row.ended_at is not None \
            or row.nonce_used_at is not None or not row.nonce_hash \
            or not secrets.compare_digest(row.nonce_hash, _hash(nonce)) \
            or _aware(row.expires_at) <= utcnow():
        return None
    # Atomic claim (security review): two simultaneous GETs of one token
    # can't both pass a read-then-write check.
    from sqlalchemy import update
    from sqlalchemy.orm.attributes import set_committed_value
    now = utcnow()
    res = db.session.execute(
        update(SupportSession)
        .where(SupportSession.id == sid, SupportSession.nonce_used_at.is_(None),
               SupportSession.ended_at.is_(None))
        .values(nonce_used_at=now).execution_options(synchronize_session=False))
    if res.rowcount != 1:
        return None
    db.session.commit()
    set_committed_value(row, "nonce_used_at", now)
    return row


# ─── per-request ─────────────────────────────────────────────────────

def current_row():
    """The live support session of this request (cached on g), or None."""
    if not session.get(_SESSION_KEY):
        return None
    if "support_row" in g:
        return g.support_row
    from ..models import SupportSession
    g.support_row = db.session.get(SupportSession, int(session[_SESSION_KEY]))
    return g.support_row


def is_support_request() -> bool:
    return bool(session.get(_SESSION_KEY))


def why_dead(row, resolved) -> str | None:
    now = utcnow()
    if row is None:
        return "missing"
    if row.ended_at is not None:
        return row.end_reason or "ended"
    if _aware(row.expires_at) <= now:
        return "expired"
    if _aware(row.last_seen_at) and now - _aware(row.last_seen_at) > timedelta(minutes=IDLE_MINUTES):
        return "idle"
    school = getattr(resolved, "school", None)
    if school is None or school.id != row.school_id:
        return "wrong_host"
    # security review: the staff member behind it must still qualify
    pu = row.platform_user
    if pu is None or not pu.is_active or pu.is_locked() or pu.role not in ("owner", "support") \
            or (row.mode == "write" and pu.role != "owner"):
        return "platform_user_inactive"
    return None


def bypass_for(resolved) -> bool:
    """Called by the resolver for a blocked school: a live support
    session for this very school may still look (read-only rules apply)."""
    row = current_row() if is_support_request() else None
    return row is not None and why_dead(row, resolved) is None


def _notify_school(school, row):
    """notify_on_support_access: mail the school's admins (reason, mode,
    duration — no staff names). The in-app notice is the dashboard banner
    built from recent sessions (recent_for_admin)."""
    if not getattr(school, "notify_on_support_access", True):
        return
    from ..models import Role, User
    from . import platform_mailer
    if not platform_mailer.is_configured():
        return
    admins = (User.query.join(Role, Role.id == User.role_id)
              .filter(User.school_id == school.id, Role.name == "admin", User.is_active.is_(True),
                      User.email.isnot(None))
              .all())
    for a in admins:
        try:
            platform_mailer.send(a.email, "منصتي — دخول الدعم الفني على مدرستك", describe(row))
        except platform_mailer.PlatformMailError:
            pass


def describe(row) -> str:
    minutes = int((_aware(row.expires_at) - _aware(row.started_at)).total_seconds() // 60)
    mode_ar = "قراءة فقط" if row.mode == "read_only" else "كتابة"
    return (f"بدأت جلسة دعم من فريق منصتي على مدرستك — الوضع: {mode_ar} — المدة: "
            f"{minutes} دقيقة. السبب: {row.reason}")


def recent_for_admin(school_id: int, days: int = 7):
    from ..models import School, SupportSession
    school = db.session.get(School, school_id)
    if school is None or not getattr(school, "notify_on_support_access", True):
        return []
    since = utcnow() - timedelta(days=days)
    return (SupportSession.query.filter(SupportSession.school_id == school_id,
                                        SupportSession.started_at >= since)
            .order_by(SupportSession.id.desc()).limit(3).all())


# ─── trail + banner ──────────────────────────────────────────────────

def record_event(support_session_id: int, status: int) -> None:
    """One row per request: method, endpoint, path WITHOUT the query
    string, status, ip — and for writes only the submitted field NAMES
    (never values, never the body). Written on its own connection so a
    view's rollback can't drop it."""
    from ..models import SupportSession, SupportSessionEvent
    fields = None
    if request.method in WRITE_METHODS:
        names = sorted(set(request.form.keys()) | set(request.files.keys()))
        fields = [n for n in names if n != "csrf_token"][:50]
    now = utcnow()
    with db.engine.begin() as conn:
        conn.execute(SupportSessionEvent.__table__.insert().values(
            support_session_id=support_session_id, ts=now, method=request.method[:8],
            endpoint=(request.endpoint or "")[:128], path=request.path[:512],
            status=int(status), ip=request.remote_addr, field_names=fields))
        conn.execute(SupportSession.__table__.update()
                     .where(SupportSession.__table__.c.id == support_session_id)
                     .values(last_seen_at=now))


def banner(row) -> dict:
    from ..models import School
    school = db.session.get(School, row.school_id)
    left = max(int((_aware(row.expires_at) - utcnow()).total_seconds()), 0)
    return {"school": school.name if school else "", "mode": row.mode,
            "seconds_left": left, "mmss": f"{left // 60:02d}:{left % 60:02d}"}


# ─── the global "hide the support user" filter ──────────────────────

_filter_registered = False


def register_filter() -> None:
    """Every ORM SELECT over users skips the platform support user, so it
    never shows up in a list, a count, an export, a recipient picker or
    a login lookup. The few callers that must see it pass
    execution_options(include_support=True)."""
    global _filter_registered
    if _filter_registered:
        return
    from sqlalchemy import event
    from sqlalchemy.orm import Session, with_loader_criteria
    from ..models import User

    @event.listens_for(Session, "do_orm_execute")
    def _hide_support_user(execute_state):
        if not execute_state.is_select or execute_state.execution_options.get("include_support"):
            return
        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(User, lambda cls: cls.is_platform_support.is_(False),
                                 include_aliases=True))
    _filter_registered = True
