"""SAAS-032 — one pattern for every dangerous console action (suspend,
archive, slug change, end all sessions, …).

Each one requires: the owner role, a TOTP verified in the last 10
minutes (or a fresh code in the form), a written reason, and the
school's slug typed back. At most DANGEROUS_PER_HOUR per user. Afterwards:
a platform audit row, a school subscription event, and a mail to every
owner. Nothing dangerous runs from a GET or a single click.
"""
from __future__ import annotations

import time
from datetime import timedelta

from flask import request, session


STEP_UP_SECONDS = 600
DANGEROUS_PER_HOUR = 5
DANGEROUS_ACTIONS = ("school_suspended", "school_resumed", "school_archived", "school_unarchived",
                     "school_slug_changed", "school_sessions_ended")


class ActionRefused(ValueError):
    """Arabic, shown on the console."""


def fresh_totp(user) -> bool:
    """TOTP verified within STEP_UP_SECONDS — or the form's `totp` code
    verifies now (which refreshes the window)."""
    from .platform_auth import decrypt, verify_totp
    if time.time() - session.get("sa_totp_at", 0) <= STEP_UP_SECONDS:
        return True
    code = (request.form.get("totp") or "").strip()
    if code and verify_totp(decrypt(user.totp_secret_encrypted), code, user=user):
        session["sa_totp_at"] = time.time()
        return True
    return False


def check(user, school, *, reason: str, confirm_slug: str) -> str:
    """Raise ActionRefused unless every condition holds; returns the
    stripped reason."""
    from ..models import PlatformAuditLog
    from .platform_auth import utcnow
    if user is None or user.role != "owner":
        raise ActionRefused("هذا الإجراء لدور owner فقط.")
    reason = (reason or "").strip()
    if not reason:
        raise ActionRefused("السبب مطلوب.")
    if (confirm_slug or "").strip().lower() != school.slug:
        raise ActionRefused("اكتب الاسم المختصر للمدرسة بالظبط للتأكيد.")
    recent = PlatformAuditLog.query.filter(
        PlatformAuditLog.platform_user_id == user.id,
        PlatformAuditLog.action.in_(DANGEROUS_ACTIONS),
        PlatformAuditLog.created_at >= utcnow() - timedelta(hours=1)).count()
    if recent >= DANGEROUS_PER_HOUR:
        raise ActionRefused("تجاوزت حد الإجراءات الخطرة في الساعة. حاول لاحقًا.")
    if not fresh_totp(user):
        raise ActionRefused("أدخل رمز التحقق (TOTP) الحالي.")
    return reason


def record(user, school, action: str, reason: str, *, from_value=None, to_value=None,
           event: bool = True, **meta) -> None:
    """Audit + subscription event + mail every owner. Caller commits.
    event=False when the service already wrote the event (suspend/resume)."""
    from .platform_auth import audit
    from .subscriptions import _event
    audit(action, user, school_id=school.id, reason=reason, before=from_value, after=to_value, **meta)
    if event:
        _event(school.id, action, None if from_value is None else str(from_value),
               None if to_value is None else str(to_value), reason, user)
    notify_owners(f"منصتي — {action} — {school.name}",
                  f"الإجراء: {action}\nالمدرسة: {school.name} ({school.slug})\n"
                  f"بواسطة: {getattr(user, 'email', '')}\nالسبب: {reason}")


def notify_owners(subject: str, body: str) -> int:
    from ..models import PlatformUser
    from . import platform_mailer
    if not platform_mailer.is_configured():
        return 0
    sent = 0
    for o in PlatformUser.query.filter_by(role="owner", is_active=True):
        try:
            platform_mailer.send(o.email, subject, body)
            sent += 1
        except platform_mailer.PlatformMailError:
            pass
    return sent
