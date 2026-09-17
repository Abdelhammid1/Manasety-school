"""Ticket D — quick-journal templates (Marsoud-style).

A single function `apply_journal_template(key, school_id, amount,
counter_account_id, description="")` produces one balanced JournalEntry
from a template. `counter_account_id` is whatever the user picked from
Ticket A's free postable-account picker.

Templates cover the common non-invoice/non-payroll operations a school
does day-to-day: opening balance, capital increase, owner drawings,
custody in/out, loan in/out, donations, refunds outside invoices, asset
purchase, depreciation entry, employee custody settle.
"""
from decimal import Decimal
from datetime import date as _date_cls
from typing import Optional

from ..extensions import db
from ..models import Account
from .accounting import post_journal
from .system_codes import get_account_by_code


class QuickJournalError(Exception):
    pass


def _dec(v) -> Decimal:
    return Decimal(str(v or 0))


# key : {label, description, side_of_counter, counter_role, requires_sign}
# `side_of_counter`: is the counter_account_id DR (debit) or CR (credit)?
# `system_code`: the fixed system-side account (if any); for opening_balance
#                we derive it dynamically from the counter account's type.
TEMPLATES = {
    "opening_balance": {
        "label": "رصيد افتتاحي",
        "hint":  "قيّد الرصيد الافتتاحي لحساب أصل أو خصم. الاتجاه يُحدَّد تلقائياً من نوع الحساب.",
    },
    "capital_increase": {
        "label": "زيادة رأس المال",
        "hint":  "دخول فلوس جديدة من المالك. DR الحساب النقدي/البنكي المختار / CR رأس المال.",
        "system_code": "3100", "counter_side": "debit",
    },
    "owner_withdrawal": {
        "label": "مسحوبات المالك",
        "hint":  "خروج فلوس للمالك شخصياً. DR مسحوبات المالك / CR الحساب النقدي/البنكي.",
        "system_code": "3300", "counter_side": "credit",
    },
    "custody_received": {
        "label": "استلام أمانة من طرف",
        "hint":  "أمانة نستلمها من طرف، ونبقى مطالبين بردها. DR الحساب النقدي / CR أمانات.",
        "system_code": "2291", "counter_side": "debit",
    },
    "custody_returned": {
        "label": "رد أمانة لطرف",
        "hint":  "رد أمانة سبق استلامها. DR أمانات / CR الحساب النقدي.",
        "system_code": "2291", "counter_side": "credit",
    },
    "loan_received": {
        "label": "استلام قرض",
        "hint":  "قرض قصير أو طويل الأجل. DR الحساب النقدي / CR القروض.",
        "system_code": "2410", "counter_side": "debit",
    },
    "loan_installment": {
        "label": "سداد قسط قرض",
        "hint":  "سداد قسط من قرض قائم. DR القروض / CR الحساب النقدي.",
        "system_code": "2410", "counter_side": "credit",
    },
    "donation_received": {
        "label": "استلام تبرع/دعم",
        "hint":  "تبرع أو دعم خارجي للمدرسة. DR الحساب النقدي / CR إيرادات التبرعات.",
        "system_code": "4290", "counter_side": "debit",
    },
    "fee_refund": {
        "label": "رسوم مستردة لولي أمر (خارج فاتورة)",
        "hint":  "استرداد رسوم عند انسحاب طالب — قيد مباشر بدون ربط بفاتورة قائمة.",
        "system_code": None, "counter_side": "credit",
        # Uses the counter account (revenue) chosen by the user directly.
    },
    "fixed_asset_purchase": {
        "label": "شراء أصل ثابت",
        "hint":  "شراء أجهزة/أثاث/سيارات. DR حساب الأصل الثابت المختار / CR الحساب النقدي.",
        # Two custom pickers: asset side + counter (payment) side — handled specially.
    },
    "depreciation_entry": {
        "label": "قيد إهلاك شهري",
        "hint":  "إهلاك الأصول الثابتة الدوري. DR 5280 مصروف إهلاك / CR 1510 مجمّع الإهلاك.",
        # System-only journal — no counter picker.
    },
    "employee_custody_settle": {
        "label": "تسوية عهدة موظف",
        "hint":  "تسوية عهدة نقدية سبق صرفها لموظف. DR الحساب المختار (مصروف/رد نقدي) / CR 1170 عهدة نقدية.",
        "system_code": "1170", "counter_side": "debit",
    },
}


