"""Validation for the academic forms (years, terms, grades, sections).

Every bad input becomes one Arabic message — what is wrong, the value,
and what to do — shown at the top of the form, with what the user typed
kept in the form. The checks run before saving; the database's unique
constraints stay the last line: an IntegrityError (e.g. two people saving
at once) is rolled back and explained, never a 500. Nothing internal
(SQL, a stack trace) reaches the message; a truly unexpected error stays
a 500 and is logged in full.

Duplicates are looked up WITH the soft-deleted rows: they still hold the
unique name / order in the database, so a check that missed them is what
used to end in an IntegrityError.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from flask import current_app
from sqlalchemy.exc import IntegrityError

from ...extensions import db

LTR, POP = "⁦", "⁩"


def iso(text) -> str:
    """Keep a name like 2026-2027 in its own order inside an Arabic sentence
    (Unicode isolate: LEFT-TO-RIGHT ISOLATE … POP DIRECTIONAL ISOLATE)."""
    return f"{LTR}{text}{POP}"


class Invalid(ValueError):
    """One user-facing message (already in Arabic)."""


def text(form, key, label, max_len=None) -> str:
    v = (form.get(key) or "").strip()
    if not v:
        raise Invalid(f"{label} مطلوب.")
    if max_len and len(v) > max_len:
        raise Invalid(f"{label} طويل جدًا (الحد الأقصى {max_len} حرف).")
    return v


def whole(form, key, label, *, minimum=1, maximum=None, keep=None) -> int:
    """A whole number >= minimum. `keep`: an existing value accepted as is
    (an old row saved before this rule)."""
    raw = (form.get(key) or "").strip()
    rule = f"{label} يجب أن يكون رقمًا صحيحًا {minimum} أو أكبر" + (f" وحتى {maximum}" if maximum else "")
    try:
        n = int(raw)
    except (TypeError, ValueError):
        raise Invalid(f"{rule} (القيمة المدخلة: «{raw or 'فاضي'}»).") from None
    if keep is not None and n == keep:
        return n
    if n < minimum or (maximum is not None and n > maximum):
        raise Invalid(f"{rule} (القيمة المدخلة: {n}).")
    return n


def percent(form, key, label="الوزن") -> Decimal:
    raw = (form.get(key) or "").strip()
    try:
        v = Decimal(raw)
    except (InvalidOperation, ValueError):
        raise Invalid(f"{label} يجب أن يكون رقمًا بين 0 و100 (القيمة المدخلة: «{raw or 'فاضي'}»).") from None
    if not v.is_finite() or v < 0 or v > 100:
        raise Invalid(f"{label} يجب أن يكون رقمًا بين 0 و100 (القيمة المدخلة: {raw}).")
    return v


def day(form, key, label) -> date:
    raw = (form.get(key) or "").strip()
    if not raw:
        raise Invalid(f"{label} مطلوب.")
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        raise Invalid(f"{label} غير صحيح — استخدم صيغة يوم/شهر/سنة من منتقي التاريخ.") from None


def clash(model, exclude_id=None, **where):
    """The row (deleted ones included) already holding these values."""
    q = model.query.execution_options(include_deleted=True).filter_by(**where)
    if exclude_id is not None:
        q = q.filter(model.id != exclude_id)
    return q.first()


def deleted_note(row) -> str:
    return " (موجود في المحذوفات — استرجعه أو اختر قيمة أخرى)" if getattr(row, "deleted_at", None) else ""


def commit(what: str) -> str | None:
    """Commit; on a unique / foreign-key violation roll back and return a
    message instead of a 500 (None = saved)."""
    try:
        db.session.commit()
        return None
    except IntegrityError:
        db.session.rollback()
        current_app.logger.warning("academic save refused by the database (%s)", what, exc_info=True)
        return (f"تعذّر حفظ {what}: يوجد سجل آخر بنفس الاسم أو الترتيب (ربما أُضيف للتو). "
                "حدّث الصفحة وراجع القيم ثم احفظ مرة أخرى.")


def values(obj, form, fields) -> dict:
    """What the form shows: the user's input after a refused save, else
    the saved row, as strings (dates as YYYY-MM-DD)."""
    if form:
        return {k: form.get(k, "") for k in form.keys()}
    out = {}
    for f in fields:
        v = getattr(obj, f, None) if obj is not None else None
        if isinstance(v, (date, datetime)):
            v = v.strftime("%Y-%m-%d")
        out[f] = "" if v is None else str(v)
    return out
