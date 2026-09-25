from datetime import datetime, date
from ..extensions import db
from .mixins import SoftDeleteMixin


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
    # Ticket B — Level-1/Level-2 rows are containers (is_postable=False),
    # only Level-3 leaves accept journal lines. Enforced by post_journal.
    is_postable = db.Column(db.Boolean, default=True, nullable=False)
    # Ticket A — semantic role that pins this account as the default for
    # a specific operation (AR upserts, cash-received default, sibling
    # discount, payroll-salary default…). Only meaningful on postable
    # rows. UNIQUE per (school_id, role) — checked by DB constraint.
    account_role = db.Column(db.String(32), nullable=True, index=True)

    parent = db.relationship("Account", remote_side=[id], backref="children")

    __table_args__ = (
        db.UniqueConstraint("school_id", "code", name="uq_account_school_code"),
        db.UniqueConstraint("school_id", "account_role", name="uq_account_school_role"),
    )

    @property
    def balance(self) -> float:
        """Ticket B — an aggregate (is_postable=False) account rolls up
        its children's balances instead of running its own SUM(JournalLine).
        Postable leaves keep the old behaviour: DR/CR side by account type.
        """
        if not self.is_postable and self.children:
            return float(sum(c.balance for c in self.children))
        from sqlalchemy import func
        d = db.session.query(func.coalesce(func.sum(JournalLine.debit), 0)).filter_by(account_id=self.id).scalar() or 0
        c = db.session.query(func.coalesce(func.sum(JournalLine.credit), 0)).filter_by(account_id=self.id).scalar() or 0
        if self.type in ("asset", "expense"):
            return float(d) - float(c)
        return float(c) - float(d)


# ─── Ticket B — default 3-level chart of accounts ────────────────────
#
# Each row: (code, name, type, parent_code, is_postable, account_role)
# Level 1 (no parent)      → is_postable=False, no role
# Level 2 (parent = L1)    → is_postable=False, no role
# Level 3 (parent = L2)    → is_postable=True, optional role
#
# Referenced by both migration 0021 (existing-school reshape) and
# seed.py (new-school bootstrap) so there's exactly one source of truth.