def apply_journal_template(
    template_key: str, school_id: int, amount, counter_account_id: int,
    description: str = "", *,
    entry_date: Optional[_date_cls] = None,
    extra_account_id: Optional[int] = None,
):
    """Runs a single template. `extra_account_id` is used only by
    fixed_asset_purchase (the asset being bought is on the DR side; the
    counter is where the money leaves)."""
    amount = _dec(amount)
    if amount <= 0:
        raise QuickJournalError("المبلغ يجب أن يكون أكبر من صفر.")
    tpl = TEMPLATES.get(template_key)
    if tpl is None:
        raise QuickJournalError(f"قالب غير معروف: {template_key}")

    counter = Account.query.filter_by(
        id=counter_account_id, school_id=school_id, is_postable=True,
    ).first()
    if counter is None:
        raise QuickJournalError("اختر حساباً قابلاً للترحيل.")

    at = entry_date or _date_cls.today()
    memo = description.strip() or tpl["label"]

    # ── Special cases ──────────────────────────────────────────────
    if template_key == "opening_balance":
        # Direction from counter account's type: assets/expense → DR;
        # liability/equity/revenue → CR. The other side lands on 3100
        # capital by convention.
        capital = get_account_by_code(school_id, "3100")
        if capital is None:
            raise QuickJournalError("لا يوجد حساب رأس مال (3100).")
        if counter.type in ("asset", "expense"):
            lines = [
                (counter.id, amount, Decimal(0), memo),
                (capital.id, Decimal(0), amount, "رصيد افتتاحي — رأس المال"),
            ]
        else:
            lines = [
                (capital.id, amount, Decimal(0), "رصيد افتتاحي — رأس المال"),
                (counter.id, Decimal(0), amount, memo),
            ]
        return post_journal(school_id=school_id, entry_date=at,
                            description=f"رصيد افتتاحي — {counter.name}",
                            reference=None, lines=lines,
                            related_kind="quick_journal", related_id=None)

    if template_key == "fixed_asset_purchase":
        asset_acc = Account.query.filter_by(
            id=extra_account_id, school_id=school_id, is_postable=True,
        ).first()
        if asset_acc is None or asset_acc.type != "asset":
            raise QuickJournalError("اختر حساب أصل ثابت صالحاً.")
        lines = [
            (asset_acc.id, amount, Decimal(0), memo or asset_acc.name),
            (counter.id, Decimal(0), amount, f"سداد — {counter.name}"),
        ]
        return post_journal(school_id=school_id, entry_date=at,
                            description=f"شراء أصل ثابت — {asset_acc.name}",
                            reference=None, lines=lines,
                            related_kind="quick_journal", related_id=None)

    if template_key == "depreciation_entry":
        expense = get_account_by_code(school_id, "5280")
        accumulated = get_account_by_code(school_id, "1510")
        if not expense or not accumulated:
            raise QuickJournalError("لا يوجد حساب مصروف/مجمّع إهلاك (5280/1510).")
        lines = [
            (expense.id, amount, Decimal(0), "مصروف إهلاك شهري"),
            (accumulated.id, Decimal(0), amount, "مجمّع إهلاك — الفترة"),
        ]
        return post_journal(school_id=school_id, entry_date=at,
                            description="قيد إهلاك شهري",
                            reference=None, lines=lines,
                            related_kind="quick_journal", related_id=None)

    # ── Standard two-line templates ───────────────────────────────
    if template_key == "fee_refund":
        # Both accounts come from the user (counter is the revenue we
        # reverse; extra is where the money exits).
        rev_acc = counter    # user picked the revenue account
        exit_acc = Account.query.filter_by(
            id=extra_account_id, school_id=school_id, is_postable=True,
        ).first()
        if exit_acc is None:
            raise QuickJournalError("اختر حساب خروج الفلوس.")
        lines = [
            (rev_acc.id, amount, Decimal(0), memo),
            (exit_acc.id, Decimal(0), amount, f"خروج — {exit_acc.name}"),
        ]
        return post_journal(school_id=school_id, entry_date=at,
                            description=f"استرداد رسوم — {memo}",
                            reference=None, lines=lines,
                            related_kind="quick_journal", related_id=None)

    # ── Rest: single system account + counter ─────────────────────
    system_code = tpl.get("system_code")
    if system_code is None:
        raise QuickJournalError("قالب لم يُعرَّف له حساب نظام.")
    sys_acc = get_account_by_code(school_id, system_code)
    if sys_acc is None:
        raise QuickJournalError(f"لا يوجد حساب النظام {system_code} — راجع الشجرة.")

    side = tpl["counter_side"]
    if side == "debit":
        lines = [
            (counter.id, amount, Decimal(0), memo),
            (sys_acc.id, Decimal(0), amount, tpl["label"]),
        ]
    else:
        lines = [
            (sys_acc.id, amount, Decimal(0), tpl["label"]),
            (counter.id, Decimal(0), amount, memo),
        ]
    return post_journal(school_id=school_id, entry_date=at,
                        description=f"{tpl['label']} — {memo}",
                        reference=None, lines=lines,
                        related_kind="quick_journal", related_id=None)
