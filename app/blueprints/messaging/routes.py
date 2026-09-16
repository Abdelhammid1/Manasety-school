"""Ticket #13 — Conversations + Messages. Two-way messaging between:

  · guardians ↔ their child's teachers + school admins
  · teachers  ↔ guardians of students in their sections + admins
  · admins    ↔ any user in the school

Everything is auditable — deletes soft-null via Message.deleted_at.
NotificationPreference rows control who wants alerts per channel/event.
"""
from datetime import datetime, timezone

from flask import flash, redirect, render_template, request, url_for, abort
from flask_login import current_user, login_required
from sqlalchemy import or_, and_, desc

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import (
    Conversation, ConversationParticipant, Message,
    NotificationPreference,
    User, Student, StudentGuardian, Guardian, Assignment, Section,
)


def _sid():
    return current_user.school_id


def _can_message(a_user, b_user):
    """Basic scope rule (ticket #13 last section):
      admins ↔ anyone
      guardian ↔ any teacher of any of their children + any admin
      teacher ↔ guardians of students in any of their sections + admins

    Returns True when the pair is allowed to open a conversation."""
    if a_user is None or b_user is None:
        return False
    if a_user.school_id != b_user.school_id:
        return False
    # Role can be either a str (legacy user.role) or a Role model. Pull
    # the .name off it when necessary.
    def _role_slug(u):
        r = getattr(u, "role", None)
        if r is None:
            return ""
        if isinstance(r, str):
            return r.lower()
        return (getattr(r, "name", "") or "").lower()
    a_role = _role_slug(a_user)
    b_role = _role_slug(b_user)
    admin_like = {"admin", "admin_full", "system_admin"}
    if a_role in admin_like or b_role in admin_like:
        return True
    # Teacher ↔ Guardian: check they share a student.
    if ({a_role, b_role} == {"teacher", "parent"}) or (a_role in ("teacher", "parent") and b_role in ("teacher", "parent")):
        # Find guardian side
        guardian_user, teacher_user = (a_user, b_user) if a_role == "parent" else (b_user, a_user)
        # guardian's linked students
        stu_ids = [g.id for g in guardian_user.guardian_profile.students] \
            if getattr(guardian_user, "guardian_profile", None) else []
        if not stu_ids:
            return False
        # teacher's sections via Assignment
        teacher_profile = getattr(teacher_user, "teacher_profile", None)
        if not teacher_profile:
            return False
        sec_ids = [a.section_id for a in Assignment.query.filter_by(
            teacher_id=teacher_profile.id, is_active=True,
        ).all()]
        if not sec_ids:
            return False
        from ...models import Enrollment
        return db.session.query(Enrollment.id).filter(
            Enrollment.student_id.in_(stu_ids),
            Enrollment.section_id.in_(sec_ids),
            Enrollment.status == "active",
        ).count() > 0
    # Same-role peers (teacher ↔ teacher, admin ↔ admin) allowed for now.
    return a_role == b_role


@bp.route("/inbox", endpoint="inbox")
@login_required
def inbox():
    """Every conversation the current user participates in."""
    my_convs = (
        Conversation.query.join(
            ConversationParticipant,
            ConversationParticipant.conversation_id == Conversation.id,
        )
        .filter(ConversationParticipant.user_id == current_user.id)
        .order_by(desc(Conversation.last_message_at), desc(Conversation.id))
        .all()
    )
    # Unread count per conversation.
    unread = {}
    for c in my_convs:
        me = next((p for p in c.participants if p.user_id == current_user.id), None)
        if me is None:
            continue
        last = me.last_read_at
        n = Message.query.filter(
            Message.conversation_id == c.id,
            Message.deleted_at.is_(None),
            *(Message.created_at > last for _ in [1] if last is not None),
        ).count()
        unread[c.id] = n
    return render_template("messaging/inbox.html", conversations=my_convs, unread=unread)


