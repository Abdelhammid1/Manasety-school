"""sprint 20: Ticket #2 — Course refactor.

Removes lms_courses.section_id and lms_courses.teacher_id; adds
grade_id + term_id. Introduces lms_course_sections join table so one
Course row now serves every Section of the same grade.

Data migration:
  · backfill lms_courses.grade_id from Section.grade_id via
    the old section_id column
  · for every existing Course, insert an lms_course_sections row
    (is_published = True, published_at = created_at)
  · for each (year, grade, subject) group of duplicate Courses,
    pick the richest by (lessons + assignments + quizzes), move
    all children (lessons/assignments/quizzes/units + the
    course_sections rows we just inserted) to the survivor, then
    delete duplicates.
  · widen the UniqueConstraint to
    (academic_year_id, grade_id, subject_id, term_id).

Revision ID: e7g9h1a3b5c6
Revises: d6f8a9b0c1e2
Create Date: 2026-09-16 15:15:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'e7g9h1a3b5c6'
down_revision = 'd6f8a9b0c1e2'
branch_labels = None
depends_on = None


CHILD_TABLES = ('lms_lessons', 'lms_assignments', 'lms_quizzes', 'lms_units')


def upgrade():
    bind = op.get_bind()

    # 1) Add new nullable columns so we can backfill.
    with op.batch_alter_table('lms_courses', schema=None) as b:
        b.add_column(sa.Column('grade_id', sa.Integer(), nullable=True))
        b.add_column(sa.Column('term_id',  sa.Integer(), nullable=True))
        b.create_index(b.f('ix_lms_courses_grade_id'), ['grade_id'], unique=False)
        b.create_index(b.f('ix_lms_courses_term_id'),  ['term_id'],  unique=False)
        b.create_foreign_key('fk_lms_courses_grade', 'grades',
                             ['grade_id'], ['id'])
        b.create_foreign_key('fk_lms_courses_term',  'terms',
                             ['term_id'], ['id'], ondelete='SET NULL')

    # 2) Backfill grade_id from Section (via the old section_id).
    bind.execute(sa.text("""
        UPDATE lms_courses
           SET grade_id = (
             SELECT grade_id FROM sections WHERE sections.id = lms_courses.section_id
           )
         WHERE section_id IS NOT NULL
    """))

    # 3) Create lms_course_sections.
    op.create_table(
        'lms_course_sections',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('course_id',  sa.Integer(), sa.ForeignKey('lms_courses.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('section_id', sa.Integer(), sa.ForeignKey('sections.id',    ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('is_published', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at',   sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('course_id', 'section_id', name='uq_course_section'),
    )

    # 4) Seed lms_course_sections from every existing course row (one row per course).
    bind.execute(sa.text("""
        INSERT INTO lms_course_sections (course_id, section_id, is_published, published_at, created_at)
        SELECT id, section_id, true, created_at, created_at
          FROM lms_courses
         WHERE section_id IS NOT NULL
    """))

    # 5) Merge duplicate Courses. For every group of Courses that shares
    #    (school_id, academic_year_id, grade_id, subject_id) we keep one
    #    survivor and move all children onto it. Duplicates then go.
    dup_groups = bind.execute(sa.text("""
        SELECT school_id, academic_year_id, grade_id, subject_id, COUNT(id) AS n
          FROM lms_courses
         WHERE grade_id IS NOT NULL
         GROUP BY school_id, academic_year_id, grade_id, subject_id
        HAVING COUNT(id) > 1
    """)).fetchall()

    for grp in dup_groups:
        ids = [r[0] for r in bind.execute(sa.text("""
            SELECT id FROM lms_courses
             WHERE school_id = :s AND academic_year_id = :y
               AND grade_id = :g AND subject_id = :sj
        """), {"s": grp[0], "y": grp[1], "g": grp[2], "sj": grp[3]}).fetchall()]

        # Score each candidate = lessons + assignments + quizzes.
        best_id = None
        best_score = -1
        for cid in ids:
            n = bind.execute(sa.text("""
                SELECT
                  (SELECT COUNT(*) FROM lms_lessons     WHERE course_id = :cid) +
                  (SELECT COUNT(*) FROM lms_assignments WHERE course_id = :cid) +
                  (SELECT COUNT(*) FROM lms_quizzes     WHERE course_id = :cid)
                  AS score
            """), {"cid": cid}).scalar()
            n = int(n or 0)
            if n > best_score:
                best_score = n; best_id = cid

        # Move children of every duplicate to the survivor, then drop
        # the duplicate. We defensively delete the losing course's
        # lms_course_sections row (there's a UNIQUE on (course_id,
        # section_id) — collision unlikely across siblings but tolerated).
        for cid in ids:
            if cid == best_id:
                continue
            for tbl in CHILD_TABLES:
                bind.execute(
                    sa.text(f"UPDATE {tbl} SET course_id = :best WHERE course_id = :cid"),
                    {"best": best_id, "cid": cid},
                )
            # For course_sections: reassign; on conflict (survivor already
            # owns that section), just delete the duplicate row.
            bind.execute(sa.text("""
                DELETE FROM lms_course_sections
                 WHERE course_id = :cid
                   AND section_id IN (
                     SELECT section_id FROM lms_course_sections WHERE course_id = :best
                   )
            """), {"cid": cid, "best": best_id})
            bind.execute(sa.text("""
                UPDATE lms_course_sections SET course_id = :best WHERE course_id = :cid
            """), {"best": best_id, "cid": cid})
            bind.execute(sa.text("DELETE FROM lms_courses WHERE id = :cid"), {"cid": cid})

    # 6) Drop old columns, old unique constraint, and add the new one.
    #
    # Reflect the existing unique constraints so we drop the right name
    # (differs between environments — Alembic's naming convention adds
    # underscores in some cases).
    from sqlalchemy import inspect as sa_inspect
    insp = sa_inspect(bind)
    uc_names = [c["name"] for c in insp.get_unique_constraints("lms_courses")]
    ix_names = {i["name"] for i in insp.get_indexes("lms_courses")}

    with op.batch_alter_table('lms_courses', schema=None) as b:
        for name in uc_names:
            b.drop_constraint(name, type_='unique')
        if b.f('ix_lms_courses_section_id') in ix_names:
            b.drop_index(b.f('ix_lms_courses_section_id'))
        if b.f('ix_lms_courses_teacher_id') in ix_names:
            b.drop_index(b.f('ix_lms_courses_teacher_id'))
        b.drop_column('section_id')
        b.drop_column('teacher_id')
        b.alter_column('grade_id', existing_type=sa.Integer(), nullable=False)
        b.create_unique_constraint(
            'uq_course_year_grade_subject_term',
            ['academic_year_id', 'grade_id', 'subject_id', 'term_id'],
        )


def downgrade():
    """Reversible best-effort — restore section_id/teacher_id as nullable
    columns and back out the join table. Recovering merged data is not
    possible; this is provided to keep the migration formally reversible.
    """
    with op.batch_alter_table('lms_courses', schema=None) as b:
        try:
            b.drop_constraint('uq_course_year_grade_subject_term', type_='unique')
        except Exception:
            pass
        b.add_column(sa.Column('section_id', sa.Integer(), nullable=True))
        b.add_column(sa.Column('teacher_id', sa.Integer(), nullable=True))
        b.create_index(b.f('ix_lms_courses_section_id'), ['section_id'], unique=False)
        b.create_index(b.f('ix_lms_courses_teacher_id'), ['teacher_id'], unique=False)
        b.create_foreign_key('fk_lms_courses_section', 'sections',
                             ['section_id'], ['id'])
        b.create_foreign_key('fk_lms_courses_teacher', 'teachers',
                             ['teacher_id'], ['id'])

    bind = op.get_bind()
    # Fill section_id from the first course_sections row so the app
    # doesn't crash on load — this is a data-lossy best effort.
    bind.execute(sa.text("""
        UPDATE lms_courses SET section_id = (
          SELECT section_id FROM lms_course_sections
           WHERE lms_course_sections.course_id = lms_courses.id
           LIMIT 1
        )
    """))

    op.drop_table('lms_course_sections')

    with op.batch_alter_table('lms_courses', schema=None) as b:
        b.drop_constraint('fk_lms_courses_grade', type_='foreignkey')
        b.drop_constraint('fk_lms_courses_term',  type_='foreignkey')
        b.drop_index(b.f('ix_lms_courses_grade_id'))
        b.drop_index(b.f('ix_lms_courses_term_id'))
        b.drop_column('grade_id')
        b.drop_column('term_id')
        b.alter_column('section_id', existing_type=sa.Integer(), nullable=False)
        b.create_unique_constraint(
            'uq_course_year_section_subject',
            ['academic_year_id', 'section_id', 'subject_id'],
        )
