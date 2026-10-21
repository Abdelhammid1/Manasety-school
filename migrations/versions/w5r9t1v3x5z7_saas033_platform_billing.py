"""SAAS-033 (2026-10-21) — platform invoices, lines and payments.
Platform tables (not tenant-owned). No prices or company data seeded.
"""

from alembic import op
import sqlalchemy as sa

revision = 'w5r9t1v3x5z7'
down_revision = 'v3p7r9t1v3x5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "platform_invoices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("number", sa.String(32), unique=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("issue_date", sa.Date()),
        sa.Column("due_date", sa.Date()),
        sa.Column("subtotal", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("tax_rate", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("tax_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("total", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text()),
        sa.Column("void_reason", sa.Text()),
        sa.Column("pdf_path", sa.String(255)),
        sa.Column("created_by_platform_user_id", sa.Integer(), sa.ForeignKey("platform_users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('draft','issued','partially_paid','paid','void')",
                           name="ck_platform_invoices_status"),
    )
    op.create_index("ix_platform_invoices_school_id", "platform_invoices", ["school_id"])
    op.create_table(
        "platform_invoice_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("platform_invoices.id"), nullable=False),
        sa.Column("description", sa.String(255), nullable=False),
        sa.Column("qty", sa.Numeric(10, 2), nullable=False, server_default="1"),
        sa.Column("unit_price", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("plans.id")),
        sa.Column("period_start", sa.Date()),
        sa.Column("period_end", sa.Date()),
    )
    op.create_index("ix_platform_invoice_lines_invoice_id", "platform_invoice_lines", ["invoice_id"])
    op.create_table(
        "platform_payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("platform_invoices.id"), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("paid_on", sa.Date(), nullable=False),
        sa.Column("method", sa.String(16), nullable=False),
        sa.Column("reference", sa.String(128)),
        sa.Column("notes", sa.Text()),
        sa.Column("reverses_payment_id", sa.Integer(), sa.ForeignKey("platform_payments.id")),
        sa.Column("recorded_by_platform_user_id", sa.Integer(), sa.ForeignKey("platform_users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("method IN ('bank_transfer','cash','instapay','other')",
                           name="ck_platform_payments_method"),
    )
    op.create_index("ix_platform_payments_invoice_id", "platform_payments", ["invoice_id"])


def downgrade():
    op.drop_table("platform_payments")
    op.drop_table("platform_invoice_lines")
    op.drop_table("platform_invoices")
