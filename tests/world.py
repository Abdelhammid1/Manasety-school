"""Seed data for the isolation matrix beyond the two_schools basics,
plus a teardown purge that removes every row two test schools own.

Each seeder returns plain ids (never ORM objects) and extra marker
strings unique to the school, so a sweep can grep responses for them.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal


def seed_finance_hr(bundle: dict) -> dict:
    """Finance + HR records for one school. Must run in an app context."""
    from app.extensions import db
    from app.models import (
        Account, BankStatementLine, Budget, CostCenter, DiscountType, Guardian, StudentGuardian,
        Employee, Expense, FeeType, Invoice, InvoiceLine, JournalEntry,
        JournalLine, LeaveRequest, PaymentMethod, Payroll,
        RecurringFeeSchedule, RefundRequest, StudentDiscount, Vendor,
    )

    slug = bundle["school"].slug
    sid = bundle["school"].id
    add = db.session.add

    def acc(code, name, typ, role=None):
        a = Account(school_id=sid, code=code, name=f"{name}-{slug}", type=typ,
                    is_postable=True, account_role=role)
        add(a)
        return a

    cash = acc("1101", "Cash", "asset", "cash_default")
    ar = acc("1201", "AR", "asset", "ar_default")
    bank = acc("1102", "Bank", "asset")
    revenue = acc("4101", "Revenue", "revenue")
    expense_acc = acc("5101", "Expense", "expense")
    acc("1170", "Petty", "asset")
    db.session.flush()

    cc = CostCenter(school_id=sid, name=f"CC-{slug}")
    ft = FeeType(school_id=sid, name=f"Fee-{slug}", revenue_account_id=revenue.id,
                 default_amount=Decimal("100"))
    pm = PaymentMethod(school_id=sid, name=f"PM-{slug}", account_id=cash.id)
    vendor = Vendor(school_id=sid, name=f"Vendor-{slug}")
    dt = DiscountType(school_id=sid, name=f"Disc-{slug}", calc_method="percent",
                      value=Decimal("10"))
    emp = Employee(school_id=sid, full_name=f"Emp-{slug}", job_title="Clerk",
                   base_salary=Decimal("5000"))
    for o in (cc, ft, pm, vendor, dt, emp):
        add(o)
    db.session.flush()

    inv = Invoice(school_id=sid, enrollment_id=bundle["enrollment"].id,
                  number=f"INV-{slug}", issue_date=date(2026, 9, 1),
                  due_date=date(2026, 10, 1), status="unpaid",
                  total_amount=Decimal("100"), paid_amount=Decimal("0"))
    add(inv)
    db.session.flush()
    add(InvoiceLine(invoice_id=inv.id, fee_type_id=ft.id, amount=Decimal("100")))

    je = JournalEntry(school_id=sid, entry_date=date(2026, 9, 1),
                      description=f"JE-{slug}")
    add(je)
    db.session.flush()
    jl = JournalLine(entry_id=je.id, account_id=cash.id, debit=Decimal("100"),
                     credit=Decimal("0"))
    add(jl)
    add(JournalLine(entry_id=je.id, account_id=revenue.id, debit=Decimal("0"),
                    credit=Decimal("100")))

    exp = Expense(school_id=sid, vendor_id=vendor.id, expense_account_id=expense_acc.id,
                  cash_account_id=cash.id, date=date(2026, 9, 2),
                  amount=Decimal("50"), description=f"Exp-{slug}",
                  approval_status="pending")
    bsl = BankStatementLine(school_id=sid, bank_account_id=bank.id,
                            statement_date=date(2026, 9, 3), amount=Decimal("100"),
                            description=f"BSL-{slug}")
    budget = Budget(school_id=sid, year_id=bundle["year"].id, account_id=expense_acc.id,
                    planned_amount=Decimal("1000"), note=f"Budget-{slug}")
    rec = RecurringFeeSchedule(school_id=sid, fee_type_id=ft.id, frequency="monthly")
    sd = StudentDiscount(school_id=sid, enrollment_id=bundle["enrollment"].id,
                         discount_type_id=dt.id, status="pending")
    rr = RefundRequest(school_id=sid, invoice_id=inv.id, amount=Decimal("10"),
                       requested_by_user_id=bundle["users"]["admin"].id,
                       status="pending", reason=f"Refund-{slug}")
    leave = LeaveRequest(school_id=sid, employee_id=emp.id, leave_type="annual",
                         start_date=date(2026, 9, 10), end_date=date(2026, 9, 11),
                         days_count=2, status="pending")
    payroll = Payroll(school_id=sid, employee_id=emp.id, period_year=2026,
                      period_month=9, base_salary=Decimal("5000"),
                      net_pay=Decimal("5000"))
    guardian = Guardian(school_id=sid, full_name=f"Guardian-{slug}", phone=f"0101{sid:07d}")
    for o in (exp, bsl, budget, rec, sd, rr, leave, payroll, guardian):
        add(o)
    db.session.flush()
    add(StudentGuardian(student_id=bundle["student"].id, guardian_id=guardian.id,
                        relationship="father", is_primary=True))
    db.session.commit()

    return {
        "account": cash.id, "bank_account": bank.id, "cost_center": cc.id,
        "fee_type": ft.id, "payment_method": pm.id, "vendor": vendor.id,
        "discount_type": dt.id, "employee": emp.id, "invoice": inv.id,
        "journal_entry": je.id, "journal_line": jl.id, "expense": exp.id,
        "bank_line": bsl.id, "budget": budget.id, "recurring": rec.id,
        "student_discount": sd.id, "refund_request": rr.id,
        "leave_request": leave.id, "payroll": payroll.id,
        "revenue_account": revenue.id, "guardian": guardian.id,
        "markers": (
            f"Vendor-{slug}", f"Emp-{slug}", f"INV-{slug}", f"Fee-{slug}",
            f"PM-{slug}", f"CC-{slug}", f"Disc-{slug}", f"BSL-{slug}",
            f"Exp-{slug}", f"JE-{slug}", f"Budget-{slug}", f"Refund-{slug}",
            f"Cash-{slug}", f"Bank-{slug}", f"Revenue-{slug}", f"Expense-{slug}",
            f"Guardian-{slug}",
        ),
    }


def ledger_state(school_ids) -> tuple:
    """Accounting fingerprint of the given schools: journal entries,
    debit/credit totals and money-moving rows. Any cross-tenant write
    that touches the books changes it."""
    from sqlalchemy import func
    from app.extensions import db
    from app.models import (
        EmployeeAdvance, Expense, Invoice, JournalEntry, JournalLine,
        Payment, Payroll, RefundRequest,
    )
    out = []
    for sid in school_ids:
        dr, cr = (db.session.query(func.coalesce(func.sum(JournalLine.debit), 0),
                                   func.coalesce(func.sum(JournalLine.credit), 0))
                  .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
                  .filter(JournalEntry.school_id == sid).one())
        counts = tuple(
            m.query.filter_by(school_id=sid).count()
            for m in (JournalEntry, Payment, RefundRequest, Expense,
                      EmployeeAdvance, Payroll, Invoice)
        )
        out.append((sid, str(dr), str(cr), counts))
    # Journal lines posted to an account of a different school than the
    # entry — invisible to the per-school totals above.
    from app.models import Account
    foreign = (db.session.query(func.count(JournalLine.id))
               .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
               .join(Account, Account.id == JournalLine.account_id)
               .filter(Account.school_id != JournalEntry.school_id).scalar())
    out.append(("foreign_lines", foreign))
    return tuple(out)


def give_subscription(school) -> None:
    """SAAS-027 — an active test school needs a current subscription or
    the resolver blocks it. Open-ended internal plan, like the migration
    gives every existing school."""
    from app.services.subscriptions import ensure_subscription
    ensure_subscription(school, reason="test fixture")


def purge_schools(school_ids) -> None:
    """Delete every row owned by `school_ids`, children first.

    Owned = has school_id in the set, or (transitively) references an
    owned row through any FK. Runs on the raw connection so soft-delete
    filters and ORM listeners don't interfere."""
    from sqlalchemy import select
    from app.extensions import db

    ids = list(school_ids)
    if not ids:
        return

    def chunks(values, n=500):
        values = list(values)
        for i in range(0, len(values), n):
            yield values[i:i + n]

    md = db.metadata
    tables = [t for t in md.sorted_tables if t.name != "schools"]
    doomed: dict[str, set] = {}
    from app.services.platform_security import audit_prune
    with db.engine.begin() as conn, audit_prune(conn):      # SAAS-036: audit rows are immutable
        for t in tables:
            if "school_id" in t.c and "id" in t.c:
                doomed[t.name] = {r[0] for r in conn.execute(
                    select(t.c.id).where(t.c.school_id.in_(ids)))}
        changed = True
        while changed:
            changed = False
            for t in tables:
                if "id" not in t.c:
                    continue
                for fk in t.foreign_keys:
                    parent_ids = doomed.get(fk.column.table.name)
                    if not parent_ids:
                        continue
                    found = set()
                    for part in chunks(parent_ids):
                        found |= {r[0] for r in conn.execute(
                            select(t.c.id).where(fk.parent.in_(part)))}
                    new = found - doomed.get(t.name, set())
                    if new:
                        doomed.setdefault(t.name, set()).update(new)
                        changed = True
        for t in reversed(tables):
            if "id" in t.c and doomed.get(t.name):
                for part in chunks(doomed[t.name]):
                    conn.execute(t.delete().where(t.c.id.in_(part)))
            elif "id" not in t.c:
                for fk in t.foreign_keys:
                    for part in chunks(doomed.get(fk.column.table.name, ())):
                        conn.execute(t.delete().where(fk.parent.in_(part)))
            if "school_id" in t.c:
                conn.execute(t.delete().where(t.c.school_id.in_(ids)))
        schools = md.tables["schools"]
        conn.execute(schools.delete().where(schools.c.id.in_(ids)))
