"""Monthly AI token cap (2026-10-25, ticket E).

`max_ai_tokens_month` (Integer, nullable, no default) on plans and on
school_limit_overrides: NULL = unlimited / the plan's, so every school
keeps working exactly as before. Downgrade drops both columns.
"""

from alembic import op
import sqlalchemy as sa

revision = 'i0d2e4f6a8b0'
down_revision = 'h9c1d3e5f7a9'
branch_labels = None
depends_on = None


def upgrade():
    for table in ("plans", "school_limit_overrides"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("max_ai_tokens_month", sa.Integer(), nullable=True))


def downgrade():
    for table in ("plans", "school_limit_overrides"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("max_ai_tokens_month")
