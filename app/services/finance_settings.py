"""The school's financial settings — the one place the app reads them.

Saved on the `schools` row by the settings page (and the console).
Everything that shows money, numbers an invoice, adds VAT, rounds an
amount or works out the fiscal year reads them here, with a safe
fallback for an empty or invalid value (an invoice never fails because
of a bad setting).

What an invoice keeps from the moment it is issued: its full number
(prefix included), its VAT rate and the rounding policy used. The
currency is never stored on it: it is always the school's current one,
so a currency change shows on every invoice, old and new, with the
amounts untouched (no conversion).

The lock: once a year that is not closed has financial activity (an
invoice, a payment or a journal entry), the seven fields below are
closed to the school's own users; only the Manasety console may change
them, and every console change is audited.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_UP, ROUND_UP, Decimal, InvalidOperation
from typing import Optional

from flask import g, has_request_context

LOCKED_FIELDS = ("currency", "currency_symbol", "default_tax_rate", "fiscal_year_start_month",
                 "invoice_prefix", "invoice_start_number", "rounding_policy")
ROUNDING = {"normal": ROUND_HALF_UP, "up": ROUND_UP, "down": ROUND_DOWN}
CENT = Decimal("0.01")
LOCKED_MESSAGE = ("الإعدادات المالية مقفولة لأن السنة الدراسية بدأ عليها شغل مالي، "
                  "للتعديل تواصل مع Manasety.")


@dataclass(frozen=True)
class FinanceSettings:
    currency: str
    currency_symbol: str
    default_tax_rate: Decimal
    fiscal_year_start_month: int
    invoice_prefix: str
    invoice_start_number: int
    rounding_policy: str


def _dec(v, default: Decimal) -> Decimal:
    try:
        d = Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return default
    return d if d.is_finite() else default


def settings_for(school) -> FinanceSettings:
    """The school's settings with every invalid value replaced by a safe one."""
    cur = (getattr(school, "currency", None) or "").strip()[:8] or "EGP"
    sym = (getattr(school, "currency_symbol", None) or "").strip()[:8] or cur
    tax = _dec(getattr(school, "default_tax_rate", 0) or 0, Decimal(0))
    tax = tax if Decimal(0) <= tax <= Decimal(100) else Decimal(0)
    month = getattr(school, "fiscal_year_start_month", None)
    month = month if isinstance(month, int) and 1 <= month <= 12 else 9
    prefix = (getattr(school, "invoice_prefix", None) or "").strip()[:16] or "INV"
    start = getattr(school, "invoice_start_number", None)
    start = start if isinstance(start, int) and start >= 1 else 1
    rounding = getattr(school, "rounding_policy", None)
    rounding = rounding if rounding in ROUNDING else "normal"
    return FinanceSettings(cur, sym, tax, month, prefix, start, rounding)


def settings_for_id(school_id: int) -> FinanceSettings:
    from ..extensions import db
    from ..models import School
    return settings_for(db.session.get(School, school_id))


def current() -> Optional[FinanceSettings]:
    """The current school's settings, once per request; None outside a school."""
    if has_request_context() and "finance_settings" in g:
        return g.finance_settings
    try:
        from .tenancy import current_school_id
        sid = current_school_id()
    except Exception:  # noqa: BLE001 — no school here (console, anonymous)
        sid = None
    fs = settings_for_id(sid) if sid else None
    if has_request_context():
        g.finance_settings = fs
    return fs


# ─── rounding ───────────────────────────────────────────────────────

def round_money(value, policy: Optional[str] = None) -> Decimal:
    """Every computed amount goes through here (to the cent)."""
    mode = ROUNDING.get(policy or "normal", ROUND_HALF_UP)
    return _dec(value, Decimal(0)).quantize(CENT, rounding=mode)


# ─── display ────────────────────────────────────────────────────────

def money(value, symbol: Optional[str] = None) -> str:
    """`1500.00 ج.م` — the school's current symbol (Jinja filter `money`)."""
    if symbol is None:
        fs = current()
        symbol = fs.currency_symbol if fs else ""
    amount = _dec(value or 0, Decimal(0)).quantize(CENT, rounding=ROUND_HALF_UP)
    return f"{amount} {symbol}".strip()


def currency_symbol() -> str:
    fs = current()
    return fs.currency_symbol if fs else ""


# ─── the fiscal year ────────────────────────────────────────────────

