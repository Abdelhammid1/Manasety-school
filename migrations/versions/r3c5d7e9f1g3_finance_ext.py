"""Budget + Expense.approval_status + ReceiptVoucher +
Installment.reminder_sent_at + School.approval_threshold +
School.installment_reminder_days_before.

Also lays down the soft-delete columns (deleted_at, deleted_by_id) on
a starter set of high-churn tables (vendors, payment_methods,
fee_types, cost_centers, roles, employees) — the mixin picks up any
additional table by just being included in the model definition, so
extending the coverage later is a per-table batch_add_column call.
"""

from alembic import op
import sqlalchemy as sa


revision = 'r3c5d7e9f1g3'
down_revision = 'q1b3c5d7e9f1'
branch_labels = None
depends_on = None


def _has(table, col):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return any(c["name"] == col for c in insp.get_columns(table))


def upgrade():
    # ── School: new fields ────────────────────────────────────────
    with op.batch_alter_table('schools') as b:
        if not _has('schools', 'approval_threshold'):
            b.add_column(sa.Column('approval_threshold', sa.Numeric(14, 2),
                                   nullable=True, server_default='0'))
        if not _has('schools', 'installment_reminder_days_before'):
            b.add_column(sa.Column('installment_reminder_days_before',
                                   sa.Integer, nullable=True, server_default='3'))

    # ── Budget ────────────────────────────────────────────────────
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if 'budgets' not in tables: op.create_table(
        'budgets',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('school_id', sa.Integer, sa.ForeignKey('schools.id'),
                  nullable=False, index=True),
        sa.Column('year_id', sa.Integer, sa.ForeignKey('academic_years.id'),
                  nullable=False, index=True),
        sa.Column('account_id', sa.Integer, sa.ForeignKey('accounts.id'),
                  nullable=True, index=True),
        sa.Column('cost_center_id', sa.Integer, sa.ForeignKey('cost_centers.id'),
                  nullable=True, index=True),
        sa.Column('period', sa.String(16), nullable=False,
                  server_default='annual'),  # annual | month_01..month_12
        sa.Column('planned_amount', sa.Numeric(14, 2), nullable=False,
                  server_default='0'),
        sa.Column('warn_pct', sa.Integer, nullable=False, server_default='90'),
        sa.Column('note', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
    )

    # ── Expense: approval workflow ──────────────────────────────────
    with op.batch_alter_table('expenses') as b:
        if not _has('expenses', 'approval_status'):
            b.add_column(sa.Column('approval_status', sa.String(16),
                                   nullable=False, server_default='approved'))
        if not _has('expenses', 'approved_by_id'):
            b.add_column(sa.Column('approved_by_id', sa.Integer, nullable=True))
            b.create_foreign_key('fk_expense_approver', 'users',
                                 ['approved_by_id'], ['id'])
        if not _has('expenses', 'approved_at'):
            b.add_column(sa.Column('approved_at', sa.DateTime(timezone=True),
                                   nullable=True))
        if not _has('expenses', 'reject_reason'):
            b.add_column(sa.Column('reject_reason', sa.String(255), nullable=True))

    # ── Installment: reminder-sent flag ─────────────────────────────
    if not _has('installments', 'reminder_sent_at'):
        with op.batch_alter_table('installments') as b:
            b.add_column(sa.Column('reminder_sent_at',
                                   sa.DateTime(timezone=True), nullable=True))

    # ── ReceiptVoucher (سند قبض/صرف) ────────────────────────────────
    if 'receipt_vouchers' not in tables: op.create_table(
        'receipt_vouchers',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('school_id', sa.Integer, sa.ForeignKey('schools.id'),
                  nullable=False, index=True),
        sa.Column('voucher_type', sa.String(8), nullable=False),  # receipt | payment
        sa.Column('voucher_number', sa.String(32), nullable=False),
        sa.Column('payment_id', sa.Integer, sa.ForeignKey('payments.id'),
                  nullable=True, index=True),
        sa.Column('expense_id', sa.Integer, sa.ForeignKey('expenses.id'),
                  nullable=True, index=True),
        sa.Column('amount', sa.Numeric(14, 2), nullable=False),
        sa.Column('voucher_date', sa.Date, nullable=False,
                  server_default=sa.func.current_date()),
        sa.Column('notes', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.UniqueConstraint('school_id', 'voucher_number',
                            name='uq_voucher_school_number'),
    )

    # ── Soft-delete columns on the starter set of high-churn tables ─
    for tbl in ('vendors', 'payment_methods', 'fee_types', 'cost_centers',
                'roles', 'employees'):
        with op.batch_alter_table(tbl) as b:
            if not _has(tbl, 'deleted_at'):
                b.add_column(sa.Column('deleted_at',
                                       sa.DateTime(timezone=True),
                                       nullable=True, index=True))
            if not _has(tbl, 'deleted_by_id'):
                b.add_column(sa.Column('deleted_by_id', sa.Integer,
                                       nullable=True))
                b.create_foreign_key(f'fk_{tbl}_deleter', 'users',
                                     ['deleted_by_id'], ['id'])


def downgrade():
    for tbl in ('vendors', 'payment_methods', 'fee_types', 'cost_centers',
                'roles', 'employees'):
        with op.batch_alter_table(tbl) as b:
            b.drop_column('deleted_by_id')
            b.drop_column('deleted_at')
    op.drop_table('receipt_vouchers')
    with op.batch_alter_table('installments') as b:
        b.drop_column('reminder_sent_at')
    with op.batch_alter_table('expenses') as b:
        b.drop_column('reject_reason')
        b.drop_column('approved_at')
        b.drop_column('approved_by_id')
        b.drop_column('approval_status')
    op.drop_table('budgets')
    with op.batch_alter_table('schools') as b:
        b.drop_column('installment_reminder_days_before')
        b.drop_column('approval_threshold')
