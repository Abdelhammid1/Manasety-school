"""Receipt / Payment voucher helpers — سند قبض / سند صرف.

Every Payment and every approved Expense gets a matching numbered
voucher generated here. The voucher lives alongside the payment /
expense row (own PK) and is what gets printed for the parent /
recipient — a decoupled document from the underlying invoice or
expense row.
"""

from __future__ import annotations

from decimal import Decimal

from ..extensions import db
from ..models import ReceiptVoucher, Payment
from ..models.finance import Expense


def _next_number(school_id: int, prefix: str) -> str:
    from sqlalchemy import func
    last = (
        db.session.query(func.max(ReceiptVoucher.voucher_number))
        .filter(ReceiptVoucher.school_id == school_id)
        .filter(ReceiptVoucher.voucher_number.like(f"{prefix}-%"))
        .scalar()
    )
    n = 1
    if last:
        try:
            n = int(last.rsplit("-", 1)[-1]) + 1
        except (ValueError, IndexError):
            n = 1
    return f"{prefix}-{n:06d}"


def auto_create_for_payment(payment: Payment) -> ReceiptVoucher:
    """Book a سند قبض for an incoming payment. Refunds are booked as
    outgoing (سند صرف) since they represent cash leaving the school."""
    vt = "payment" if payment.is_refund else "receipt"
    prefix = "PV" if payment.is_refund else "RV"
    v = ReceiptVoucher(
        school_id=payment.school_id,
        voucher_type=vt,
        voucher_number=_next_number(payment.school_id, prefix),
        payment_id=payment.id,
        amount=Decimal(str(payment.amount or 0)),
        voucher_date=payment.payment_date,
        notes=payment.notes,
    )
    db.session.add(v); db.session.flush()
    return v


def auto_create_for_expense(expense: Expense) -> ReceiptVoucher:
    """سند صرف for an approved outgoing expense."""
    v = ReceiptVoucher(
        school_id=expense.school_id,
        voucher_type="payment",
        voucher_number=_next_number(expense.school_id, "PV"),
        expense_id=expense.id,
        amount=Decimal(str(expense.amount or 0)),
        voucher_date=expense.date,
        notes=expense.description,
    )
    db.session.add(v); db.session.flush()
    return v
