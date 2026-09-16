"""sprint 15: content ecosystem — units, term status, teacher-subjects,
extended bank tags, assignment questions, assignment templates.

Covers tickets #12 (part 1) + #14 (part 1) + #16 (parts 1-3, 5) in a
single additive migration. Every existing row's behavior is preserved —
new columns are nullable or carry a safe server default, and every
UniqueConstraint change is a strict widening.

Revision ID: b3d4e5f6a7c8
Revises: a9c1e5f28d13
Create Date: 2026-09-16 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'b3d4e5f6a7c8'
down_revision = 'a9c1e5f28d13'
branch_labels = None
depends_on = None


def upgrade():
    # ── Ticket #12 Part 1 — Term open/closed state ─────────────────────
    with op.batch_alter_table('terms', schema=None) as batch:
        batch.add_column(sa.Column('status_mode', sa.String(length=8),
                                   nullable=False, server_default='auto'))
        batch.add_column(sa.Column('manual_status', sa.String(length=8), nullable=True))

    # ── Ticket #14 Part 2 — teacher_subjects M2M (specialization filter) ──
    op.create_table(
        'teacher_subjects',
        sa.Column('teacher_id', sa.Integer(), nullable=False),
        sa.Column('subject_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['teacher_id'], ['teachers.id'], ),
        sa.ForeignKeyConstraint(['subject_id'], ['subjects.id'], ),
        sa.PrimaryKeyConstraint('teacher_id', 'subject_id'),
    )

    # ── Ticket #14 Part 1 — assignments.term_id + widened UniqueConstraint ──
    with op.batch_alter_table('assignments', schema=None) as batch:
        batch.add_column(sa.Column('term_id', sa.Integer(), nullable=True))
        batch.create_index(batch.f('ix_assignments_term_id'), ['term_id'], unique=False)
        batch.create_foreign_key('fk_assignments_term', 'terms',
                                 ['term_id'], ['id'], ondelete='SET NULL')
        # The old (year, section, subject, teacher) uniqueness is widened to
        # include term so a teacher can hold two term-scoped assignments for
        # the same section/subject in one year. NULL term_id keeps behaving
        # like the old "whole year" assignment because a NULL never collides
        # with itself in uniqueness on any RDBMS we support.
        try:
            batch.drop_constraint('uq_assignment_unique_quad', type_='unique')
        except Exception:
            # Constraint may not have been named exactly this in older DBs.
            # SQLite ignores this path via batch anyway.
            pass
        batch.create_unique_constraint(
            'uq_assignment_year_term_section_subject_teacher',
            ['year_id', 'term_id', 'section_id', 'subject_id', 'teacher_id'],
        )

    # ── Ticket #16 Part 1 — Unit table + Lesson.unit_id ────────────────
    op.create_table(
        'lms_units',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('course_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('order_index', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['course_id'], ['lms_courses.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('lms_units', schema=None) as batch:
        batch.create_index(batch.f('ix_lms_units_course_id'), ['course_id'], unique=False)

    with op.batch_alter_table('lms_lessons', schema=None) as batch:
        batch.add_column(sa.Column('unit_id', sa.Integer(), nullable=True))
        batch.create_index(batch.f('ix_lms_lessons_unit_id'), ['unit_id'], unique=False)
        batch.create_foreign_key('fk_lms_lessons_unit', 'lms_units',
                                 ['unit_id'], ['id'], ondelete='SET NULL')

    # ── Ticket #16 Part 2 — BankQuestion + term_id + unit_id + lesson_id ──
    with op.batch_alter_table('lms_bank_questions', schema=None) as batch:
        batch.add_column(sa.Column('term_id',   sa.Integer(), nullable=True))
        batch.add_column(sa.Column('unit_id',   sa.Integer(), nullable=True))
        batch.add_column(sa.Column('lesson_id', sa.Integer(), nullable=True))
        batch.create_index(batch.f('ix_lms_bank_questions_term_id'),   ['term_id'],   unique=False)
        batch.create_index(batch.f('ix_lms_bank_questions_unit_id'),   ['unit_id'],   unique=False)
        batch.create_index(batch.f('ix_lms_bank_questions_lesson_id'), ['lesson_id'], unique=False)
        batch.create_foreign_key('fk_bank_q_term',   'terms',       ['term_id'],   ['id'], ondelete='SET NULL')
        batch.create_foreign_key('fk_bank_q_unit',   'lms_units',   ['unit_id'],   ['id'], ondelete='SET NULL')
        batch.create_foreign_key('fk_bank_q_lesson', 'lms_lessons', ['lesson_id'], ['id'], ondelete='SET NULL')

    # ── Ticket #16 Part 5 — Assignment template library ────────────────
    op.create_table(
        'lms_assignment_templates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('school_id',     sa.Integer(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('subject_id',    sa.Integer(), nullable=True),
        sa.Column('grade_id',      sa.Integer(), nullable=True),
        sa.Column('title',        sa.String(length=200), nullable=False),
        sa.Column('instructions', sa.Text(), nullable=True),
        sa.Column('max_score',    sa.Numeric(6, 2), nullable=True),
        sa.Column('allow_late',   sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('usage_count',  sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at',   sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at',   sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['school_id'],     ['schools.id'], ),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['subject_id'],    ['subjects.id'], ),
        sa.ForeignKeyConstraint(['grade_id'],      ['grades.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('lms_assignment_templates', schema=None) as batch:
        batch.create_index(batch.f('ix_lms_assignment_templates_school_id'),  ['school_id'],  unique=False)
        batch.create_index(batch.f('ix_lms_assignment_templates_subject_id'), ['subject_id'], unique=False)
        batch.create_index(batch.f('ix_lms_assignment_templates_grade_id'),   ['grade_id'],   unique=False)

    op.create_table(
        'lms_assignment_template_questions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('template_id',    sa.Integer(), nullable=False),
        sa.Column('order_index',    sa.Integer(), nullable=False, server_default='0'),
        sa.Column('kind',           sa.String(length=20),  nullable=True),
        sa.Column('prompt',         sa.Text(),             nullable=False),
        sa.Column('points',         sa.Numeric(6, 2),      nullable=True),
        sa.Column('correct_short',  sa.String(length=200), nullable=True),
        sa.Column('source_bank_id', sa.Integer(),          nullable=True),
        sa.ForeignKeyConstraint(['template_id'],    ['lms_assignment_templates.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_bank_id'], ['lms_bank_questions.id'],       ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('lms_assignment_template_questions', schema=None) as batch:
        batch.create_index(batch.f('ix_lms_atq_template_id'),    ['template_id'],    unique=False)
        batch.create_index(batch.f('ix_lms_atq_source_bank_id'), ['source_bank_id'], unique=False)

    op.create_table(
        'lms_assignment_template_choices',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('question_id', sa.Integer(), nullable=False),
        sa.Column('order_index', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('label',       sa.String(length=500), nullable=False),
        sa.Column('is_correct',  sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(['question_id'], ['lms_assignment_template_questions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('lms_assignment_template_choices', schema=None) as batch:
        batch.create_index(batch.f('ix_lms_atc_question_id'), ['question_id'], unique=False)

    # ── Ticket #16 Part 3 — Smart assignments (questions + answers) ────
    with op.batch_alter_table('lms_assignments', schema=None) as batch:
        batch.add_column(sa.Column('source_template_id', sa.Integer(), nullable=True))
        batch.create_index(batch.f('ix_lms_assignments_source_template_id'),
                           ['source_template_id'], unique=False)
        batch.create_foreign_key(
            'fk_lms_assignments_source_template',
            'lms_assignment_templates', ['source_template_id'], ['id'],
            ondelete='SET NULL',
        )

    op.create_table(
        'lms_assignment_questions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('assignment_id',  sa.Integer(), nullable=False),
        sa.Column('order_index',    sa.Integer(), nullable=False, server_default='0'),
        sa.Column('kind',           sa.String(length=20),  nullable=True),
        sa.Column('prompt',         sa.Text(),             nullable=False),
        sa.Column('points',         sa.Numeric(6, 2),      nullable=True),
        sa.Column('correct_short',  sa.String(length=200), nullable=True),
        sa.Column('source_bank_id', sa.Integer(),          nullable=True),
        sa.ForeignKeyConstraint(['assignment_id'],  ['lms_assignments.id'],    ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_bank_id'], ['lms_bank_questions.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('lms_assignment_questions', schema=None) as batch:
        batch.create_index(batch.f('ix_lms_aq_assignment_id'),  ['assignment_id'],  unique=False)
        batch.create_index(batch.f('ix_lms_aq_source_bank_id'), ['source_bank_id'], unique=False)

    op.create_table(
        'lms_assignment_choices',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('question_id', sa.Integer(), nullable=False),
        sa.Column('order_index', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('label',       sa.String(length=500), nullable=False),
        sa.Column('is_correct',  sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(['question_id'], ['lms_assignment_questions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('lms_assignment_choices', schema=None) as batch:
        batch.create_index(batch.f('ix_lms_ac_question_id'), ['question_id'], unique=False)

    op.create_table(
        'lms_assignment_answers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('submission_id',   sa.Integer(),      nullable=False),
        sa.Column('question_id',     sa.Integer(),      nullable=False),
        sa.Column('choice_id',       sa.Integer(),      nullable=True),
        sa.Column('text_answer',     sa.Text(),         nullable=True),
        sa.Column('is_correct',      sa.Boolean(),      nullable=True),
        sa.Column('awarded_points',  sa.Numeric(6, 2),  nullable=True),
        sa.ForeignKeyConstraint(['submission_id'], ['lms_submissions.id'],           ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['question_id'],   ['lms_assignment_questions.id']),
        sa.ForeignKeyConstraint(['choice_id'],     ['lms_assignment_choices.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('lms_assignment_answers', schema=None) as batch:
        batch.create_index(batch.f('ix_lms_aa_submission_id'), ['submission_id'], unique=False)


def downgrade():
    # Reverse strict order — drop children before parents.
    with op.batch_alter_table('lms_assignment_answers', schema=None) as batch:
        batch.drop_index(batch.f('ix_lms_aa_submission_id'))
    op.drop_table('lms_assignment_answers')

    with op.batch_alter_table('lms_assignment_choices', schema=None) as batch:
        batch.drop_index(batch.f('ix_lms_ac_question_id'))
    op.drop_table('lms_assignment_choices')

    with op.batch_alter_table('lms_assignment_questions', schema=None) as batch:
        batch.drop_index(batch.f('ix_lms_aq_source_bank_id'))
        batch.drop_index(batch.f('ix_lms_aq_assignment_id'))
    op.drop_table('lms_assignment_questions')

    with op.batch_alter_table('lms_assignments', schema=None) as batch:
        batch.drop_constraint('fk_lms_assignments_source_template', type_='foreignkey')
        batch.drop_index(batch.f('ix_lms_assignments_source_template_id'))
        batch.drop_column('source_template_id')

    with op.batch_alter_table('lms_assignment_template_choices', schema=None) as batch:
        batch.drop_index(batch.f('ix_lms_atc_question_id'))
    op.drop_table('lms_assignment_template_choices')

    with op.batch_alter_table('lms_assignment_template_questions', schema=None) as batch:
        batch.drop_index(batch.f('ix_lms_atq_source_bank_id'))
        batch.drop_index(batch.f('ix_lms_atq_template_id'))
    op.drop_table('lms_assignment_template_questions')

    with op.batch_alter_table('lms_assignment_templates', schema=None) as batch:
        batch.drop_index(batch.f('ix_lms_assignment_templates_grade_id'))
        batch.drop_index(batch.f('ix_lms_assignment_templates_subject_id'))
        batch.drop_index(batch.f('ix_lms_assignment_templates_school_id'))
    op.drop_table('lms_assignment_templates')

    with op.batch_alter_table('lms_bank_questions', schema=None) as batch:
        for fk in ('fk_bank_q_lesson', 'fk_bank_q_unit', 'fk_bank_q_term'):
            batch.drop_constraint(fk, type_='foreignkey')
        batch.drop_index(batch.f('ix_lms_bank_questions_lesson_id'))
        batch.drop_index(batch.f('ix_lms_bank_questions_unit_id'))
        batch.drop_index(batch.f('ix_lms_bank_questions_term_id'))
        batch.drop_column('lesson_id')
        batch.drop_column('unit_id')
        batch.drop_column('term_id')

    with op.batch_alter_table('lms_lessons', schema=None) as batch:
        batch.drop_constraint('fk_lms_lessons_unit', type_='foreignkey')
        batch.drop_index(batch.f('ix_lms_lessons_unit_id'))
        batch.drop_column('unit_id')

    with op.batch_alter_table('lms_units', schema=None) as batch:
        batch.drop_index(batch.f('ix_lms_units_course_id'))
    op.drop_table('lms_units')

    with op.batch_alter_table('assignments', schema=None) as batch:
        batch.drop_constraint('uq_assignment_year_term_section_subject_teacher', type_='unique')
        batch.create_unique_constraint(
            'uq_assignment_unique_quad',
            ['year_id', 'section_id', 'subject_id', 'teacher_id'],
        )
        batch.drop_constraint('fk_assignments_term', type_='foreignkey')
        batch.drop_index(batch.f('ix_assignments_term_id'))
        batch.drop_column('term_id')

    op.drop_table('teacher_subjects')

    with op.batch_alter_table('terms', schema=None) as batch:
        batch.drop_column('manual_status')
        batch.drop_column('status_mode')