DEFAULT_ACCOUNT_TREE = [
    # ── 1000 الأصول ──
    ("1000", "الأصول", "asset", None, False, None),
    ("1100", "النقدية وما في حكمها", "asset", "1000", False, None),
    ("1110", "الصندوق النقدي", "asset", "1100", True, "cash_default"),
    ("1120", "الحساب البنكي", "asset", "1100", True, None),
    ("1200", "ذمم مدينة", "asset", "1000", False, None),
    ("1210", "ذمم الطلاب (AR)", "asset", "1200", True, "ar_default"),
    ("1150", "سلف ومستحقات موظفين", "asset", "1100", False, None),
    ("1160", "سلف الموظفين", "asset", "1150", True, "employee_advance_default"),
    ("1300", "مصروفات مقدّمة", "asset", "1000", False, None),
    ("1310", "إيجارات مقدّمة", "asset", "1300", True, None),
    ("1320", "تأمينات مستردة", "asset", "1300", True, None),
    ("1400", "أصول ثابتة", "asset", "1000", False, None),
    ("1410", "أثاث ومعدات", "asset", "1400", True, None),
    ("1420", "أجهزة حاسوب وتقنية", "asset", "1400", True, None),
    ("1430", "مبانٍ وتحسينات", "asset", "1400", True, None),
    ("1500", "مجمّع الإهلاك", "asset", "1000", False, None),
    ("1510", "مجمّع إهلاك الأصول الثابتة", "asset", "1500", True, None),
    # Ticket C — extra asset leaves (schools domain).
    ("1140", "مخزون بضاعة (كتب/زي مدرسي للبيع)", "asset", "1100", True, None),
    ("1170", "عهدة نقدية تحت التسوية", "asset", "1100", True, None),
    ("1220", "شيكات تحت التحصيل", "asset", "1200", True, None),
    ("1440", "سيارات وباصات", "asset", "1400", True, None),
    # ── 2000 الخصوم ──
    ("2000", "الخصوم", "liability", None, False, None),
    ("2100", "ذمم دائنة", "liability", "2000", False, None),
    ("2110", "ذمم الموردين (AP)", "liability", "2100", True, "ap_default"),
    ("2200", "مصروفات مستحقة", "liability", "2000", False, None),
    ("2210", "رواتب مستحقة", "liability", "2200", True, None),
    ("2220", "إيجار مستحق", "liability", "2200", True, None),
    ("2230", "مرافق مستحقة (كهرباء/مياه/إنترنت)", "liability", "2200", True, None),
    ("2240", "ضرائب مستحقة", "liability", "2200", True, None),
    ("2250", "ضريبة القيمة المضافة المستحقة", "liability", "2200", True, "vat_payable_default"),
    ("2300", "دفعات مقدّمة من أولياء الأمور", "liability", "2000", False, None),
    ("2310", "دفعات مقدّمة — رسوم دراسية", "liability", "2300", True, None),
    # Ticket C — extra liability leaves.
    ("2140", "شيكات مستحقة الدفع", "liability", "2100", True, None),
    ("2260", "تأمينات مستردة لأولياء الأمور", "liability", "2300", True, None),
    ("2270", "ضمانات وتأمينات موظفين", "liability", "2100", True, None),
    ("2280", "التأمينات الاجتماعية المستحقة للموظفين", "liability", "2200", True, None),
    # Ticket D — required aggregates + leaves for Quick Journal templates.
    ("2290", "أمانات لدى الغير", "liability", "2000", False, None),
    ("2291", "أمانات لدى الغير — عام", "liability", "2290", True, None),
    ("2400", "قروض", "liability", "2000", False, None),
    ("2410", "قروض قصيرة الأجل", "liability", "2400", True, None),
    ("2420", "قروض طويلة الأجل", "liability", "2400", True, None),
    # ── 3000 حقوق الملكية ──
    ("3000", "حقوق الملكية", "equity", None, False, None),
    ("3100", "رأس المال", "equity", "3000", True, None),
    ("3200", "أرباح/خسائر مرحّلة", "equity", "3000", True, "retained_earnings_default"),
    # Ticket D — owner drawings leaf.
    ("3300", "مسحوبات المالك", "equity", "3000", True, None),
    # ── 4000 الإيرادات ──
    ("4000", "الإيرادات", "revenue", None, False, None),
    ("4100", "إيرادات رسوم دراسية", "revenue", "4000", False, None),
    ("4110", "رسوم دراسية سنوية", "revenue", "4100", True, "tuition_default"),
    ("4120", "رسوم دراسية فصلية", "revenue", "4100", True, None),
    ("4200", "إيرادات رسوم إضافية", "revenue", "4000", False, None),
    ("4210", "رسوم كتب ومستلزمات", "revenue", "4200", True, None),
    ("4220", "رسوم نقل", "revenue", "4200", True, None),
    ("4230", "رسوم أنشطة إضافية", "revenue", "4200", True, None),
    ("4900", "خصومات وتخفيضات (Contra-Revenue)", "revenue", "4000", False, None),
    ("4910", "خصم إخوة", "revenue", "4900", True, "discount_default"),
    ("4920", "منح دراسية", "revenue", "4900", True, None),
    # Ticket C — extra revenue leaves.
    ("4140", "إيرادات رسوم التقديم والقبول", "revenue", "4100", True, None),
    ("4150", "إيرادات اختبارات القبول", "revenue", "4100", True, None),
    ("4240", "إيرادات الزي المدرسي", "revenue", "4200", True, None),
    ("4250", "إيرادات الكافتيريا/المقصف", "revenue", "4200", True, None),
    ("4260", "إيرادات الأنشطة الصيفية", "revenue", "4200", True, None),
    ("4270", "إيرادات تأجير المرافق (قاعات/ملاعب)", "revenue", "4200", True, None),
    ("4290", "إيرادات التبرعات والدعم", "revenue", "4000", True, None),
    ("4295", "إيرادات متنوعة أخرى", "revenue", "4000", True, None),
    # ── 5000 المصروفات ──
    ("5000", "المصروفات", "expense", None, False, None),
    ("5100", "المصروفات التشغيلية", "expense", "5000", False, None),
    ("5110", "رواتب المعلمين", "expense", "5100", True, "payroll_salary_default"),
    ("5120", "رواتب الإداريين", "expense", "5100", True, None),
    ("5130", "مصروف المرافق", "expense", "5100", True, None),
    ("5140", "مصروف الصيانة", "expense", "5100", True, None),
    ("5150", "مصروف القرطاسية والمستلزمات", "expense", "5100", True, None),
    ("5160", "مصروف النقل والمواصلات", "expense", "5100", True, None),
    ("5200", "مصروفات أخرى", "expense", "5000", False, None),
    ("5210", "مصروفات متنوعة", "expense", "5200", True, None),
    # Ticket C — extra expense leaves.
    ("5115", "التأمينات الاجتماعية على المعلمين (حصة المدرسة)", "expense", "5100", True, None),
    ("5170", "مصروف الأنشطة والرحلات المدرسية", "expense", "5100", True, None),
    ("5180", "مصروف المسابقات والفعاليات", "expense", "5100", True, None),
    ("5190", "مصروف تدريب وتطوير المعلمين", "expense", "5100", True, None),
    ("5195", "مصروف اشتراكات المناهج والبرامج التعليمية", "expense", "5100", True, None),
    ("5220", "مصروف التأمين", "expense", "5200", True, None),
    ("5230", "مصروف الدعاية والتسويق", "expense", "5200", True, None),
    ("5240", "مصروف استشارات قانونية ومحاسبية", "expense", "5200", True, None),
    ("5250", "مصروف رسوم بنكية وتحويلات", "expense", "5200", True, None),
    ("5260", "مصروف الأمن والحراسة", "expense", "5200", True, None),
    ("5270", "مصروف النظافة", "expense", "5200", True, None),
    ("5280", "مصروف إهلاك الأصول الثابتة", "expense", "5200", True, None),
]


