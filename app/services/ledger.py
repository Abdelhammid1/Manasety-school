"""High-level ledger operations — the single entry point every screen
uses to book money.

Every function here is a **complete** operation that produces at least
one balanced journal entry through `post_journal`. Callers pass
business-level intent ("record this payment", "settle this accrual") —
they never touch account IDs directly. Account resolution is entirely
handled inside this service via `services.subsidiary`.

This is Marsoud's design ported to the school-platform vocabulary:
`post_invoice_to_ledger`, `record_payment`, `settle_accrual`, plus the
supporting `settle_liability` for deferred expenses.
"""
from decimal import Decimal
from datetime import date as _date_cls
from typing import Optional, Sequence, Tuple

from ..extensions import db
from ..models import (
    Account, Invoice, InvoiceLine, PaymentMethod, FeeType, Payment,
)
from ..models.hr import Payroll, PayrollSettlement
from .accounting import post_journal
from .subsidiary import (
    ensure_student_account, ensure_employee_account,
    party_ar_account, party_payroll_account,
)
from .system_codes import get_account_by_code


class LedgerError(Exception):
    """User-facing money-operation error. `.args[0]` is Arabic text
    intended to surface in a flash message, so keep it short & clear."""


# ─── Helpers ─────────────────────────────────────────────────────────

def _dec(v) -> Decimal:
    return Decimal(str(v or 0))


def _discount_account_for(school_id: int) -> Optional[Account]:
    from .system_codes import get_account_by_code
    return get_account_by_code(school_id, "4910")


def _ap_default_for(school_id: int) -> Optional[Account]:
    """AP header used for deferred expense bookings."""
    from .system_codes import get_account_by_code
    return get_account_by_code(school_id, "2110")


def _resolve_pm(school_id: int, payment_method_id: int) -> PaymentMethod:
    pm = PaymentMethod.query.filter_by(
        id=payment_method_id, school_id=school_id, is_active=True,
    ).first()
    if pm is None:
        raise LedgerError("طريقة الدفع غير موجودة أو معطّلة.")
    return pm


def _revenue_lines_by_fee_type(invoice: Invoice):
    """One credit line per fee_type on the invoice, keyed by the
    fee-type's own revenue_account. Marsoud's cost-centre pattern."""
    groups: dict[int, Decimal] = {}
    for line in invoice.lines:
        amt = _dec(line.amount)
        if amt == 0:
            continue
        if amt > 0:
            groups[line.fee_type_id] = groups.get(line.fee_type_id, Decimal(0)) + amt
    out = []
    for fee_type_id, amount in groups.items():
        ft = db.session.get(FeeType, fee_type_id)
        if not ft or not ft.revenue_account_id:
            continue
        out.append((ft.revenue_account_id, Decimal(0), amount, f"إيراد: {ft.name}"))
    return out


# ─── Invoices ────────────────────────────────────────────────────────

def post_invoice_to_ledger(invoice: Invoice, *, entry_date: Optional[_date_cls] = None):
    """Auto-post the invoice's journal on creation. No account choice
    from the caller. Debit = student's AR sub-account, credit = one
    line per fee_type + a discount contra-line if any negative InvoiceLine
    is present (sibling discount / scholarship) + a VAT payable line
    if invoice.tax_amount is set (Ticket "Additional 9")."""
    ar = party_ar_account(invoice)   # lazy-creates if missing
    total = _dec(invoice.total_amount)
    if total <= 0:
        raise LedgerError("لا يمكن قيد فاتورة بمبلغ صفر أو سالب.")

    lines: list[tuple[int, Decimal, Decimal, str]] = [
        (ar.id, total, Decimal(0), f"ذمم — {invoice.enrollment.student.full_name}"),
    ]
    lines.extend(_revenue_lines_by_fee_type(invoice))

    # Ticket "Additional 9" — split off VAT from the last revenue line
    # so the sum stays balanced. `invoice.tax_amount` is already
    # included in total_amount (gross); revenue lines added above are
    # gross-of-tax and need to be reduced.
    tax_amt = _dec(invoice.tax_amount)
    if tax_amt > 0:
        from .system_codes import get_account_by_code
        vat_acc = get_account_by_code(invoice.school_id, "2250")
        if vat_acc is not None:
            lines.append((vat_acc.id, Decimal(0), tax_amt, "ضريبة قيمة مضافة مستحقة"))
            rev_lines = [i for i, l in enumerate(lines) if l[2] > 0 and l[0] != vat_acc.id]
            if rev_lines:
                idx = rev_lines[0]
                aid, dr, cr, desc = lines[idx]
                lines[idx] = (aid, dr, cr - tax_amt, desc)

    # Discounts are negative InvoiceLine rows; aggregate their absolute
    # amount and post it to the discount account (contra-revenue debit).
    discount_amt = sum(
        -_dec(l.amount) for l in invoice.lines if _dec(l.amount) < 0
    )
    if discount_amt > 0:
        d_acc = _discount_account_for(invoice.school_id)
        if d_acc is not None:
            # A discount reduces net revenue by shifting DR to the
            # discount account (contra-revenue). To keep DR==CR when the
            # revenue lines above already include the *pre-discount*
            # amounts, we add both a DR on discount and a CR on the same
            # account… but the simpler symmetric form is: DR discount
            # (positive amount) + CR the corresponding revenue lines
            # (already included above). Instead we lower AR by the
            # discount: reduce the first DR line and post a matching CR
            # on the discount account so DR==CR holds.
            lines[0] = (ar.id, total - discount_amt, Decimal(0),
                        f"ذمم — {invoice.enrollment.student.full_name}")
            lines.append((d_acc.id, discount_amt, Decimal(0), "خصم"))
            # Now we must lower the total revenue by discount_amt so that
            # DR (net) equals CR (sum of positive rev lines). Take it
            # off the largest revenue line to keep the split intact.
            rev_lines = [l for l in lines if l[2] > 0]
            rev_lines.sort(key=lambda x: -x[2])
            if rev_lines:
                head = rev_lines[0]
                idx = lines.index(head)
                lines[idx] = (head[0], head[1], head[2] - discount_amt, head[3])

    je = post_journal(
        school_id=invoice.school_id,
        entry_date=entry_date or invoice.issue_date,
        description=f"فاتورة {invoice.number}",
        reference=invoice.number,
        lines=lines,
        related_kind="invoice", related_id=invoice.id,
    )
    return je


