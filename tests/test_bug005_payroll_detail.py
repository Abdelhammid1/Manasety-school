"""BUG-005 — every payroll row opens its detail page (the only place to
settle it), so an accrual can be paid days later; the settle refuses a
zero / negative / too-large amount and a second click can't pay twice."""

from __future__ import annotations

from decimal import Decimal

import pytest

from isolation_harness import hid, host


@pytest.fixture
def papp(app, two_schools, monkeypatch):
    from app.extensions import db
    from app.models import Account, Employee, PaymentMethod
    from app.models.finance import ensure_default_chart
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    ids = {}
    with app.app_context():
        for k in ("A", "B"):
            sid = two_schools[k]["school"].id
            ensure_default_chart(sid)
            cash = Account.query.filter_by(school_id=sid, code="1110").one()
            pm = PaymentMethod(school_id=sid, name=f"نقدي-{k}", kind="immediate_cash", account_id=cash.id)
            emp = Employee(school_id=sid, full_name=f"منى-{k}", job_title="معلمة", base_salary=Decimal("6000"))
            db.session.add_all([pm, emp])
            db.session.flush()
            ids[k] = {"pm": pm.id, "emp": emp.id}
        db.session.commit()
        db.session.remove()
    app.extra_ids = ids
    return app


def _client(app, login_as, bundle, role="admin"):
    c = app.test_client()
    login_as(c, bundle["users"][role], base_url=host(bundle))
    return c


def _accrue(app, c, bundle, k):
    """The real form: 6000 + 500, no deductions."""
    r = c.post("/hr/payroll/new", base_url=host(bundle), data={
        "employee_id": app.extra_ids[k]["emp"], "period_year": "2026", "period_month": "10",
        "base_salary": "6000", "allowances": "500", "deductions": "0", "paid_at": "2026-10-28"})
    assert r.status_code == 302, r.get_data(as_text=True)[:300]
    from app.extensions import db
    from app.models import Payroll
    with app.app_context():
        pid = Payroll.query.filter_by(employee_id=app.extra_ids[k]["emp"]).one().id
        db.session.remove()
    return pid


def _state(app, pid):
    """(paid_amount, settlements, balance of the employee's 2210 account)."""
    from sqlalchemy import func
    from app.extensions import db
    from app.models import JournalLine, Payroll
    from app.services.ledger import party_payroll_account
    with app.app_context():
        p = db.session.get(Payroll, pid)
        acct = party_payroll_account(p.employee)
        cr, dr = db.session.query(func.coalesce(func.sum(JournalLine.credit), 0),
                                  func.coalesce(func.sum(JournalLine.debit), 0)) \
            .filter(JournalLine.account_id == acct.id).one()
        out = (Decimal(str(p.paid_amount)), len(p.settlements), Decimal(str(cr)) - Decimal(str(dr)))
        db.session.rollback()
        db.session.remove()
    return out


def test_every_payroll_row_links_to_its_detail_page(papp, two_schools, login_as):
    A = two_schools["A"]
    c = _client(papp, login_as, A)
    pid = _accrue(papp, c, A, "A")
    body = c.get("/hr/payroll", base_url=host(A)).get_data(as_text=True)
    assert f"/hr/payroll/{hid(pid)}\"" in body and "تفاصيل" in body and "مستحق" in body
    emp = c.get(f"/hr/employees/{hid(papp.extra_ids['A']['emp'])}", base_url=host(A)).get_data(as_text=True)
    assert f"/hr/payroll/{hid(pid)}\"" in emp
    page = c.get(f"/hr/payroll/{hid(pid)}", base_url=host(A)).get_data(as_text=True)
    for label in ("الأساسي", "البدلات", "الخصومات", "الصافي", "مخصوم سداداً لسلف", "المصروف", "المتبقّي للصرف"):
        assert label in page
    assert "6500" in page and 'name="amount"' in page


def test_settle_later_in_two_payments_then_2210_is_zero(papp, two_schools, login_as):
    A = two_schools["A"]
    c = _client(papp, login_as, A)
    pid = _accrue(papp, c, A, "A")
    assert _state(papp, pid) == (Decimal("0"), 0, Decimal("6500"))
    pm = papp.extra_ids["A"]["pm"]
    url = f"/hr/payroll/{hid(pid)}/settle"
    c.post(url, base_url=host(A), data={"amount": "2000", "payment_method_id": pm, "settled_at": "2026-11-01"})
    assert _state(papp, pid) == (Decimal("2000"), 1, Decimal("4500"))
    body = c.get("/hr/payroll", base_url=host(A)).get_data(as_text=True)
    assert "مصروف جزئيًا" in body and "4500" in body
    # the rest, empty amount = all that remains
    c.post(url, base_url=host(A), data={"amount": "", "payment_method_id": pm, "settled_at": "2026-11-03"})
    assert _state(papp, pid) == (Decimal("6500"), 2, Decimal("0"))
    page = c.get(f"/hr/payroll/{hid(pid)}", base_url=host(A)).get_data(as_text=True)
    assert "مصروف بالكامل" in page and 'name="amount"' not in page   # nothing left to settle


