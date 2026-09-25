"""Quiz shuffle/partial-credit + per-attempt shuffle seed.

Tickets P0-7 (shuffle) + P1-10 (partial credit). Adds:
  · lms_quizzes.shuffle_choices        (bool, default False)
  · lms_quizzes.allow_partial_credit   (bool, default False)
  · lms_quiz_attempts.shuffle_seed     (int, nullable)

Idempotent — inspects existing columns first so a retry is a no-op.
"""

from alembic import op
import sqlalchemy as sa


revision = 'v1h3j5l7n9p1'
down_revision = 'u9f1h3j5l7n9'
branch_labels = None
depends_on = None


def _has(bind, table, col):
    insp = sa.inspect(bind)
    return any(c["name"] == col for c in insp.get_columns(table))


def upgrade():
    bind = op.get_bind()
    with op.batch_alter_table("lms_quizzes") as batch:
        if not _has(bind, "lms_quizzes", "shuffle_choices"):
            batch.add_column(sa.Column(
                "shuffle_choices", sa.Boolean(),
                nullable=False, server_default=sa.false(),
            ))
        if not _has(bind, "lms_quizzes", "allow_partial_credit"):
            batch.add_column(sa.Column(
                "allow_partial_credit", sa.Boolean(),
                nullable=False, server_default=sa.false(),
            ))
    with op.batch_alter_table("lms_quiz_attempts") as batch:
        if not _has(bind, "lms_quiz_attempts", "shuffle_seed"):
            batch.add_column(sa.Column(
                "shuffle_seed", sa.Integer(), nullable=True,
            ))


def downgrade():
    with op.batch_alter_table("lms_quiz_attempts") as batch:
        try: batch.drop_column("shuffle_seed")
        except Exception: pass
    with op.batch_alter_table("lms_quizzes") as batch:
        try: batch.drop_column("allow_partial_credit")
        except Exception: pass
        try: batch.drop_column("shuffle_choices")
        except Exception: pass
