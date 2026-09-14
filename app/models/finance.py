from datetime import datetime, date
from ..extensions import db


ACCOUNT_TYPES = ["asset", "liability", "equity", "revenue", "expense"]
INVOICE_STATUSES = ["draft", "sent", "partial", "paid", "overdue", "refunded"]
INSTALLMENT_STATUSES = ["pending", "paid", "overdue"]


class Account(db.Model):
    __tablename__ = "accounts"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    code = db.Column(db.String(16), nullable=False)
    name = db.Column(db.String(128), nullable=False)
    type = db.Column(db.String(16), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey("accounts.id"))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_system = db.Column(db.Boolean, default=False, nullable=False)

    parent = db.relationship("Account", remote_side=[id], backref="children")

    __table_args__ = (
        db.UniqueConstraint("school_id", "code", name="uq_account_school_code"),
    )

    @property
    def balance(self) -> float:
        from sqlalchemy import func
        d = db.session.query(func.coalesce(func.sum(JournalLine.debit), 0)).filter_by(account_id=self.id).scalar() or 0
        c = db.session.query(func.coalesce(func.sum(JournalLine.credit), 0)).filter_by(account_id=self.id).scalar() or 0
        if self.type in ("asset", "expense"):
            return float(d) - float(c)
        return float(c) - float(d)


class JournalEntry(db.Model):
    __tablename__ = "journal_entries"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    entry_date = db.Column(db.Date, nullable=False, index=True)
    reference = db.Column(db.String(64))
    description = db.Column(db.String(255), nullable=False)
    related_kind = db.Column(db.String(32))
    related_id = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    lines = db.relationship("JournalLine", backref="entry", cascade="all, delete-orphan")

    @property
    def total_debit(self) -> float:
        return float(sum((l.debit or 0) for l in self.lines))

    @property
    def total_credit(self) -> float:
        return float(sum((l.credit or 0) for l in self.lines))


class JournalLine(db.Model):
    __tablename__ = "journal_lines"

    id = db.Column(db.Integer, primary_key=True)
    entry_id = db.Column(db.Integer, db.ForeignKey("journal_entries.id"), nullable=False, index=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False, index=True)
    debit = db.Column(db.Numeric(14, 2), default=0, nullable=False)
    credit = db.Column(db.Numeric(14, 2), default=0, nullable=False)
    description = db.Column(db.String(255))

    account = db.relationship("Account")


class FeeType(db.Model):
    __tablename__ = "fee_types"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    name = db.Column(db.String(128), nullable=False)
    default_amount = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    installable = db.Column(db.Boolean, default=True, nullable=False)
    revenue_account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    revenue_account = db.relationship("Account")

    __table_args__ = (
        db.UniqueConstraint("school_id", "name", name="uq_fee_type_school_name"),
    )


class Invoice(db.Model):
    __tablename__ = "invoices"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    enrollment_id = db.Column(db.Integer, db.ForeignKey("enrollments.id"), nullable=False, index=True)
    number = db.Column(db.String(32), nullable=False)
    issue_date = db.Column(db.Date, default=date.today, nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(16), default="draft", nullable=False)
    total_amount = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    paid_amount = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    notes = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    enrollment = db.relationship("Enrollment", backref="invoices")
    lines = db.relationship("InvoiceLine", backref="invoice", cascade="all, delete-orphan")
    installments = db.relationship("Installment", backref="invoice", cascade="all, delete-orphan", order_by="Installment.due_date")
    payments = db.relationship("Payment", backref="invoice")

    __table_args__ = (
        db.UniqueConstraint("school_id", "number", name="uq_invoice_school_number"),
    )

    @property
    def remaining(self) -> float:
        return float(self.total_amount) - float(self.paid_amount)


class InvoiceLine(db.Model):
    __tablename__ = "invoice_lines"

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=False, index=True)
    fee_type_id = db.Column(db.Integer, db.ForeignKey("fee_types.id"), nullable=False)
    description = db.Column(db.String(255))
    amount = db.Column(db.Numeric(12, 2), nullable=False)

    fee_type = db.relationship("FeeType")


class Installment(db.Model):
    __tablename__ = "installments"

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=False, index=True)
    due_date = db.Column(db.Date, nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    paid_amount = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    status = db.Column(db.String(16), default="pending", nullable=False)

    @property
    def remaining(self) -> float:
        return float(self.amount) - float(self.paid_amount)


class Payment(db.Model):
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=False, index=True)
    payment_date = db.Column(db.Date, default=date.today, nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    method = db.Column(db.String(16), default="cash", nullable=False)
    cash_account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    reference = db.Column(db.String(64))
    notes = db.Column(db.String(255))
    is_refund = db.Column(db.Boolean, default=False, nullable=False)
    journal_entry_id = db.Column(db.Integer, db.ForeignKey("journal_entries.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    cash_account = db.relationship("Account")
    journal_entry = db.relationship("JournalEntry")


class Vendor(db.Model):
    __tablename__ = "vendors"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(32))
    email = db.Column(db.String(128))
    address = db.Column(db.String(255))
    notes = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    expenses = db.relationship("Expense", backref="vendor")


class Expense(db.Model):
    __tablename__ = "expenses"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    vendor_id = db.Column(db.Integer, db.ForeignKey("vendors.id"))
    expense_account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    cash_account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    date = db.Column(db.Date, default=date.today, nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    reference = db.Column(db.String(64))
    journal_entry_id = db.Column(db.Integer, db.ForeignKey("journal_entries.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    expense_account = db.relationship("Account", foreign_keys=[expense_account_id])
    cash_account = db.relationship("Account", foreign_keys=[cash_account_id])
    journal_entry = db.relationship("JournalEntry")
