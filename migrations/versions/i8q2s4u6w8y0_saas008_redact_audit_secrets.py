"""SAAS-008 (2026-10-20) — scrub secrets already written to audit_logs.

Before SAAS-008, services/audit.py serialised every column of watched
models, so User create/update/delete rows carry `password_hash` in
`new_value` / `old_value`. This rewrites those values to "[REDACTED]"
in place. No row is deleted and the row count is unchanged.

This is a deliberate, approved exception to audit_logs being
append-only (approval recorded in the PR).

The matching rules are a frozen copy of services.audit.redact() so a
later change to the live code cannot change what this migration did.

downgrade() is a documented no-op: the original hashes are gone and
cannot be restored (restore from the pre-migration backup if needed).
"""

import re

from alembic import op
import sqlalchemy as sa


revision = 'i8q2s4u6w8y0'
down_revision = 'h5n9p1r3t5v7'
branch_labels = None
depends_on = None


REDACTED = "[REDACTED]"
_SECRET_NAMES = frozenset({"password_hash", "smtp_password_encrypted"})
_SECRET_NAME_RE = re.compile(r"password|(?:^|_)(?:token|secret|key)$", re.IGNORECASE)
_BCRYPT_RE = re.compile(r"^\$2[abxy]\$\d{2}\$")
_BATCH = 1000


def _is_secret(name):
    return isinstance(name, str) and (
        name.lower() in _SECRET_NAMES or bool(_SECRET_NAME_RE.search(name)))


def _redact(value):
    if isinstance(value, dict):
        return {k: (REDACTED if _is_secret(k) else _redact(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    if isinstance(value, str) and _BCRYPT_RE.match(value):
        return REDACTED
    return value


audit_logs = sa.table(
    "audit_logs",
    sa.column("id", sa.Integer),
    sa.column("old_value", sa.JSON),
    sa.column("new_value", sa.JSON),
)


def upgrade():
    bind = op.get_bind()
    total = bind.execute(sa.select(sa.func.count()).select_from(audit_logs)).scalar()
    changed = 0
    last_id = 0
    while True:
        rows = bind.execute(
            sa.select(audit_logs.c.id, audit_logs.c.old_value, audit_logs.c.new_value)
            .where(audit_logs.c.id > last_id)
            .order_by(audit_logs.c.id)
            .limit(_BATCH)
        ).all()
        if not rows:
            break
        for rid, old, new in rows:
            r_old, r_new = _redact(old), _redact(new)
            if r_old != old or r_new != new:
                bind.execute(
                    audit_logs.update().where(audit_logs.c.id == rid)
                    .values(old_value=r_old, new_value=r_new))
                changed += 1
        last_id = rows[-1][0]
    after = bind.execute(sa.select(sa.func.count()).select_from(audit_logs)).scalar()
    if after != total:
        raise RuntimeError(f"audit_logs row count changed {total} -> {after}")
    print(f"[SAAS-008] audit_logs rows={total} redacted={changed}")


def downgrade():
    # Intentional no-op: redacted secrets cannot be restored.
    pass