# ─── Payments (invoice reception) ────────────────────────────────────

def record_payment(
    invoice: Invoice, amount, payment_method_id: Optional[int],
    *, payment_date: Optional[_date_cls] = None,
    reference: Optional[str] = None, notes: Optional[str] = None,
    override_account_id: Optional[int] = None,
    created_by: Optional[int] = None,
):
    """Record a real cash/bank receipt against an invoice.

      DR   payment_method.account (or override_account_id if picked)
      CR   student's AR sub-account (يتخفّض دينها)

    Ticket A — when the caller passes `override_account_id`, we bypass
    PaymentMethod entirely and route the DR to that postable account.
    The pm_name label falls back to the account name so the audit trail
    still reads clearly.
    """
    amount = _dec(amount)
    if amount <= 0:
        raise LedgerError("المبلغ يجب أن يكون أكبر من صفر.")

    remaining = _dec(invoice.remaining)
    if amount > remaining + Decimal("0.01"):
        raise LedgerError(
            f"المبلغ ({amount:.2f}) أكبر من الرصيد المتبقّي ({remaining:.2f})."
        )

    pm = None
    if override_account_id:
        target_acc = Account.query.filter_by(
            id=override_account_id, school_id=invoice.school_id, is_postable=True,
        ).first()
        if target_acc is None:
            raise LedgerError("الحساب المختار غير صالح — يجب أن يكون قابلاً للترحيل.")
        target_account_id = target_acc.id
        label = target_acc.name
    else:
        if not payment_method_id:
            raise LedgerError("اختر طريقة دفع أو حساب استلام.")
        pm = _resolve_pm(invoice.school_id, payment_method_id)
        if pm.kind == "deferred":
            raise LedgerError(
                "لا يمكن استخدام طريقة دفع مؤجلة لقبض الفاتورة — الفاتورة الأصلية "
                "هي الالتزام."
            )
        if pm.account_id is None:
            raise LedgerError("طريقة الدفع غير مرتبطة بحساب — راجع إعدادات طرق الدفع.")
        target_account_id = pm.account_id
        label = pm.name

    ar = party_ar_account(invoice)
    pay_date = payment_date or _date_cls.today()

    je = post_journal(
        school_id=invoice.school_id,
        entry_date=pay_date,
        description=f"سداد فاتورة {invoice.number}",
        reference=invoice.number,
        lines=[
            (target_account_id, amount, Decimal(0), f"استلام — {label}"),
            (ar.id, Decimal(0), amount, f"تخفيض ذمة — {invoice.enrollment.student.full_name}"),
        ],
        related_kind="payment", related_id=invoice.id,
    )

    invoice.paid_amount = _dec(invoice.paid_amount) + amount
    # Distribute across installments FIFO for the running "next due"
    # tracking.
    left = amount
    for inst in invoice.installments:
        if left <= 0:
            break
        r = _dec(inst.remaining)
        if r <= 0:
            continue
        take = min(r, left)
        inst.paid_amount = _dec(inst.paid_amount) + take
        inst.status = "paid" if _dec(inst.remaining) <= 0 else "pending"
        left -= take

    if invoice.paid_amount >= invoice.total_amount:
        invoice.status = "paid"
    elif invoice.paid_amount > 0:
        invoice.status = "partial"

    payment = Payment(
        school_id=invoice.school_id,
        invoice_id=invoice.id,
        payment_date=pay_date,
        amount=amount,
        method=(pm.name if pm else label)[:16],
        cash_account_id=target_account_id,
        reference=reference,
        notes=notes,
        journal_entry_id=je.id,
    )
    db.session.add(payment); db.session.flush()
    return payment


