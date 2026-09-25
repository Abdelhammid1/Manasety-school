"""Phase-4 six features — T1 YearResult GPA/rank, T2 Leave workflow,
T5 Refund + Petty cash.

T3 and T6 are read-only reports over existing tables. T4 adds one
static field on Message (`attachment_path`) that already exists in
the schema — no migration change needed on that model.

Idempotent per column and per table."""

from alembic import op
import sqlalchemy as sa


revision = 'c5v7x9z1c3e5'
down_revision = 'b3t5v7x9z1c3'
branch_labels = None
depends_on = None


def _has(bind, table, col):
    insp = sa.inspect(bind)
    return any(c["name"] == col for c in insp.get_columns(table))


def _has_table(bind, name):
    return sa.inspect(bind).has_table(name)


def upgrade():
    bind = op.get_bind()

    # T1 — YearResult extras
    with op.batch_alter_table("year_results") as batch:
        if not _has(bind, "year_results", "gpa"):
            batch.add_column(sa.Column("gpa", sa.Numeric(4, 2), nullable=True))
        if not _has(bind, "year_results", "grade_letter"):
            batch.add_column(sa.Column("grade_letter", sa.String(4), nullable=True))
        if not _has(bind, "year_results", "rank_in_section"):
            batch.add_column(sa.Column("rank_in_section", sa.Integer(), nullable=True))
        if not _has(bind, "year_results", "rank_in_grade"):
            batch.add_column(sa.Column("rank_in_grade", sa.Integer(), nullable=True))

    # T2 — leave_requests
    if not _has_table(bind, "leave_requests"):
        op.create_table(
            "leave_requests",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("school_id", sa.Integer(),
                      sa.ForeignKey("schools.id"),
                      nullable=False, index=True),
            sa.Column("employee_id", sa.Integer(),
                      sa.ForeignKey("employees.id", ondelete="CASCADE"),
                      nullable=False, index=True),
            sa.Column("leave_type", sa.String(32), nullable=False),
            sa.Column("start_date", sa.Date(), nullable=False),
            sa.Column("end_date",   sa.Date(), nullable=False),
            sa.Column("days_count", sa.Integer(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("status", sa.String(16),
                      nullable=False, server_default="pending"),
            sa.Column("approved_by_user_id", sa.Integer(),
                      sa.ForeignKey("users.id"), nullable=True),
            sa.Column("approved_at", sa.DateTime(), nullable=True),
            sa.Column("reject_reason", sa.String(255), nullable=True),
            sa.Column("created_at", sa.DateTime(),
                      server_default=sa.func.now(), nullable=False),
        )

    # T2 — leave_balances
    if not _has_table(bind, "leave_balances"):
        op.create_table(
            "leave_balances",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("school_id", sa.Integer(),
                      sa.ForeignKey("schools.id"),
                      nullable=False, index=True),
            sa.Column("employee_id", sa.Integer(),
                      sa.ForeignKey("employees.id", ondelete="CASCADE"),
                      nullable=False, index=True),
            sa.Column("year", sa.Integer(), nullable=False),
            sa.Column("leave_type", sa.String(32), nullable=False),
            sa.Column("total_days", sa.Numeric(6, 2),
                      nullable=False, server_default="0"),
            sa.Column("used_days",  sa.Numeric(6, 2),
                      nullable=False, server_default="0"),
            sa.UniqueConstraint(
                "employee_id", "year", "leave_type",
                name="uq_leave_balance_employee_year_type",
            ),
        )

    # T5 — refund_requests
    if not _has_table(bind, "refund_requests"):
        op.create_table(
            "refund_requests",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("school_id", sa.Integer(),
                      sa.ForeignKey("schools.id"),
                      nullable=False, index=True),
            sa.Column("invoice_id", sa.Integer(),
                      sa.ForeignKey("invoices.id"),
                      nullable=False, index=True),
            sa.Column("amount", sa.Numeric(14, 2), nullable=False),
            sa.Column("reason", sa.String(500), nullable=True),
            sa.Column("payment_method_id", sa.Integer(),
                      sa.ForeignKey("payment_methods.id"), nullable=True),
            sa.Column("override_account_id", sa.Integer(),
                      sa.ForeignKey("accounts.id"), nullable=True),
            sa.Column("requested_by_user_id", sa.Integer(),
                      sa.ForeignKey("users.id"), nullable=False),
            sa.Column("status", sa.String(16),
                      nullable=False, server_default="pending"),
            sa.Column("approved_by_user_id", sa.Integer(),
                      sa.ForeignKey("users.id"), nullable=True),
            sa.Column("approved_at", sa.DateTime(), nullable=True),
            sa.Column("reject_reason", sa.String(500), nullable=True),
            sa.Column("payment_id", sa.Integer(),
                      sa.ForeignKey("payments.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(),
                      server_default=sa.func.now(), nullable=False),
        )

    # T5 — petty_cash_transactions
    if not _has_table(bind, "petty_cash_transactions"):
        op.create_table(
            "petty_cash_transactions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("school_id", sa.Integer(),
                      sa.ForeignKey("schools.id"),
                      nullable=False, index=True),
            sa.Column("kind", sa.String(10), nullable=False),
            sa.Column("custodian_employee_id", sa.Integer(),
                      sa.ForeignKey("employees.id"), nullable=True),
            sa.Column("amount", sa.Numeric(14, 2), nullable=False),
            sa.Column("tx_date", sa.Date(), nullable=False),
            sa.Column("reason", sa.String(500), nullable=True),
            sa.Column("journal_entry_id", sa.Integer(),
                      sa.ForeignKey("journal_entries.id"), nullable=True),
            sa.Column("counter_account_id", sa.Integer(),
                      sa.ForeignKey("accounts.id"), nullable=True),
            sa.Column("recorded_by_user_id", sa.Integer(),
                      sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(),
                      server_default=sa.func.now(), nullable=False),
        )


def downgrade():
    for table in ("petty_cash_transactions", "refund_requests",
                  "leave_balances", "leave_requests"):
        try: op.drop_table(table)
        except Exception: pass
    with op.batch_alter_table("year_results") as batch:
        for c in ("rank_in_grade", "rank_in_section", "grade_letter", "gpa"):
            try: batch.drop_column(c)
            except Exception: pass
