"""Subsidiary-ledger helpers — one sub-account per party.

Mirrors Marsoud's `subsidiary.py` design: instead of every invoice
posting against a single "1210 ذمم الطلاب" leaf, we treat 1210 as a
header (is_postable=False) and create one child leaf per student the
first time we need it (lazy creation).  Same idea for 2210 with
employees.

Sub-account codes follow the pattern <parent_code>-<6-digit-serial>
(e.g. `1210-000017`).  Serials are per-(school, parent) so different
schools can't collide with each other.  Numbers are never reused —
even after a party is deleted the counter walks forward.
"""
from typing import Optional

from ..extensions import db
from ..models import Account, Student, Vendor
from ..models.hr import Employee


# Header (aggregate) codes we lazily create when a school is missing
# them entirely. Marsoud calls this `_lazy_create_known_header`.
_KNOWN_HEADERS = {
    # code : (name, type, parent_code)
    "1210": ("ذمم الطلاب (AR)", "asset",     "1200"),
    "2110": ("ذمم الموردين (AP)", "liability", "2100"),
    "2210": ("رواتب مستحقة",    "liability", "2200"),
}


def _lazy_create_known_header(school_id: int, code: str) -> Optional[Account]:
    """If a well-known header code is missing on a school, self-heal by
    creating it as an aggregate row. This never happens on a healthy
    install; it's protection against half-migrated legacy data.
    """
    if code not in _KNOWN_HEADERS:
        return None
    row = Account.query.filter_by(school_id=school_id, code=code).first()
    if row is not None:
        return row
    name, type_, parent_code = _KNOWN_HEADERS[code]
    parent_id = None
    if parent_code:
        parent = Account.query.filter_by(school_id=school_id, code=parent_code).first()
        parent_id = parent.id if parent else None
    row = Account(
        school_id=school_id, code=code, name=name, type=type_,
        parent_id=parent_id, is_postable=False, is_system=True,
    )
    db.session.add(row); db.session.flush()
    return row


def create_party_subaccount(
    school_id: int, parent_code: str, party_name: str,
) -> Account:
    """Create a new sub-account under `parent_code` for a specific party
    (student / employee). Never reuses a serial: pulls MAX(existing) + 1.
    """
    parent = Account.query.filter_by(school_id=school_id, code=parent_code).first()
    if parent is None:
        parent = _lazy_create_known_header(school_id, parent_code)
    if parent is None:
        raise RuntimeError(
            f"لا يوجد حساب أب برمز {parent_code} في دليل حسابات المدرسة."
        )

    # Same-shape prefix so all children read as siblings in the tree.
    prefix = f"{parent_code}-"
    existing = (
        db.session.query(Account.code)
        .filter(Account.school_id == school_id,
                Account.code.like(f"{prefix}%"))
        .all()
    )
    max_serial = 0
    for (code,) in existing:
        try:
            n = int(code[len(prefix):])
        except (ValueError, TypeError):
            continue
        if n > max_serial:
            max_serial = n
    new_code = f"{prefix}{max_serial + 1:06d}"
    child = Account(
        school_id=school_id, code=new_code, name=party_name,
        type=parent.type, parent_id=parent.id,
        is_postable=True, is_system=True,
    )
    db.session.add(child); db.session.flush()
    # Ticket "Header Accounts is_postable=False" — the moment a parent
    # code (1210 / 2110 / 2210 …) gets its first child, any direct-post
    # against that parent becomes wrong: aggregate roll-up now happens
    # via Account.balance's `not self.is_postable and self.children`
    # branch. Idempotent — we only flip when the flag is still True.
    if parent.is_postable:
        parent.is_postable = False
        db.session.flush()
    return child


def ensure_student_account(student: Student) -> Account:
    """Idempotent — returns the student's existing AR sub-account or
    lazily creates one under 1210. First call also self-heals 1210 if
    the header row is missing on a school."""
    if student.ar_account_id:
        row = db.session.get(Account, student.ar_account_id)
        if row is not None:
            return row
    row = create_party_subaccount(
        student.school_id, "1210",
        f"{student.full_name} ({student.permanent_code})",
    )
    student.ar_account_id = row.id
    db.session.flush()
    return row


def ensure_employee_account(employee: Employee) -> Account:
    """Idempotent — same behaviour under 2210 for salary-payable."""
    if employee.ap_account_id:
        row = db.session.get(Account, employee.ap_account_id)
        if row is not None:
            return row
    row = create_party_subaccount(
        employee.school_id, "2210",
        f"{employee.full_name} — راتب مستحق",
    )
    employee.ap_account_id = row.id
    db.session.flush()
    return row


def ensure_vendor_account(vendor: Vendor) -> Account:
    """Ticket "Additional 7" — same lazy pattern under 2110 (AP) for
    vendors. `ap_default` still points at the header, so if an expense
    is booked without picking a vendor we fall back to the header —
    but if a vendor is chosen we route to their sub-account instead."""
    if vendor.ap_account_id:
        row = db.session.get(Account, vendor.ap_account_id)
        if row is not None:
            return row
    row = create_party_subaccount(
        vendor.school_id, "2110", f"{vendor.name} — مورد",
    )
    vendor.ap_account_id = row.id
    db.session.flush()
    return row


def party_ar_account(invoice) -> Account:
    """Shortcut used by invoice-posting code — resolves the student
    behind an invoice, guarantees a sub-account, returns it."""
    student = invoice.enrollment.student
    return ensure_student_account(student)


def party_payroll_account(employee: Employee) -> Account:
    return ensure_employee_account(employee)


def party_ap_account(vendor: Vendor) -> Account:
    return ensure_vendor_account(vendor)
