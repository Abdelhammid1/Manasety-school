"""Ticket G — financial + operational reports.

Every function returns a plain-dict view-model that a template can
render. Date filtering and cost-center filtering are consistent
across all reports so the same URL knobs work everywhere.
"""
from decimal import Decimal
from datetime import date as _date_cls
from typing import Optional

from sqlalchemy import func

from ..extensions import db
from ..models import (
    Account, JournalEntry, JournalLine, Invoice, InvoiceLine, FeeType,
    Payment, Enrollment, Student, Section, Grade, AcademicYear,
    CostCenter,
)
from ..models.hr import Payroll


def _range(start: Optional[_date_cls], end: Optional[_date_cls]):
    if start is None:
        start = _date_cls(2000, 1, 1)
    if end is None:
        end = _date_cls.today()
    return start, end


# ─── Financial reports ─────────────────────────────────────────────

def trial_balance(school_id: int, *, start=None, end=None):
    """Every postable account with its DR/CR totals within the range."""
    s, e = _range(start, end)
    rows = (
        db.session.query(
            Account.id, Account.code, Account.name, Account.type,
            func.coalesce(func.sum(JournalLine.debit), 0).label("d"),
            func.coalesce(func.sum(JournalLine.credit), 0).label("c"),
        )
        .join(JournalLine, JournalLine.account_id == Account.id, isouter=True)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id, isouter=True)
        .filter(Account.school_id == school_id, Account.is_postable == True,
                (JournalEntry.entry_date >= s) | (JournalEntry.entry_date.is_(None)),
                (JournalEntry.entry_date <= e) | (JournalEntry.entry_date.is_(None)))
        .group_by(Account.id).order_by(Account.code).all()
    )
    out = []
    total_d = total_c = Decimal(0)
    for aid, code, name, t, d, c in rows:
        d = Decimal(str(d or 0)); c = Decimal(str(c or 0))
        bal = d - c if t in ("asset", "expense") else c - d
        out.append({"code": code, "name": name, "type": t,
                    "debit": d, "credit": c, "balance": bal})
        total_d += d; total_c += c
    return {"rows": out, "total_debit": total_d, "total_credit": total_c,
            "start": s, "end": e}


def income_statement(school_id: int, *, start=None, end=None):
    s, e = _range(start, end)
    def _sum(type_):
        rows = (
            db.session.query(Account.id, Account.code, Account.name,
                             func.coalesce(func.sum(JournalLine.debit), 0),
                             func.coalesce(func.sum(JournalLine.credit), 0))
            .join(JournalLine, JournalLine.account_id == Account.id)
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .filter(Account.school_id == school_id, Account.type == type_,
                    Account.is_postable == True,
                    JournalEntry.entry_date >= s, JournalEntry.entry_date <= e)
            .group_by(Account.id).order_by(Account.code).all()
        )
        return [{"code": r[1], "name": r[2],
                 "amount": (Decimal(str(r[4])) - Decimal(str(r[3]))) if type_ == "revenue"
                            else (Decimal(str(r[3])) - Decimal(str(r[4])))}
                for r in rows]
    revs = _sum("revenue"); exps = _sum("expense")
    total_rev = sum((r["amount"] for r in revs), Decimal(0))
    total_exp = sum((r["amount"] for r in exps), Decimal(0))
    return {"revenue": revs, "expense": exps,
            "total_revenue": total_rev, "total_expense": total_exp,
            "net_income": total_rev - total_exp, "start": s, "end": e}


def balance_sheet(school_id: int, *, at=None):
    at = at or _date_cls.today()
    def _bal(type_):
        rows = (
            db.session.query(Account.id, Account.code, Account.name,
                             func.coalesce(func.sum(JournalLine.debit), 0),
                             func.coalesce(func.sum(JournalLine.credit), 0))
            .join(JournalLine, JournalLine.account_id == Account.id)
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .filter(Account.school_id == school_id, Account.type == type_,
                    Account.is_postable == True,
                    JournalEntry.entry_date <= at)
            .group_by(Account.id).order_by(Account.code).all()
        )
        out = []
        total = Decimal(0)
        for aid, code, name, d, c in rows:
            d = Decimal(str(d)); c = Decimal(str(c))
            bal = d - c if type_ in ("asset", "expense") else c - d
            if bal != 0:
                out.append({"code": code, "name": name, "amount": bal})
                total += bal
        return out, total
    assets, ta = _bal("asset")
    liabilities, tl = _bal("liability")
    equity, te = _bal("equity")
    return {"assets": assets, "liabilities": liabilities, "equity": equity,
            "total_assets": ta, "total_liabilities": tl, "total_equity": te,
            "at": at}


