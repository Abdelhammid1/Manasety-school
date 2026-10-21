"""SAAS-033 — the platform's own invoices to schools. Completely separate
from a school's finance (own tables, numbering and maths). Platform
tables: no tenant ownership, never visible on a school host."""
from __future__ import annotations

from datetime import datetime, timezone

from ..extensions import db


def _utcnow():
    return datetime.now(timezone.utc)


INVOICE_STATUSES = ("draft", "issued", "partially_paid", "paid", "void")
PAYMENT_METHODS = ("bank_transfer", "cash", "instapay", "other")


class PlatformInvoice(db.Model):
    __tablename__ = "platform_invoices"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    # MNS-<year>-<0001>; assigned when issued (drafts have none), no gaps.
    number = db.Column(db.String(32), unique=True)
    status = db.Column(db.String(16), nullable=False, default="draft")
    currency = db.Column(db.String(8), nullable=False)
    issue_date = db.Column(db.Date)
    due_date = db.Column(db.Date)
    subtotal = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    tax_rate = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    tax_amount = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    total = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    notes = db.Column(db.Text)
    void_reason = db.Column(db.Text)
    pdf_path = db.Column(db.String(255))
    created_by_platform_user_id = db.Column(db.Integer, db.ForeignKey("platform_users.id"))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)

    lines = db.relationship("PlatformInvoiceLine", backref="invoice", order_by="PlatformInvoiceLine.id",
                            cascade="all, delete-orphan")
    payments = db.relationship("PlatformPayment", backref="invoice", order_by="PlatformPayment.id")
    school = db.relationship("School")

    __table_args__ = (
        db.CheckConstraint("status IN ('draft','issued','partially_paid','paid','void')",
                           name="ck_platform_invoices_status"),
    )


class PlatformInvoiceLine(db.Model):
    __tablename__ = "platform_invoice_lines"

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("platform_invoices.id"), nullable=False, index=True)
    description = db.Column(db.String(255), nullable=False)
    qty = db.Column(db.Numeric(10, 2), nullable=False, default=1)
    unit_price = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    amount = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    # subscription line
    plan_id = db.Column(db.Integer, db.ForeignKey("plans.id"))
    period_start = db.Column(db.Date)
    period_end = db.Column(db.Date)


class PlatformPayment(db.Model):
    """Never edited: a mistake is cancelled by a reversing (negative) payment."""
    __tablename__ = "platform_payments"

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("platform_invoices.id"), nullable=False, index=True)
    amount = db.Column(db.Numeric(14, 2), nullable=False)
    paid_on = db.Column(db.Date, nullable=False)
    method = db.Column(db.String(16), nullable=False)
    reference = db.Column(db.String(128))
    notes = db.Column(db.Text)
    reverses_payment_id = db.Column(db.Integer, db.ForeignKey("platform_payments.id"))
    recorded_by_platform_user_id = db.Column(db.Integer, db.ForeignKey("platform_users.id"))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        db.CheckConstraint("method IN ('bank_transfer','cash','instapay','other')",
                           name="ck_platform_payments_method"),
    )
