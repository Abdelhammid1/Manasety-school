"""The top bar's bell: what is waiting for the signed-in user.

  * notifications about the user's own children (a parent) or about the
    user (a student) — the same rule as the mobile API's parent feed and
    its mark-read. The school's outbound log (every SMS / email sent to
    every family) is not anyone's inbox.
  * the school's own notices (backup / restore results) for its admins —
    the only ones allowed to open those pages.
  * unread messages in the user's conversations (every role).

Both are school-scoped and cheap: one query each.
"""

from __future__ import annotations

import json

from sqlalchemy import and_, func, or_

from ..extensions import db
from ..models import ConversationParticipant, Message, NotificationLog, Student

KIND_LABELS = {
    "absence": "غياب",
    "attendance_rule": "تنبيه حضور",
    "invoice_issued": "فاتورة جديدة",
    "reminder": "تذكير بالسداد",
    "result_approved": "اعتماد النتائج",
    "refund": "استرداد",
    "substitution": "حصة احتياط",
    "school_backup": "النسخة الاحتياطية",
    "school_restore": "استرجاع النسخة الاحتياطية",
}
# Notices about the school itself (no student): its admins' inbox.
ADMIN_KINDS = ("school_backup", "school_restore")


def _my_student_ids(user) -> list[int]:
    return [r[0] for r in db.session.query(Student.id).filter(
        Student.school_id == user.school_id,
        or_(Student.parent_user_id == user.id, Student.user_id == user.id),
    ).all()]


def _is_admin(user) -> bool:
    return getattr(getattr(user, "role", None), "name", None) == "admin"


def _mine(user):
    ids = _my_student_ids(user)
    conds = [NotificationLog.student_id.in_(ids)] if ids else []
    if _is_admin(user):
        conds.append(and_(NotificationLog.student_id.is_(None),
                          NotificationLog.kind.in_(ADMIN_KINDS)))
    if not conds:
        return None
    return NotificationLog.query.filter(NotificationLog.school_id == user.school_id, or_(*conds))


def unread_messages(user) -> int:
    me = ConversationParticipant
    return int(db.session.query(func.count(Message.id))
               .join(me, and_(me.conversation_id == Message.conversation_id, me.user_id == user.id))
               .filter(Message.deleted_at.is_(None),
                       Message.sender_user_id != user.id,
                       or_(me.last_read_at.is_(None), Message.created_at > me.last_read_at))
               .scalar() or 0)


def unread_count(user) -> int:
    q = _mine(user)
    n = q.filter(NotificationLog.read_at.is_(None)).count() if q is not None else 0
    return n + unread_messages(user)


def _text(n) -> tuple[str, str]:
    try:
        p = json.loads(n.payload or "{}")
    except (TypeError, ValueError):
        p = {}
    if not isinstance(p, dict):
        p = {}
    title = p.get("title") or p.get("subject") or KIND_LABELS.get(n.kind, "إشعار")
    body = p.get("body") or p.get("message") or ""
    if not body and p.get("invoice_number"):
        body = f"فاتورة {p['invoice_number']}"
    return str(title), str(body)


def recent(user, limit: int = 20) -> list[dict]:
    q = _mine(user)
    if q is None:
        return []
    out = []
    for n in q.order_by(NotificationLog.created_at.desc()).limit(limit).all():
        title, body = _text(n)
        out.append({"title": title, "body": body, "created_at": n.created_at,
                    "unread": n.read_at is None,
                    "student": n.student.full_name if n.student else ""})
    return out


def mark_all_read(user) -> int:
    from datetime import datetime
    q = _mine(user)
    if q is None:
        return 0
    n = q.filter(NotificationLog.read_at.is_(None)).update(
        {NotificationLog.read_at: datetime.utcnow()}, synchronize_session=False)
    db.session.commit()
    return n
