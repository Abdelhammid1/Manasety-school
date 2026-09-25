"""Ticket #1 (2026-09-25) — backfill the `student` role.

Before this ticket, `seeds/seed.py` did not create a `student` role
(only `admin, student_affairs, teacher, accountant, warehouse,
parent`). Now that every Student creation calls
`provision_user(kind="student")` which resolves the role by name,
a school without that row is completely blocked from adding new
students. Insert it for every school that does not already have
one — idempotent per-school.

Runs after d7f1h3j5l7n9 which set is_system=True on the existing
teacher/parent/student rows.
"""

from alembic import op
import sqlalchemy as sa


revision = 'e9h3j5l7n9p1'
down_revision = 'd7f1h3j5l7n9'
branch_labels = None
depends_on = None


STUDENT_ROLE_NAME = "student"
STUDENT_ROLE_NAME_AR = "طالب"
STUDENT_ROLE_PERMS = {"portal": ["view"]}


def upgrade():
    bind = op.get_bind()

    # Lightweight table def so the JSON column is bound through
    # SQLAlchemy's type system — works the same on SQLite (TEXT) and
    # Postgres (JSON/JSONB) without hand-rolled ::json casts.
    roles = sa.table(
        "roles",
        sa.column("school_id",  sa.Integer),
        sa.column("name",       sa.String),
        sa.column("name_ar",    sa.String),
        sa.column("is_system",  sa.Boolean),
        sa.column("permissions", sa.JSON),
    )

    schools = bind.execute(sa.text("SELECT id FROM schools")).fetchall()
    for (school_id,) in schools:
        exists = bind.execute(sa.text(
            "SELECT 1 FROM roles WHERE school_id = :sid AND name = :n"
        ), {"sid": school_id, "n": STUDENT_ROLE_NAME}).first()
        if exists:
            continue
        bind.execute(roles.insert().values(
            school_id=school_id,
            name=STUDENT_ROLE_NAME,
            name_ar=STUDENT_ROLE_NAME_AR,
            is_system=True,
            permissions=STUDENT_ROLE_PERMS,
        ))


def downgrade():
    # Do not remove — deleting a role that seeded users now depend on
    # would strand orphan User.role_id references.
    pass