def fiscal_year_start(on: date, start_month: int) -> date:
    """The first day of the fiscal year that contains `on`."""
    year = on.year if on.month >= start_month else on.year - 1
    return date(year, start_month, 1)


# ─── the lock ───────────────────────────────────────────────────────

def has_financial_activity(school_id: int) -> bool:
    """An invoice, a payment or a journal entry in a year that is not
    closed yet. Not only the year marked active, and with no upper date:
    editing a year's dates or status must not reopen the settings. A year
    counts as closed only when the year-end process closed it (its
    YEAR-CLOSE journal entry, ledger.close_year) — a status flipped to
    "closed" in the year form does not."""
    from datetime import timedelta
    from ..extensions import db
    from ..models import AcademicYear, Enrollment, Invoice, JournalEntry, Payment
    years = AcademicYear.query.filter_by(school_id=school_id).all()
    closed_by_process = {r for (r,) in db.session.query(JournalEntry.related_id).filter(
        JournalEntry.school_id == school_id, JournalEntry.related_kind == "year_close").all()}
    closed = [y for y in years if y.status == "closed" and y.id in closed_by_process]
    open_years = [y for y in years if y not in closed]
    if not open_years:
        return False
    since = min(y.start_date for y in open_years)
    if closed:
        since = min(since, max(y.end_date for y in closed) + timedelta(days=1))
    year_ids = [y.id for y in open_years]
    if (db.session.query(Invoice.id)
            .outerjoin(Enrollment, Enrollment.id == Invoice.enrollment_id)
            .filter(Invoice.school_id == school_id,
                    db.or_(Enrollment.year_id.in_(year_ids), Invoice.issue_date >= since))
            .first()):
        return True
    if (db.session.query(Payment.id)
            .filter(Payment.school_id == school_id, Payment.payment_date >= since).first()):
        return True
    return (db.session.query(JournalEntry.id)
            .filter(JournalEntry.school_id == school_id, JournalEntry.entry_date >= since)
            .first()) is not None


# ─── the settings form ──────────────────────────────────────────────

def parse_form(form, school) -> tuple[dict, list[str]]:
    """The financial fields the form posted that differ from the school's
    current values, validated: ({field: new value}, [Arabic errors]).
    A field not posted (disabled while locked) is not a change."""
    changes: dict = {}
    errors: list[str] = []

    def text(field, max_len, label):
        if field not in form:
            return
        v = (form.get(field) or "").strip()
        if not v:
            errors.append(f"{label} مطلوب.")
        elif len(v) > max_len:
            errors.append(f"{label}: حتى {max_len} حروف.")
        elif v != (getattr(school, field) or ""):
            changes[field] = v

    def integer(field, lo, hi, label):
        if field not in form:
            return
        try:
            v = int((form.get(field) or "").strip())
        except ValueError:
            errors.append(f"{label}: رقم غير صحيح.")
            return
        if not lo <= v <= hi:
            errors.append(f"{label}: من {lo} إلى {hi}." if hi < 10**9 else f"{label}: لازم {lo} أو أكثر.")
        elif v != getattr(school, field):
            changes[field] = v

    text("currency", 8, "العملة (ISO)")
    text("currency_symbol", 8, "رمز العملة")
    if "currency" in changes:
        changes["currency"] = changes["currency"].upper()
    if "default_tax_rate" in form:
        try:
            rate = Decimal((form.get("default_tax_rate") or "0").strip())
            if not rate.is_finite():
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            errors.append("نسبة VAT: رقم غير صحيح.")
        else:
            if not Decimal(0) <= rate <= Decimal(100):
                errors.append("نسبة VAT من 0 إلى 100.")
            elif rate != _dec(getattr(school, "default_tax_rate", 0) or 0, Decimal(0)):
                changes["default_tax_rate"] = rate
    integer("fiscal_year_start_month", 1, 12, "شهر بداية السنة المالية")
    text("invoice_prefix", 16, "بادئة رقم الفاتورة")
    integer("invoice_start_number", 1, 10**9, "رقم الفاتورة الأولى")
    if "rounding_policy" in form:
        v = (form.get("rounding_policy") or "").strip()
        if v not in ROUNDING:
            errors.append("سياسة التقريب غير معروفة.")
        elif v != school.rounding_policy:
            changes["rounding_policy"] = v
    return changes, errors


def init_app(app) -> None:
    app.jinja_env.filters["money"] = money

    @app.context_processor
    def _finance_settings_ctx():
        return {"currency_symbol": currency_symbol}