def ensure_default_chart(school_id: int) -> None:
    """Idempotently populate the 3-level chart for a given school.

    Called from seed.py on bootstrap AND from the migration when a school
    has no accounts yet (fresh install). Existing rows are left alone so
    running twice is safe; only missing codes are inserted."""
    for code, name, type_, parent_code, is_postable, role in DEFAULT_ACCOUNT_TREE:
        row = Account.query.filter_by(school_id=school_id, code=code).first()
        parent_id = None
        if parent_code:
            parent = Account.query.filter_by(school_id=school_id, code=parent_code).first()
            parent_id = parent.id if parent else None
        if row is None:
            db.session.add(Account(
                school_id=school_id, code=code, name=name, type=type_,
                parent_id=parent_id, is_postable=is_postable, account_role=role,
                is_system=True,
            ))
        else:
            # Refresh non-destructive fields on system accounts so shape
            # upgrades roll forward cleanly. Never overwrite a role that
            # a different account already owns.
            row.name = row.name or name
            if row.parent_id is None and parent_id:
                row.parent_id = parent_id
            row.is_postable = is_postable
            if role and row.account_role is None:
                conflict = Account.query.filter_by(
                    school_id=school_id, account_role=role,
                ).first()
                if conflict is None:
                    row.account_role = role
    db.session.flush()


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
    # Ticket F — optional cost-center tag for management reports.
    cost_center_id = db.Column(db.Integer,
                               db.ForeignKey("cost_centers.id", ondelete="SET NULL"),
                               nullable=True, index=True)

    account = db.relationship("Account")


class FeeType(SoftDeleteMixin, db.Model):
    __tablename__ = "fee_types"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    name = db.Column(db.String(128), nullable=False)
    default_amount = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    installable = db.Column(db.Boolean, default=True, nullable=False)
    revenue_account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    # Ticket "Additional 9" — mark VAT-eligible fee types. Invoice
    # posting reads this + School.default_tax_rate to derive tax_amount
    # automatically. Untaxable rows post as before.
    is_taxable = db.Column(db.Boolean, default=False, nullable=False)

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
    # Ticket "Additional 9" — cached VAT figures. total_amount stays the
    # GROSS (net + tax) so paid/remaining math doesn't change.
    tax_rate = db.Column(db.Numeric(5, 2), default=0, nullable=False)
    tax_amount = db.Column(db.Numeric(12, 2), default=0, nullable=False)
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
    # Ticket F — optional cost-center tag.
    cost_center_id = db.Column(db.Integer,
                               db.ForeignKey("cost_centers.id", ondelete="SET NULL"),
                               nullable=True, index=True)

    fee_type = db.relationship("FeeType")
    cost_center = db.relationship("CostCenter")


