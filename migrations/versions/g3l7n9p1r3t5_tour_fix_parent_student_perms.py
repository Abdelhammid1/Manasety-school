"""Playwright-tour fix (2026-10-02) — remediate perms data drift.

Three fixes rolled into one data migration:

1. Strip `students.view` from parent and student roles — a parent
   or student with that perm could list every student in the
   school from /students and read their PII.

2. Grant `lms.view/add/edit` to the `teacher` role on every school
   that doesn't already have it. The lms module was never seeded
   so teachers couldn't open the bank, quizzes or assignments.

3. Grant the full `lms` perm to the `admin` role on every school
   that uses the explicit permissions dict (the `admin` demo
   seed stored every module explicitly rather than carrying a
   wildcard, so new modules don't auto-flow in).

All three are idempotent — a second run finds no rows to update.
"""

import json
from alembic import op
import sqlalchemy as sa


revision = 'g3l7n9p1r3t5'
down_revision = 'f1j5l7n9p1r3'
branch_labels = None
depends_on = None


def _decode_perms(raw) -> dict:
    """SQLAlchemy's JSON type usually decodes for us, but a raw text
    column on SQLite comes back as str — handle both."""
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode()
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return dict(raw or {})


def upgrade():
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, name, permissions FROM roles "
        "WHERE name IN ('parent','student','teacher','admin')"
    )).fetchall()

    for role_id, name, perms_raw in rows:
        perms = _decode_perms(perms_raw)
        changed = False

        if name in ("parent", "student"):
            # Fix 1 — strip students.* entirely from parent / student.
            if "students" in perms:
                del perms["students"]
                changed = True
            # Ensure portal.view is granted — the one perm both
            # roles actually need.
            if "portal" not in perms:
                perms["portal"] = ["view"]
                changed = True
            elif "view" not in perms["portal"]:
                perms["portal"] = sorted(set(perms["portal"]) | {"view"})
                changed = True

        if name == "teacher":
            # Fix 2 — add lms view/add/edit for teachers.
            want = {"view", "add", "edit"}
            cur = set(perms.get("lms") or [])
            if not want.issubset(cur):
                perms["lms"] = sorted(cur | want)
                changed = True

        if name == "admin":
            # Fix 3 — ensure admin has the full lms perm (its
            # permissions dict was stored explicitly so a new
            # module doesn't auto-flow in).
            want = {"view", "add", "edit", "delete"}
            cur = set(perms.get("lms") or [])
            if not want.issubset(cur):
                perms["lms"] = sorted(cur | want)
                changed = True

        if changed:
            bind.execute(
                sa.text("UPDATE roles SET permissions = :p WHERE id = :i"),
                {"p": json.dumps(perms), "i": role_id},
            )


def downgrade():
    # Intentional no-op: restoring the leaky permission would
    # re-open the PII hole. If a reinstall of the old behaviour is
    # ever needed, write a new migration explicitly.
    pass
