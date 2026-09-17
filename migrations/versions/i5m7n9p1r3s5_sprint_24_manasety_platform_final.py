"""sprint 24: Manasety financial platform — Tickets A → H.

Adds:
  · schools.* — 18 new fields (legal names, logo, license, tax, email,
    website, currency, fiscal year, invoice numbering, rounding, print
    templates, notification channels/reminder days)
  · journal_lines.cost_center_id + invoice_lines.cost_center_id +
    expenses.cost_center_id (all nullable FKs)
  · cost_centers table + 9 default rows per school

Grows DEFAULT_ACCOUNT_TREE with 30+ leaves (Ticket C) + Ticket D
required 2290/2291/2400/2410/2420 aggregates+leaves + 3300 owner
drawings. ensure_default_chart runs on every school idempotently.

Revision ID: i5m7n9p1r3s5
Revises: h3k5m7n9p1r3
Create Date: 2026-09-17 17:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'i5m7n9p1r3s5'
down_revision = 'h3k5m7n9p1r3'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    # ── schools.* extended fields (Ticket H) ─────────────────────
    with op.batch_alter_table('schools', schema=None) as b:
        for col in [
            sa.Column('legal_name_ar', sa.String(length=255)),
            sa.Column('legal_name_en', sa.String(length=255)),
            sa.Column('logo_url', sa.String(length=500)),
            sa.Column('license_number', sa.String(length=64)),
            sa.Column('tax_number', sa.String(length=64)),
            sa.Column('email', sa.String(length=128)),
            sa.Column('website', sa.String(length=255)),
            sa.Column('currency', sa.String(length=8), nullable=False, server_default='EGP'),
            sa.Column('currency_symbol', sa.String(length=8), nullable=False, server_default='ج.م'),
            sa.Column('fiscal_year_start_month', sa.Integer(), nullable=False, server_default='9'),
            sa.Column('invoice_prefix', sa.String(length=16), nullable=False, server_default='INV'),
            sa.Column('invoice_start_number', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('rounding_policy', sa.String(length=16), nullable=False, server_default='normal'),
            sa.Column('invoice_header_text', sa.Text()),
            sa.Column('invoice_footer_text', sa.Text()),
            sa.Column('invoice_policy_text', sa.Text()),
            sa.Column('show_logo_on_prints', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('day_start_time', sa.Time()),
            sa.Column('day_end_time', sa.Time()),
            sa.Column('reminder_days_before', sa.String(length=32), nullable=False, server_default='7,3'),
            sa.Column('notify_channels', sa.String(length=64), nullable=False, server_default='in_app,email'),
        ]:
            b.add_column(col)

    # ── cost_centers (Ticket F) ──────────────────────────────────
    op.create_table(
        'cost_centers',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('school_id', sa.Integer(), sa.ForeignKey('schools.id'), nullable=False, index=True),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('code', sa.String(length=32)),
        sa.Column('parent_id', sa.Integer(), sa.ForeignKey('cost_centers.id')),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint('school_id', 'name', name='uq_cost_center_school_name'),
    )

    # ── cost_center_id FKs on JournalLine / Expense / InvoiceLine ─
    with op.batch_alter_table('journal_lines', schema=None) as b:
        b.add_column(sa.Column('cost_center_id', sa.Integer(), nullable=True))
        b.create_index(b.f('ix_journal_lines_cost_center_id'), ['cost_center_id'], unique=False)
        b.create_foreign_key('fk_jl_cost_center', 'cost_centers',
                             ['cost_center_id'], ['id'], ondelete='SET NULL')
    with op.batch_alter_table('invoice_lines', schema=None) as b:
        b.add_column(sa.Column('cost_center_id', sa.Integer(), nullable=True))
        b.create_index(b.f('ix_invoice_lines_cost_center_id'), ['cost_center_id'], unique=False)
        b.create_foreign_key('fk_il_cost_center', 'cost_centers',
                             ['cost_center_id'], ['id'], ondelete='SET NULL')
    with op.batch_alter_table('expenses', schema=None) as b:
        b.add_column(sa.Column('cost_center_id', sa.Integer(), nullable=True))
        b.create_index(b.f('ix_expenses_cost_center_id'), ['cost_center_id'], unique=False)
        b.create_foreign_key('fk_expenses_cost_center', 'cost_centers',
                             ['cost_center_id'], ['id'], ondelete='SET NULL')

    # ── Grow chart of accounts with Ticket C leaves + Ticket D
    # aggregates. Same raw-SQL pattern used in sprint 23 to avoid ORM
    # autoflush deadlocks.
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
                continue   # keep existing rows untouched
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

    # ── Seed 9 default cost centers per school ────────────────────
    from app.models.finance import DEFAULT_COST_CENTERS
    for sid in schools:
        for name in DEFAULT_COST_CENTERS:
            exists = bind.execute(sa.text("""
                SELECT 1 FROM cost_centers
                 WHERE school_id = :s AND name = :n LIMIT 1
            """), {"s": sid, "n": name}).scalar()
            if exists:
                continue
            bind.execute(sa.text("""
                INSERT INTO cost_centers (school_id, name, is_active)
                VALUES (:s, :n, TRUE)
            """), {"s": sid, "n": name})


def downgrade():
    with op.batch_alter_table('expenses', schema=None) as b:
        b.drop_constraint('fk_expenses_cost_center', type_='foreignkey')
        b.drop_index(b.f('ix_expenses_cost_center_id'))
        b.drop_column('cost_center_id')
    with op.batch_alter_table('invoice_lines', schema=None) as b:
        b.drop_constraint('fk_il_cost_center', type_='foreignkey')
        b.drop_index(b.f('ix_invoice_lines_cost_center_id'))
        b.drop_column('cost_center_id')
    with op.batch_alter_table('journal_lines', schema=None) as b:
        b.drop_constraint('fk_jl_cost_center', type_='foreignkey')
        b.drop_index(b.f('ix_journal_lines_cost_center_id'))
        b.drop_column('cost_center_id')
    op.drop_table('cost_centers')

    with op.batch_alter_table('schools', schema=None) as b:
        for col in [
            'notify_channels', 'reminder_days_before',
            'day_end_time', 'day_start_time', 'show_logo_on_prints',
            'invoice_policy_text', 'invoice_footer_text', 'invoice_header_text',
            'rounding_policy', 'invoice_start_number', 'invoice_prefix',
            'fiscal_year_start_month', 'currency_symbol', 'currency',
            'website', 'email', 'tax_number', 'license_number',
            'logo_url', 'legal_name_en', 'legal_name_ar',
        ]:
            b.drop_column(col)
