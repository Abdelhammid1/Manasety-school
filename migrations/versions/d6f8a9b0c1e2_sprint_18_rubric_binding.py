"""sprint 18: rubric_id on CourseAssignment + AssessmentComponent
(ticket #16 wiring).

Revision ID: d6f8a9b0c1e2
Revises: c5e6f7a8b9d1
Create Date: 2026-09-16 17:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'd6f8a9b0c1e2'
down_revision = 'c5e6f7a8b9d1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('lms_assignments', schema=None) as b:
        b.add_column(sa.Column('rubric_id', sa.Integer(), nullable=True))
        b.create_index(b.f('ix_lms_assignments_rubric_id'), ['rubric_id'], unique=False)
        b.create_foreign_key('fk_lms_assignments_rubric', 'rubrics',
                             ['rubric_id'], ['id'], ondelete='SET NULL')
    with op.batch_alter_table('assessment_components', schema=None) as b:
        b.add_column(sa.Column('rubric_id', sa.Integer(), nullable=True))
        b.create_index(b.f('ix_assessment_components_rubric_id'), ['rubric_id'], unique=False)
        b.create_foreign_key('fk_component_rubric', 'rubrics',
                             ['rubric_id'], ['id'], ondelete='SET NULL')


def downgrade():
    with op.batch_alter_table('assessment_components', schema=None) as b:
        b.drop_constraint('fk_component_rubric', type_='foreignkey')
        b.drop_index(b.f('ix_assessment_components_rubric_id'))
        b.drop_column('rubric_id')
    with op.batch_alter_table('lms_assignments', schema=None) as b:
        b.drop_constraint('fk_lms_assignments_rubric', type_='foreignkey')
        b.drop_index(b.f('ix_lms_assignments_rubric_id'))
        b.drop_column('rubric_id')
