"""sprint 21: Tickets A + B — Account.account_role + is_postable +
3-level hierarchical chart of accounts.

Adds two columns on accounts:
  · account_role  — semantic pin ("ar_default", "cash_default", …).
                    Unique per (school_id, role).
  · is_postable   — False on aggregate rows (levels 1/2), True on leaves.

Data migration for every school:
  1. Populate the full 3-level tree from finance.DEFAULT_ACCOUNT_TREE
     (idempotent — pre-existing codes are updated, not duplicated).
  2. Old flat accounts that already used the target codes get their
     parent_id + is_postable + account_role refreshed inline; no rows
     are deleted so any pre-existing JournalLine stays wired to the
     same account row.

Revision ID: f9h1i3k5m7n8
Revises: e7g9h1a3b5c6
Create Date: 2026-09-17 09:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'f9h1i3k5m7n8'
down_revision = 'e7g9h1a3b5c6'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    with op.batch_alter_table('accounts', schema=None) as b:
        b.add_column(sa.Column('is_postable', sa.Boolean(), nullable=False,
                               server_default=sa.text('1')))
        b.add_column(sa.Column('account_role', sa.String(length=32), nullable=True))
        b.create_index(b.f('ix_accounts_account_role'), ['account_role'], unique=False)
        b.create_unique_constraint('uq_account_school_role',
                                   ['school_id', 'account_role'])

    # Reshape every school's chart into the 3-level tree. We use raw
    # SQL over the migration's connection so writes land in this
    # transaction — no ORM session needed.
    from app.models.finance import DEFAULT_ACCOUNT_TREE  # type: ignore
    _apply_tree(bind, DEFAULT_ACCOUNT_TREE)


def _apply_tree(bind, tree):
    """Populate the tree for every school. Never demotes a pre-existing
    account to aggregate if it already has journal lines — protecting
    production bookkeeping data. Duplicate-code collisions between an
    old flat account and a new tree aggregate are resolved by keeping
    the old row postable so its history stays valid; the admin can
    reassign codes / merge later from the accounts UI."""
    schools = [r[0] for r in bind.execute(sa.text("SELECT id FROM schools")).fetchall()]

    for sid in schools:
        rows = bind.execute(
            sa.text("SELECT id, code FROM accounts WHERE school_id = :s"),
            {"s": sid},
        ).fetchall()
        code_to_id = {r[1]: r[0] for r in rows}

        def _has_lines(acc_id):
            return bool(bind.execute(
                sa.text("SELECT 1 FROM journal_lines WHERE account_id = :a LIMIT 1"),
                {"a": acc_id},
            ).scalar())

        for code, name, type_, parent_code, is_postable, role in tree:
            parent_id = code_to_id.get(parent_code) if parent_code else None
            if code in code_to_id:
                # Protect production data: an existing account that
                # already carries journal lines stays postable regardless
                # of what the tree says.
                effective_postable = is_postable or _has_lines(code_to_id[code])
                claim_role = None
                if role:
                    role_owner = bind.execute(sa.text("""
                        SELECT id FROM accounts
                         WHERE school_id = :s AND account_role = :r
                    """), {"s": sid, "r": role}).fetchone()
                    if role_owner is None and effective_postable:
                        claim_role = role
                bind.execute(sa.text("""
                    UPDATE accounts
                       SET parent_id = COALESCE(parent_id, :p),
                           is_postable = :postable,
                           account_role = COALESCE(account_role, :role)
                     WHERE id = :id
                """), {"p": parent_id, "postable": effective_postable,
                       "role": claim_role, "id": code_to_id[code]})
            else:
                result = bind.execute(sa.text("""
                    INSERT INTO accounts
                        (school_id, code, name, type, parent_id,
                         is_active, is_system, is_postable, account_role)
                    VALUES
                        (:s, :code, :name, :type, :parent, 1, 1, :postable, :role)
                """), {"s": sid, "code": code, "name": name, "type": type_,
                       "parent": parent_id, "postable": is_postable, "role": role})
                new_id = result.lastrowid if hasattr(result, "lastrowid") else \
                    bind.execute(
                        sa.text("SELECT id FROM accounts WHERE school_id=:s AND code=:c"),
                        {"s": sid, "c": code},
                    ).scalar()
                code_to_id[code] = new_id


def downgrade():
    with op.batch_alter_table('accounts', schema=None) as b:
        b.drop_constraint('uq_account_school_role', type_='unique')
        b.drop_index(b.f('ix_accounts_account_role'))
        b.drop_column('account_role')
        b.drop_column('is_postable')
