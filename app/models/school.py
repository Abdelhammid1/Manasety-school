from datetime import datetime
from ..extensions import db


class School(db.Model):
    __tablename__ = "schools"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(32), unique=True, nullable=False)
    name = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(32))
    address = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    # Ticket 8 — attendance display mode. Governs which UI the school
    # sees on the attendance screen.
    #   daily        → one status per day (legacy)
    #   per_period   → one status per Period
    #   both         → both modes available side-by-side
    attendance_mode = db.Column(db.String(16), default="daily",
                                nullable=False, server_default="daily")
    # Ticket "Additional 9" — default VAT rate applied to taxable
    # invoice lines. 0 for most Egyptian schools, 15 for Saudi.
    default_tax_rate = db.Column(db.Numeric(5, 2), default=0,
                                 nullable=False, server_default="0")
    # Ticket H — extended school settings.
    legal_name_ar = db.Column(db.String(255))
    legal_name_en = db.Column(db.String(255))
    logo_url = db.Column(db.String(500))
    license_number = db.Column(db.String(64))
    tax_number = db.Column(db.String(64))
    email = db.Column(db.String(128))
    website = db.Column(db.String(255))
    currency = db.Column(db.String(8), default="EGP", nullable=False,
                         server_default="EGP")
    currency_symbol = db.Column(db.String(8), default="ج.م", nullable=False,
                                server_default="ج.م")
    fiscal_year_start_month = db.Column(db.Integer, default=9, nullable=False,
                                        server_default="9")   # September
    invoice_prefix = db.Column(db.String(16), default="INV", nullable=False,
                               server_default="INV")
    invoice_start_number = db.Column(db.Integer, default=1, nullable=False,
                                     server_default="1")
    rounding_policy = db.Column(db.String(16), default="normal", nullable=False,
                                server_default="normal")
    invoice_header_text = db.Column(db.Text)
    invoice_footer_text = db.Column(db.Text)
    invoice_policy_text = db.Column(db.Text)
    show_logo_on_prints = db.Column(db.Boolean, default=True, nullable=False,
                                    server_default="1")
    day_start_time = db.Column(db.Time)
    day_end_time = db.Column(db.Time)
    reminder_days_before = db.Column(db.String(32), default="7,3",
                                     nullable=False, server_default="7,3")
    notify_channels = db.Column(db.String(64), default="in_app,email",
                                nullable=False, server_default="in_app,email")

    # Ticket "SMTP per school + email channel" — per-school outbound
    # mail. Password is stored Fernet-encrypted at rest; the raw value
    # never touches the database.
    smtp_host = db.Column(db.String(255))
    smtp_port = db.Column(db.Integer, default=587)
    smtp_username = db.Column(db.String(255))
    smtp_password_encrypted = db.Column(db.Text)
    smtp_use_tls = db.Column(db.Boolean, default=True, nullable=False,
                             server_default="1")
    smtp_from_name = db.Column(db.String(255))
    smtp_from_email = db.Column(db.String(255))

    # Ticket "Approval Workflow" — expense amount above this needs
    # explicit approval before ledger posting. 0 = every expense.
    approval_threshold = db.Column(db.Numeric(14, 2), default=0)
    # Ticket "تذكير قبل الاستحقاق" — days before due_date at which
    # the cron sends an email reminder to the parent.
    installment_reminder_days_before = db.Column(db.Integer, default=3)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<School {self.code} {self.name}>"
