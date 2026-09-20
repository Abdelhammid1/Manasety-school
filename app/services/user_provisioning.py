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

    username = (username or "").strip() or suggest_username(full_name, phone)
    # De-duplicate username inside the school by appending a short tail.
    base = username
    tries = 0
    while User.query.filter_by(school_id=school_id, username=username).first():
        tries += 1
        if tries > 20:
            return None, "تعذّر توليد اسم مستخدم فريد — أدخل اسمًا مختلفًا."
        username = f"{base}{secrets.token_hex(1)}"

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
    db.session.add(user)
    db.session.flush()
    return user, None