@pytest.mark.parametrize("amount", ["0", "-5", "abc", "NaN", "Infinity", "6500.01"])
def test_a_bad_amount_is_refused_and_nothing_is_paid(papp, two_schools, login_as, amount):
    A = two_schools["A"]
    c = _client(papp, login_as, A)
    pid = _accrue(papp, c, A, "A")
    r = c.post(f"/hr/payroll/{hid(pid)}/settle", base_url=host(A), follow_redirects=True,
               data={"amount": amount, "payment_method_id": papp.extra_ids["A"]["pm"]})
    body = r.get_data(as_text=True)
    assert r.status_code == 200 and ("أكبر من صفر" in body or "أكبر من الرصيد المتبقي" in body)
    assert _state(papp, pid) == (Decimal("0"), 0, Decimal("6500"))


def test_a_second_click_cannot_pay_twice(papp, two_schools, login_as):
    A = two_schools["A"]
    c = _client(papp, login_as, A)
    pid = _accrue(papp, c, A, "A")
    data = {"amount": "6500", "payment_method_id": papp.extra_ids["A"]["pm"]}
    c.post(f"/hr/payroll/{hid(pid)}/settle", base_url=host(A), data=data)
    r = c.post(f"/hr/payroll/{hid(pid)}/settle", base_url=host(A), data=data, follow_redirects=True)
    assert "تم صرفه بالكامل" in r.get_data(as_text=True)
    assert _state(papp, pid) == (Decimal("6500"), 1, Decimal("0"))


@pytest.mark.parametrize("role", ["teacher", "student", "parent"])
def test_without_payroll_rights_detail_and_settle_are_403(papp, two_schools, login_as, role):
    A = two_schools["A"]
    pid = _accrue(papp, _client(papp, login_as, A), A, "A")
    c = _client(papp, login_as, A, role)
    assert c.get(f"/hr/payroll/{hid(pid)}", base_url=host(A)).status_code == 403
    assert c.get("/hr/payroll", base_url=host(A)).status_code == 403
    r = c.post(f"/hr/payroll/{hid(pid)}/settle", base_url=host(A),
               data={"amount": "100", "payment_method_id": papp.extra_ids["A"]["pm"]})
    assert r.status_code == 403
    assert _state(papp, pid) == (Decimal("0"), 0, Decimal("6500"))


def test_another_schools_payroll_is_404(papp, two_schools, login_as):
    A, B = two_schools["A"], two_schools["B"]
    pid_b = _accrue(papp, _client(papp, login_as, B), B, "B")
    c = _client(papp, login_as, A)
    assert c.get(f"/hr/payroll/{hid(pid_b)}", base_url=host(A)).status_code == 404
    r = c.post(f"/hr/payroll/{hid(pid_b)}/settle", base_url=host(A),
               data={"amount": "100", "payment_method_id": papp.extra_ids["A"]["pm"]})
    assert r.status_code == 404
    assert _state(papp, pid_b) == (Decimal("0"), 0, Decimal("6500"))


def test_an_advance_deducted_at_accrual_shows_and_the_rest_settles(papp, two_schools, login_as):
    from app.extensions import db
    from app.models import EmployeeAdvance
    A = two_schools["A"]
    with papp.app_context():
        db.session.add(EmployeeAdvance(school_id=A["school"].id, employee_id=papp.extra_ids["A"]["emp"],
                                       amount=Decimal("1000"), remaining_balance=Decimal("1000"),
                                       deduction_plan="full_next_month", status="active"))
        db.session.commit()
        db.session.remove()
    c = _client(papp, login_as, A)
    pid = _accrue(papp, c, A, "A")
    assert _state(papp, pid) == (Decimal("1000"), 0, Decimal("5500"))   # the ticket's 5500 left
    page = c.get(f"/hr/payroll/{hid(pid)}", base_url=host(A)).get_data(as_text=True)
    assert "1000" in page and "5500" in page and "مصروف جزئيًا" in page   # the advance covered part of it
    c.post(f"/hr/payroll/{hid(pid)}/settle", base_url=host(A),
           data={"amount": "5500", "payment_method_id": papp.extra_ids["A"]["pm"]})
    assert _state(papp, pid) == (Decimal("6500"), 1, Decimal("0"))


def test_bug006_the_list_header_shows_what_was_really_paid(papp, two_schools, login_as):
    """BUG-006 (recommended option): «الصافي» stays what was earned; the
    header separates advances, money paid out and what is still owed."""
    from app.extensions import db
    from app.models import EmployeeAdvance
    A = two_schools["A"]
    with papp.app_context():
        db.session.add(EmployeeAdvance(school_id=A["school"].id, employee_id=papp.extra_ids["A"]["emp"],
                                       amount=Decimal("1000"), remaining_balance=Decimal("1000"),
                                       deduction_plan="full_next_month", status="active"))
        db.session.commit(); db.session.remove()
    c = _client(papp, login_as, A)
    pid = _accrue(papp, c, A, "A")
    c.post(f"/hr/payroll/{hid(pid)}/settle", base_url=host(A),
           data={"amount": "2000", "payment_method_id": papp.extra_ids["A"]["pm"]})
    body = c.get("/hr/payroll", base_url=host(A)).get_data(as_text=True)
    head = body[body.index("مسيرة ·"):body.index("مسيرة ·") + 900]
    for label, value in (("إجمالي الصافي المستحق", "6500"), ("مخصوم سلف", "1000"),
                         ("مصروف فعلياً", "2000"), ("متبقٍّ للصرف", "3500")):
        i = head.index(label)
        assert value in head[i:i + 120], (label, value)