class Installment(db.Model):
    __tablename__ = "installments"

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=False, index=True)
    due_date = db.Column(db.Date, nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    paid_amount = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    status = db.Column(db.String(16), default="pending", nullable=False)
    # Ticket "تذكير تلقائي بالبريد قبل الاستحقاق" — stamped after the
    # cron sends a reminder so the same installment can't be pinged
    # twice in one window.
    reminder_sent_at = db.Column(db.DateTime(timezone=True), nullable=True)

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


class Vendor(SoftDeleteMixin, db.Model):
    __tablename__ = "vendors"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(32))
    email = db.Column(db.String(128))
    address = db.Column(db.String(255))
    # Ticket "Additional 7" — extra vendor profile fields + a dedicated
    # AP sub-account under 2110 that gets lazy-created on first expense.
    tax_number = db.Column(db.String(32))
    contact_person = db.Column(db.String(160))
    ap_account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"),
                              nullable=True, index=True)
    notes = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    expenses = db.relationship("Expense", backref="vendor")
    ap_account = db.relationship("Account", foreign_keys=[ap_account_id])


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

    # Ticket F — optional cost-center tag.
    cost_center_id = db.Column(db.Integer,
                               db.ForeignKey("cost_centers.id", ondelete="SET NULL"),
                               nullable=True, index=True)

    # Ticket "Approval Workflow على المصروفات" — mirror of StudentDiscount:
    # pending → approved (posted) or rejected. Threshold-driven at
    # save time from School.approval_threshold.
    approval_status = db.Column(db.String(16), default="approved",
                                nullable=False, server_default="approved")
    approved_by_id = db.Column(db.Integer, db.ForeignKey("users.id"),
                               nullable=True)
    approved_at = db.Column(db.DateTime(timezone=True), nullable=True)
    reject_reason = db.Column(db.String(255), nullable=True)

    expense_account = db.relationship("Account", foreign_keys=[expense_account_id])
    cash_account = db.relationship("Account", foreign_keys=[cash_account_id])
    journal_entry = db.relationship("JournalEntry")
    cost_center = db.relationship("CostCenter")


# ─── Financial-automation ticket — PaymentMethod ─────────────────────
#
# Layer that hides accounting-account names from the daily UI. The
# admin sees "نقدي"/"تحويل بنكي - الأهلي"/"آجل" and picks one; behind
# it the record_payment / settle_accrual services book the correct
# journal lines against `account_id`.

# `kind` disambiguates the semantics for the ledger service:
#   immediate_cash  — cash received now → DR the linked cash account
#   immediate_bank  — bank transfer now → DR the linked bank account
#   deferred        — no cash movement now → book against a liability
#                     account (invoices leave the AR sub-account alone;
#                     expenses/salary book against 2110/2210).
PAYMENT_METHOD_KINDS = ("immediate_cash", "immediate_bank", "deferred")


class PaymentMethod(SoftDeleteMixin, db.Model):
    __tablename__ = "payment_methods"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"),
                          nullable=False, index=True)
    name = db.Column(db.String(64), nullable=False)
    kind = db.Column(db.String(16), nullable=False, default="immediate_cash")
    # NULL when kind == "deferred" — the liability account is picked by
    # the operation (invoices: none; expenses: 2110; salary: 2210 sub).
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    account = db.relationship("Account", foreign_keys=[account_id])

    __table_args__ = (
        db.UniqueConstraint("school_id", "name", name="uq_payment_method_school_name"),
    )

    @property
    def is_deferred(self) -> bool:
        return self.kind == "deferred"


# ─── Ticket "Additional 8" — Recurring fee schedules ────────────────
#
# One row = "every month/term/year at day D, issue a fee-type F invoice
# for every active student in grade G (or all)". The cron sweep in
# services.ledger.generate_recurring_invoices materialises these into
# Invoice rows. A (schedule, student, period-key) uniqueness guard
# prevents duplicates on repeated sweeps.

RECURRING_FREQUENCIES = ("monthly", "termly", "yearly")


