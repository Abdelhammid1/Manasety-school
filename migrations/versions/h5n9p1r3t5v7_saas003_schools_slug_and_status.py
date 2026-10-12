"""SAAS-003 (2026-10-12) — tenant identity on `schools`.

Adds two columns:

* `slug`   — the subdomain, unique, [a-z0-9-] with no leading/trailing
             hyphen, max 63 chars.
* `status` — lifecycle: one of {active, suspended, archived}.

Three-step pattern (safe on a table that already has rows):
  1. add both columns nullable
  2. backfill — if there's exactly one school it becomes `demo/active`;
     if there are many rows the migration FAILS LOUDLY instead of
     guessing. Fresh schools (zero rows) are a no-op for the backfill
     and the NOT NULL/unique add still runs.
  3. tighten: NOT NULL, unique index on slug, CHECK on slug regex,
     CHECK on status enum.

SQLite-safe: constraints that need ALTER are gated by dialect so a
Postgres deploy gets the real CHECK while SQLite dev DBs still move
forward (SQLite only enforces CHECK when the table is created
through batch_alter_table; adding one post-hoc is a no-op there).
"""

from alembic import op
import sqlalchemy as sa


revision = 'h5n9p1r3t5v7'
down_revision = 'g3l7n9p1r3t5'
branch_labels = None
depends_on = None


def _has(bind, table: str, col: str) -> bool:
    insp = sa.inspect(bind)
    return any(c["name"] == col for c in insp.get_columns(table))


def _has_index(bind, table: str, name: str) -> bool:
    insp = sa.inspect(bind)
    return any(ix["name"] == name for ix in insp.get_indexes(table))


SLUG_REGEX = r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$"


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    # ── 1. Add nullable columns ───────────────────────────────────
    if not _has(bind, "schools", "slug"):
        op.add_column("schools",
            sa.Column("slug", sa.String(63), nullable=True))
    if not _has(bind, "schools", "status"):
        op.add_column("schools",
            sa.Column("status", sa.String(16), nullable=True,
                      server_default="active"))

    # ── 2. Backfill ───────────────────────────────────────────────
    row_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM schools")
    ).scalar() or 0

    if row_count == 1:
        bind.execute(sa.text(
            "UPDATE schools SET slug = 'demo', status = 'active' "
            "WHERE slug IS NULL OR status IS NULL"
        ))
    elif row_count > 1:
        # Refuse — operator must assign slugs explicitly before
        # tightening uniqueness.
        unresolved = bind.execute(sa.text(
            "SELECT COUNT(*) FROM schools "
            "WHERE slug IS NULL OR status IS NULL"
        )).scalar() or 0
        if unresolved > 0:
            raise RuntimeError(
                f"schools has {row_count} rows and {unresolved} of them "
                "lack a slug/status. Set them explicitly (one must be "
                "'demo') and re-run the migration — refusing to guess."
            )

    # ── 3. Tighten: NOT NULL + unique + CHECK ─────────────────────
    # Postgres path — all three constraints.
    if not is_sqlite:
        op.alter_column("schools", "slug", nullable=False,
                        existing_type=sa.String(63))
        op.alter_column("schools", "status", nullable=False,
                        existing_type=sa.String(16),
                        existing_server_default="active")
        op.create_check_constraint(
            "ck_schools_slug_format", "schools",
            f"slug ~ '{SLUG_REGEX}'",
        )
        op.create_check_constraint(
            "ck_schools_status_enum", "schools",
            "status IN ('active','suspended','archived')",
        )

    # Unique index on slug — both dialects. Partial on NOT NULL so
    # the index can be added before NOT NULL on dialects where that
    # order matters (SQLite). Alembic translates `unique=True` to a
    # proper UNIQUE index in both.
    if not _has_index(bind, "schools", "uq_schools_slug"):
        op.create_index(
            "uq_schools_slug", "schools", ["slug"], unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    try:
        op.drop_index("uq_schools_slug", table_name="schools")
    except Exception:
        pass

    if not is_sqlite:
        for name in ("ck_schools_slug_format", "ck_schools_status_enum"):
            try:
                op.drop_constraint(name, "schools", type_="check")
            except Exception:
                pass

    for col in ("status", "slug"):
        try:
            op.drop_column("schools", col)
        except Exception:
            pass
