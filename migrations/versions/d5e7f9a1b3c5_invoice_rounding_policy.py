"""Financial settings (2026-10-25) — an invoice keeps the rounding policy
it was issued with.

`invoices.rounding_policy` (nullable): set on every new invoice from the
school's settings, next to `tax_rate` (already stored), so recomputing or
printing an issued invoice gives the same amounts after any settings
change. Existing invoices are filled from their school's current policy.
No other change; downgrade drops the column.
"""

from alembic import op
import sqlalchemy as sa

revision = 'd5e7f9a1b3c5'
down_revision = 'c4d6f8a0b2c4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("invoices") as batch:
        batch.add_column(sa.Column("rounding_policy", sa.String(16), nullable=True))
    op.execute(
        "UPDATE invoices SET rounding_policy = "
        "(SELECT schools.rounding_policy FROM schools WHERE schools.id = invoices.school_id) "
        "WHERE rounding_policy IS NULL"
    )


def downgrade():
    with op.batch_alter_table("invoices") as batch:
        batch.drop_column("rounding_policy")
