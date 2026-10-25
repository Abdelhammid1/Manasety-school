"""Features inside modules (2026-10-25) — per-school page / ability overrides.

  * school_feature_overrides: (school, feature_key) → enabled, with reason
    and who changed it. Same shape as school_module_overrides.
  * Every school that exists now keeps what it has: for each feature that
    is OFF by default for new schools, it gets an "enabled" row with the
    reason «الوضع قبل هذه التذكرة». The keys are written out here (no
    import from the service). Idempotent: a school that already has a row
    for the key is skipped.

Downgrade drops the table.
"""

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = 'g8b0c2d4e6f8'
down_revision = 'f7a9b1c3d5e7'
branch_labels = None
depends_on = None

# features with default_on=False at the time of this migration
DEFAULT_OFF = ("lms.ai",)
REASON = "الوضع قبل هذه التذكرة"


def upgrade():
    bind = op.get_bind()
    if "school_feature_overrides" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "school_feature_overrides",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False),
            sa.Column("feature_key", sa.String(64), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("updated_by_platform_user_id", sa.Integer(), sa.ForeignKey("platform_users.id")),
            sa.Column("updated_at", sa.DateTime(timezone=True)),
            sa.UniqueConstraint("school_id", "feature_key", name="uq_school_feature_override"),
        )
        op.create_index("ix_school_feature_overrides_school_id", "school_feature_overrides", ["school_id"])
    now = datetime.now(timezone.utc)
    for key in DEFAULT_OFF:
        bind.execute(sa.text(
            "INSERT INTO school_feature_overrides (school_id, feature_key, enabled, reason, updated_at) "
            "SELECT s.id, :key, :on, :reason, :now FROM schools s "
            "WHERE NOT EXISTS (SELECT 1 FROM school_feature_overrides o "
            "                  WHERE o.school_id = s.id AND o.feature_key = :key)"
        ).bindparams(key=key, on=True, reason=REASON, now=now))


def downgrade():
    op.drop_index("ix_school_feature_overrides_school_id", table_name="school_feature_overrides")
    op.drop_table("school_feature_overrides")
