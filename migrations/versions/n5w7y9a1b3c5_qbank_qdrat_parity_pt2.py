"""Qdrat-parity part 2 — 2-level taxonomy (axis + indicator),
per-question public code + UUID, hide toggle, template-item hide.

Closes 6 of the 8 qdrat-vs-us gaps:
  * (1) Axis + Indicator tables — a two-level skill taxonomy per
    school (المحور = axis, المؤشر = indicator/skill). Every school
    owns its own taxonomy, so a rename in school A doesn't leak into
    school B's item bank.
  * (2) `bank_questions.code` — printable public identifier, e.g.
    "MB79Q11". Free-form string so a school can adopt qdrat's exact
    numbering scheme or roll its own.
  * (3) `bank_questions.uuid` — anti-piracy fingerprint printed on
    hard-copy sheets. Generated once, immutable, unique per row.
  * (5) `bank_questions.is_archived` — a soft-hide separate from the
    review_state machine. An archived question stays in the tables
    but is filtered out of picker + gallery views. This is the
    equivalent of qdrat's النشطة/الأرشيف toggle.
  * (7) housekeeping views can key off `axis_id IS NULL` — no
    schema addition needed, just the query.
  * (8) `lms_assessment_template_questions.is_hidden` — soft-hide
    an item from a specific template without deleting the row.

Skips (4) print — pure UI, no data model change — and (6) reading
passages, which needs the Stitch design the user is going to send.
"""

from alembic import op
import sqlalchemy as sa


revision = 'n5w7y9a1b3c5'
down_revision = 'm3u5w7y9z1a3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'axes',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('school_id', sa.Integer, sa.ForeignKey('schools.id'),
                  nullable=False, index=True),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('order_index', sa.Integer, nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.UniqueConstraint('school_id', 'name', name='uq_axes_school_name'),
    )
    op.create_table(
        'indicators',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('school_id', sa.Integer, sa.ForeignKey('schools.id'),
                  nullable=False, index=True),
        sa.Column('axis_id', sa.Integer, sa.ForeignKey('axes.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('name', sa.String(160), nullable=False),
        sa.Column('order_index', sa.Integer, nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.UniqueConstraint('axis_id', 'name', name='uq_indicators_axis_name'),
    )
    with op.batch_alter_table('lms_bank_questions') as b:
        b.add_column(sa.Column('axis_id', sa.Integer, nullable=True, index=True))
        b.add_column(sa.Column('indicator_id', sa.Integer, nullable=True, index=True))
        b.create_foreign_key('fk_bank_axis', 'axes', ['axis_id'], ['id'],
                             ondelete='SET NULL')
        b.create_foreign_key('fk_bank_indicator', 'indicators',
                             ['indicator_id'], ['id'], ondelete='SET NULL')
        b.add_column(sa.Column('code', sa.String(32), nullable=True, index=True))
        b.add_column(sa.Column('uuid', sa.String(36), nullable=True))
        b.add_column(sa.Column('is_archived', sa.Boolean, nullable=False,
                               server_default=sa.false()))
    with op.batch_alter_table('lms_assessment_template_questions') as b:
        b.add_column(sa.Column('is_hidden', sa.Boolean, nullable=False,
                               server_default=sa.false()))


def downgrade():
    with op.batch_alter_table('lms_assessment_template_questions') as b:
        b.drop_column('is_hidden')
    with op.batch_alter_table('lms_bank_questions') as b:
        b.drop_column('is_archived')
        b.drop_column('uuid')
        b.drop_column('code')
        b.drop_column('indicator_id')
        b.drop_column('axis_id')
    op.drop_table('indicators')
    op.drop_table('axes')
