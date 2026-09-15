"""sprint 14: subject_terms association — a subject can span 1..N academic
terms (Grade many-to-many already exists via subject_grades).

Revision ID: a9c1e5f28d13
Revises: f7c8e91a2b4d
Create Date: 2026-09-15 13:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'a9c1e5f28d13'
down_revision = 'f7c8e91a2b4d'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'subject_terms',
        sa.Column('subject_id', sa.Integer(), nullable=False),
        sa.Column('term_id',    sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['subject_id'], ['subjects.id'], ),
        sa.ForeignKeyConstraint(['term_id'],    ['terms.id'],    ),
        sa.PrimaryKeyConstraint('subject_id', 'term_id'),
    )


def downgrade():
    op.drop_table('subject_terms')