class RecurringFeeSchedule(SoftDeleteMixin, db.Model):
    __tablename__ = "recurring_fee_schedules"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"),
                          nullable=False, index=True)
    fee_type_id = db.Column(db.Integer, db.ForeignKey("fee_types.id"),
                            nullable=False, index=True)
    frequency = db.Column(db.String(16), nullable=False, default="monthly")
    day_of_period = db.Column(db.Integer, nullable=False, default=1)
    applies_to_grade_id = db.Column(db.Integer, db.ForeignKey("grades.id"),
                                    nullable=True, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    last_run_at = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    fee_type = db.relationship("FeeType")
    grade = db.relationship("Grade")


class CostCenter(SoftDeleteMixin, db.Model):
    """Ticket F — cost/profit center for management reporting.
    Optional 2-level hierarchy (name + code + parent). Applied on
    JournalLine/Expense/InvoiceLine via a nullable FK — completely
    optional, never blocks a posting."""
    __tablename__ = "cost_centers"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"),
                          nullable=False, index=True)
    name = db.Column(db.String(128), nullable=False)
    code = db.Column(db.String(32))
    parent_id = db.Column(db.Integer, db.ForeignKey("cost_centers.id"),
                          nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    parent = db.relationship("CostCenter", remote_side=[id], backref="children")

    __table_args__ = (
        db.UniqueConstraint("school_id", "name", name="uq_cost_center_school_name"),
    )


DEFAULT_COST_CENTERS = [
    "المرحلة الابتدائية",
    "المرحلة المتوسطة",
    "المرحلة الثانوية",
    "النقل المدرسي",
    "الأنشطة والرحلات",
    "المقصف/الكافتيريا",
    "الدورات الصيفية",
    "الإدارة العامة",
    "الصيانة والمرافق",
]


def ensure_default_cost_centers(school_id: int) -> None:
    """Idempotently seed the 9 default cost centers for a school."""
    for name in DEFAULT_COST_CENTERS:
        exists = CostCenter.query.filter_by(school_id=school_id, name=name).first()
        if exists is None:
            db.session.add(CostCenter(school_id=school_id, name=name))
    db.session.flush()


class BankStatementLine(db.Model):
    """Ticket "Additional 10" — one row from an imported bank statement.

    `matched_journal_line_id` links to the JournalLine that mirrors this
    bank movement (matched=True). Unmatched rows surface in the recon
    UI as gaps that either need a fresh journal entry or a manual link
    to an existing one."""
    __tablename__ = "bank_statement_lines"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    bank_account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False, index=True)
    statement_date = db.Column(db.Date, nullable=False, index=True)
    description = db.Column(db.String(255))
    amount = db.Column(db.Numeric(12, 2), nullable=False)  # signed: DR positive, CR negative
    is_matched = db.Column(db.Boolean, default=False, nullable=False)
    matched_journal_line_id = db.Column(db.Integer,
                                        db.ForeignKey("journal_lines.id",
                                                      ondelete="SET NULL"),
                                        nullable=True)
    reference = db.Column(db.String(64))
    imported_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    bank_account = db.relationship("Account")
    matched_journal_line = db.relationship("JournalLine")


class RecurringInvoiceLog(db.Model):
    """Guard against double-generation across cron ticks. period_key is
    e.g. `2026-09` (monthly), `2026-T1` (termly), `2026` (yearly)."""
    __tablename__ = "recurring_invoice_log"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False)
    schedule_id = db.Column(db.Integer,
                            db.ForeignKey("recurring_fee_schedules.id", ondelete="CASCADE"),
                            nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"),
                           nullable=False, index=True)
    period_key = db.Column(db.String(16), nullable=False)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"),
                           nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("schedule_id", "student_id", "period_key",
                            name="uq_recurring_run"),
    )


# ── Budget (planned amount per year × account or cost center) ────
class Budget(db.Model):
    __tablename__ = "budgets"
    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"),
                          nullable=False, index=True)
    year_id = db.Column(db.Integer, db.ForeignKey("academic_years.id"),
                        nullable=False, index=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"),
                           nullable=True, index=True)
    cost_center_id = db.Column(db.Integer, db.ForeignKey("cost_centers.id"),
                               nullable=True, index=True)
    period = db.Column(db.String(16), default="annual", nullable=False)
    planned_amount = db.Column(db.Numeric(14, 2), default=0, nullable=False)
    warn_pct = db.Column(db.Integer, default=90, nullable=False)
    note = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    year = db.relationship("AcademicYear")
    account = db.relationship("Account")
    cost_center = db.relationship("CostCenter")


# ── Receipt / Payment Voucher (سند قبض/صرف) ──────────────────────
class ReceiptVoucher(db.Model):
    __tablename__ = "receipt_vouchers"
    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"),
                          nullable=False, index=True)
    voucher_type = db.Column(db.String(8), nullable=False)  # receipt | payment
    voucher_number = db.Column(db.String(32), nullable=False)
    payment_id = db.Column(db.Integer, db.ForeignKey("payments.id"),
                           nullable=True, index=True)
    expense_id = db.Column(db.Integer, db.ForeignKey("expenses.id"),
                           nullable=True, index=True)
    amount = db.Column(db.Numeric(14, 2), nullable=False)
    voucher_date = db.Column(db.Date, default=lambda: date.today(),
                             nullable=False)
    notes = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    payment = db.relationship("Payment")
    expense = db.relationship("Expense")

    __table_args__ = (
        db.UniqueConstraint("school_id", "voucher_number",
                            name="uq_voucher_school_number"),
    )
