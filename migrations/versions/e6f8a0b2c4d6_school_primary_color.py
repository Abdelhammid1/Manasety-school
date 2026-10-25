"""School branding (2026-10-25) — the school's primary colour.

`schools.primary_color` (String(7), nullable, no default): every school
stays NULL, i.e. the platform's own colours, until its admin picks one.
Downgrade drops the column.
"""

from alembic import op
import sqlalchemy as sa

revision = 'e6f8a0b2c4d6'
down_revision = 'd5e7f9a1b3c5'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("schools") as batch:
        batch.add_column(sa.Column("primary_color", sa.String(7), nullable=True))


def downgrade():
    with op.batch_alter_table("schools") as batch:
        batch.drop_column("primary_color")
