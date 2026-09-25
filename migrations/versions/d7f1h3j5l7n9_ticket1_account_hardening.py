"""Ticket #1 (2026-09-25) — account-management hardening.

Two changes, both idempotent and both safe against existing data:

1. `students.user_id` gets a UNIQUE index — no Student may share a
   User row with another. If duplicate values already exist the
   migration refuses rather than silently drop rows, so operators
   can decide how to reconcile.

2. The system roles `teacher`, `parent`, `student` are pinned with
   `is_system=True` so `role_delete` refuses to remove them (they
   are looked up by name by `provision_user`). Any school that
   didn't already have that flag set is patched in place.
"""

from alembic import op
import sqlalchemy as sa


revision = 'd7f1h3j5l7n9'
down_revision = 'c5v7x9z1c3e5'
branch_labels = None
depends_on = None


def _has_index(bind, table: str, name: str) -> bool:
    insp = sa.inspect(bind)
    return any(ix["name"] == name for ix in insp.get_indexes(table))


def upgrade():
    bind = op.get_bind()

    # ── 1. UNIQUE(students.user_id) ────────────────────────────────
    # Refuse the migration if duplicates exist so operators are
    # forced to reconcile before the constraint locks it in.
    dup = bind.execute(sa.text("""
        SELECT user_id, COUNT(*) AS n
          FROM students
         WHERE user_id IS NOT NULL
      GROUP BY user_id
        HAVING COUNT(*) > 1
    """)).fetchall()
    if dup:
        raise RuntimeError(
            "students.user_id has duplicate values — clean up before "
            "applying the unique constraint: " + repr(dup)
        )

    if not _has_index(bind, "students", "uq_students_user_id"):
        op.create_index(
            "uq_students_user_id", "students", ["user_id"], unique=True,
        )

    # ── 2. is_system=True for teacher/parent/student roles ─────────
    bind.execute(sa.text("""
        UPDATE roles
           SET is_system = 1
         WHERE name IN ('teacher', 'parent', 'student')
           AND (is_system IS NULL OR is_system = 0)
    """))


def downgrade():
    try:
        op.drop_index("uq_students_user_id", table_name="students")
    except Exception:
        pass
    # Do NOT undo the is_system flip on teacher/parent/student — the
    # rollback would let admins delete critical seeded roles.
