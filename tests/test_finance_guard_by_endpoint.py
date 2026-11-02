"""The finance guard by endpoint: parents reach their own invoices again (the
old URL pattern expected digits and refused link codes), nobody else's and
no other finance page; the warehouse role reaches the expense pages it
holds; money figures stay off a dashboard without the permission."""

from __future__ import annotations

from datetime import date

import pytest

from isolation_harness import hid, host
from test_bug016_017_staff_nav import _client, _nav_links, _user_with_default_role


@pytest.fixture
def fapp(app, monkeypatch):
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    return app


MONEY = ("الرصيد النقدي", "مستحقّات مفتوحة", "محصّلات هذا الشهر", "مصروفات هذا الشهر", "أقساط قريبة")


def _other_family_invoice(app, A):
    from app.extensions import db
    from app.models import Enrollment, Invoice, Student
    with app.app_context():
        st = Student(school_id=A["school"].id, permanent_code="PC-other", full_name="Other Child")
        db.session.add(st)
        db.session.flush()
        en = Enrollment(student_id=st.id, school_id=A["school"].id, year_id=A["year"].id, grade_id=A["grade"].id,
                        section_id=A["section"].id, status="active", enrolled_at=date(2026, 9, 1))
        db.session.add(en)
        db.session.flush()
        inv = Invoice(school_id=A["school"].id, enrollment_id=en.id, number="INV-other", issue_date=date(2026, 9, 1),
                      due_date=date(2026, 10, 1), status="unpaid", total_amount=100, paid_amount=0)
        db.session.add(inv)
        db.session.commit()
        out = inv.id
        db.session.remove()
    return out


def test_a_parent_opens_their_childs_invoice_and_print(fapp, world, login_as):
    A = world["A"]
    c = _client(fapp, login_as, A["users"]["parent"], A)
    h = host(A)
    page = c.get(f"/finance/invoices/{hid(A['invoice'])}", base_url=h)
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert "INV-alpha" in body
    # the page's staff forms and the chart of accounts stay out
    assert "/void" not in body and "/pay" not in body and "Cash-alpha" not in body
    assert c.get(f"/finance/invoices/{hid(A['invoice'])}/print", base_url=h).status_code == 200


def test_a_parent_cannot_open_another_familys_invoice(fapp, world, login_as):
    A = world["A"]
    other = _other_family_invoice(fapp, A)
    c = _client(fapp, login_as, A["users"]["parent"], A)
    assert c.get(f"/finance/invoices/{hid(other)}", base_url=host(A)).status_code == 403
    assert c.get(f"/finance/invoices/{hid(other)}/print", base_url=host(A)).status_code == 403
    assert "INV-other" not in c.get("/finance/invoices", base_url=host(A)).get_data(as_text=True)


@pytest.mark.parametrize("path", [
    "/finance/invoices/new", "/finance/dashboard", "/finance/accounts", "/finance/journal", "/finance/treasury",
    "/finance/reports", "/finance/expenses", "/finance/expenses/new",
])
def test_a_parent_stays_out_of_the_rest_of_finance(fapp, world, login_as, path):
    A = world["A"]
    c = _client(fapp, login_as, A["users"]["parent"], A)
    assert c.get(path, base_url=host(A)).status_code == 403


def test_the_expense_prefix_matches_only_expense_pages(fapp):
    """Nothing new slips through by its name: the open set is exact, and the
    expense prefix matches only expense pages."""
    names = {r.endpoint for r in fapp.url_map.iter_rules() if r.endpoint.startswith("finance.expense")}
    assert names and all("/expenses" in r.rule for r in fapp.url_map.iter_rules() if r.endpoint in names)


def test_the_warehouse_role_reaches_its_expense_pages_only(fapp, world, login_as):
    A = world["A"]
    c = _client(fapp, login_as, _user_with_default_role(fapp, A, "warehouse"), A)
    h = host(A)
    assert "/finance/expenses" in _nav_links(c.get("/dashboard", base_url=h).get_data(as_text=True))
    assert c.get("/finance/expenses", base_url=h).status_code == 200
    assert c.get("/finance/expenses/new", base_url=h).status_code == 200          # the role holds expenses.add
    for path in ("/finance/accounts", "/finance/invoices/new", "/finance/journal", "/finance/reports"):
        assert c.get(path, base_url=h).status_code == 403, path
    r = c.post(f"/finance/expenses/{hid(A['expense'])}/edit", base_url=h, data={})
    assert r.status_code == 403                                                   # no expenses.edit
    assert c.post(f"/finance/expenses/{hid(A['expense'])}/delete", base_url=h).status_code == 403
    assert c.post(f"/finance/expenses/{hid(A['expense'])}/approve", base_url=h).status_code == 403


