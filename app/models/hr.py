from datetime import datetime, date
from ..extensions import db


class Employee(db.Model):
    __tablename__ = "employees"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    full_name = db.Column(db.String(160), nullable=False)
    national_id = db.Column(db.String(32))
    job_title = db.Column(db.String(128), nullable=False)
    base_salary = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    hire_date = db.Column(db.Date)
    bank_account = db.Column(db.String(64))
    phone = db.Column(db.String(32))
    email = db.Column(db.String(128))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    notes = db.Column(db.Text)
    # Financial-automation ticket — subsidiary salary-payable sub-account
    # under 2210. Lazy-created by services.subsidiary.ensure_employee_account
    # on the first accrual.
    ap_account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"),
                              nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User")
    ap_account = db.relationship("Account", foreign_keys=[ap_account_id])
    payrolls = db.relationship("Payroll", backref="employee", order_by="Payroll.period_month.desc()")


class Payroll(db.Model):
    """A single monthly salary run for an employee.

    Financial-automation ticket — the Payroll row is now the *accrual*:
    it holds net_pay as a liability against the employee's sub-account
    of 2210. paid_amount tracks partial settlements (سلفة) and
    is_settled is a computed marker for `net_pay <= paid_amount`.
    """
    __tablename__ = "payrolls"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False, index=True)
    period_year = db.Column(db.Integer, nullable=False)
    period_month = db.Column(db.Integer, nullable=False)
    base_salary = db.Column(db.Numeric(12, 2), nullable=False)
    allowances = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    deductions = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    net_pay = db.Column(db.Numeric(12, 2), nullable=False)
    paid_amount = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    paid_at = db.Column(db.Date)
    notes = db.Column(db.String(255))
    journal_entry_id = db.Column(db.Integer, db.ForeignKey("journal_entries.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    journal_entry = db.relationship("JournalEntry")
    settlements = db.relationship("PayrollSettlement", backref="payroll",
                                  cascade="all, delete-orphan")

    __table_args__ = (
        db.UniqueConstraint("employee_id", "period_year", "period_month",
                            name="uq_payroll_employee_period"),
    )

    @property
    def remaining(self) -> float:
        return float(self.net_pay) - float(self.paid_amount)

    @property
    def is_settled(self) -> bool:
        return self.remaining <= 0.005


class EmployeeAdvance(db.Model):
    """Ticket "Additional 12" — cash advance to an employee (سلفة).

    Books DR 1160 سلف الموظفين / CR payment_method.account on issue.
    Each new payroll accrual auto-deducts the next installment from
    net_pay and posts a matching CR against the advance, until fully
    settled."""
    __tablename__ = "employee_advances"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False, index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    date_given = db.Column(db.Date, default=date.today, nullable=False)
    # "full_next_month" = deduct the whole thing on the very next payroll.
    # "installments"     = split across `installment_count` payrolls.
    deduction_plan = db.Column(db.String(16), nullable=False, default="full_next_month")
    installment_count = db.Column(db.Integer)
    remaining_balance = db.Column(db.Numeric(12, 2), nullable=False)
    status = db.Column(db.String(16), default="active", nullable=False)
    journal_entry_id = db.Column(db.Integer, db.ForeignKey("journal_entries.id"))
    notes = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    employee = db.relationship("Employee", backref="advances")
    journal_entry = db.relationship("JournalEntry")

    @property
    def is_settled(self) -> bool:
        return self.status == "settled" or float(self.remaining_balance) <= 0.005


class PayrollSettlement(db.Model):
    """One concrete settlement (partial or full) of an accrued Payroll.
    Lets salaries be paid piecewise (سلفة) across multiple dates while
    keeping the accrual/settle journal chain clean."""
    __tablename__ = "payroll_settlements"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    payroll_id = db.Column(db.Integer, db.ForeignKey("payrolls.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    payment_method_id = db.Column(db.Integer, db.ForeignKey("payment_methods.id"),
                                  nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    settled_at = db.Column(db.Date, default=date.today, nullable=False)
    journal_entry_id = db.Column(db.Integer, db.ForeignKey("journal_entries.id"))
    notes = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    payment_method = db.relationship("PaymentMethod")
    journal_entry = db.relationship("JournalEntry")
