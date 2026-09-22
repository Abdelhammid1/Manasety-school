"""نداء — parent pickup calls.

Parent taps "نداء" from the parent app/web when they arrive at
school; the record lands here and fans out to the student + the
responsible teacher (homeroom / class teacher) as notifications.

Lifecycle:
  created → acknowledged_by_teacher → acknowledged_by_student → released
`released_at` is set by the parent (parent tapped "تم الاستلام") or by
an admin/teacher (student picked up).
"""

from alembic import op
import sqlalchemy as sa


revision = 'p9a1b3c5d7e9'
down_revision = 'o7y9a1b3c5d7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'pickup_calls',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('school_id', sa.Integer, sa.ForeignKey('schools.id'),
                  nullable=False, index=True),
        sa.Column('parent_user_id', sa.Integer, sa.ForeignKey('users.id'),
                  nullable=False, index=True),
        sa.Column('student_id', sa.Integer, sa.ForeignKey('students.id'),
                  nullable=False, index=True),
        sa.Column('teacher_user_id', sa.Integer, sa.ForeignKey('users.id'),
                  nullable=True, index=True),
        sa.Column('section_id', sa.Integer, sa.ForeignKey('sections.id'),
                  nullable=True, index=True),
        sa.Column('note', sa.String(255), nullable=True),
        sa.Column('gate', sa.String(64), nullable=True),  # e.g. البوابة الرئيسية
        sa.Column('called_at', sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now(), index=True),
        sa.Column('seen_by_student_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('seen_by_teacher_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('released_at', sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column('released_by_user_id', sa.Integer, sa.ForeignKey('users.id'),
                  nullable=True),
    )


def downgrade():
    op.drop_table('pickup_calls')