# ─── Payroll ─────────────────────────────────────────────────────────

def post_payroll_accrual(payroll: Payroll, salary_expense_account: Account,
                        *, entry_date: Optional[_date_cls] = None):
    """Book the accrual on payroll creation:

      DR   salary expense account
      CR   employee's 2210 sub-account (رواتب مستحقة — <name>)
    """
    salary_payable = party_payroll_account(payroll.employee)
    net = _dec(payroll.net_pay)
    if net <= 0:
        raise LedgerError("صافي الراتب يجب أن يكون أكبر من صفر.")

    je = post_journal(
        school_id=payroll.school_id,
        entry_date=entry_date or _date_cls.today(),
        description=(
            f"استحقاق راتب {payroll.employee.full_name} — "
            f"{payroll.period_year}/{payroll.period_month:02d}"
        ),
        reference=f"PAYROLL-{payroll.id}",
        lines=[
            (salary_expense_account.id, net, Decimal(0), "مصروف رواتب"),
            (salary_payable.id, Decimal(0), net,
             f"استحقاق راتب — {payroll.employee.full_name}"),
        ],
        related_kind="payroll_accrual", related_id=payroll.id,
    )
    return je


def issue_employee_advance(employee, amount, payment_method_id: int,
                           *, deduction_plan: str = "full_next_month",
                           installment_count: Optional[int] = None,
                           date_given=None, notes: Optional[str] = None):
    """Ticket "Additional 12" — hand out a cash advance to an employee.

      DR   1160 سلف الموظفين
      CR   payment_method.account
    """
    from ..models.hr import EmployeeAdvance
    amount = _dec(amount)
    if amount <= 0:
        raise LedgerError("مبلغ السلفة يجب أن يكون أكبر من صفر.")
    pm = _resolve_pm(employee.school_id, payment_method_id)
    if pm.kind == "deferred" or pm.account_id is None:
        raise LedgerError("اختر طريقة دفع فعلية للسلفة (نقدي/بنك).")

    advance_acc = get_account_by_code(employee.school_id, "1160")
    if advance_acc is None:
        raise LedgerError(
            "لا يوجد حساب مُعيَّن لسلف الموظفين — حدّده من دليل الحسابات."
        )

    at = date_given or _date_cls.today()
    je = post_journal(
        school_id=employee.school_id,
        entry_date=at,
        description=f"صرف سلفة — {employee.full_name}",
        reference=None,
        lines=[
            (advance_acc.id, amount, Decimal(0), f"سلفة — {employee.full_name}"),
            (pm.account_id, Decimal(0), amount, f"خروج — {pm.name}"),
        ],
        related_kind="employee_advance", related_id=None,
    )
    adv = EmployeeAdvance(
        school_id=employee.school_id, employee_id=employee.id,
        amount=amount, remaining_balance=amount,
        date_given=at, deduction_plan=deduction_plan,
        installment_count=installment_count if deduction_plan == "installments" else None,
        journal_entry_id=je.id, notes=notes,
    )
    db.session.add(adv); db.session.flush()
    return adv


def apply_advance_deductions(payroll: Payroll) -> Decimal:
    """Ticket "Additional 12" — deduct any active advance installments
    from a payroll accrual. Called AFTER post_payroll_accrual so the
    accrual booking is against the full net_pay, then this posts a
    supplementary entry moving the deduction back to 1160.

      DR   employee 2210 sub-account   (reduce the just-accrued liability)
      CR   1160 سلف الموظفين          (recover the advance)

    Returns the total amount deducted. Payroll.net_pay stays as-is;
    Payroll.paid_amount rises by the deducted amount so the remaining
    liability to actually cash-out shrinks. The employee's payslip
    shows this line separately (rendered on payroll_detail.html)."""
    from ..models.hr import EmployeeAdvance
    active = EmployeeAdvance.query.filter_by(
        employee_id=payroll.employee_id, status="active",
    ).all()
    if not active:
        return Decimal(0)

    advance_acc = get_account_by_code(payroll.school_id, "1160")
    if advance_acc is None:
        return Decimal(0)
    salary_payable = party_payroll_account(payroll.employee)

    net = _dec(payroll.net_pay)
    total_deducted = Decimal(0)
    for adv in active:
        remaining_on_payroll = net - total_deducted
        if remaining_on_payroll <= 0:
            break
        # Compute per-payroll installment.
        if adv.deduction_plan == "installments" and (adv.installment_count or 0) > 0:
            per = (_dec(adv.amount) / Decimal(adv.installment_count)).quantize(Decimal("0.01"))
        else:
            per = _dec(adv.remaining_balance)   # full_next_month → clear it
        take = min(per, _dec(adv.remaining_balance), remaining_on_payroll)
        if take <= 0:
            continue

        post_journal(
            school_id=payroll.school_id,
            entry_date=_date_cls.today(),
            description=f"خصم سلفة — {payroll.employee.full_name}",
            reference=f"PAYROLL-{payroll.id}",
            lines=[
                (salary_payable.id, take, Decimal(0), "خصم سلفة من راتب مستحق"),
                (advance_acc.id, Decimal(0), take, "سداد سلفة"),
            ],
            related_kind="advance_deduction", related_id=adv.id,
        )
        adv.remaining_balance = _dec(adv.remaining_balance) - take
        if adv.remaining_balance <= Decimal("0.005"):
            adv.status = "settled"
        payroll.paid_amount = _dec(payroll.paid_amount) + take
        total_deducted += take
    return total_deducted


