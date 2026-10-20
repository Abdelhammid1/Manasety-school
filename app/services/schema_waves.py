"""SAAS-019..021 — add school_id to a child table, safely.

Used from Alembic migrations. Pure SQLAlchemy core (no models) so a
later model change can't alter what an applied migration did.

Per table, in order:
  (a) add school_id nullable + index + FK to schools
  (b) backfill from the primary parent:  UPDATE child SET school_id =
      (SELECT school_id FROM parent WHERE parent.id = child.fk)
  (c) verify, then NOT NULL. Fails loudly (table + counts) when a row
      is still NULL (orphan / parent without school) or when any other
      school-owned parent disagrees. Never guesses, never skips.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import sqlalchemy as sa


@dataclass(frozen=True)
class Child:
    table: str
    parent: str            # primary parent table (backfill source)
    fk: str                # child column pointing at parent.id
    # other parents that must agree: ((table, child_column), ...)
    also: tuple[tuple[str, str], ...] = field(default_factory=tuple)


class WaveIntegrityError(RuntimeError):
    pass


def _ix(table):
    return f"ix_{table}_school_id"


def _fk(table):
    return f"fk_{table}_school_id"


def add_school_id(op, child: Child) -> dict:
    bind = op.get_bind()
    t, p, fk = child.table, child.parent, child.fk
    before = bind.execute(sa.text(f"SELECT COUNT(*) FROM {t}")).scalar()

    with op.batch_alter_table(t) as b:
        b.add_column(sa.Column("school_id", sa.Integer(), nullable=True))
        b.create_index(_ix(t), ["school_id"])
        b.create_foreign_key(_fk(t), "schools", ["school_id"], ["id"])

    bind.execute(sa.text(
        f"UPDATE {t} SET school_id = "
        f"(SELECT {p}.school_id FROM {p} WHERE {p}.id = {t}.{fk}) "
        f"WHERE school_id IS NULL"))

    nulls = bind.execute(sa.text(f"SELECT COUNT(*) FROM {t} WHERE school_id IS NULL")).scalar()
    if nulls:
        raise WaveIntegrityError(
            f"{t}: {nulls} row(s) have no school after backfill from {p}.{fk} "
            f"(orphaned or parent without school_id) — fix the data, nothing was guessed.")
    for other, col in child.also:
        bad = bind.execute(sa.text(
            f"SELECT COUNT(*) FROM {t} JOIN {other} o ON o.id = {t}.{col} "
            f"WHERE o.school_id IS NOT NULL AND o.school_id != {t}.school_id")).scalar()
        if bad:
            raise WaveIntegrityError(
                f"{t}: {bad} row(s) link a {p} of one school to a {other} "
                f"(via {col}) of another school.")

    with op.batch_alter_table(t) as b:
        b.alter_column("school_id", existing_type=sa.Integer(), nullable=False)

    after = bind.execute(sa.text(f"SELECT COUNT(*) FROM {t}")).scalar()
    if after != before:
        raise WaveIntegrityError(f"{t}: row count changed {before} -> {after}")
    return {"table": t, "rows": after}


def drop_school_id(op, child: Child) -> None:
    with op.batch_alter_table(child.table) as b:
        b.drop_constraint(_fk(child.table), type_="foreignkey")
        b.drop_index(_ix(child.table))
        b.drop_column("school_id")


def run_wave(op, label: str, children) -> None:
    for ch in children:
        print(f"[{label}] {add_school_id(op, ch)}")
