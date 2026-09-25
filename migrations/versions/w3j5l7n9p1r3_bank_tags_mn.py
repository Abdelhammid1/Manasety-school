"""Bank tags — unified M:N taxonomy (ticket P1-8).

Creates `lms_bank_tags` (school-scoped, unique name per school) and
`lms_bank_question_tags` (assoc). Backfills from the legacy
`lms_bank_questions.tags` comma-string, folding case so "Algebra",
"algebra" and "  algebra " collapse to a single row per school.

The legacy `tags` column is left in place — writes now dual-write both
sides so old exports keep working. A later migration can drop it.

Idempotent: re-runs on an already-migrated DB are a no-op.
"""

from alembic import op
import sqlalchemy as sa


revision = 'w3j5l7n9p1r3'
down_revision = 'v1h3j5l7n9p1'
branch_labels = None
depends_on = None


def _has_table(bind, name):
    return sa.inspect(bind).has_table(name)


def upgrade():
    bind = op.get_bind()

    if not _has_table(bind, "lms_bank_tags"):
        op.create_table(
            "lms_bank_tags",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("school_id", sa.Integer(),
                      sa.ForeignKey("schools.id"),
                      nullable=False, index=True),
            sa.Column("name", sa.String(80), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now()),
            sa.UniqueConstraint("school_id", "name",
                                name="uq_bank_tags_school_name"),
        )

    if not _has_table(bind, "lms_bank_question_tags"):
        op.create_table(
            "lms_bank_question_tags",
            sa.Column("question_id", sa.Integer(),
                      sa.ForeignKey("lms_bank_questions.id",
                                    ondelete="CASCADE"),
                      primary_key=True),
            sa.Column("tag_id", sa.Integer(),
                      sa.ForeignKey("lms_bank_tags.id",
                                    ondelete="CASCADE"),
                      primary_key=True),
        )

    # Backfill from the legacy comma-string. Skips rows where the
    # target assoc row already exists (retry safety).
    rows = bind.execute(
        sa.text(
            "SELECT id, school_id, COALESCE(tags,'') AS tags "
            "FROM lms_bank_questions WHERE COALESCE(tags,'') <> ''"
        )
    ).fetchall()
    tag_cache = {}  # (school_id, name_casefold) -> tag_id
    for qid, school_id, raw in rows:
        seen = set()
        for piece in str(raw).split(","):
            name = piece.strip()
            if not name:
                continue
            key = (school_id, name.casefold())
            if key in seen:
                continue
            seen.add(key)
            tag_id = tag_cache.get(key)
            if tag_id is None:
                row = bind.execute(
                    sa.text(
                        "SELECT id FROM lms_bank_tags "
                        "WHERE school_id = :sid AND lower(name) = :n LIMIT 1"
                    ),
                    {"sid": school_id, "n": name.casefold()},
                ).fetchone()
                if row:
                    tag_id = row[0]
                else:
                    res = bind.execute(
                        sa.text(
                            "INSERT INTO lms_bank_tags (school_id, name) "
                            "VALUES (:sid, :n) RETURNING id"
                        ),
                        {"sid": school_id, "n": name},
                    )
                    tag_id = res.fetchone()[0]
                tag_cache[key] = tag_id
            # Insert-or-ignore into assoc.
            bind.execute(
                sa.text(
                    "INSERT INTO lms_bank_question_tags (question_id, tag_id) "
                    "VALUES (:q, :t) ON CONFLICT DO NOTHING"
                ),
                {"q": qid, "t": tag_id},
            )


def downgrade():
    op.drop_table("lms_bank_question_tags")
    op.drop_table("lms_bank_tags")