def settle_accrual(payroll: Payroll, payment_method_id: int, amount=None,
                   *, settled_at: Optional[_date_cls] = None,
                   notes: Optional[str] = None):
    """Settle all-or-part of an accrued payroll. Partial supported.

      DR   employee's 2210 sub-account
      CR   payment_method.account (or leaves as deferred if the caller
           insists — shouldn't, since the accrual is already the liability).
    """
    if payroll.is_settled:
        raise LedgerError("هذا المستحق تم صرفه بالكامل مسبقاً.")

    remaining = _dec(payroll.remaining)
    pay_amt = _dec(amount) if amount is not None else remaining
    if pay_amt <= 0:
        raise LedgerError("المبلغ يجب أن يكون أكبر من صفر.")
    if pay_amt > remaining + Decimal("0.005"):
        raise LedgerError(
            f"القيمة ({pay_amt:.2f}) أكبر من الرصيد المتبقي ({remaining:.2f})."
        )

    pm = _resolve_pm(payroll.school_id, payment_method_id)
    if pm.kind == "deferred" or pm.account_id is None:
        raise LedgerError(
            "لا يمكن صرف راتب عبر طريقة مؤجلة — الاستحقاق نفسه هو الالتزام."
        )

    salary_payable = party_payroll_account(payroll.employee)
    at = settled_at or _date_cls.today()

    je = post_journal(
        school_id=payroll.school_id,
        entry_date=at,
        description=(
            f"صرف راتب {payroll.employee.full_name} — "
            f"{payroll.period_year}/{payroll.period_month:02d}"
        ),
        reference=f"PAYROLL-{payroll.id}",
        lines=[
            (salary_payable.id, pay_amt, Decimal(0),
             f"سداد راتب مستحق — {payroll.employee.full_name}"),
            (pm.account_id, Decimal(0), pay_amt, f"خروج — {pm.name}"),
        ],
        related_kind="payroll_settlement", related_id=payroll.id,
    )

    payroll.paid_amount = _dec(payroll.paid_amount) + pay_amt
    if _dec(payroll.remaining) <= Decimal("0.005"):
        payroll.paid_at = at

    settlement = PayrollSettlement(
        school_id=payroll.school_id,
        payroll_id=payroll.id,
        payment_method_id=pm.id,
        amount=pay_amt, settled_at=at,
        journal_entry_id=je.id, notes=notes,
    )
    db.session.add(settlement); db.session.flush()
    return settlement


# ─── Void / Refund ───────────────────────────────────────────────────

def void_invoice(invoice: Invoice, reason: str, *, entry_date=None):
    """Reverse the original invoice journal entry entirely. Only allowed
    while paid_amount == 0; anything else needs `issue_refund`."""
    if _dec(invoice.paid_amount) > 0:
        raise LedgerError(
            "لا يمكن إلغاء فاتورة عليها مبالغ مسددة — استخدم استرداد بدل الإلغاء."
        )
    if invoice.status == "cancelled":
        raise LedgerError("الفاتورة ملغاة بالفعل.")

    ar = party_ar_account(invoice)
    total = _dec(invoice.total_amount)
    if total <= 0:
        # Nothing to reverse — just mark cancelled.
        invoice.status = "cancelled"
        return None

    # Reverse the original entry with symmetric CR/DR flip.
    #   CR AR (release the receivable)
    #   DR revenue lines (reverse recognition)
    lines: list[tuple[int, Decimal, Decimal, str]] = [
        (ar.id, Decimal(0), total, f"إلغاء ذمم — {invoice.enrollment.student.full_name}"),
    ]
    for aid, dr, cr, desc in _revenue_lines_by_fee_type(invoice):
        # swap dr↔cr
        lines.append((aid, cr, dr, f"عكس {desc}"))

    je = post_journal(
        school_id=invoice.school_id,
        entry_date=entry_date or _date_cls.today(),
        description=f"إلغاء فاتورة {invoice.number} — {reason}",
        reference=invoice.number,
        lines=lines,
        related_kind="invoice_void", related_id=invoice.id,
    )
    invoice.status = "cancelled"
    invoice.notes = ((invoice.notes or "") + f"\nإلغاء: {reason}").strip()
    return je


