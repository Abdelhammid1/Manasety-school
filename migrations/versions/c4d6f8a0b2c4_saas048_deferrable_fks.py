"""SAAS-048 (2026-10-22) — every foreign key DEFERRABLE INITIALLY IMMEDIATE.

Behaviour is unchanged (checked immediately); a school restore's
transaction alone runs SET CONSTRAINTS ALL DEFERRED so it can delete and
re-insert a module's rows, and checks every constraint before commit.
PostgreSQL only (SQLite dev databases don't enforce foreign keys here).
"""

from alembic import op
import sqlalchemy as sa

revision = 'c4d6f8a0b2c4'
down_revision = 'b3c5d7e9f1a3'
branch_labels = None
depends_on = None

_LIST = sa.text(
    "SELECT c.conrelid::regclass::text, c.conname FROM pg_constraint c "
    "JOIN pg_namespace n ON n.oid = c.connamespace "
    "WHERE c.contype = 'f' AND n.nspname = current_schema() AND c.condeferrable = :d")


def _alter(deferrable: bool):
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    rows = bind.execute(_LIST, {"d": not deferrable}).fetchall()
    clause = "DEFERRABLE INITIALLY IMMEDIATE" if deferrable else "NOT DEFERRABLE"
    for table, name in rows:
        op.execute(f'ALTER TABLE {table} ALTER CONSTRAINT "{name}" {clause}')


def upgrade():
    _alter(True)


def downgrade():
    _alter(False)
