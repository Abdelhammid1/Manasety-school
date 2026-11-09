"""Sequential per-school journal entry number (2026-11-09).

Adds journal_entries.entry_no (nullable int) and numbers every existing
entry per school in id order (1, 2, 3 ...). A unique index on
(school_id, entry_no) guarantees no duplicates; new entries get their
number from a before_insert hook in the model. Nothing else is touched.

Downgrade drops the index and the column.
"""

from alembic import op
import sqlalchemy as sa

revision = 'k2f4a6b8c0d2'
down_revision = 'j1e3f5a7b9c1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("journal_entries", sa.Column("entry_no", sa.Integer(), nullable=True))
    op.execute(sa.text("""
        UPDATE journal_entries
           SET entry_no = s.rn
          FROM (SELECT id,
                       ROW_NUMBER() OVER (PARTITION BY school_id ORDER BY id) AS rn
                  FROM journal_entries) AS s
         WHERE journal_entries.id = s.id
    """))
    op.create_index("uq_je_school_no", "journal_entries",
                    ["school_id", "entry_no"], unique=True)


def downgrade():
    op.drop_index("uq_je_school_no", table_name="journal_entries")
    op.drop_column("journal_entries", "entry_no")
