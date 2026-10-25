"""The school's banks and bank accounts: everything under 1120 in its chart.

    1100 النقدية
    └── 1120 البنوك (aggregate)
        ├── 1120-01 بنك CIB (aggregate)
        │   ├── 4501237789          (postable — the real account number)
        │   └── 4501237790
        └── 1120-02 بنك الراجحي (aggregate)
            └── SA0380000000608010167519

A bank account is known by its place in the tree (parent_id), never by its
code: the code is the real account number, so it can start with anything —
and an unrelated account that happens to start with 112 is not a bank.
1120 is found by its code inside the school (never by id). Cash stays
"postable 111x"; the other 11xx accounts (1130 …) keep their old place.
"""

from __future__ import annotations

import re

from ..extensions import db
from ..models import Account

BANKS_ROOT = "1120"
#: a bank's real account number / IBAN: letters, digits and "-", no spaces
ACCOUNT_NUMBER_RE = re.compile(r"^[A-Z0-9-]{1,30}$")
CODE_MAX = 30


def normalize_account_number(raw) -> str | None:
    """The code of an account under a bank: strip + upper; None if invalid."""
    v = (raw or "").strip().upper()
    return v if ACCOUNT_NUMBER_RE.match(v) else None


def banks_root(school_id: int):
    return Account.query.filter_by(school_id=school_id, code=BANKS_ROOT).first()


def subtree_ids(school_id: int) -> set[int]:
    """1120 and every account below it (any depth), for this school."""
    root = banks_root(school_id)
    if root is None:
        return set()
    children: dict[int, list[int]] = {}
    for aid, pid in (db.session.query(Account.id, Account.parent_id)
                     .filter(Account.school_id == school_id, Account.parent_id.isnot(None)).all()):
        children.setdefault(pid, []).append(aid)
    out, todo = set(), [root.id]
    while todo:
        aid = todo.pop()
        if aid in out:                      # a cycle in bad data must not loop forever
            continue
        out.add(aid)
        todo.extend(children.get(aid, ()))
    return out


def bank_accounts(school_id: int, *, active_only: bool = False) -> list[Account]:
    """The postable accounts under 1120 (1120 itself while it is still
    postable, before the migration), by code."""
    ids = subtree_ids(school_id)
    if not ids:
        return []
    q = Account.query.filter(Account.school_id == school_id, Account.id.in_(ids),
                             Account.is_postable.is_(True))
    if active_only:
        q = q.filter(Account.is_active.is_(True))
    return q.order_by(Account.code).all()


def cash_accounts(school_id: int, *, active_only: bool = False) -> list[Account]:
    """Postable 111x asset accounts — outside the bank tree."""
    banks = subtree_ids(school_id)
    q = Account.query.filter(Account.school_id == school_id, Account.is_postable.is_(True),
                             Account.type == "asset", Account.code.startswith("111"))
    if active_only:
        q = q.filter(Account.is_active.is_(True))
    return [a for a in q.order_by(Account.code).all() if a.id not in banks]


def cash_and_bank_ids(school_id: int, *, active_only: bool = False) -> set[int]:
    """What used to be "postable 11xx": every postable 11xx account outside
    the bank tree, plus the bank accounts (whatever their number) — each once."""
    banks = subtree_ids(school_id)
    q = db.session.query(Account.id).filter(Account.school_id == school_id,
                                            Account.is_postable.is_(True),
                                            Account.code.startswith("11"))
    if active_only:
        q = q.filter(Account.is_active.is_(True))
    out = {aid for (aid,) in q.all() if aid not in banks}
    return out | {a.id for a in bank_accounts(school_id, active_only=active_only)}


def position(school_id: int, parent) -> str:
    """Where a new child of `parent` sits: "bank" (directly under 1120 — a
    bank's name), "bank_account" (under a bank — a real account number) or
    "other" (the rest of the chart, unchanged rules)."""
    if parent is None:
        return "other"
    if parent.code == BANKS_ROOT:
        return "bank"
    grand = db.session.get(Account, parent.parent_id) if parent.parent_id else None
    if grand is not None and grand.school_id == school_id and grand.code == BANKS_ROOT:
        return "bank_account"
    return "other"


def next_bank_code(school_id: int) -> str:
    """1120-NN: the first unused two-digit number."""
    used = {c for (c,) in db.session.query(Account.code)
            .filter(Account.school_id == school_id, Account.code.like(f"{BANKS_ROOT}-%")).all()}
    for n in range(1, 100):
        code = f"{BANKS_ROOT}-{n:02d}"
        if code not in used:
            return code
    return ""
