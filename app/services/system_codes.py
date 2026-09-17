"""Ticket A — hardcoded system-account lookups.

The eight "system accounts" below are guaranteed to exist on every
school by `finance.DEFAULT_ACCOUNT_TREE` + `ensure_default_chart`.
The rest of the codebase looks them up by their fixed code, not by
their (deprecated) `account_role`. The role column stays in the DB —
we just stop exposing it in the UI.

If a school's chart is somehow missing one of these codes at
resolution time (only possible on a corrupted install), the caller
gets a LedgerError-level exception rather than silently posting to
the wrong place.
"""
from typing import Optional

from ..models import Account


# code : (arabic label — for UI-only "system account" chips and error msgs)
SYSTEM_ACCOUNT_CODES = {
    "1110": "الصندوق النقدي — الافتراضي",
    "1160": "سلف الموظفين",
    "1210": "ذمم الطلاب (AR)",
    "2110": "ذمم الموردين (AP)",
    "2210": "رواتب مستحقة",
    "2250": "ضريبة القيمة المضافة المستحقة",
    "3200": "أرباح/خسائر مرحّلة",
    "4910": "خصم إخوة",
}


def get_account_by_code(school_id: int, code: str) -> Optional[Account]:
    """Direct lookup — no fallback, no auto-create at the header level.
    Callers that need lazy-create semantics (student/vendor/employee
    subs) go through `services.subsidiary` which builds on top of this."""
    return Account.query.filter_by(school_id=school_id, code=code).first()


def is_system_account(account: Account) -> bool:
    """Ticket A — the eight system codes are code-locked in the UI
    (name/description remain editable). Everything else is free."""
    return account.code in SYSTEM_ACCOUNT_CODES
