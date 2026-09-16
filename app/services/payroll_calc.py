"""Ticket #9 — payroll auto-deduction from StaffAttendance rows.

For a given (employee × year × month), count days marked as
unpaid-absence:
  · status='absent' with leave_type=NULL          → unpaid
  · status='leave'  with leave_type='unpaid'      → unpaid
  · status='leave'  with leave_type in
    ('annual','sick','emergency')                 → paid, no deduction
  · status='late' costs half a day.

Deduction = base_salary / 30 × unpaid_days + late_days × (daily / 2).
"""
from calendar import monthrange
from decimal import Decimal

from ..extensions import db
from ..models import StaffAttendance


def compute_absence_deduction(employee, year, month, base_salary):
    if not employee:
        return Decimal(0)
    days_in_month = monthrange(year, month)[1]
    if days_in_month <= 0:
        return Decimal(0)
    from datetime import date
    start = date(year, month, 1)
    end = date(year, month, days_in_month)

    rows = StaffAttendance.query.filter(
        StaffAttendance.employee_id == employee.id,
        StaffAttendance.date >= start,
        StaffAttendance.date <= end,
    ).all()

    unpaid_days = 0
    late_days = 0
    for r in rows:
        s = (r.status or "").lower()
        lt = (r.leave_type or "").lower()
        if s == "absent" and not lt:
            unpaid_days += 1
        elif s == "leave" and lt == "unpaid":
            unpaid_days += 1
        elif s == "late":
            late_days += 1
    daily = Decimal(str(base_salary or 0)) / Decimal(30)
    return (daily * unpaid_days + (daily / Decimal(2)) * late_days).quantize(Decimal("0.01"))
