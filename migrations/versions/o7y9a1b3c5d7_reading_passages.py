"""Reading passages — qdrat-parity #6 (القطع اللفظية).

A `Passage` is shared text that N bank questions can attach to.
Every school owns its own set; a passage stays independent of the
questions that reference it (they're just linked by
`bank_questions.passage_id`).
"""

from alembic import op
import sqlalchemy as sa


revision = 'o7y9a1b3c5d7'
down_revision = 'n5w7y9a1b3c5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'passages',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('school_id', sa.Integer, sa.ForeignKey('schools.id'),
                  nullable=False, index=True),
        sa.Column('created_by_id', sa.Integer, sa.ForeignKey('users.id'),
                  nullable=True, index=True),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('body', sa.Text, nullable=False, server_default=''),
        sa.Column('source', sa.String(200), nullable=True),
        sa.Column('language', sa.String(8), nullable=False, server_default='ar'),
        sa.Column('subject_id', sa.Integer, sa.ForeignKey('subjects.id'),
                  nullable=True, index=True),
        sa.Column('grade_id', sa.Integer, sa.ForeignKey('grades.id'),
                  nullable=True, index=True),
        sa.Column('word_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('image_url', sa.String(500), nullable=True),
        sa.Column('audio_url', sa.String(500), nullable=True),
        sa.Column('state', sa.String(16), nullable=False,
                  server_default='draft'),  # draft | published | archived
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
    )
    with op.batch_alter_table('lms_bank_questions') as b:
        b.add_column(sa.Column('passage_id', sa.Integer, nullable=True, index=True))
        b.create_foreign_key('fk_bank_passage', 'passages',
                             ['passage_id'], ['id'], ondelete='SET NULL')


def downgrade():
    with op.batch_alter_table('lms_bank_questions') as b:
        b.drop_column('passage_id')
    op.drop_table('passages')
