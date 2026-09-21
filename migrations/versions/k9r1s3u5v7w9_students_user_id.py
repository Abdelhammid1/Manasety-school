"""Add students.user_id — the student's own login account.

Nullable FK; existing rows stay untouched. Populated by
`_create_student_account` in students/routes.py when an admin ticks
"إنشاء حساب دخول للطالب" on the student form, and by any migration
that back-links existing users named after students.

Revision ID: k9r1s3u5v7w9
Revises: j7p9r1s3t5u7
Create Date: 2026-09-21 18:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'k9r1s3u5v7w9'
down_revision = 'j7p9r1s3t5u7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('students', schema=None) as b:
        b.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        b.create_foreign_key(
            'fk_students_user_id_users', 'users',
            ['user_id'], ['id'],
        )
    op.create_index('ix_students_user_id', 'students', ['user_id'])


def downgrade():
    op.drop_index('ix_students_user_id', table_name='students')
    with op.batch_alter_table('students', schema=None) as b:
        b.drop_constraint('fk_students_user_id_users', type_='foreignkey')
        b.drop_column('user_id')
