"""Shared helpers for the LMS blueprint.

Extracted from `views.py` (ticket P1-18) so the individual route
modules (bank/quiz/assignment/templates/reports/passages/…) can share
them without pulling the whole monolith. No routes live here — pure
utility."""
import os
import uuid as _uuid
from datetime import datetime, timezone
from decimal import Decimal

from flask import current_app, flash, redirect, request, url_for
from flask_login import current_user

from ...extensions import db
from ...models import Student


ALLOWED_SUBMISSION_EXT = {"pdf", "doc", "docx", "png", "jpg", "jpeg", "zip", "txt"}


def _tz_safe_now(reference=None):
    """Return a `now` datetime whose tz-awareness matches `reference`.

    Postgres columns declared as DateTime(timezone=True) come back as
    tz-aware; SQLite gives us naive datetimes. Comparing the two raises
    'can't compare offset-naive and offset-aware datetimes'."""
    now = datetime.now(timezone.utc)
    if reference is None or reference.tzinfo is not None:
        return now
    return now.replace(tzinfo=None)


def _past_due(due_at):
    if due_at is None:
        return False
    return _tz_safe_now(due_at) > due_at


def _parse_dt(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def _current_student():
    """Resolve the logged-in user → Student row via an EXPLICIT link.

    Returns None when unlinked (no dev-fallback — that was ticket P1-16)."""
    uid = getattr(current_user, "id", None)
    if not uid:
        return None
    if hasattr(Student, "user_id"):
        s = Student.query.filter_by(user_id=uid).first()
        if s:
            return s
    return None


def _school_scope(query, model):
    school_id = getattr(current_user, "school_id", None)
    if school_id and hasattr(model, "school_id"):
        return query.filter(model.school_id == school_id)
    return query


# ─── Short-answer normalization (ticket P1-11) ─────────────────────────
_ARABIC_DIGIT_MAP = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_TASHKEEL = "".join(chr(c) for c in range(0x064B, 0x0653)) + "ٰۭۖ"
_TASHKEEL_MAP = {ord(ch): None for ch in _TASHKEEL}
_STRIP_PUNCT = ".,،؛?؟!:;\"'()[]{}<>«»…-_/\\"
_STRIP_PUNCT_MAP = {ord(ch): " " for ch in _STRIP_PUNCT}


def _normalize_short_answer(text) -> str:
    if text is None:
        return ""
    s = str(text)
    s = s.translate(_ARABIC_DIGIT_MAP)
    s = s.translate(_TASHKEEL_MAP)
    s = s.translate(_STRIP_PUNCT_MAP)
    s = " ".join(s.split()).strip().casefold()
    s = s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    s = s.replace("ى", "ي").replace("ة", "ه")
    return s


def _rubrics_for_subject(subject_id):
    from ...models import Rubric
    if not subject_id:
        return Rubric.query.filter_by(school_id=current_user.school_id).order_by(Rubric.title).all()
    return (
        Rubric.query.filter_by(school_id=current_user.school_id)
        .filter((Rubric.subject_id == subject_id) | (Rubric.subject_id.is_(None)))
        .order_by(Rubric.title).all()
    )


__all__ = [
    "os", "_uuid", "datetime", "timezone", "Decimal",
    "current_app", "flash", "redirect", "request", "url_for",
    "current_user", "db",
    "ALLOWED_SUBMISSION_EXT",
    "_tz_safe_now", "_past_due", "_parse_dt", "_current_student",
    "_school_scope", "_normalize_short_answer", "_rubrics_for_subject",
]
