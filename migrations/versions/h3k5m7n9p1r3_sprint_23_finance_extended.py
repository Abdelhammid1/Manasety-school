"""sprint 23: financial-automation extended tickets 7–12.

Adds:
  · vendors.(tax_number, contact_person, ap_account_id)
  · fee_types.is_taxable
  · invoices.(tax_rate, tax_amount)
  · schools.default_tax_rate
  · payrolls tracks advances via new employee_advances table
  · bank_statement_lines            (Ticket 10)
  · recurring_fee_schedules         (Ticket 8)
  · recurring_invoice_log           (Ticket 8 dedup)
  · employee_advances               (Ticket 12)
  · new account leaves: 1150/1160 employee-advance,
    2250 VAT-payable, plus roles employee_advance_default /
    retained_earnings_default / vat_payable_default are pinned onto
    their leaves via ensure_default_chart on every school.

Revision ID: h3k5m7n9p1r3
Revises: g1i3k5m7n9p1
Create Date: 2026-09-17 14:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'h3k5m7n9p1r3'
down_revision = 'g1i3k5m7n9p1'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    with op.batch_alter_table('vendors', schema=None) as b:
        b.add_column(sa.Column('tax_number', sa.String(length=32)))
        b.add_column(sa.Column('contact_person', sa.String(length=160)))
        b.add_column(sa.Column('ap_account_id', sa.Integer(), nullable=True))
        b.create_index(b.f('ix_vendors_ap_account_id'), ['ap_account_id'], unique=False)
        b.create_foreign_key('fk_vendors_ap_account', 'accounts',
                             ['ap_account_id'], ['id'])

    with op.batch_alter_table('fee_types', schema=None) as b:
        b.add_column(sa.Column('is_taxable', sa.Boolean(), nullable=False,
                               server_default=sa.false()))

    with op.batch_alter_table('invoices', schema=None) as b:
        b.add_column(sa.Column('tax_rate', sa.Numeric(5, 2), nullable=False,
                               server_default=sa.text('0')))
        b.add_column(sa.Column('tax_amount', sa.Numeric(12, 2), nullable=False,
                               server_default=sa.text('0')))

    with op.batch_alter_table('schools', schema=None) as b:
        b.add_column(sa.Column('default_tax_rate', sa.Numeric(5, 2),
                               nullable=False, server_default=sa.text('0')))

    op.create_table(
        'recurring_fee_schedules',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('school_id', sa.Integer(), sa.ForeignKey('schools.id'), nullable=False, index=True),
        sa.Column('fee_type_id', sa.Integer(), sa.ForeignKey('fee_types.id'), nullable=False, index=True),
        sa.Column('frequency', sa.String(length=16), nullable=False, server_default='monthly'),
        sa.Column('day_of_period', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('applies_to_grade_id', sa.Integer(), sa.ForeignKey('grades.id'), nullable=True, index=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('last_run_at', sa.Date()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        'recurring_invoice_log',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('school_id', sa.Integer(), sa.ForeignKey('schools.id'), nullable=False),
        sa.Column('schedule_id', sa.Integer(),
                  sa.ForeignKey('recurring_fee_schedules.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('student_id', sa.Integer(), sa.ForeignKey('students.id'), nullable=False, index=True),
        sa.Column('period_key', sa.String(length=16), nullable=False),
        sa.Column('invoice_id', sa.Integer(), sa.ForeignKey('invoices.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint('schedule_id', 'student_id', 'period_key', name='uq_recurring_run'),
    )

    op.create_table(
        'bank_statement_lines',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('school_id', sa.Integer(), sa.ForeignKey('schools.id'), nullable=False, index=True),
        sa.Column('bank_account_id', sa.Integer(), sa.ForeignKey('accounts.id'), nullable=False, index=True),
        sa.Column('statement_date', sa.Date(), nullable=False, index=True),
        sa.Column('description', sa.String(length=255)),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('is_matched', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('matched_journal_line_id', sa.Integer(),
                  sa.ForeignKey('journal_lines.id', ondelete='SET NULL'), nullable=True),
        sa.Column('reference', sa.String(length=64)),
        sa.Column('imported_at', sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        'employee_advances',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('school_id', sa.Integer(), sa.ForeignKey('schools.id'), nullable=False, index=True),
        sa.Column('employee_id', sa.Integer(), sa.ForeignKey('employees.id'), nullable=False, index=True),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('date_given', sa.Date(), nullable=False),
        sa.Column('deduction_plan', sa.String(length=16), nullable=False, server_default='full_next_month'),
        sa.Column('installment_count', sa.Integer()),
        sa.Column('remaining_balance', sa.Numeric(12, 2), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='active'),
        sa.Column('journal_entry_id', sa.Integer(), sa.ForeignKey('journal_entries.id')),
        sa.Column('notes', sa.String(length=255)),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # Grow the chart of accounts with the three new leaves + roles.
    # Use raw SQL over the migration connection to sidestep ORM
    # autoflush deadlocks when running inside `flask db upgrade`.
    from app.models.finance import DEFAULT_ACCOUNT_TREE
    schools = [r[0] for r in bind.execute(sa.text("SELECT id FROM schools")).fetchall()]
    for sid in schools:
        rows = bind.execute(
            sa.text("SELECT id, code FROM accounts WHERE school_id = :s"),
            {"s": sid},
        ).fetchall()
        code_to_id = {r[1]: r[0] for r in rows}
        for code, name, type_, parent_code, is_postable, role in DEFAULT_ACCOUNT_TREE:
            if code in code_to_id:
                # Existing row — just claim the role if it's still free.
                if role:
                    owned_by = bind.execute(sa.text("""
                        SELECT id FROM accounts
                         WHERE school_id = :s AND account_role = :r
                    """), {"s": sid, "r": role}).scalar()
                    if owned_by is None:
                        bind.execute(sa.text("""
                            UPDATE accounts SET account_role = :r WHERE id = :id
                        """), {"r": role, "id": code_to_id[code]})
                continue
            parent_id = code_to_id.get(parent_code) if parent_code else None
            bind.execute(sa.text("""
                INSERT INTO accounts
                    (school_id, code, name, type, parent_id,
                     is_active, is_system, is_postable, account_role)
                VALUES
                    (:s, :code, :name, :type, :parent, TRUE, TRUE, :postable, :role)
            """), {"s": sid, "code": code, "name": name, "type": type_,
                   "parent": parent_id, "postable": is_postable, "role": role})
            new_id = bind.execute(
                sa.text("SELECT id FROM accounts WHERE school_id=:s AND code=:c"),
                {"s": sid, "c": code},
            ).scalar()
            code_to_id[code] = new_id


def downgrade():
    op.drop_table('employee_advances')
    op.drop_table('bank_statement_lines')
    op.drop_table('recurring_invoice_log')
    op.drop_table('recurring_fee_schedules')

    with op.batch_alter_table('schools', schema=None) as b:
        b.drop_column('default_tax_rate')

    with op.batch_alter_table('invoices', schema=None) as b:
        b.drop_column('tax_amount')
        b.drop_column('tax_rate')

    with op.batch_alter_table('fee_types', schema=None) as b:
        b.drop_column('is_taxable')

    with op.batch_alter_table('vendors', schema=None) as b:
        b.drop_constraint('fk_vendors_ap_account', type_='foreignkey')
        b.drop_index(b.f('ix_vendors_ap_account_id'))
        b.drop_column('ap_account_id')
        b.drop_column('contact_person')
        b.drop_column('tax_number')
