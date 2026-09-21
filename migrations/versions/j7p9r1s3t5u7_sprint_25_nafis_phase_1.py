"""sprint 25 — NAFIS phase 1 (learning outcomes catalog + cycles + result shell).

Tables added (all school-scoped except learning_outcomes whose school_id
is nullable so a global seed can be shared across every tenant):
  · learning_outcomes         — hierarchical ETEC standards tree
  · nafis_cycles              — one testing round (e.g. 1447/2026)
  · nafis_results             — per (student, cycle, subject) top score
  · nafis_outcome_scores      — per-outcome fine-grain scores
  · student_gaps              — derived weaknesses per student
  · intervention_plans        — remedial plans
  · intervention_plan_outcomes
  · intervention_sessions

No default rows — the seed is loaded separately by
`scripts/seed_nafis_outcomes.py` from `seeds/nafis_outcomes.json`.

Revision ID: j7p9r1s3t5u7
Revises: i5m7n9p1r3s5
Create Date: 2026-09-21 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'j7p9r1s3t5u7'
down_revision = 'i5m7n9p1r3s5'
branch_labels = None
depends_on = None


def upgrade():
    # ── Learning outcomes tree ──────────────────────────────────
    op.create_table(
        'learning_outcomes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('school_id', sa.Integer(),
                  sa.ForeignKey('schools.id'), nullable=True),
        sa.Column('parent_id', sa.Integer(),
                  sa.ForeignKey('learning_outcomes.id'), nullable=True),
        sa.Column('subject', sa.String(length=16), nullable=False),
        sa.Column('level',   sa.String(length=4),  nullable=False),
        sa.Column('kind',    sa.String(length=16), nullable=False),
        sa.Column('code',    sa.String(length=64), nullable=True),
        sa.Column('seq',     sa.Integer(),         nullable=True),
        sa.Column('text_ar', sa.Text(),            nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.UniqueConstraint('school_id', 'code', name='uq_lo_school_code'),
    )
    op.create_index('ix_learning_outcomes_school_id',
                    'learning_outcomes', ['school_id'])
    op.create_index('ix_learning_outcomes_parent_id',
                    'learning_outcomes', ['parent_id'])
    op.create_index('ix_learning_outcomes_code',
                    'learning_outcomes', ['code'])
    op.create_index('ix_lo_subject_level_kind',
                    'learning_outcomes', ['subject', 'level', 'kind'])

    # ── NAFIS cycles ────────────────────────────────────────────
    op.create_table(
        'nafis_cycles',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('school_id', sa.Integer(),
                  sa.ForeignKey('schools.id'), nullable=False),
        sa.Column('academic_year_id', sa.Integer(),
                  sa.ForeignKey('academic_years.id'), nullable=True),
        sa.Column('name_ar', sa.String(length=128), nullable=False),
        sa.Column('hijri_year', sa.String(length=8), nullable=True),
        sa.Column('gregorian_year', sa.Integer(), nullable=True),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('end_date',   sa.Date(), nullable=True),
        sa.Column('levels', sa.String(length=32),
                  nullable=False, server_default='g3,g6,g9'),
        sa.Column('status', sa.String(length=24),
                  nullable=False, server_default='upcoming'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.UniqueConstraint('school_id', 'name_ar',
                            name='uq_nafis_cycle_school_name'),
    )
    op.create_index('ix_nafis_cycles_school_id', 'nafis_cycles', ['school_id'])
    op.create_index('ix_nafis_cycles_academic_year_id',
                    'nafis_cycles', ['academic_year_id'])

    # ── NAFIS results (subject-level headline) ──────────────────
    op.create_table(
        'nafis_results',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('school_id', sa.Integer(),
                  sa.ForeignKey('schools.id'), nullable=False),
        sa.Column('cycle_id', sa.Integer(),
                  sa.ForeignKey('nafis_cycles.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('student_id', sa.Integer(),
                  sa.ForeignKey('students.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('level', sa.String(length=4), nullable=False),
        sa.Column('subject', sa.String(length=16), nullable=False),
        sa.Column('raw_score', sa.Integer(), nullable=True),
        sa.Column('total_questions', sa.Integer(), nullable=True),
        sa.Column('percentage', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('band', sa.String(length=16), nullable=True),
        sa.Column('national_percentile',
                  sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('imported_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('imported_by_user_id', sa.Integer(),
                  sa.ForeignKey('users.id'), nullable=True),
        sa.UniqueConstraint('cycle_id', 'student_id', 'subject',
                            name='uq_nafis_result_cycle_student_subject'),
    )
    op.create_index('ix_nafis_results_school_id', 'nafis_results', ['school_id'])
    op.create_index('ix_nafis_results_cycle_id',  'nafis_results', ['cycle_id'])
    op.create_index('ix_nafis_results_student_id','nafis_results', ['student_id'])
    op.create_index('ix_nafis_result_level_subject',
                    'nafis_results', ['level', 'subject'])

    # ── NAFIS outcome scores (fine grain) ───────────────────────
    op.create_table(
        'nafis_outcome_scores',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('result_id', sa.Integer(),
                  sa.ForeignKey('nafis_results.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('outcome_id', sa.Integer(),
                  sa.ForeignKey('learning_outcomes.id'), nullable=False),
        sa.Column('mastered', sa.Boolean(), nullable=True),
        sa.Column('score_pct', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.UniqueConstraint('result_id', 'outcome_id',
                            name='uq_nafis_outcome_score_result_outcome'),
    )
    op.create_index('ix_nafis_outcome_scores_result_id',
                    'nafis_outcome_scores', ['result_id'])
    op.create_index('ix_nafis_outcome_scores_outcome_id',
                    'nafis_outcome_scores', ['outcome_id'])

    # ── Student gaps ────────────────────────────────────────────
    op.create_table(
        'student_gaps',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('school_id', sa.Integer(),
                  sa.ForeignKey('schools.id'), nullable=False),
        sa.Column('student_id', sa.Integer(),
                  sa.ForeignKey('students.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('outcome_id', sa.Integer(),
                  sa.ForeignKey('learning_outcomes.id'), nullable=False),
        sa.Column('severity', sa.String(length=16), nullable=False),
        sa.Column('source',   sa.String(length=16), nullable=False),
        sa.Column('evidence_ref', sa.String(length=64), nullable=True),
        sa.Column('detected_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('student_id', 'outcome_id',
                            name='uq_student_gap_student_outcome'),
    )
    op.create_index('ix_student_gaps_school_id', 'student_gaps', ['school_id'])
    op.create_index('ix_student_gaps_student_id','student_gaps', ['student_id'])
    op.create_index('ix_student_gaps_outcome_id','student_gaps', ['outcome_id'])

    # ── Intervention plans ──────────────────────────────────────
    op.create_table(
        'intervention_plans',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('school_id', sa.Integer(),
                  sa.ForeignKey('schools.id'), nullable=False),
        sa.Column('student_id', sa.Integer(),
                  sa.ForeignKey('students.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('owner_teacher_id', sa.Integer(),
                  sa.ForeignKey('teachers.id'), nullable=True),
        sa.Column('title_ar', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('end_date',   sa.Date(), nullable=True),
        sa.Column('status', sa.String(length=16),
                  nullable=False, server_default='draft'),
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('created_by_user_id', sa.Integer(),
                  sa.ForeignKey('users.id'), nullable=True),
    )
    op.create_index('ix_intervention_plans_school_id',
                    'intervention_plans', ['school_id'])
    op.create_index('ix_intervention_plans_student_id',
                    'intervention_plans', ['student_id'])
    op.create_index('ix_intervention_plans_owner_teacher_id',
                    'intervention_plans', ['owner_teacher_id'])

    op.create_table(
        'intervention_plan_outcomes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('plan_id', sa.Integer(),
                  sa.ForeignKey('intervention_plans.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('outcome_id', sa.Integer(),
                  sa.ForeignKey('learning_outcomes.id'), nullable=False),
        sa.UniqueConstraint('plan_id', 'outcome_id',
                            name='uq_plan_outcome_plan_outcome'),
    )
    op.create_index('ix_intervention_plan_outcomes_plan_id',
                    'intervention_plan_outcomes', ['plan_id'])
    op.create_index('ix_intervention_plan_outcomes_outcome_id',
                    'intervention_plan_outcomes', ['outcome_id'])

    op.create_table(
        'intervention_sessions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('plan_id', sa.Integer(),
                  sa.ForeignKey('intervention_plans.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('session_date', sa.Date(), nullable=False),
        sa.Column('duration_minutes', sa.Integer(), nullable=True),
        sa.Column('attended', sa.Boolean(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
    )
    op.create_index('ix_intervention_sessions_plan_id',
                    'intervention_sessions', ['plan_id'])


def downgrade():
    op.drop_index('ix_intervention_sessions_plan_id',
                  table_name='intervention_sessions')
    op.drop_table('intervention_sessions')
    op.drop_index('ix_intervention_plan_outcomes_outcome_id',
                  table_name='intervention_plan_outcomes')
    op.drop_index('ix_intervention_plan_outcomes_plan_id',
                  table_name='intervention_plan_outcomes')
    op.drop_table('intervention_plan_outcomes')
    op.drop_index('ix_intervention_plans_owner_teacher_id',
                  table_name='intervention_plans')
    op.drop_index('ix_intervention_plans_student_id',
                  table_name='intervention_plans')
    op.drop_index('ix_intervention_plans_school_id',
                  table_name='intervention_plans')
    op.drop_table('intervention_plans')

    op.drop_index('ix_student_gaps_outcome_id', table_name='student_gaps')
    op.drop_index('ix_student_gaps_student_id', table_name='student_gaps')
    op.drop_index('ix_student_gaps_school_id',  table_name='student_gaps')
    op.drop_table('student_gaps')

    op.drop_index('ix_nafis_outcome_scores_outcome_id',
                  table_name='nafis_outcome_scores')
    op.drop_index('ix_nafis_outcome_scores_result_id',
                  table_name='nafis_outcome_scores')
    op.drop_table('nafis_outcome_scores')

    op.drop_index('ix_nafis_result_level_subject', table_name='nafis_results')
    op.drop_index('ix_nafis_results_student_id',   table_name='nafis_results')
    op.drop_index('ix_nafis_results_cycle_id',     table_name='nafis_results')
    op.drop_index('ix_nafis_results_school_id',    table_name='nafis_results')
    op.drop_table('nafis_results')

    op.drop_index('ix_nafis_cycles_academic_year_id', table_name='nafis_cycles')
    op.drop_index('ix_nafis_cycles_school_id',        table_name='nafis_cycles')
    op.drop_table('nafis_cycles')

    op.drop_index('ix_lo_subject_level_kind',    table_name='learning_outcomes')
    op.drop_index('ix_learning_outcomes_code',   table_name='learning_outcomes')
    op.drop_index('ix_learning_outcomes_parent_id', table_name='learning_outcomes')
    op.drop_index('ix_learning_outcomes_school_id', table_name='learning_outcomes')
    op.drop_table('learning_outcomes')
