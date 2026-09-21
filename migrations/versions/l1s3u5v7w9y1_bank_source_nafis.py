"""Add BankQuestion.source + outcome_id + nafis_level.

Every existing row is a school-bank question (`source='school'`), so
the migration is safe to run against a populated bank. NAFIS-flagged
questions land later via seeding or admin authoring; they carry a
mandatory `outcome_id` back to `learning_outcomes` and a `nafis_level`
so a G6 drill only surfaces G6-tagged NAFIS items.

Revision ID: l1s3u5v7w9y1
Revises: k9r1s3u5v7w9
Create Date: 2026-09-21 20:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'l1s3u5v7w9y1'
down_revision = 'k9r1s3u5v7w9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('lms_bank_questions', schema=None) as b:
        b.add_column(sa.Column('source', sa.String(length=16),
                               nullable=False, server_default='school'))
        b.add_column(sa.Column('outcome_id', sa.Integer(), nullable=True))
        b.add_column(sa.Column('nafis_level', sa.String(length=4), nullable=True))
        b.create_foreign_key(
            'fk_bank_questions_outcome_id_learning_outcomes',
            'learning_outcomes',
            ['outcome_id'], ['id'],
        )
    op.create_index('ix_lms_bank_questions_source',
                    'lms_bank_questions', ['source'])
    op.create_index('ix_lms_bank_questions_outcome_id',
                    'lms_bank_questions', ['outcome_id'])
    op.create_index('ix_lms_bank_questions_nafis_level',
                    'lms_bank_questions', ['nafis_level'])


def downgrade():
    op.drop_index('ix_lms_bank_questions_nafis_level',
                  table_name='lms_bank_questions')
    op.drop_index('ix_lms_bank_questions_outcome_id',
                  table_name='lms_bank_questions')
    op.drop_index('ix_lms_bank_questions_source',
                  table_name='lms_bank_questions')
    with op.batch_alter_table('lms_bank_questions', schema=None) as b:
        b.drop_constraint(
            'fk_bank_questions_outcome_id_learning_outcomes',
            type_='foreignkey',
        )
        b.drop_column('nafis_level')
        b.drop_column('outcome_id')
        b.drop_column('source')