def general_ledger(school_id: int, account_id: int, *, start=None, end=None):
    s, e = _range(start, end)
    account = db.session.get(Account, account_id)
    lines = (
        db.session.query(JournalLine, JournalEntry)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .filter(JournalLine.account_id == account_id,
                JournalEntry.school_id == school_id,
                JournalEntry.entry_date >= s, JournalEntry.entry_date <= e)
        .order_by(JournalEntry.entry_date, JournalLine.id).all()
    )
    running = Decimal(0)
    out = []
    for jl, je in lines:
        d = Decimal(str(jl.debit or 0)); c = Decimal(str(jl.credit or 0))
        if account.type in ("asset", "expense"):
            running += (d - c)
        else:
            running += (c - d)
        out.append({"date": je.entry_date, "description": je.description,
                    "reference": je.reference, "debit": d, "credit": c,
                    "balance": running})
    return {"account": account, "rows": out, "start": s, "end": e}


def cash_flow(school_id: int, *, start=None, end=None):
    """Simplified: net cash movement across each 11xx (cash) account."""
    s, e = _range(start, end)
    rows = (
        db.session.query(Account.code, Account.name,
                         func.coalesce(func.sum(JournalLine.debit), 0),
                         func.coalesce(func.sum(JournalLine.credit), 0))
        .join(JournalLine, JournalLine.account_id == Account.id)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .filter(Account.school_id == school_id, Account.is_postable == True,
                Account.code.startswith("11"),
                JournalEntry.entry_date >= s, JournalEntry.entry_date <= e)
        .group_by(Account.id).order_by(Account.code).all()
    )
    out = []
    total_in = total_out = Decimal(0)
    for code, name, d, c in rows:
        d = Decimal(str(d)); c = Decimal(str(c))
        out.append({"code": code, "name": name, "inflow": d, "outflow": c, "net": d - c})
        total_in += d; total_out += c
    return {"rows": out, "total_in": total_in, "total_out": total_out,
            "net_flow": total_in - total_out, "start": s, "end": e}


def aging_report(school_id: int, *, at=None):
    """Buckets unpaid invoices: <30 / 30-60 / 60-90 / >90 days past due."""
    at = at or _date_cls.today()
    invoices = (
        Invoice.query.filter(
            Invoice.school_id == school_id,
            Invoice.status.notin_(("paid", "cancelled", "refunded")),
        ).all()
    )
    buckets = {"current": Decimal(0), "d30": Decimal(0),
               "d60": Decimal(0), "d90": Decimal(0), "d90p": Decimal(0)}
    detail = []
    for inv in invoices:
        remaining = Decimal(str(inv.remaining))
        if remaining <= 0:
            continue
        days = (at - inv.due_date).days
        if days <= 0:
            bucket = "current"
        elif days <= 30:
            bucket = "d30"
        elif days <= 60:
            bucket = "d60"
        elif days <= 90:
            bucket = "d90"
        else:
            bucket = "d90p"
        buckets[bucket] += remaining
        detail.append({
            "number": inv.number, "student": inv.enrollment.student.full_name,
            "due_date": inv.due_date, "days_overdue": max(0, days),
            "remaining": remaining, "bucket": bucket,
        })
    detail.sort(key=lambda r: -r["days_overdue"])
    return {"buckets": buckets, "invoices": detail, "at": at}


