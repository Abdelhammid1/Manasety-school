"""SMTP settings per school + encrypted password.

Every column is nullable — a school without SMTP configured keeps
falling back on the notification-log stub the way it does today.
"""

from alembic import op
import sqlalchemy as sa


revision = 'q1b3c5d7e9f1'
down_revision = 'p9a1b3c5d7e9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('schools') as b:
        b.add_column(sa.Column('smtp_host', sa.String(255), nullable=True))
        b.add_column(sa.Column('smtp_port', sa.Integer, nullable=True,
                               server_default='587'))
        b.add_column(sa.Column('smtp_username', sa.String(255), nullable=True))
        b.add_column(sa.Column('smtp_password_encrypted', sa.Text, nullable=True))
        b.add_column(sa.Column('smtp_use_tls', sa.Boolean, nullable=False,
                               server_default=sa.true()))
        b.add_column(sa.Column('smtp_from_name', sa.String(255), nullable=True))
        b.add_column(sa.Column('smtp_from_email', sa.String(255), nullable=True))


def downgrade():
    with op.batch_alter_table('schools') as b:
        b.drop_column('smtp_from_email')
        b.drop_column('smtp_from_name')
        b.drop_column('smtp_use_tls')
        b.drop_column('smtp_password_encrypted')
        b.drop_column('smtp_username')
        b.drop_column('smtp_port')
        b.drop_column('smtp_host')
