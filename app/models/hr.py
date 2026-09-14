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
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User")
    payrolls = db.relationship("Payroll", backref="employee", order_by="Payroll.period_month.desc()")


class Payroll(db.Model):
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
    paid_at = db.Column(db.Date)
    notes = db.Column(db.String(255))
    journal_entry_id = db.Column(db.Integer, db.ForeignKey("journal_entries.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    journal_entry = db.relationship("JournalEntry")

    __table_args__ = (
        db.UniqueConstraint("employee_id", "period_year", "period_month",
                            name="uq_payroll_employee_period"),
    )
