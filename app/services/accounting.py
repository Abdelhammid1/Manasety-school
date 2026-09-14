"""Double-entry posting helper (T-8.1).

Every financial operation (invoice issue, payment, expense, salary)
calls post_journal(...) which builds a balanced JournalEntry. The helper
enforces debit==credit and writes it as one atomic record.
"""
from datetime import date
from decimal import Decimal
from typing import Iterable, Tuple, Optional

from flask_login import current_user

from ..extensions import db
from ..models import JournalEntry, JournalLine


def post_journal(
    school_id: int,
    entry_date: date,
    description: str,
    lines: Iterable[Tuple[int, Decimal, Decimal, Optional[str]]],
    reference: Optional[str] = None,
    related_kind: Optional[str] = None,
    related_id: Optional[int] = None,
) -> JournalEntry:
    """Lines: iterable of (account_id, debit, credit, line_description)."""
    lines = list(lines)
    total_d = sum((Decimal(str(d)) for _, d, _, _ in lines), Decimal(0))
    total_c = sum((Decimal(str(c)) for _, _, c, _ in lines), Decimal(0))
    if total_d != total_c:
        raise ValueError(f"Unbalanced journal entry: DR {total_d} != CR {total_c}")
    if total_d == 0:
        raise ValueError("Cannot post an empty journal entry")

    entry = JournalEntry(
        school_id=school_id,
        entry_date=entry_date,
        description=description,
        reference=reference,
        related_kind=related_kind,
        related_id=related_id,
        created_by_user_id=getattr(current_user, "id", None),
    )
    db.session.add(entry)
    db.session.flush()

    for account_id, debit, credit, line_desc in lines:
        db.session.add(JournalLine(
            entry_id=entry.id,
            account_id=account_id,
            debit=Decimal(str(debit)),
            credit=Decimal(str(credit)),
            description=line_desc,
        ))
    db.session.flush()
    return entry
