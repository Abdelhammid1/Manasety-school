"""sprint 11: notification_logs.student_id FK + backfill

Adds a direct student_id foreign key to notification_logs so the
`/parent/notifications` endpoint can filter by student ownership
(via Student.parent_user_id) instead of the fragile target_phone
string match. Backfills existing rows by joining target_phone against
Student.parent_phone within the same school.

Revision ID: a1b2c3d4e5f6
Revises: 73e172653d23
Create Date: 2026-08-23
"""
from alembic import op
import sqlalchemy as sa


revision = 'a1b2c3d4e5f6'
down_revision = '73e172653d23'
branch_labels = None
depends_on = None


def upgrade():
    # 1) Add the column + FK + index. Use batch_alter_table so SQLite works.
    with op.batch_alter_table('notification_logs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('student_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_notification_logs_student_id',
            'students',
            ['student_id'], ['id'],
            ondelete='SET NULL',
        )
        batch_op.create_index(
            'ix_notification_logs_student_id',
            ['student_id'],
            unique=False,
        )

    # 2) Backfill: match on (school_id, target_phone == parent_phone).
    #    First row wins on ties (rare and expected — shared-phone families).
    bind = op.get_bind()
    bind.execute(sa.text("""
        UPDATE notification_logs
           SET student_id = (
                 SELECT s.id
                   FROM students s
                  WHERE s.school_id = notification_logs.school_id
                    AND s.parent_phone IS NOT NULL
                    AND TRIM(s.parent_phone) = TRIM(notification_logs.target_phone)
                  ORDER BY s.id
                  LIMIT 1
               )
         WHERE notification_logs.target_phone IS NOT NULL
           AND notification_logs.student_id IS NULL;
    """))


def downgrade():
    with op.batch_alter_table('notification_logs', schema=None) as batch_op:
        batch_op.drop_index('ix_notification_logs_student_id')
        batch_op.drop_constraint('fk_notification_logs_student_id', type_='foreignkey')
        batch_op.drop_column('student_id')
