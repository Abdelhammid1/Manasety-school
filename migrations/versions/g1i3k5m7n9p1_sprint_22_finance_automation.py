"""sprint 22: financial-automation foundation.

Adds:
  · students.ar_account_id   → student subsidiary AR sub-account
  · employees.ap_account_id  → employee subsidiary salary-payable sub
  · payrolls.paid_amount     → partial-settlement tracking
  · payment_methods table    → "استلمت الفلوس فين؟" abstraction
  · payroll_settlements table → per-settlement journal chain

Converts the two headers 1210 (ذمم الطلاب) and 2210 (رواتب مستحقة) to
is_postable=False so nothing can be posted directly on the header; from
here on children are lazy-created per-party.

Seeds two default PaymentMethod rows per school:
  · "نقدي"        → immediate_cash on cash_default (1110)
  · "تحويل بنكي" → immediate_bank on the first non-cash asset
  · "آجل"        → deferred, no account.

Revision ID: g1i3k5m7n9p1
Revises: f9h1i3k5m7n8
Create Date: 2026-09-17 11:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'g1i3k5m7n9p1'
down_revision = 'f9h1i3k5m7n8'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    with op.batch_alter_table('students', schema=None) as b:
        b.add_column(sa.Column('ar_account_id', sa.Integer(), nullable=True))
        b.create_index(b.f('ix_students_ar_account_id'), ['ar_account_id'], unique=False)
        b.create_foreign_key('fk_students_ar_account', 'accounts',
                             ['ar_account_id'], ['id'])

    with op.batch_alter_table('employees', schema=None) as b:
        b.add_column(sa.Column('ap_account_id', sa.Integer(), nullable=True))
        b.create_index(b.f('ix_employees_ap_account_id'), ['ap_account_id'], unique=False)
        b.create_foreign_key('fk_employees_ap_account', 'accounts',
                             ['ap_account_id'], ['id'])

    with op.batch_alter_table('payrolls', schema=None) as b:
        b.add_column(sa.Column(
            'paid_amount', sa.Numeric(12, 2),
            nullable=False, server_default=sa.text('0'),
        ))

    op.create_table(
        'payment_methods',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('school_id', sa.Integer(),
                  sa.ForeignKey('schools.id'), nullable=False, index=True),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False,
                  server_default='immediate_cash'),
        sa.Column('account_id', sa.Integer(), sa.ForeignKey('accounts.id')),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint('school_id', 'name', name='uq_payment_method_school_name'),
    )

    op.create_table(
        'payroll_settlements',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('school_id', sa.Integer(),
                  sa.ForeignKey('schools.id'), nullable=False, index=True),
        sa.Column('payroll_id', sa.Integer(),
                  sa.ForeignKey('payrolls.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('payment_method_id', sa.Integer(),
                  sa.ForeignKey('payment_methods.id'), nullable=False),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('settled_at', sa.Date(), nullable=False),
        sa.Column('journal_entry_id', sa.Integer(),
                  sa.ForeignKey('journal_entries.id')),
        sa.Column('notes', sa.String(length=255)),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # 1210 / 2210 become headers — nothing gets posted directly on them
    # anymore. If an account with journal lines already exists on this
    # code (test data) we leave it postable; the finance code checks
    # is_postable at post time and refuses on the header row only.
    bind.execute(sa.text("""
        UPDATE accounts SET is_postable = FALSE
         WHERE code IN ('1210', '2210')
           AND id NOT IN (SELECT DISTINCT account_id FROM journal_lines)
    """))

    # Grant `finance_transactions` permission to existing admin +
    # accountant roles so post-migration bookings don't 403. The JSON
    # column is read-modify-write since sqlite/postgres both support it.
    import json
    role_rows = bind.execute(sa.text("""
        SELECT id, permissions FROM roles WHERE name IN ('admin', 'accountant')
    """)).fetchall()
    for rid, perms_raw in role_rows:
        try:
            perms = json.loads(perms_raw) if isinstance(perms_raw, str) else (perms_raw or {})
        except Exception:
            perms = {}
        if 'finance_transactions' not in perms:
            perms['finance_transactions'] = ['view', 'add', 'edit', 'delete']
            bind.execute(sa.text("""
                UPDATE roles SET permissions = :p WHERE id = :id
            """), {"p": json.dumps(perms, ensure_ascii=False), "id": rid})

    # Seed defaults for every school. Idempotent: skip if the row already
    # exists (identified by unique name per school).
    schools = [r[0] for r in bind.execute(sa.text("SELECT id FROM schools")).fetchall()]
    for sid in schools:
        cash_account = bind.execute(sa.text("""
            SELECT id FROM accounts
             WHERE school_id = :s AND account_role = 'cash_default'
             LIMIT 1
        """), {"s": sid}).scalar()
        # Bank fallback — first asset leaf that isn't the cash account.
        bank_account = bind.execute(sa.text("""
            SELECT id FROM accounts
             WHERE school_id = :s AND type = 'asset' AND is_postable = TRUE
               AND (:cash IS NULL OR id != :cash)
             ORDER BY code
             LIMIT 1
        """), {"s": sid, "cash": cash_account}).scalar()

        for name, kind, acc_id in (
            ("نقدي",        "immediate_cash", cash_account),
            ("تحويل بنكي", "immediate_bank", bank_account),
            ("آجل",         "deferred",       None),
        ):
            exists = bind.execute(sa.text("""
                SELECT id FROM payment_methods
                 WHERE school_id = :s AND name = :n LIMIT 1
            """), {"s": sid, "n": name}).scalar()
            if exists:
                continue
            bind.execute(sa.text("""
                INSERT INTO payment_methods (school_id, name, kind, account_id, is_active)
                VALUES (:s, :n, :k, :a, TRUE)
            """), {"s": sid, "n": name, "k": kind, "a": acc_id})


def downgrade():
    op.drop_table('payroll_settlements')
    op.drop_table('payment_methods')

    with op.batch_alter_table('payrolls', schema=None) as b:
        b.drop_column('paid_amount')

    with op.batch_alter_table('employees', schema=None) as b:
        b.drop_constraint('fk_employees_ap_account', type_='foreignkey')
        b.drop_index(b.f('ix_employees_ap_account_id'))
        b.drop_column('ap_account_id')

    with op.batch_alter_table('students', schema=None) as b:
        b.drop_constraint('fk_students_ar_account', type_='foreignkey')
        b.drop_index(b.f('ix_students_ar_account_id'))
        b.drop_column('ar_account_id')

    op.get_bind().execute(sa.text("""
        UPDATE accounts SET is_postable = TRUE
         WHERE code IN ('1210', '2210')
    """))