def cost_center_pl(school_id: int, *, start=None, end=None):
    """P&L per cost center — revenue via InvoiceLine.cost_center_id +
    expenses via Expense.cost_center_id (JournalLine.cost_center_id is
    reserved for manual quick-journal entries which we skip for now)."""
    s, e = _range(start, end)
    centers = CostCenter.query.filter_by(school_id=school_id).all()
    from ..models import Expense
    out = []
    for cc in centers:
        rev = db.session.query(func.coalesce(func.sum(InvoiceLine.amount), 0))\
            .join(Invoice, Invoice.id == InvoiceLine.invoice_id)\
            .filter(InvoiceLine.cost_center_id == cc.id,
                    Invoice.issue_date >= s, Invoice.issue_date <= e).scalar() or 0
        exp = db.session.query(func.coalesce(func.sum(Expense.amount), 0))\
            .filter(Expense.cost_center_id == cc.id,
                    Expense.date >= s, Expense.date <= e).scalar() or 0
        rev = Decimal(str(rev)); exp = Decimal(str(exp))
        out.append({"center": cc.name, "revenue": rev, "expense": exp,
                    "net": rev - exp})
    return {"rows": out, "start": s, "end": e}


# ─── Operational reports ──────────────────────────────────────────

def collection_report(school_id: int, *, start=None, end=None):
    """Invoiced vs collected per grade for the range."""
    s, e = _range(start, end)
    grades = Grade.query.filter_by(school_id=school_id).order_by(Grade.order_index).all()
    out = []
    total_inv = total_paid = Decimal(0)
    for g in grades:
        rows = (
            db.session.query(func.coalesce(func.sum(Invoice.total_amount), 0),
                             func.coalesce(func.sum(Invoice.paid_amount), 0))
            .join(Enrollment, Enrollment.id == Invoice.enrollment_id)
            .filter(Enrollment.grade_id == g.id,
                    Invoice.issue_date >= s, Invoice.issue_date <= e)
            .first()
        )
        invoiced = Decimal(str(rows[0] or 0)); paid = Decimal(str(rows[1] or 0))
        rate = float(paid / invoiced * 100) if invoiced > 0 else 0
        out.append({"grade": g.name, "invoiced": invoiced, "paid": paid,
                    "collection_rate": round(rate, 1)})
        total_inv += invoiced; total_paid += paid
    return {"rows": out, "total_invoiced": total_inv, "total_paid": total_paid,
            "overall_rate": round(float(total_paid / total_inv * 100), 1) if total_inv > 0 else 0,
            "start": s, "end": e}


def overdue_by_grade(school_id: int, *, at=None):
    at = at or _date_cls.today()
    grades = Grade.query.filter_by(school_id=school_id).order_by(Grade.order_index).all()
    out = []
    for g in grades:
        rows = (
            db.session.query(func.coalesce(func.sum(Invoice.total_amount - Invoice.paid_amount), 0),
                             func.count(Invoice.id))
            .join(Enrollment, Enrollment.id == Invoice.enrollment_id)
            .filter(Enrollment.grade_id == g.id,
                    Invoice.due_date < at,
                    Invoice.status.notin_(("paid", "cancelled", "refunded")))
            .first()
        )
        out.append({"grade": g.name, "overdue_amount": Decimal(str(rows[0] or 0)),
                    "overdue_count": int(rows[1] or 0)})
    return {"rows": sorted(out, key=lambda r: -r["overdue_amount"]), "at": at}


def revenue_by_fee_type(school_id: int, *, start=None, end=None):
    s, e = _range(start, end)
    rows = (
        db.session.query(FeeType.name,
                         func.coalesce(func.sum(InvoiceLine.amount), 0))
        .join(InvoiceLine, InvoiceLine.fee_type_id == FeeType.id)
        .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
        .filter(FeeType.school_id == school_id,
                Invoice.issue_date >= s, Invoice.issue_date <= e)
        .group_by(FeeType.id).order_by(func.sum(InvoiceLine.amount).desc()).all()
    )
    out = [{"name": n, "amount": Decimal(str(a))} for n, a in rows]
    total = sum((r["amount"] for r in out), Decimal(0))
    return {"rows": out, "total": total, "start": s, "end": e}


