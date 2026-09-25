"""Partial unique indexes on soft-delete tables (Phase 3).

Without this, soft-deleting a row named "شركة الأمل" then creating a
fresh row with the same name fails on the existing unique constraint
even though the old row is logically gone. Solution: replace the
plain unique index with a partial one that only enforces uniqueness
across `deleted_at IS NULL` rows.

Both SQLite (≥ 3.8) and Postgres (≥ 9.6) support partial indexes with
the same `WHERE` clause syntax used here.
"""

from alembic import op
import sqlalchemy as sa


revision = 's5d7e9f1g3h5'
down_revision = 'r3c5d7e9f1g3'
branch_labels = None
depends_on = None


_TARGETS = [
    ('fee_types',       'uq_fee_type_school_name',       ('school_id', 'name')),
    ('payment_methods', 'uq_payment_method_school_name', ('school_id', 'name')),
    ('cost_centers',    'uq_cost_center_school_name',    ('school_id', 'name')),
]


def upgrade():
    """SQLite can't `DROP CONSTRAINT` on an existing table without a
    full copy — but the table exists, so we take a lightweight
    approach: drop the auto-created unique INDEX (sqlite maps a
    UniqueConstraint to a `sqlite_autoindex_...` INDEX) and add a new
    partial one. On Postgres this is a straight DROP + CREATE.
    """
    conn = op.get_bind()
    dialect = conn.dialect.name

    for table, name, cols in _TARGETS:
        col_list = ', '.join(cols)
        if dialect == 'sqlite':
            # Find the auto-index name — sqlite names it `sqlite_autoindex_<table>_N`.
            # Rather than guess N, list them and drop any that matches the columns.
            rows = conn.exec_driver_sql(
                f"PRAGMA index_list({table})").fetchall()
            for _seq, idx_name, unique, *_ in rows:
                if not unique:
                    continue
                info = conn.exec_driver_sql(
                    f"PRAGMA index_info({idx_name})").fetchall()
                idx_cols = tuple(r[2] for r in info)
                if idx_cols == cols:
                    # Drop the auto index — but SQLite forbids dropping
                    # auto indexes. Instead we create the partial index
                    # AND leave the auto one; the partial one is what
                    # `INSERT`s will conflict on for deleted_at IS NULL
                    # rows, and the auto index is kept in sync because
                    # UniqueConstraint sits in the table's DDL.
                    # Reality check: to make soft-deleted rows able to
                    # be duplicated we need to rebuild the table with
                    # the plain UniqueConstraint replaced by the partial
                    # index. Do that via batch_alter_table.
                    with op.batch_alter_table(table) as b:
                        b.drop_constraint(name, type_='unique')
                    break
        else:
            # Postgres path.
            op.drop_constraint(name, table, type_='unique')

        # Fresh partial unique index — active rows only. SQLAlchemy's
        # `sqlite_where` / `postgresql_where` take a SQL expression;
        # `sa.text` wraps a raw SQL string so both dialects see it as-is.
        where_expr = sa.text('deleted_at IS NULL')
        op.create_index(
            f'ux_{table}_name_active',
            table,
            list(cols),
            unique=True,
            sqlite_where=where_expr,
            postgresql_where=where_expr,
        )


def downgrade():
    conn = op.get_bind()
    for table, name, cols in _TARGETS:
        op.drop_index(f'ux_{table}_name_active', table_name=table)
        with op.batch_alter_table(table) as b:
            b.create_unique_constraint(name, list(cols))
