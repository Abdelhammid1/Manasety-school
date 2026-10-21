"""SAAS-032 (2026-10-21) — full school control from the console.

- schools.blocked_message (optional text on the blocked page)
- school_slug_history (old slugs: 301 for 90 days, reserved forever)
- platform_school_notes, school_contacts, school_tags,
  platform_announcements (platform tables; schools never see them)
No data changes.
"""

from alembic import op
import sqlalchemy as sa

revision = 'v3p7r9t1v3x5'
down_revision = 'u1n5p7r9t1v3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("schools") as b:
        b.add_column(sa.Column("blocked_message", sa.Text()))
    op.create_table(
        "school_slug_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("old_slug", sa.String(63), nullable=False, unique=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("changed_by_platform_user_id", sa.Integer(), sa.ForeignKey("platform_users.id")),
        sa.Column("redirect_until", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_school_slug_history_school_id", "school_slug_history", ["school_id"])
    op.create_table(
        "platform_school_notes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("author_platform_user_id", sa.Integer(), sa.ForeignKey("platform_users.id")),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_platform_school_notes_school_id", "platform_school_notes", ["school_id"])
    op.create_table(
        "school_contacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("role", sa.String(64)),
        sa.Column("phone", sa.String(32)),
        sa.Column("email", sa.String(128)),
        sa.Column("is_billing_contact", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_school_contacts_school_id", "school_contacts", ["school_id"])
    op.create_table(
        "school_tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("tag", sa.String(40), nullable=False),
        sa.UniqueConstraint("school_id", "tag", name="uq_school_tag"),
    )
    op.create_index("ix_school_tags_school_id", "school_tags", ["school_id"])
    op.create_table(
        "platform_announcements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_ar", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False, server_default="info"),
        sa.Column("target_school_ids", sa.JSON()),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_platform_user_id", sa.Integer(), sa.ForeignKey("platform_users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("severity IN ('info','warning')", name="ck_platform_announcements_severity"),
    )


def downgrade():
    op.drop_table("platform_announcements")
    op.drop_table("school_tags")
    op.drop_table("school_contacts")
    op.drop_table("platform_school_notes")
    op.drop_table("school_slug_history")
    with op.batch_alter_table("schools") as b:
        b.drop_column("blocked_message")