def payroll_summary(school_id: int, *, start=None, end=None):
    s, e = _range(start, end)
    rows = (
        Payroll.query.filter(
            Payroll.school_id == school_id,
        ).all()
    )
    # Group by (year, month)
    buckets: dict = {}
    for p in rows:
        key = (p.period_year, p.period_month)
        b = buckets.setdefault(key, {"base": Decimal(0), "allow": Decimal(0),
                                      "ded": Decimal(0), "net": Decimal(0),
                                      "count": 0})
        b["base"] += Decimal(str(p.base_salary or 0))
        b["allow"] += Decimal(str(p.allowances or 0))
        b["ded"] += Decimal(str(p.deductions or 0))
        b["net"] += Decimal(str(p.net_pay or 0))
        b["count"] += 1
    out = []
    for (y, m), b in sorted(buckets.items(), reverse=True):
        out.append({"period": f"{y}/{m:02d}", **b})
    return {"rows": out}


def cost_per_student(school_id: int, *, start=None, end=None):
    s, e = _range(start, end)
    from ..models import Expense
    total_exp = db.session.query(func.coalesce(func.sum(Expense.amount), 0))\
        .filter(Expense.school_id == school_id,
                Expense.date >= s, Expense.date <= e).scalar() or 0
    active_enrollments = Enrollment.query.filter_by(
        school_id=school_id, status="active",
    ).count()
    per_student = Decimal(str(total_exp)) / Decimal(active_enrollments) if active_enrollments else Decimal(0)
    return {"total_expense": Decimal(str(total_exp)),
            "students": active_enrollments,
            "per_student": per_student.quantize(Decimal("0.01")),
            "start": s, "end": e}


def discounts_grants(school_id: int, *, start=None, end=None):
    s, e = _range(start, end)
    rows = (
        db.session.query(
            Student.full_name, Invoice.number, InvoiceLine.description,
            InvoiceLine.amount,
        )
        .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
        .join(Enrollment, Enrollment.id == Invoice.enrollment_id)
        .join(Student, Student.id == Enrollment.student_id)
        .filter(Invoice.school_id == school_id,
                InvoiceLine.amount < 0,
                Invoice.issue_date >= s, Invoice.issue_date <= e)
        .order_by(InvoiceLine.amount).all()
    )
    detail = [{"student": r[0], "invoice": r[1], "reason": r[2],
               "amount": Decimal(str(r[3])).copy_abs()} for r in rows]
    total = sum((r["amount"] for r in detail), Decimal(0))
    return {"rows": detail, "total": total, "start": s, "end": e}


def year_comparison(school_id: int, year_a_id: int, year_b_id: Optional[int] = None):
    """Revenues and expenses for two academic years, side by side."""
    ya = db.session.get(AcademicYear, year_a_id)
    yb = db.session.get(AcademicYear, year_b_id) if year_b_id else None
    def _totals(y):
        if not y:
            return {"revenue": Decimal(0), "expense": Decimal(0)}
        s, e = y.start_date, y.end_date
        inc = income_statement(school_id, start=s, end=e)
        return {"revenue": inc["total_revenue"], "expense": inc["total_expense"]}
    return {"year_a": ya, "year_b": yb,
            "totals_a": _totals(ya), "totals_b": _totals(yb)}


def forecast_report(school_id: int, months_ahead: int = 6):
    """Sum of scheduled installments' remaining balance grouped by
    year-month for the next N months — an approximation of expected
    inflow assuming everyone pays on time."""
    from ..models import Installment
    from datetime import timedelta
    today = _date_cls.today()
    end = today + timedelta(days=30 * months_ahead)
    rows = (
        db.session.query(Installment.due_date,
                         func.coalesce(func.sum(Installment.amount - Installment.paid_amount), 0))
        .join(Invoice, Invoice.id == Installment.invoice_id)
        .filter(Invoice.school_id == school_id,
                Installment.due_date >= today, Installment.due_date <= end,
                Installment.status != "paid")
        .group_by(Installment.due_date).order_by(Installment.due_date).all()
    )
    buckets: dict = {}
    for d, amt in rows:
        key = f"{d.year}-{d.month:02d}"
        buckets[key] = buckets.get(key, Decimal(0)) + Decimal(str(amt or 0))
    out = [{"period": k, "expected": v} for k, v in sorted(buckets.items())]
    return {"rows": out, "total": sum((r["expected"] for r in out), Decimal(0))}
