"""Notification Integration Point.

Per the PDF (T-6.2): WhatsApp message cost is on the client. The system designs
a flexible Integration Point so the provider can be swapped later without
touching call sites. Routes call send_notification(...); the configured
provider handles delivery.

Sprint 10 Phase 3 adds send_push() (FCM) alongside the WhatsApp channel.
Both fire additively — parents get WhatsApp + push, teachers get push only.
"""
from datetime import datetime
from typing import Optional
import json

from flask import current_app

from ..extensions import db
from ..models import DeviceToken, NotificationLog, Student, User


# Module-level guard so we only initialize firebase-admin once per process.
_firebase_initialized = False


def _ensure_firebase():
    """Lazy-init firebase-admin the first time send_push() is called.

    Returns True on success, False if not configured / unavailable.
    """
    global _firebase_initialized
    if _firebase_initialized:
        return True
    path = current_app.config.get("FCM_SERVICE_ACCOUNT_PATH")
    if not path:
        return False
    try:
        import firebase_admin
        from firebase_admin import credentials
        if not firebase_admin._apps:
            firebase_admin.initialize_app(credentials.Certificate(path))
        _firebase_initialized = True
        return True
    except Exception as e:  # noqa: BLE001
        current_app.logger.warning("firebase-admin init failed: %s", e)
        return False


def send_push(
    user_id: int, title: str, body: str,
    data: Optional[dict] = None,
) -> int:
    """Send a push notification to all of user_id's registered device tokens.

    Returns the count of tokens the FCM service accepted. If FCM isn't
    configured, returns 0 without raising (so it's safe to call in dev).
    """
    if not _ensure_firebase():
        return 0
    tokens_q = DeviceToken.query.filter_by(user_id=user_id).all()
    if not tokens_q:
        return 0
    token_strs = [t.token for t in tokens_q]

    from firebase_admin import messaging  # local import — heavy
    msg = messaging.MulticastMessage(
        tokens=token_strs,
        notification=messaging.Notification(title=title, body=body),
        data={k: str(v) for k, v in (data or {}).items()},
    )
    try:
        resp = messaging.send_each_for_multicast(msg)
    except Exception as e:  # noqa: BLE001
        current_app.logger.warning("FCM send failed: %s", e)
        return 0

    # Prune tokens FCM told us are no longer valid
    invalid_codes = {"registration-token-not-registered", "invalid-argument"}
    for idx, r in enumerate(resp.responses):
        if not r.success and r.exception is not None:
            code = getattr(r.exception, "code", "")
            msg_txt = str(r.exception)
            if code in invalid_codes or "not-registered" in msg_txt:
                DeviceToken.query.filter_by(token=token_strs[idx]).delete()
    db.session.commit()
    return resp.success_count


def _push_to_parent_of(target_phone: Optional[str], school_id: int,
                       title: str, body: str, data: Optional[dict] = None) -> int:
    """Best-effort: resolve target_phone → Student → parent User → send_push()."""
    if not target_phone:
        return 0
    student = Student.query.filter_by(
        school_id=school_id, parent_phone=target_phone,
    ).first()
    if not student or not student.parent_user_id:
        return 0
    return send_push(student.parent_user_id, title, body, data=data)


def send_notification(
    school_id: int, kind: str, payload: dict,
    target_phone: Optional[str] = None, target_email: Optional[str] = None,
    related_kind: Optional[str] = None, related_id: Optional[int] = None,
    student_id: Optional[int] = None,
) -> NotificationLog:
    """Sprint 11: `student_id` is now the primary parent-scoping key.

    Passing `student_id` at insert time lets `/parent/notifications` filter
    by direct FK (Student.parent_user_id → this row's student_id) instead of
    fuzzy-matching on target_phone. target_phone stays for the SMS gateway.
    """
    log = NotificationLog(
        school_id=school_id,
        kind=kind,
        payload=json.dumps(payload, ensure_ascii=False),
        target_phone=target_phone,
        target_email=target_email,
        related_kind=related_kind,
        related_id=related_id,
        student_id=student_id,
        status="queued",
    )
    db.session.add(log)
    db.session.flush()

    provider = current_app.config.get("WHATSAPP_PROVIDER", "stub")
    try:
        if provider == "stub":
            _send_stub(log)
        else:
            log.error = f"unknown provider: {provider}"
            log.status = "failed"
        log.attempts += 1
        log.last_attempt_at = datetime.utcnow()
    except Exception as e:  # noqa: BLE001
        log.status = "failed"
        log.error = str(e)[:255]
        log.attempts += 1
        log.last_attempt_at = datetime.utcnow()

    # Sprint 10 — additive push (does nothing if FCM isn't configured yet)
    try:
        _dispatch_push_for(kind, payload, target_phone, school_id, log.id)
    except Exception as e:  # noqa: BLE001
        current_app.logger.warning("push dispatch failed for kind=%s: %s", kind, e)

    db.session.commit()
    return log


def _dispatch_push_for(
    kind: str, payload: dict, target_phone: Optional[str],
    school_id: int, notif_id: int,
) -> None:
    """Map notification kind → parent push notification with deep link."""
    student = payload.get("student", "ابنك")
    date = payload.get("date", "")
    amount = payload.get("amount")

    if kind == "absence":
        # Find child_id to build the deep link
        child_id = None
        if target_phone:
            s = Student.query.filter_by(
                school_id=school_id, parent_phone=target_phone).first()
            if s:
                child_id = s.id
        _push_to_parent_of(
            target_phone, school_id,
            title="غياب",
            body=f"تم تسجيل غياب لـ {student}{' بتاريخ ' + date if date else ''}",
            data={
                "route": f"/children/{child_id}/attendance" if child_id else "/",
                "notification_id": notif_id,
            },
        )
    elif kind == "result_approved":
        child_id = payload.get("student_id")
        _push_to_parent_of(
            target_phone, school_id,
            title="اعتماد النتيجة",
            body=f"تم اعتماد نتائج {student} — يمكنك الاطلاع الآن",
            data={
                "route": f"/children/{child_id}/results" if child_id else "/",
                "notification_id": notif_id,
            },
        )
    elif kind == "invoice_issued":
        child_id = payload.get("student_id")
        _push_to_parent_of(
            target_phone, school_id,
            title="فاتورة جديدة",
            body=f"فاتورة جديدة{' بمبلغ ' + str(amount) + ' ج.س' if amount else ''}",
            data={
                "route": f"/children/{child_id}/invoices" if child_id else "/",
                "notification_id": notif_id,
            },
        )
    elif kind in ("payment_received", "payment"):
        child_id = payload.get("student_id")
        _push_to_parent_of(
            target_phone, school_id,
            title="استلام دفعة",
            body=f"تم استلام دفعة{' بمبلغ ' + str(amount) + ' ج.س' if amount else ''}",
            data={
                "route": f"/children/{child_id}/invoices" if child_id else "/",
                "notification_id": notif_id,
            },
        )
    elif kind == "refund":
        child_id = payload.get("student_id")
        _push_to_parent_of(
            target_phone, school_id,
            title="استرداد مبلغ",
            body=f"تم استرداد {amount} ج.س" if amount else "تم تسجيل استرداد",
            data={
                "route": f"/children/{child_id}/invoices" if child_id else "/",
                "notification_id": notif_id,
            },
        )


def _send_stub(log: NotificationLog) -> None:
    log.status = "sent"
    log.sent_at = datetime.utcnow()
