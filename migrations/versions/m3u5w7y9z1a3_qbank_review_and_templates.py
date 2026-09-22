"""Qdrat-parity question-bank review state + AssessmentTemplate model.

Adds a `review_state` + `review_notes` pair on `lms_bank_questions` so
we can surface the same "معتمد / قيد المراجعة / بدون إجابة / متشابهات
محتملة / مرفوض / مسوّدة" chip that the Qdrat dashboard shows. Every
existing row keeps the historical behaviour of "usable immediately",
so the default is `approved`.

Creates a lightweight `lms_assessment_templates` table on top of the
existing `lms_assignment_templates` — this one is Qdrat's "النموذج
الاحترافي": a reusable container that groups a set of BankQuestion
ids and can be sent as either an assignment OR an exam. The two
existing template tables (assignment-specific) keep working for
teacher-authored assignment templates; this new one is the shared
building block used by the blueprint-based exam generator.

Revision ID: m3u5w7y9z1a3
Revises: l1s3u5v7w9y1
Create Date: 2026-09-22 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'm3u5w7y9z1a3'
down_revision = 'l1s3u5v7w9y1'
branch_labels = None
depends_on = None


def upgrade():
    # 1. review_state + notes on the bank
    with op.batch_alter_table('lms_bank_questions', schema=None) as b:
        b.add_column(sa.Column('review_state', sa.String(length=16),
                               nullable=False, server_default='approved'))
        b.add_column(sa.Column('review_notes', sa.Text(),
                               nullable=True, server_default=''))
        b.create_index('ix_lms_bank_questions_review_state',
                       ['review_state'], unique=False)

    # 2. Assessment templates (Qdrat "نموذج احترافي").
    op.create_table(
        'lms_assessment_templates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=False, index=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('code', sa.String(length=40), nullable=True, index=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('subject_id', sa.Integer(), nullable=True, index=True),
        sa.Column('grade_id', sa.Integer(), nullable=True, index=True),
        # 'assignment' | 'exam' — same building block, two send flows.
        sa.Column('kind', sa.String(length=16), nullable=False,
                  server_default='assignment'),
        sa.Column('difficulty_mix', sa.String(length=64), nullable=True),
        # 'draft' | 'published' | 'archived'
        sa.Column('state', sa.String(length=16), nullable=False,
                  server_default='published'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['school_id'],    ['schools.id']),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['subject_id'],   ['subjects.id']),
        sa.ForeignKeyConstraint(['grade_id'],     ['grades.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    # 3. Join table — one template holds an ordered list of bank questions.
    op.create_table(
        'lms_assessment_template_questions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('template_id', sa.Integer(), nullable=False, index=True),
        sa.Column('bank_question_id', sa.Integer(), nullable=False, index=True),
        sa.Column('order_index', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('points_override', sa.Numeric(6, 2), nullable=True),
        sa.ForeignKeyConstraint(['template_id'],
                                ['lms_assessment_templates.id'],
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['bank_question_id'],
                                ['lms_bank_questions.id'],
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('template_id', 'bank_question_id',
                            name='uq_asstmpl_q'),
    )


def downgrade():
    op.drop_table('lms_assessment_template_questions')
    op.drop_table('lms_assessment_templates')
    with op.batch_alter_table('lms_bank_questions', schema=None) as b:
        b.drop_index('ix_lms_bank_questions_review_state')
        b.drop_column('review_notes')
        b.drop_column('review_state')
