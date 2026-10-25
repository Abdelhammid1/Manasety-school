"""Banks under 1120 (2026-10-25).

  * accounts.code String(16) → String(30): a bank account is coded with its
    real number / IBAN. Widening only.
  * 1120 becomes an aggregate (is_postable = false) in every school — found
    by its code inside each school, never by id. Idempotent: a school with
    no 1120, or one already aggregate, is left as it is. No journal line,
    payment method or payment is moved or deleted; the lines already on
    1120 still count in its balance (Account.balance).

Downgrade: 1120 goes back to postable only where it has no children, and
the code column is narrowed back to 16 only if no code is longer than 16.
"""

from alembic import op
import sqlalchemy as sa

revision = 'f7a9b1c3d5e7'
down_revision = 'e6f8a0b2c4d6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("accounts") as batch:
        batch.alter_column("code", existing_type=sa.String(16), type_=sa.String(30),
                           existing_nullable=False)
    op.execute(sa.text("UPDATE accounts SET is_postable = :f WHERE code = '1120' AND is_postable = :t")
               .bindparams(f=False, t=True))


def downgrade():
    op.execute(sa.text(
        "UPDATE accounts SET is_postable = :t WHERE code = '1120' AND is_postable = :f "
        "AND NOT EXISTS (SELECT 1 FROM accounts c WHERE c.parent_id = accounts.id)"
    ).bindparams(t=True, f=False))
    longest = op.get_bind().execute(sa.text("SELECT MAX(LENGTH(code)) FROM accounts")).scalar() or 0
    if longest <= 16:
        with op.batch_alter_table("accounts") as batch:
            batch.alter_column("code", existing_type=sa.String(30), type_=sa.String(16),
                               existing_nullable=False)
