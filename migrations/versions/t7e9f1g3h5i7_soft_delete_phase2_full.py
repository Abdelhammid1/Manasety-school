"""Soft-delete Phase 2 — extend deleted_at/deleted_by_id to the
remaining ~26 tables the ticket enumerated.

Every column is nullable so a fresh row keeps the default `NULL`
(alive). Idempotent — guarded against re-runs the same way the
Phase 0 migration was.

Also swaps every unique-name constraint that could collide with a
soft-deleted row for a partial unique index scoped to
`deleted_at IS NULL` — same pattern the Phase 3 migration already
applied to FeeType / PaymentMethod / CostCenter.
"""

from alembic import op
import sqlalchemy as sa


revision = 't7e9f1g3h5i7'
down_revision = 's5d7e9f1g3h5'
branch_labels = None
depends_on = None


# Every table getting the two new columns.
_TABLES = [
    # academic
    'terms', 'grades', 'sections', 'subjects', 'academic_years',
    'days', 'periods', 'schedule_slots', 'calendar_days',
    # rooms + platform
    'rooms', 'student_guardians', 'student_documents',
    # results
    'assessment_components', 'grading_scales', 'grading_scale_levels',
    'rubrics', 'rubric_criteria',
    # lms
    'lms_courses', 'lms_units', 'lms_lessons',
    'lms_assignments', 'lms_announcements', 'lms_assignment_templates',
    'lms_assignment_questions', 'lms_quizzes', 'lms_questions',
    'lms_bank_questions',
    'lms_assessment_template_questions', 'passages',
    # hr + finance-recurring
    'payrolls', 'recurring_fee_schedules',
    # nafis
    'nafis_cycles',
]


# Unique constraints to swap for partial indexes.
# Format: (table, constraint_name, columns)
_UNIQUES = [
    # 'terms' excluded — no unique constraint on (year_id, name) exists;
    # the real one is uq_term_year_order on (year_id, order_index), a
    # different concern not covered by this soft-delete swap.
    ('grades',          'uq_grade_school_name',        ('school_id', 'name')),
    ('sections',        'uq_section_year_grade_name',  ('year_id', 'grade_id', 'name')),
    ('subjects',        'uq_subject_school_name',      ('school_id', 'name')),
]


def _has(table, col):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return any(c["name"] == col for c in insp.get_columns(table))


def _table_exists(name):
    bind = op.get_bind()
    return sa.inspect(bind).has_table(name)


def _index_exists(table, name):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return any(ix["name"] == name for ix in insp.get_indexes(table))


def upgrade():
    for tbl in _TABLES:
        if not _table_exists(tbl):
            continue
        with op.batch_alter_table(tbl) as b:
            if not _has(tbl, 'deleted_at'):
                b.add_column(sa.Column('deleted_at',
                                       sa.DateTime(timezone=True),
                                       nullable=True, index=True))
            if not _has(tbl, 'deleted_by_id'):
                b.add_column(sa.Column('deleted_by_id',
                                       sa.Integer, nullable=True))

    # Swap the plain unique constraints for partial ones on the
    # subset of tables where a soft-deleted row + a fresh insert
    # would otherwise 409 at the DB level.
    conn = op.get_bind()
    dialect = conn.dialect.name
    for table, name, cols in _UNIQUES:
        if not _table_exists(table):
            continue
        idx_name = f'ux_{table}_active_uq'
        if _index_exists(table, idx_name):
            continue
        try:
            if dialect == 'sqlite':
                with op.batch_alter_table(table) as b:
                    try:
                        b.drop_constraint(name, type_='unique')
                    except Exception:
                        pass  # constraint may not exist under that name
            else:
                op.drop_constraint(name, table, type_='unique')
        except Exception:
            pass
        where_expr = sa.text('deleted_at IS NULL')
        op.create_index(
            idx_name, table, list(cols), unique=True,
            sqlite_where=where_expr, postgresql_where=where_expr,
        )


def downgrade():
    for table, name, cols in _UNIQUES:
        if _table_exists(table):
            try:
                op.drop_index(f'ux_{table}_active_uq', table_name=table)
            except Exception:
                pass
            with op.batch_alter_table(table) as b:
                try:
                    b.create_unique_constraint(name, list(cols))
                except Exception:
                    pass
    for tbl in _TABLES:
        if not _table_exists(tbl):
            continue
        with op.batch_alter_table(tbl) as b:
            if _has(tbl, 'deleted_by_id'):
                b.drop_column('deleted_by_id')
            if _has(tbl, 'deleted_at'):
                b.drop_column('deleted_at')
