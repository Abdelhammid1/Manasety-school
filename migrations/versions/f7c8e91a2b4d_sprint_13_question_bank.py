"""sprint 13: question bank — lms_bank_questions, lms_bank_choices +
Question.source_bank_id pointer

The bank is the school's pool of reusable questions. When a teacher composes
a quiz they pick from the bank; picked rows are copied into lms_questions +
lms_choices, and each Question keeps a nullable `source_bank_id` back to the
BankQuestion it was cloned from (SET NULL on delete so historical quizzes
survive a bank cleanup).

Revision ID: f7c8e91a2b4d
Revises: e360ab83c84a
Create Date: 2026-09-15 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'f7c8e91a2b4d'
down_revision = 'e360ab83c84a'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'lms_bank_questions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('subject_id', sa.Integer(), nullable=True),
        sa.Column('grade_id', sa.Integer(), nullable=True),
        sa.Column('academic_year_id', sa.Integer(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('kind', sa.String(length=20), nullable=True),
        sa.Column('prompt', sa.Text(), nullable=False),
        sa.Column('points', sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column('correct_short', sa.String(length=200), nullable=True),
        sa.Column('difficulty', sa.String(length=10), nullable=True),
        sa.Column('tags', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id'], ),
        sa.ForeignKeyConstraint(['subject_id'], ['subjects.id'], ),
        sa.ForeignKeyConstraint(['grade_id'], ['grades.id'], ),
        sa.ForeignKeyConstraint(['academic_year_id'], ['academic_years.id'], ),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('lms_bank_questions', schema=None) as batch:
        batch.create_index(batch.f('ix_lms_bank_questions_school_id'),        ['school_id'],        unique=False)
        batch.create_index(batch.f('ix_lms_bank_questions_subject_id'),       ['subject_id'],       unique=False)
        batch.create_index(batch.f('ix_lms_bank_questions_grade_id'),         ['grade_id'],         unique=False)
        batch.create_index(batch.f('ix_lms_bank_questions_academic_year_id'), ['academic_year_id'], unique=False)

    op.create_table(
        'lms_bank_choices',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('question_id', sa.Integer(), nullable=False),
        sa.Column('order_index', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(length=500), nullable=False),
        sa.Column('is_correct', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['question_id'], ['lms_bank_questions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('lms_bank_choices', schema=None) as batch:
        batch.create_index(batch.f('ix_lms_bank_choices_question_id'), ['question_id'], unique=False)

    # Add the pointer on the existing Question rows. batch_alter_table is used
    # so this works cleanly on SQLite (dev) as well as Postgres (prod).
    with op.batch_alter_table('lms_questions', schema=None) as batch:
        batch.add_column(sa.Column('source_bank_id', sa.Integer(), nullable=True))
        batch.create_index(batch.f('ix_lms_questions_source_bank_id'), ['source_bank_id'], unique=False)
        batch.create_foreign_key(
            'fk_lms_questions_source_bank',
            'lms_bank_questions', ['source_bank_id'], ['id'],
            ondelete='SET NULL',
        )


def downgrade():
    with op.batch_alter_table('lms_questions', schema=None) as batch:
        batch.drop_constraint('fk_lms_questions_source_bank', type_='foreignkey')
        batch.drop_index(batch.f('ix_lms_questions_source_bank_id'))
        batch.drop_column('source_bank_id')

    with op.batch_alter_table('lms_bank_choices', schema=None) as batch:
        batch.drop_index(batch.f('ix_lms_bank_choices_question_id'))
    op.drop_table('lms_bank_choices')

    with op.batch_alter_table('lms_bank_questions', schema=None) as batch:
        batch.drop_index(batch.f('ix_lms_bank_questions_academic_year_id'))
        batch.drop_index(batch.f('ix_lms_bank_questions_grade_id'))
        batch.drop_index(batch.f('ix_lms_bank_questions_subject_id'))
        batch.drop_index(batch.f('ix_lms_bank_questions_school_id'))
    op.drop_table('lms_bank_questions')