def issue_refund(invoice: Invoice, amount, payment_method_id: int, reason: str,
                 *, refund_date: Optional[_date_cls] = None):
    """Refund cash we already received on this invoice.

      DR   student's AR sub-account (يعاد الدين — لا شيء مطلوب من الطالب الآن)
      CR   payment_method.account (خروج فلوس)

    Capped by paid_amount so we can never refund more than was actually
    collected. Also lowers invoice.paid_amount + installment.paid_amount
    LIFO (reverse of intake).
    """
    amount = _dec(amount)
    if amount <= 0:
        raise LedgerError("مبلغ الاسترداد يجب أن يكون أكبر من صفر.")
    if amount > _dec(invoice.paid_amount) + Decimal("0.01"):
        raise LedgerError(
            f"لا يمكن استرداد أكثر من المدفوع ({invoice.paid_amount})."
        )

    pm = _resolve_pm(invoice.school_id, payment_method_id)
    if pm.kind == "deferred" or pm.account_id is None:
        raise LedgerError("اختر طريقة دفع فعلية — الاسترداد يستدعي حركة كاش/بنك.")

    ar = party_ar_account(invoice)
    at = refund_date or _date_cls.today()

    je = post_journal(
        school_id=invoice.school_id,
        entry_date=at,
        description=f"استرداد على الفاتورة {invoice.number} — {reason}",
        reference=invoice.number,
        lines=[
            (ar.id, amount, Decimal(0), f"إعادة ذمة — {invoice.enrollment.student.full_name}"),
            (pm.account_id, Decimal(0), amount, f"خروج — {pm.name}"),
        ],
        related_kind="invoice_refund", related_id=invoice.id,
    )

    invoice.paid_amount = _dec(invoice.paid_amount) - amount
    left = amount
    for inst in reversed(list(invoice.installments)):
        if left <= 0:
            break
        paid = _dec(inst.paid_amount)
        if paid <= 0:
            continue
        take = min(paid, left)
        inst.paid_amount = paid - take
        inst.status = "paid" if _dec(inst.remaining) <= 0 else "pending"
        left -= take

    if invoice.paid_amount <= 0:
        invoice.status = "refunded"
    else:
        invoice.status = "partial"

    payment = Payment(
        school_id=invoice.school_id,
        invoice_id=invoice.id,
        payment_date=at,
        amount=amount,
        method=pm.name[:16],
        cash_account_id=pm.account_id,
        is_refund=True,
        reference=None, notes=reason,
        journal_entry_id=je.id,
    )
    db.session.add(payment); db.session.flush()
    return payment


# ─── Bulk payment across invoices (Ticket "Additional 5") ────────────

def record_bulk_payment(
    invoices_amounts: Sequence[Tuple[Invoice, Decimal]],
    payment_method_id: int, *,
    payment_date: Optional[_date_cls] = None,
    notes: Optional[str] = None,
    reference: Optional[str] = None,
):
    """Cover several invoices with a single receipt. `invoices_amounts`
    is a list of (invoice, amount) pairs; the sum is DR-ed to the
    payment method once, and each invoice's AR sub-account is credited
    separately in the same balanced entry.

    Callers can hand-tune allocations, or use `distribute_fifo` to
    auto-fill oldest-first.
    """
    if not invoices_amounts:
        raise LedgerError("لم تُختَر فواتير للسداد.")
    school_ids = {inv.school_id for inv, _ in invoices_amounts}
    if len(school_ids) > 1:
        raise LedgerError("لا يمكن دمج فواتير من مدرستين في نفس الدفعة.")
    school_id = school_ids.pop()

    pm = _resolve_pm(school_id, payment_method_id)
    if pm.kind == "deferred" or pm.account_id is None:
        raise LedgerError("طريقة دفع مؤجلة لا تناسب قبضاً فعلياً.")

    # Validate + accumulate.
    total = Decimal(0)
    per_line = []
    for inv, amt in invoices_amounts:
        amt = _dec(amt)
        if amt <= 0:
            continue
        remaining = _dec(inv.remaining)
        if amt > remaining + Decimal("0.01"):
            raise LedgerError(
                f"مبلغ فاتورة {inv.number} ({amt}) أكبر من المتبقي ({remaining})."
            )
        ar = party_ar_account(inv)
        per_line.append((inv, ar, amt))
        total += amt
    if total <= 0:
        raise LedgerError("إجمالي الدفعة صفر.")

    at = payment_date or _date_cls.today()
    lines = [(pm.account_id, total, Decimal(0), f"استلام مجمّع — {pm.name}")]
    for inv, ar, amt in per_line:
        lines.append((ar.id, Decimal(0), amt,
                      f"تخفيض ذمة — {inv.enrollment.student.full_name} ({inv.number})"))

    je = post_journal(
        school_id=school_id, entry_date=at,
        description=f"دفعة مجمّعة — {len(per_line)} فاتورة",
        reference=reference,
        lines=lines,
        related_kind="bulk_payment", related_id=None,
    )

    payments = []
    for inv, ar, amt in per_line:
        inv.paid_amount = _dec(inv.paid_amount) + amt
        left = amt
        for inst in inv.installments:
            if left <= 0:
                break
            r = _dec(inst.remaining)
            if r <= 0:
                continue
            take = min(r, left)
            inst.paid_amount = _dec(inst.paid_amount) + take
            inst.status = "paid" if _dec(inst.remaining) <= 0 else "pending"
            left -= take
        if inv.paid_amount >= inv.total_amount:
            inv.status = "paid"
        elif inv.paid_amount > 0:
            inv.status = "partial"
        p = Payment(
            school_id=school_id, invoice_id=inv.id, payment_date=at,
            amount=amt, method=pm.name[:16], cash_account_id=pm.account_id,
            reference=reference, notes=notes, journal_entry_id=je.id,
        )
        db.session.add(p)
        payments.append(p)
    db.session.flush()
    return je, payments


