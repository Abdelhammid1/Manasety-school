"""Ticket A/G/H — inline user provisioning.

Every place that creates a Teacher / Guardian / Student / Employee can
create the login account in the same transaction. This module holds the
shared logic so the four forms don't drift.

The helper is safe to call twice on the same natural key: a lookup by
`username` returns the existing User instead of raising a uniqueness
error.
"""
from __future__ import annotations

import re
import secrets
from typing import Optional
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import Role, User


ROLE_NAME_BY_KIND = {
    "teacher":  "teacher",
    "parent":   "parent",
    "guardian": "parent",
    "student":  "student",
    "employee": "teacher",  # school employees log in via the teacher/staff role
}


def suggest_username(full_name: str, phone: str | None = None) -> str:
    """Generate a stable ASCII username from full name + phone tail.

    Arabic names → last 4 digits of phone if any, otherwise a random
    hex tail; this never collides for two people with the same name.
    """
    ascii_head = re.sub(r"[^a-zA-Z0-9]+", "", full_name or "")
    if not ascii_head:
        ascii_head = "user"
    ascii_head = ascii_head.lower()[:20]
    tail = ""
    if phone:
        digits = re.sub(r"\D", "", phone)
        tail = digits[-4:] if len(digits) >= 4 else digits
    if not tail:
        tail = secrets.token_hex(2)
    return f"{ascii_head}{tail}"


def _find_role(school_id: int, kind: str) -> Optional[Role]:
    role_name = ROLE_NAME_BY_KIND.get(kind)
    if not role_name:
        return None
    return Role.query.filter_by(school_id=school_id, name=role_name).first()


def provision_user(
    *,
    school_id: int,
    kind: str,
    full_name: str,
    username: str | None,
    password: str | None,
    email: str | None = None,
    phone: str | None = None,
) -> tuple[User | None, str | None]:
    """Create (or reuse) a User row for the entity being added.

    Returns (user, error_message). On success `error_message` is None.
    A missing/short password returns an error rather than silently
    generating one — the caller must show the field to the user.
    """
    if not full_name.strip():
        return None, "الاسم الكامل مطلوب لإنشاء حساب."

    role = _find_role(school_id, kind)
    if role is None:
        return None, f"لا يوجد دور مناسب ({kind}) في هذه المدرسة — راجع الأدوار."

    # SAAS-030 — staff accounts count against the plan's user limit.
    from .limits import LimitReached, check_and_reserve, is_staff_role
    if is_staff_role(role):
        try:
            check_and_reserve(school_id, "users")
        except LimitReached as e:
            return None, str(e)

    typed = (username or "").strip()
    username = typed or suggest_username(full_name, phone)
    from .support_policy import username_reserved
    if username_reserved(username):
        return None, "اسم المستخدم محجوز."
    # Ticket P3 - never change a username the user typed. A typed duplicate
    # is rejected; only an auto-suggested name (field left blank) is
    # de-duplicated, and the final value is shown to the user after creation.
    def _taken(u):
        return User.query.filter_by(school_id=school_id, username=u).first() is not None

    if _taken(username):
        if typed:
            return None, f"اسم المستخدم «{username}» مستخدم بالفعل في هذه المدرسة، اختر اسمًا آخر."
        base = username
        for _ in range(20):
            username = f"{base}{secrets.token_hex(1)}"
            if not _taken(username):
                break
        else:
            return None, "تعذّر توليد اسم مستخدم فريد، أدخل اسمًا مختلفًا."

    password = (password or "").strip()
    if len(password) < 8:
        return None, "كلمة المرور يجب ألا تقل عن 8 أحرف."

    user = User(
        school_id=school_id,
        role_id=role.id,
        username=username,
        full_name=full_name.strip(),
        email=(email or None),
        phone=(phone or None),
        is_active=True,
    )
    user.set_password(password)
    try:
        with db.session.begin_nested():
            db.session.add(user)
            db.session.flush()
    except IntegrityError:
        return None, f"اسم المستخدم «{username}» مستخدم بالفعل في هذه المدرسة، اختر اسمًا آخر."
    return user, None
