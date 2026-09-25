"""Bank question — real FK on axis_id / indicator_id.

Ticket P0-5. Columns already existed as plain integers; this migration
adds the missing `SET NULL` FK constraints so orphan tags can't leak
across schools and a delete of the parent taxonomy row nulls out the
back-reference cleanly. Idempotent — inspects the existing constraints
before creating new ones so a retry is a no-op.
"""

from alembic import op
import sqlalchemy as sa


revision = 'u9f1h3j5l7n9'
down_revision = 't7e9f1g3h5i7'
branch_labels = None
depends_on = None


def _has_fk(bind, table, name):
    insp = sa.inspect(bind)
    return any(fk.get("name") == name for fk in insp.get_foreign_keys(table))


def upgrade():
    bind = op.get_bind()
    with op.batch_alter_table("lms_bank_questions") as batch:
        if not _has_fk(bind, "lms_bank_questions", "fk_bankq_axis"):
            batch.create_foreign_key(
                "fk_bankq_axis", "axes", ["axis_id"], ["id"],
                ondelete="SET NULL",
            )
        if not _has_fk(bind, "lms_bank_questions", "fk_bankq_indicator"):
            batch.create_foreign_key(
                "fk_bankq_indicator", "indicators", ["indicator_id"], ["id"],
                ondelete="SET NULL",
            )


def downgrade():
    with op.batch_alter_table("lms_bank_questions") as batch:
        try:
            batch.drop_constraint("fk_bankq_indicator", type_="foreignkey")
        except Exception:
            pass
        try:
            batch.drop_constraint("fk_bankq_axis", type_="foreignkey")
        except Exception:
            pass