def distribute_fifo(invoices, total_amount) -> list[tuple[Invoice, Decimal]]:
    """Split a lump-sum across invoices oldest-due first, filling each
    up to its remaining before moving to the next. Convenience for the
    bulk-payment UI."""
    total = _dec(total_amount)
    out = []
    for inv in sorted(invoices, key=lambda i: (i.due_date, i.id)):
        if total <= 0:
            break
        r = _dec(inv.remaining)
        if r <= 0:
            continue
        take = min(r, total)
        out.append((inv, take))
        total -= take
    return out


# ─── Overdue sweep ───────────────────────────────────────────────────

def send_payment_reminders(school_id: int, *, today=None) -> dict:
    """Ticket "Additional 4" — daily sweep. For each unpaid invoice we
    emit at most ONE reminder per (invoice, kind) tuple, which is what
    NotificationLog.(related_kind, related_id, kind) already enforces
    logically for us — we check before sending.

    Kinds emitted:
      · `reminder_7d` — due_date is 7 days out
      · `reminder_3d` — due_date is 3 days out
      · `reminder_overdue` — status is 'overdue'

    Uses services.notifications.send_notification which handles the
    WhatsApp/email fan-out; on a stub provider this just writes to
    NotificationLog and stops there.
    """
    from datetime import timedelta
    from ..models import Invoice, NotificationLog
    from .notifications import send_notification
    today = today or _date_cls.today()

    windows = [
        ("reminder_7d",       today + timedelta(days=7),  "قبل استحقاق"),
        ("reminder_3d",       today + timedelta(days=3),  "قبل استحقاق"),
        ("reminder_overdue",  None,                        "متأخرة"),
    ]
    counts = {k: 0 for k, _, _ in windows}

    for kind, matched_date, label in windows:
        q = Invoice.query.filter(
            Invoice.school_id == school_id,
            Invoice.status.notin_(("paid", "cancelled", "refunded")),
        )
        if matched_date is not None:
            q = q.filter(Invoice.due_date == matched_date)
        else:
            q = q.filter(Invoice.status == "overdue")

        for inv in q.all():
            already = NotificationLog.query.filter_by(
                school_id=school_id,
                related_kind="reminder",
                related_id=inv.id,
                kind=kind,
            ).first()
            if already:
                continue
            student = inv.enrollment.student if inv.enrollment else None
            phone = (student.parent_phone or "").strip() if student else ""
            send_notification(
                school_id=school_id,
                kind=kind,
                payload={
                    "student":         student.full_name if student else "",
                    "invoice_number":  inv.number,
                    "amount":          float(inv.remaining),
                    "due_date":        inv.due_date.isoformat(),
                    "message": (
                        f"تذكير رسوم ({label}): الفاتورة {inv.number} — "
                        f"المتبقّي {inv.remaining:.2f} — الاستحقاق {inv.due_date}."
                    ),
                },
                target_phone=phone or None,
                student_id=(student.id if student else None),
                related_kind="reminder", related_id=inv.id,
            )
            counts[kind] += 1
    return counts