@pytest.mark.parametrize("role,visible", [
    ("student_affairs", ()), ("warehouse", ("مصروفات هذا الشهر",)),
    ("accountant", MONEY),
])
def test_money_figures_follow_the_permission(fapp, world, login_as, role, visible):
    A = world["A"]
    c = _client(fapp, login_as, _user_with_default_role(fapp, A, role), A)
    body = c.get("/dashboard", base_url=host(A)).get_data(as_text=True)
    for label in MONEY:
        assert (label in body) == (label in visible), label


def test_the_admin_dashboard_keeps_the_money_figures(fapp, world, login_as):
    A = world["A"]
    body = _client(fapp, login_as, A["users"]["admin"], A).get("/dashboard", base_url=host(A)).get_data(as_text=True)
    for label in MONEY:
        assert label in body


def _expense_form(app, A, **over):
    from app.extensions import db
    from app.models import Account
    with app.app_context():
        acct = Account.query.filter_by(school_id=A["school"].id, code="5101").one().id
        db.session.remove()
    return {"amount": "75", "date": "2026-10-20", "expense_account_id": acct,
            "payment_method_id": A["payment_method"], "description": "expense-probe", **over}


def _probe(app):
    """(status, has a journal entry) of the expense the form created, or None."""
    from app.extensions import db
    from app.models import Expense
    with app.app_context():
        e = Expense.query.filter_by(description="expense-probe").first()
        out = (e.approval_status, e.journal_entry_id is not None, e.id) if e else None
        db.session.remove()
    return out


def _journal_count(app, A):
    from app.extensions import db
    from app.models import JournalEntry
    with app.app_context():
        n = JournalEntry.query.filter_by(school_id=A["school"].id).count()
        db.session.remove()
    return n


def test_add_only_records_a_pending_expense_and_moves_no_money(fapp, world, login_as):
    A = world["A"]
    before = _journal_count(fapp, A)
    c = _client(fapp, login_as, _user_with_default_role(fapp, A, "warehouse"), A)
    r = c.post("/finance/expenses/new", base_url=host(A), data=_expense_form(fapp, A))
    assert r.status_code == 302
    status, posted, eid = _probe(fapp)
    assert (status, posted) == ("pending", False)
    assert _journal_count(fapp, A) == before
    # the accountant approves it: only then it posts
    acc = _client(fapp, login_as, _user_with_default_role(fapp, A, "accountant"), A)
    assert acc.post(f"/finance/expenses/{hid(eid)}/approve", base_url=host(A)).status_code == 302
    assert _probe(fapp)[:2] == ("approved", True) and _journal_count(fapp, A) > before


def test_expenses_edit_still_posts_directly(fapp, world, login_as):
    A = world["A"]
    c = _client(fapp, login_as, _user_with_default_role(fapp, A, "accountant"), A)
    assert c.post("/finance/expenses/new", base_url=host(A), data=_expense_form(fapp, A)).status_code == 302
    assert _probe(fapp)[:2] == ("approved", True)


@pytest.mark.parametrize("over", [{"amount": "-75"}, {"amount": "0"}, {"amount": "abc"}, {"amount": "NaN"}, {"amount": ""}])
def test_a_bad_amount_is_refused(fapp, world, login_as, over):
    A = world["A"]
    c = _client(fapp, login_as, _user_with_default_role(fapp, A, "accountant"), A)
    r = c.post("/finance/expenses/new", base_url=host(A), data=_expense_form(fapp, A, **over), follow_redirects=True)
    assert r.status_code == 200 and "أكبر من صفر" in r.get_data(as_text=True)
    assert _probe(fapp) is None


def test_only_a_postable_expense_account_can_be_debited(fapp, world, login_as):
    A, B = world["A"], world["B"]
    c = _client(fapp, login_as, _user_with_default_role(fapp, A, "accountant"), A)
    for acct in (A["account"], B["account"]):        # A's cash; another school's account
        r = c.post("/finance/expenses/new", base_url=host(A), follow_redirects=True,
                   data=_expense_form(fapp, A, expense_account_id=acct))
        assert "اختر حساب مصروف صالحاً" in r.get_data(as_text=True)
    assert _probe(fapp) is None


def test_rejecting_a_pending_expense_redirects_and_posts_nothing(fapp, world, login_as):
    A = world["A"]
    before = _journal_count(fapp, A)
    c = _client(fapp, login_as, _user_with_default_role(fapp, A, "warehouse"), A)
    c.post("/finance/expenses/new", base_url=host(A), data=_expense_form(fapp, A))
    eid = _probe(fapp)[2]
    acc = _client(fapp, login_as, _user_with_default_role(fapp, A, "accountant"), A)
    r = acc.post(f"/finance/expenses/{hid(eid)}/reject", base_url=host(A), data={"reason": "no"})
    assert r.status_code == 302 and "/finance/expenses" in r.headers["Location"]
    assert _probe(fapp)[:2] == ("rejected", False) and _journal_count(fapp, A) == before
