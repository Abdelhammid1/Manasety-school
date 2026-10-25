"""Payment methods left on an aggregate account (2026-10-25).

f7a9b1c3d5e7 turned 1120 into an aggregate, but payment methods still
point at it, and post_journal refuses any line on an aggregate — so a
collection / refund through them fails.

For every payment method that isn't deleted and whose account is an
aggregate (is_postable = false): the postable accounts under that account
(any depth, same school) are looked up —
  * exactly one → the method is moved onto it;
  * none or several → nothing changes; the case is written to the log
    (school_id, payment_method_id, reason) to be fixed by hand.
No account is created, no journal line / payment is touched. Accounts are
followed by parent_id inside the method's own school; no school is
assumed to have a 1120. Idempotent: a method already on a postable
account is never looked at again.

Downgrade: a no-op on purpose — pointing a method back at an aggregate
would only break collections again (and the old account is not kept).
"""

import logging

from alembic import op
import sqlalchemy as sa

revision = 'j1e3f5a7b9c1'
down_revision = 'i0d2e4f6a8b0'
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")


def _postable_below(conn, school_id, account_id):
    """Postable accounts under account_id (any depth) in this school."""
    rows = conn.execute(sa.text("SELECT id, parent_id, is_postable FROM accounts WHERE school_id = :s"),
                        {"s": school_id}).all()
    children = {}
    postable = set()
    for aid, pid, is_postable in rows:
        if pid is not None:
            children.setdefault(pid, []).append(aid)
        if is_postable:
            postable.add(aid)
    out, todo, seen = [], list(children.get(account_id, ())), set()
    while todo:
        aid = todo.pop()
        if aid in seen:
            continue
        seen.add(aid)
        if aid in postable:
            out.append(aid)
        todo.extend(children.get(aid, ()))
    return sorted(out)


def upgrade():
    conn = op.get_bind()
    broken = conn.execute(sa.text(
        "SELECT pm.id, pm.school_id, pm.account_id, a.code FROM payment_methods pm "
        "JOIN accounts a ON a.id = pm.account_id AND a.school_id = pm.school_id "
        "WHERE pm.deleted_at IS NULL AND a.is_postable = :f ORDER BY pm.school_id, pm.id"
    ).bindparams(f=False)).all()
    for pm_id, school_id, account_id, code in broken:
        below = _postable_below(conn, school_id, account_id)
        if len(below) == 1:
            conn.execute(sa.text("UPDATE payment_methods SET account_id = :new WHERE id = :pm AND account_id = :old"),
                         {"new": below[0], "pm": pm_id, "old": account_id})
            log.info("payment method moved: school_id=%s payment_method_id=%s from account %s (%s) to %s",
                     school_id, pm_id, account_id, code, below[0])
        else:
            reason = "no postable account under it" if not below else f"{len(below)} postable accounts under it"
            log.warning("payment method needs fixing by hand: school_id=%s payment_method_id=%s account %s (%s): %s",
                        school_id, pm_id, account_id, code, reason)
            print(f"[payment-methods] fix by hand: school_id={school_id} payment_method_id={pm_id} "
                  f"account={code}: {reason}")


def downgrade():
    pass       # see the docstring: never point a method back at an aggregate
