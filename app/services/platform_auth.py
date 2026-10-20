"""SAAS-025 — platform (Super Admin) authentication helpers.

Everything here is for the console host only. Secrets (TOTP seeds,
recovery codes, passwords) never reach a log or an audit row: audit
`meta` goes through services.audit.redact().
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import pyotp
from cryptography.fernet import Fernet, InvalidToken
from flask import current_app, request
from flask.sessions import SecureCookieSessionInterface

from ..extensions import db

ISSUER = "منصتي — Console"
RECOVERY_CODE_COUNT = 10
LOGIN_FAILS_PER_IP = 20          # within LOGIN_WINDOW, across all accounts
LOGIN_WINDOW = timedelta(minutes=15)


def utcnow():
    return datetime.now(timezone.utc)


# ─── host ───────────────────────────────────────────────────────────

def is_platform_host() -> bool:
    """True when the request's Host is a configured platform host. Read
    straight from the Host header (the session opens before the tenant
    resolver runs)."""
    from .tenancy import normalize_host
    hosts = {h.strip().lower() for h in current_app.config.get("PLATFORM_HOSTS") or ()}
    return bool(hosts) and normalize_host(request.host) in hosts


class HostAwareSessionInterface(SecureCookieSessionInterface):
    """Separate session cookie on the platform host: its own name and
    SameSite=Strict, so a school session can never ride along (and the
    platform cookie stays host-only like every other, decision D5)."""

    def get_cookie_name(self, app):
        if _in_request() and is_platform_host():
            return app.config["PLATFORM_SESSION_COOKIE_NAME"]
        return super().get_cookie_name(app)

    def get_cookie_samesite(self, app):
        if _in_request() and is_platform_host():
            return "Strict"
        return super().get_cookie_samesite(app)


def _in_request():
    from flask import has_request_context
    return has_request_context()


# ─── secrets at rest ────────────────────────────────────────────────

def _fernet() -> Fernet:
    raw = current_app.config["PLATFORM_ENC_KEY"].encode()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(raw).digest()))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str | None) -> str | None:
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None


# ─── TOTP ───────────────────────────────────────────────────────────

def new_totp_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=ISSUER)


def verify_totp(secret: str | None, code: str | None, user=None) -> bool:
    """Check a 6-digit code (+-1 time-step). With `user`, a code whose
    time-step is not newer than the last accepted one is refused
    (no replay) and the accepted step is recorded."""
    import time as _time
    code = (code or "").strip().replace(" ", "")
    if not secret or not code.isdigit() or len(code) != 6:
        return False
    totp = pyotp.TOTP(secret)
    now = _time.time()
    for offset in (-1, 0, 1):
        t = now + offset * totp.interval
        if hmac.compare_digest(totp.at(t), code):
            counter = totp.timecode(datetime.fromtimestamp(t, tz=timezone.utc))
            if user is not None:
                last = user.totp_last_counter
                if last is not None and counter <= last:
                    return False
                user.totp_last_counter = counter
            return True
    return False


def qr_svg(data: str) -> str:
    import io
    import segno
    buf = io.StringIO()
    segno.make(data, error="m").save(buf, kind="svg", scale=5, border=2, xmldecl=False)
    return buf.getvalue()


# ─── recovery codes ─────────────────────────────────────────────────

def _code_hash(code: str) -> str:
    key = current_app.config["PLATFORM_ENC_KEY"].encode()
    return hmac.new(key, code.strip().lower().encode(), hashlib.sha256).hexdigest()


def issue_recovery_codes(user) -> list[str]:
    """Replace the user's codes with RECOVERY_CODE_COUNT fresh ones and
    return them in clear — exactly once, for display."""
    from ..models import PlatformRecoveryCode
    PlatformRecoveryCode.query.filter_by(platform_user_id=user.id).delete()
    codes = ["-".join(secrets.token_hex(3) for _ in range(2)) for _ in range(RECOVERY_CODE_COUNT)]
    for c in codes:
        db.session.add(PlatformRecoveryCode(platform_user_id=user.id, code_hash=_code_hash(c)))
    return codes


def use_recovery_code(user, code: str) -> bool:
    from ..models import PlatformRecoveryCode
    row = PlatformRecoveryCode.query.filter_by(
        platform_user_id=user.id, code_hash=_code_hash(code or ""), used_at=None).first()
    if row is None:
        return False
    row.used_at = utcnow()
    return True


# ─── audit ──────────────────────────────────────────────────────────

def audit(action: str, user=None, school_id=None, **meta) -> None:
    """Append a platform audit row. Caller commits."""
    from ..models import PlatformAuditLog
    from .audit import redact
    ip = ua = None
    if _in_request():
        ip = request.remote_addr
        ua = (request.user_agent.string or "")[:255] if request.user_agent else None
    db.session.add(PlatformAuditLog(
        platform_user_id=getattr(user, "id", None), action=action,
        target_school_id=school_id, ip=ip, user_agent=ua,
        meta=redact(meta) if meta else None,
    ))


def ip_is_throttled() -> bool:
    from ..models import PlatformAuditLog
    since = utcnow() - LOGIN_WINDOW
    n = PlatformAuditLog.query.filter(
        PlatformAuditLog.action == "login_failed",
        PlatformAuditLog.ip == request.remote_addr,
        PlatformAuditLog.created_at >= since,
    ).count()
    return n >= LOGIN_FAILS_PER_IP


# A real bcrypt hash of a random value: checking an unknown email costs
# the same as checking a real one, so timing doesn't reveal accounts.
_DUMMY_HASH: str | None = None


def dummy_password_check(password: str) -> None:
    global _DUMMY_HASH
    from ..extensions import bcrypt
    if _DUMMY_HASH is None:
        _DUMMY_HASH = bcrypt.generate_password_hash(secrets.token_urlsafe(16)).decode()
    bcrypt.check_password_hash(_DUMMY_HASH, password or "x")


MIN_PASSWORD_LEN = 12


def password_problem(password: str) -> str | None:
    if len(password or "") < MIN_PASSWORD_LEN:
        return f"كلمة المرور يجب أن تكون {MIN_PASSWORD_LEN} حرفًا على الأقل."
    return None
