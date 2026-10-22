"""SAAS-048 (2026-10-22) — school_restores (preview -> confirm -> run, with
undo), and school_backups.kind ("restore_point" = the automatic copy taken
before a restore, never pruned by retention).
"""

from alembic import op
import sqlalchemy as sa

revision = 'b3c5d7e9f1a3'
down_revision = 'a2b4c6d8e0f2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("school_backups") as b:
        b.add_column(sa.Column("kind", sa.String(16), nullable=False, server_default="manual"))
    op.create_table(
        "school_restores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending_preview"),
        sa.Column("mode", sa.String(16), nullable=False, server_default="replace"),
        sa.Column("modules", sa.JSON()),
        sa.Column("source_backup_id", sa.Integer(),
                  sa.ForeignKey("school_backups.id", ondelete="SET NULL")),
        sa.Column("package_file", sa.String(255)),
        sa.Column("preview", sa.JSON()),
        sa.Column("result", sa.JSON()),
        sa.Column("error", sa.String(255)),
        sa.Column("restore_point_backup_id", sa.Integer(),
                  sa.ForeignKey("school_backups.id", ondelete="SET NULL")),
        sa.Column("undo_of_id", sa.Integer(), sa.ForeignKey("school_restores.id", ondelete="SET NULL")),
        sa.Column("requested_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("platform_user_id", sa.Integer(),
                  sa.ForeignKey("platform_users.id", ondelete="SET NULL")),
        sa.Column("reason", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('pending_preview','previewing','previewed','confirmed','running',"
            "'succeeded','failed')", name="ck_school_restores_status"),
        sa.CheckConstraint("mode IN ('replace','add_missing')", name="ck_school_restores_mode"),
    )
    op.create_index("ix_school_restores_school_id", "school_restores", ["school_id"])
    op.create_index("ix_school_restores_status", "school_restores", ["status"])


def downgrade():
    op.drop_index("ix_school_restores_status", table_name="school_restores")
    op.drop_index("ix_school_restores_school_id", table_name="school_restores")
    op.drop_table("school_restores")
    with op.batch_alter_table("school_backups") as b:
        b.drop_column("kind")