def record_transfer(school_id: int, from_account_id: int, to_account_id: int,
                    amount, *, transfer_date=None, description: str = "",
                    created_by: Optional[int] = None):
    """Ticket E — move money between two treasury/bank accounts.

      DR   to_account
      CR   from_account

    Both accounts must be postable leaves. No revenue/expense impact.
    """
    amount = _dec(amount)
    if amount <= 0:
        raise LedgerError("المبلغ يجب أن يكون أكبر من صفر.")
    if from_account_id == to_account_id:
        raise LedgerError("لا يمكن التحويل بين الحساب ونفسه.")

    frm = Account.query.filter_by(id=from_account_id, school_id=school_id, is_postable=True).first()
    to  = Account.query.filter_by(id=to_account_id,   school_id=school_id, is_postable=True).first()
    if not frm or not to:
        raise LedgerError("اختر حسابين قابلين للترحيل.")

    at = transfer_date or _date_cls.today()
    memo = description.strip() or f"تحويل من {frm.name} إلى {to.name}"

    return post_journal(
        school_id=school_id, entry_date=at, description=memo,
        reference=None,
        lines=[
            (to.id, amount, Decimal(0), f"استلام تحويل — {frm.name}"),
            (frm.id, Decimal(0), amount, f"إرسال تحويل — {to.name}"),
        ],
        related_kind="transfer", related_id=None,
    )


def close_fiscal_year(school_id: int, year, *, entry_date=None, dry_run=False):
    """Ticket "Additional 11" — zero out every P&L account into 3200
    retained earnings and mark the AcademicYear as closed.

    Reads DR/CR sums from JournalLine directly so aggregate balances
    aren't double-counted. `year` is the AcademicYear ORM instance.
    When `dry_run` is True nothing is written; returns the preview.
    """
    from sqlalchemy import func
    year_start, year_end = year.start_date, year.end_date

    revenue_leaves = Account.query.filter_by(
        school_id=school_id, type="revenue", is_postable=True,
    ).all()
    expense_leaves = Account.query.filter_by(
        school_id=school_id, type="expense", is_postable=True,
    ).all()

    def _balance_in_range(acc_id: int) -> Decimal:
        d = db.session.query(func.coalesce(func.sum(JournalLine.debit), 0)) \
            .join(JournalLine.entry) \
            .filter(JournalLine.account_id == acc_id,
                    JournalEntry.entry_date >= year_start,
                    JournalEntry.entry_date <= year_end).scalar() or 0
        c = db.session.query(func.coalesce(func.sum(JournalLine.credit), 0)) \
            .join(JournalLine.entry) \
            .filter(JournalLine.account_id == acc_id,
                    JournalEntry.entry_date >= year_start,
                    JournalEntry.entry_date <= year_end).scalar() or 0
        return Decimal(str(c)) - Decimal(str(d))  # revenue: CR positive; expense: DR positive (we'll flip)

    total_revenue = Decimal(0)
    revenue_moves: list[tuple[int, Decimal, Decimal, str]] = []
    for acc in revenue_leaves:
        net = _balance_in_range(acc.id)   # positive for revenues
        if net == 0:
            continue
        total_revenue += net
        revenue_moves.append((acc.id, net, Decimal(0), f"إقفال إيرادات — {acc.name}"))

    total_expense = Decimal(0)
    expense_moves: list[tuple[int, Decimal, Decimal, str]] = []
    for acc in expense_leaves:
        # For expenses, DR-CR is positive; flip sign to keep CR side above.
        d = db.session.query(func.coalesce(func.sum(JournalLine.debit), 0)) \
            .join(JournalLine.entry) \
            .filter(JournalLine.account_id == acc.id,
                    JournalEntry.entry_date >= year_start,
                    JournalEntry.entry_date <= year_end).scalar() or 0
        c = db.session.query(func.coalesce(func.sum(JournalLine.credit), 0)) \
            .join(JournalLine.entry) \
            .filter(JournalLine.account_id == acc.id,
                    JournalEntry.entry_date >= year_start,
                    JournalEntry.entry_date <= year_end).scalar() or 0
        net = Decimal(str(d)) - Decimal(str(c))   # positive for expenses
        if net == 0:
            continue
        total_expense += net
        expense_moves.append((acc.id, Decimal(0), net, f"إقفال مصروفات — {acc.name}"))

    net_income = total_revenue - total_expense
    retained = get_account_by_code(school_id, "3200")

    preview = {
        "total_revenue": float(total_revenue),
        "total_expense": float(total_expense),
        "net_income":    float(net_income),
        "retained_earnings_account": retained.code if retained else None,
        "revenue_lines_to_close": len(revenue_moves),
        "expense_lines_to_close": len(expense_moves),
    }
    if dry_run:
        return preview
    if retained is None:
        raise LedgerError(
            "لا يوجد حساب مُعيَّن كـ «أرباح/خسائر مرحّلة». حدّده من دليل الحسابات."
        )

    lines = list(revenue_moves) + list(expense_moves)
    if net_income > 0:
        lines.append((retained.id, Decimal(0), net_income, "صافي الربح المرحّل"))
    elif net_income < 0:
        lines.append((retained.id, -net_income, Decimal(0), "صافي الخسارة المرحّلة"))

    if not lines:
        year.status = "closed"
        return preview

    post_journal(
        school_id=school_id,
        entry_date=entry_date or year.end_date,
        description=f"إقفال السنة المالية {year.name}",
        reference=f"YEAR-CLOSE-{year.id}",
        lines=lines,
        related_kind="year_close", related_id=year.id,
    )
    year.status = "closed"
    return preview