@bp.route("/new", methods=["GET", "POST"], endpoint="conversation_new")
@login_required
def conversation_new():
    """Start a new conversation with a picked recipient."""
    if request.method == "POST":
        recipient_id = request.form.get("recipient_id", type=int)
        subject = (request.form.get("subject") or "").strip() or None
        body = (request.form.get("body") or "").strip()
        if not recipient_id or not body:
            flash("اختر المستلم واكتب رسالة.", "danger")
            return redirect(url_for("messaging.conversation_new"))
        recipient = User.query.filter_by(id=recipient_id, school_id=_sid()).first()
        if recipient is None:
            abort(404)
        if not _can_message(current_user, recipient):
            flash("لا تملك صلاحية مراسلة هذا المستخدم.", "danger")
            return redirect(url_for("messaging.inbox"))
        conv = Conversation(
            school_id=_sid(), subject=subject,
            created_by_user_id=current_user.id,
            last_message_at=datetime.now(timezone.utc),
        )
        db.session.add(conv); db.session.flush()
        db.session.add(ConversationParticipant(
            conversation_id=conv.id, user_id=current_user.id, role="initiator",
            last_read_at=datetime.now(timezone.utc),
        ))
        db.session.add(ConversationParticipant(
            conversation_id=conv.id, user_id=recipient.id, role="recipient",
        ))
        db.session.add(Message(
            conversation_id=conv.id, sender_user_id=current_user.id, body=body,
        ))
        db.session.commit()
        flash("تم إرسال الرسالة.", "success")
        return redirect(url_for("messaging.conversation_view", conv_id=conv.id))

    # Recipient list — everyone the current user is allowed to message.
    candidates = User.query.filter_by(school_id=_sid()).order_by(User.full_name).all()
    allowed = [u for u in candidates if u.id != current_user.id and _can_message(current_user, u)]
    return render_template("messaging/new.html", recipients=allowed)


@bp.route("/c/<int:conv_id>", methods=["GET", "POST"], endpoint="conversation_view")
@login_required
def conversation_view(conv_id):
    conv = Conversation.query.filter_by(id=conv_id, school_id=_sid()).first_or_404()
    me = next((p for p in conv.participants if p.user_id == current_user.id), None)
    if me is None:
        abort(403)

    if request.method == "POST":
        body = (request.form.get("body") or "").strip()
        if not body:
            flash("لا يمكن إرسال رسالة فارغة.", "danger")
        else:
            db.session.add(Message(
                conversation_id=conv.id, sender_user_id=current_user.id, body=body,
            ))
            conv.last_message_at = datetime.now(timezone.utc)
            db.session.commit()
        return redirect(url_for("messaging.conversation_view", conv_id=conv.id))

    me.last_read_at = datetime.now(timezone.utc)
    db.session.commit()
    messages = [m for m in conv.messages if m.deleted_at is None]
    others = [p for p in conv.participants if p.user_id != current_user.id]
    return render_template(
        "messaging/conversation.html",
        conversation=conv, messages=messages, others=others,
    )


@bp.route("/m/<int:msg_id>/delete", methods=["POST"], endpoint="message_delete")
@login_required
def message_delete(msg_id):
    """Soft-delete a message the current user sent. Deleted rows stay in
    the DB (with deleted_at set) for the audit trail."""
    m = Message.query.get_or_404(msg_id)
    if m.sender_user_id != current_user.id:
        abort(403)
    m.deleted_at = datetime.now(timezone.utc)
    db.session.commit()
    return redirect(url_for("messaging.conversation_view", conv_id=m.conversation_id))


@bp.route("/preferences", methods=["GET", "POST"], endpoint="preferences")
@login_required
def preferences():
    """Notification preferences — channel × event checkbox grid."""
    channels = ["in_app", "email", "sms", "whatsapp", "push"]
    events = ["attendance", "grades", "homework", "invoice", "behavior", "announcement"]

    if request.method == "POST":
        # rebuild the whole grid from the ticks
        existing = {(p.channel, p.event_type): p
                    for p in NotificationPreference.query.filter_by(user_id=current_user.id).all()}
        for ch in channels:
            for ev in events:
                key = f"{ch}_{ev}"
                enabled = key in request.form
                row = existing.get((ch, ev))
                if row is None:
                    db.session.add(NotificationPreference(
                        user_id=current_user.id, channel=ch, event_type=ev,
                        is_enabled=enabled,
                    ))
                else:
                    row.is_enabled = enabled
        db.session.commit()
        flash("تم حفظ تفضيلات الإشعارات.", "success")
        return redirect(url_for("messaging.preferences"))

    prefs = {(p.channel, p.event_type): p.is_enabled
             for p in NotificationPreference.query.filter_by(user_id=current_user.id).all()}
    return render_template(
        "messaging/preferences.html",
        channels=channels, events=events, prefs=prefs,
    )
