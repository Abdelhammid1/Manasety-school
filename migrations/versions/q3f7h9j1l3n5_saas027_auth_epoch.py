"""SAAS-027 (2026-10-21) — schools.auth_epoch (subscription kill switch).

NOT NULL with server default 0: existing rows read 0, and sessions /
JWTs minted before this column existed carry no epoch (= 0), so the
deploy logs nobody out.
"""

from alembic import op
import sqlalchemy as sa

revision = 'q3f7h9j1l3n5'
down_revision = 'p1d5f7h9j1l3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("schools") as b:
        b.add_column(sa.Column("auth_epoch", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    with op.batch_alter_table("schools") as b:
        b.drop_column("auth_epoch")