def _period_key(freq: str, today) -> str:
    """Stable string used to dedup recurring invoices per (student,
    schedule, period). Monthly = YYYY-MM, yearly = YYYY, termly falls
    back to YYYY-Q<n> derived from month/3 so we don't need the school's
    actual term calendar for the guard."""
    from datetime import date as _d
    if freq == "monthly":
        return f"{today.year}-{today.month:02d}"
    if freq == "yearly":
        return f"{today.year}"
    if freq == "termly":
        return f"{today.year}-T{((today.month - 1) // 3) + 1}"
    return today.isoformat()


def generate_recurring_invoices(school_id: int, *, today=None) -> dict:
    """Ticket "Additional 8" — sweep every active RecurringFeeSchedule
    for a school and materialise invoices for every eligible student.

    Idempotent via RecurringInvoiceLog (schedule_id, student_id,
    period_key). One journal per invoice via post_invoice_to_ledger.

    Returns {schedule_id: count} for the cron summary.
    """
    from datetime import date as _d, timedelta
    from ..models import (
        AcademicYear, RecurringFeeSchedule, RecurringInvoiceLog,
        Enrollment, Student, Invoice, InvoiceLine, Installment, FeeType,
    )
    today = today or _d.today()
    year = AcademicYear.query.filter_by(school_id=school_id, status="active").first()
    if not year:
        return {}

    schedules = RecurringFeeSchedule.query.filter_by(
        school_id=school_id, is_active=True,
    ).all()
    counts: dict[int, int] = {}

    for sched in schedules:
        # `day_of_period` is treated as day-of-month for monthly/yearly
        # and day-of-quarter for termly. Only fire on the matching day.
        if today.day != sched.day_of_period:
            continue

        ft = db.session.get(FeeType, sched.fee_type_id)
        if not ft or not ft.is_active:
            continue

        eligible = Enrollment.query.filter_by(
            school_id=school_id, year_id=year.id, status="active",
        )
        if sched.applies_to_grade_id:
            eligible = eligible.filter(Enrollment.grade_id == sched.applies_to_grade_id)
        eligible_list = eligible.all()
        period_key = _period_key(sched.frequency, today)

        for enr in eligible_list:
            already = RecurringInvoiceLog.query.filter_by(
                schedule_id=sched.id, student_id=enr.student_id,
                period_key=period_key,
            ).first()
            if already:
                continue

            n = Invoice.query.filter_by(school_id=school_id).count() + 1
            number = f"INV-{year.name}-R{sched.id}-{period_key}-{n:05d}"
            due = today + timedelta(days=15)
            amount = ft.default_amount or Decimal(0)
            if amount <= 0:
                continue

            inv = Invoice(
                school_id=school_id, enrollment_id=enr.id,
                number=number, issue_date=today, due_date=due,
                status="sent", total_amount=amount,
            )
            db.session.add(inv); db.session.flush()
            db.session.add(InvoiceLine(
                invoice_id=inv.id, fee_type_id=ft.id,
                description=ft.name, amount=amount,
            ))
            db.session.add(Installment(
                invoice_id=inv.id, due_date=due, amount=amount,
            ))
            db.session.flush()
            try:
                post_invoice_to_ledger(inv, entry_date=today)
            except LedgerError:
                # Rare — happens if a school has no student sub-account
                # header. Skip this student, keep sweeping the rest.
                db.session.rollback()
                continue
            db.session.add(RecurringInvoiceLog(
                school_id=school_id, schedule_id=sched.id,
                student_id=enr.student_id, period_key=period_key,
                invoice_id=inv.id,
            ))
            counts[sched.id] = counts.get(sched.id, 0) + 1

        sched.last_run_at = today
    return counts


def update_overdue_invoices(school_id: int, *, today=None) -> int:
    """Flip due_date<today AND status not in (paid, cancelled, refunded)
    → status=overdue. Returns the row count so cron can log a summary.
    Idempotent — running twice on the same day does nothing new."""
    today = today or _date_cls.today()
    q = (
        Invoice.query.filter(
            Invoice.school_id == school_id,
            Invoice.due_date < today,
            Invoice.status.notin_(("paid", "cancelled", "refunded", "overdue")),
        )
    )
    rows = q.all()
    for inv in rows:
        inv.status = "overdue"
    return len(rows)
