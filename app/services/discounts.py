"""Ticket #17 — discount evaluator.

Given an Enrollment.id and a base total, resolves every discount
applicable to that enrollment:

  · Any StudentDiscount rows with status='approved' attached to the
    enrollment (manual approvals).
  · Any DiscountType with auto_rule matched:
        sibling_count_2   → the student has ≥2 siblings enrolled active
        sibling_count_3   → the student has ≥3 siblings enrolled active
        staff_child       → the guardian is also an active Employee

Returns a list of (label, decimal_amount, StudentDiscount|None) so
the caller (invoice_new) can write matching InvoiceLine rows.
"""
from decimal import Decimal

from ..extensions import db
from ..models import (
    StudentDiscount, DiscountType, Enrollment,
    Student, StudentGuardian, Guardian, Employee,
)


def _apply(discount_type, base_total, override=None):
    """Return the money amount this discount evaluates to."""
    if override is not None:
        try:
            return Decimal(str(override))
        except Exception:
            pass
    v = Decimal(str(discount_type.value or 0))
    if discount_type.calc_method == "percentage":
        return (base_total * v / Decimal(100)).quantize(Decimal("0.01"))
    return v


def _sibling_count(enrollment):
    """Number of OTHER active enrollments sharing at least one guardian
    with this student. Matches the audit rule in the ticket."""
    student = enrollment.student
    if student is None:
        return 0
    my_guardian_ids = [l.guardian_id for l in student.guardian_links]
    if not my_guardian_ids:
        return 0
    sibling_stu_ids = (
        db.session.query(StudentGuardian.student_id)
        .filter(StudentGuardian.guardian_id.in_(my_guardian_ids),
                StudentGuardian.student_id != student.id)
        .distinct().all()
    )
    sibling_ids = [s[0] for s in sibling_stu_ids]
    if not sibling_ids:
        return 0
    return (
        Enrollment.query.filter(
            Enrollment.student_id.in_(sibling_ids),
            Enrollment.status == "active",
        ).count()
    )


def _is_staff_child(enrollment):
    """True when any of the student's guardians is also a live Employee."""
    student = enrollment.student
    if student is None:
        return False
    guardian_users = [
        l.guardian.user_id for l in student.guardian_links
        if l.guardian and l.guardian.user_id
    ]
    if not guardian_users:
        return False
    return db.session.query(Employee.id).filter(
        Employee.user_id.in_(guardian_users),
        Employee.is_active.is_(True),
    ).count() > 0


def applicable_discounts_for(enrollment_id, base_total):
    """Return a list of (label, Decimal amount, StudentDiscount|None).

    Iterates approved manual discounts first, then evaluates auto-rules
    on active DiscountTypes. Duplicate suppression: a manual approval
    for the same DiscountType wins over the auto-rule.
    """
    enrollment = Enrollment.query.get(enrollment_id)
    if enrollment is None:
        return []

    manual = (
        StudentDiscount.query.filter_by(
            enrollment_id=enrollment_id, status="approved",
        ).all()
    )
    seen_types = set()
    out = []
    for sd in manual:
        dt = sd.discount_type
        if dt is None or not dt.is_active:
            continue
        amt = _apply(dt, base_total, override=sd.override_value)
        if amt <= 0:
            continue
        out.append((dt.name, amt, sd))
        seen_types.add(dt.id)

    # Auto rules.
    sid = enrollment.school_id
    sib_n = None
    is_staff = None
    for dt in DiscountType.query.filter_by(
        school_id=sid, is_active=True,
    ).all():
        if dt.id in seen_types or not dt.auto_rule:
            continue
        matched = False
        if dt.auto_rule == "sibling_count_2":
            if sib_n is None: sib_n = _sibling_count(enrollment)
            matched = sib_n >= 2
        elif dt.auto_rule == "sibling_count_3":
            if sib_n is None: sib_n = _sibling_count(enrollment)
            matched = sib_n >= 3
        elif dt.auto_rule == "staff_child":
            if is_staff is None: is_staff = _is_staff_child(enrollment)
            matched = is_staff
        if not matched:
            continue
        amt = _apply(dt, base_total)
        if amt <= 0:
            continue
        out.append((f"{dt.name} (تلقائي)", amt, None))
        seen_types.add(dt.id)

    return out
