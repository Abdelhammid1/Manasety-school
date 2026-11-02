"""BUG-018 — editing an expense was a 500: the route deleted the journal entry
while expenses.journal_entry_id still pointed at it. Postgres refuses that;
SQLite doesn't check foreign keys unless asked, so these tests ask. The edit
now reverses the original entry and posts a new one: the balances move by the
net difference only, and all the entries stay in the ledger."""

from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal

import pytest
from sqlalchemy import event, text

from isolation_harness import hid, host
from test_bug016_017_staff_nav import _client, _user_with_default_role

DAY = "2026-02-11"


@pytest.fixture
def eapp(app, monkeypatch):
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    return app


@contextmanager
def foreign_keys_on(app):
    """Like Postgres, for one request (the fixtures' own cleanup stays as is)."""
    from app.extensions import db
    with app.app_context():
        engine = db.engine

    def on_connect(conn, _record):
        conn.execute("PRAGMA foreign_keys=ON")
    event.listen(engine, "connect", on_connect)
    engine.dispose()
    try:
        yield
    finally:
        event.remove(engine, "connect", on_connect)
        engine.dispose()


def _ids(app, A):
    from app.extensions import db
    from app.models import Account
    with app.app_context():
        out = {a.code: a.id for a in Account.query.filter_by(school_id=A["school"].id)}
        db.session.remove()
    return out


def _form(app, A, **over):
    return {"amount": "500", "date": DAY, "expense_account_id": _ids(app, A)["5101"],
            "payment_method_id": A["payment_method"], "reference": "TEST-EXP-001",
            "description": "شراء قرطاسية", **over}


@pytest.fixture
def expense(eapp, world, login_as):
    """(accountant client, A, expense id): an expense recorded through the form."""
    from app.extensions import db
    from app.models import Expense
    A = world["A"]
    c = _client(eapp, login_as, _user_with_default_role(eapp, A, "accountant"), A)
    assert c.post("/finance/expenses/new", base_url=host(A), data=_form(eapp, A)).status_code == 302
    with eapp.app_context():
        eid = Expense.query.filter_by(reference="TEST-EXP-001").one().id
        db.session.remove()
    return c, A, eid


def _balance(app, A, code):
    """Debit minus credit of an account, from its lines."""
    from app.extensions import db
    from app.models import Account, JournalLine
    with app.app_context():
        acct = Account.query.filter_by(school_id=A["school"].id, code=code).one()
        total = sum((Decimal(str(x.debit)) - Decimal(str(x.credit)))
                    for x in JournalLine.query.filter_by(account_id=acct.id))
        db.session.remove()
    return total


def _row(app, eid):
    from app.extensions import db
    from app.models import Expense
    with app.app_context():
        e = db.session.get(Expense, eid)
        out = {"date": e.date.isoformat(), "amount": Decimal(str(e.amount)), "description": e.description,
               "je": e.journal_entry_id, "status": e.approval_status}
        db.session.remove()
    return out


def _entries(app, A):
    from app.extensions import db
    from app.models import JournalEntry
    with app.app_context():
        out = [(j.id, j.related_kind, j.related_id, j.entry_date.isoformat(),
                sum(Decimal(str(x.debit)) for x in j.lines), sum(Decimal(str(x.credit)) for x in j.lines))
               for j in JournalEntry.query.filter_by(school_id=A["school"].id)
               .filter(JournalEntry.related_kind.in_(("expense", "expense_reversal"))).order_by(JournalEntry.id)]
        db.session.remove()
    return out


def _post(app, c, A, eid, **over):
    with foreign_keys_on(app):
        return c.post(f"/finance/expenses/{hid(eid)}/edit", base_url=host(A), follow_redirects=True,
                      data=_form(app, A, **over))


def test_the_date_alone_moves_the_expense_and_not_the_cash(eapp, expense):
    c, A, eid = expense
    cash = _balance(eapp, A, "1101")
    r = _post(eapp, c, A, eid, date="2026-11-02")
    assert r.status_code == 200 and "تم تعديل المصروف" in r.get_data(as_text=True)
    assert _row(eapp, eid)["date"] == "2026-11-02"
    assert _balance(eapp, A, "1101") == cash
    assert _balance(eapp, A, "5101") == Decimal("500")


def test_the_amount_moves_the_cash_by_the_difference_only(eapp, expense):
    c, A, eid = expense
    cash, spent = _balance(eapp, A, "1101"), _balance(eapp, A, "5101")
    assert _post(eapp, c, A, eid, amount="600").status_code == 200
    assert _row(eapp, eid)["amount"] == Decimal("600")
    assert _balance(eapp, A, "1101") == cash - 100
    assert _balance(eapp, A, "5101") == spent + 100


def test_original_reversal_and_new_stay_in_the_ledger_balanced(eapp, expense):
    c, A, eid = expense
    original = _row(eapp, eid)["je"]
    _post(eapp, c, A, eid, amount="600", date="2026-11-02")
    rows = _entries(eapp, A)
    mine = [r for r in rows if r[0] == original or r[2] == eid]
    assert [r[1] for r in mine] == ["expense", "expense_reversal", "expense"]
    assert mine[0][0] == original                       # the original is still there
    assert mine[1][3] == DAY                            # reversed on its own date
    assert mine[2][0] == _row(eapp, eid)["je"] and mine[2][3] == "2026-11-02"
    assert all(r[4] == r[5] for r in rows)              # DR = CR


def test_two_edits_never_double_count(eapp, expense):
    c, A, eid = expense
    cash = _balance(eapp, A, "1101")
    _post(eapp, c, A, eid, amount="600")
    _post(eapp, c, A, eid, amount="550", date="2026-03-01")
    assert _balance(eapp, A, "1101") == cash - 50 and _balance(eapp, A, "5101") == Decimal("550")


def test_the_description_alone_posts_nothing_new(eapp, expense):
    c, A, eid = expense
    before = _entries(eapp, A)
    r = _post(eapp, c, A, eid, description="وصف جديد", reference="NEW-REF")
    assert "تم تعديل المصروف" in r.get_data(as_text=True)
    assert _row(eapp, eid)["description"] == "وصف جديد"
    assert _entries(eapp, A) == before
    from app.extensions import db
    from app.models import JournalEntry
    with eapp.app_context():
        je = db.session.get(JournalEntry, _row(eapp, eid)["je"])
        assert "وصف جديد" in je.description and je.reference == "NEW-REF"
        db.session.remove()


def test_the_voucher_follows_the_edit(eapp, expense):
    from app.extensions import db
    from app.models import ReceiptVoucher
    c, A, eid = expense
    _post(eapp, c, A, eid, amount="600", date="2026-11-02", description="بعد التعديل")
    with eapp.app_context():
        v = ReceiptVoucher.query.filter_by(expense_id=eid).one()
        assert (Decimal(str(v.amount)), v.voucher_date.isoformat(), v.notes) == (
            Decimal("600"), "2026-11-02", "بعد التعديل")
        db.session.remove()


@pytest.mark.parametrize("over,message", [
    ({"amount": "0"}, "أكبر من صفر"), ({"amount": "-5"}, "أكبر من صفر"), ({"amount": "abc"}, "أكبر من صفر"),
    ({"amount": "NaN"}, "أكبر من صفر"), ({"date": ""}, "التاريخ"), ({"date": "not-a-date"}, "التاريخ"),
    ({"payment_method_id": ""}, "طريقة دفع"), ({"description": "   "}, "الوصف"),
    ({"expense_account_id": ""}, "حساب مصروف"), ({"expense_account_id": "999999"}, "حساب مصروف"),
])
def test_bad_input_stays_on_the_form_and_changes_nothing(eapp, expense, over, message):
    c, A, eid = expense
    before, entries, cash = _row(eapp, eid), _entries(eapp, A), _balance(eapp, A, "1101")
    r = _post(eapp, c, A, eid, **{"reference": "KEPT-REF", **over})
    body = r.get_data(as_text=True)
    assert r.status_code == 400 and message in body
    assert 'value="KEPT-REF"' in body                   # what was typed is still there
    assert _row(eapp, eid) == before and _entries(eapp, A) == entries and _balance(eapp, A, "1101") == cash


def test_a_debit_on_a_non_expense_account_is_refused(eapp, expense):
    c, A, eid = expense
    r = _post(eapp, c, A, eid, expense_account_id=_ids(eapp, A)["1101"])
    assert r.status_code == 400 and "حساب مصروف" in r.get_data(as_text=True)


def test_a_failed_posting_is_a_message_and_rolls_everything_back(eapp, expense):
    """A payment method pointing at an aggregate account: post_journal refuses."""
    from app.extensions import db
    from app.models import Account, PaymentMethod
    c, A, eid = expense
    with eapp.app_context():
        parent = Account(school_id=A["school"].id, code="1199", name="تجميعي", type="asset", is_postable=False)
        db.session.add(parent)
        db.session.flush()
        pm = PaymentMethod(school_id=A["school"].id, name="مجمع", kind="immediate_bank", account_id=parent.id)
        db.session.add(pm)
        db.session.commit()
        pm_id = pm.id
        db.session.remove()
    before, entries = _row(eapp, eid), _entries(eapp, A)
    r = _post(eapp, c, A, eid, payment_method_id=pm_id, amount="700")
    assert r.status_code == 400 and "تجميعي" in r.get_data(as_text=True)
    assert _row(eapp, eid) == before and _entries(eapp, A) == entries


def test_a_pending_expense_edits_without_posting(eapp, world, login_as):
    """Editing must not slip past the approval step."""
    from app.extensions import db
    from app.models import Expense
    A = world["A"]
    w = _client(eapp, login_as, _user_with_default_role(eapp, A, "warehouse"), A)
    w.post("/finance/expenses/new", base_url=host(A), data=_form(eapp, A, reference="PEND-1"))
    with eapp.app_context():
        eid = Expense.query.filter_by(reference="PEND-1").one().id
        db.session.remove()
    before = _entries(eapp, A)
    c = _client(eapp, login_as, _user_with_default_role(eapp, A, "accountant"), A)
    r = _post(eapp, c, A, eid, amount="90", reference="PEND-1")
    assert r.status_code == 200
    row = _row(eapp, eid)
    assert (row["amount"], row["status"], row["je"]) == (Decimal("90"), "pending", None)
    assert _entries(eapp, A) == before


def test_an_expense_with_a_voucher_cannot_be_deleted(eapp, expense):
    c, A, eid = expense
    cash = _balance(eapp, A, "1101")
    assert f"/finance/expenses/{hid(eid)}/delete" not in c.get(
        "/finance/expenses?start=2026-01-01&end=2026-12-31", base_url=host(A)).get_data(as_text=True)
    with foreign_keys_on(eapp):
        r = c.post(f"/finance/expenses/{hid(eid)}/delete", base_url=host(A), follow_redirects=True)
    assert r.status_code == 200 and "صحّحه من" in r.get_data(as_text=True)
    assert _row(eapp, eid)["status"] == "approved" and _balance(eapp, A, "1101") == cash


def _set_threshold(app, A, value):
    from app.extensions import db
    from app.models import School
    with app.app_context():
        db.session.get(School, A["school"].id).approval_threshold = value
        db.session.commit()
        db.session.remove()


def _vouchers(app, eid):
    from app.extensions import db
    from app.models import ReceiptVoucher
    with app.app_context():
        out = [(Decimal(str(v.amount)), v.notes) for v in ReceiptVoucher.query.filter_by(expense_id=eid)]
        db.session.remove()
    return out


def test_raising_past_the_threshold_goes_back_to_approval(eapp, expense):
    c, A, eid = expense
    _set_threshold(eapp, A, 1000)
    cash = _balance(eapp, A, "1101")
    r = _post(eapp, c, A, eid, amount="1500")
    assert "حد الاعتماد" in r.get_data(as_text=True)
    row = _row(eapp, eid)
    assert (row["status"], row["je"], row["amount"]) == ("pending", None, Decimal("1500"))
    assert _balance(eapp, A, "1101") == cash + 500          # the old 500 is back
    assert _balance(eapp, A, "5101") == 0
    # the approver posts it, with one voucher
    with foreign_keys_on(eapp):
        assert c.post(f"/finance/expenses/{hid(eid)}/approve", base_url=host(A)).status_code == 302
    assert _row(eapp, eid)["status"] == "approved"
    assert _balance(eapp, A, "1101") == cash + 500 - 1500 and _balance(eapp, A, "5101") == Decimal("1500")
    assert [v[0] for v in _vouchers(eapp, eid)] == [Decimal("1500")]


def test_rejecting_one_sent_back_marks_its_voucher_and_keeps_the_money_out(eapp, expense):
    c, A, eid = expense
    _set_threshold(eapp, A, 1000)
    cash = _balance(eapp, A, "1101")
    _post(eapp, c, A, eid, amount="1500")
    assert c.post(f"/finance/expenses/{hid(eid)}/reject", base_url=host(A), data={"reason": "مبلغ خطأ"}).status_code == 302
    assert _row(eapp, eid)["status"] == "rejected" and _balance(eapp, A, "1101") == cash + 500
    assert "مبلغ خطأ" in _vouchers(eapp, eid)[0][1]         # kept, marked


def test_below_or_lowering_or_already_over_stays_posted(eapp, expense):
    c, A, eid = expense
    _set_threshold(eapp, A, 1000)
    _post(eapp, c, A, eid, amount="900")                    # below it
    assert _row(eapp, eid)["status"] == "approved"
    _set_threshold(eapp, A, 500)
    _post(eapp, c, A, eid, amount="800")                    # over it but lowered
    assert _row(eapp, eid)["status"] == "approved"
    _post(eapp, c, A, eid, date="2026-03-01", amount="800")  # same amount, other date
    assert _row(eapp, eid)["status"] == "approved"


def _pending(app, login_as, A, reference="PEND-UI"):
    from app.extensions import db
    from app.models import Expense
    w = _client(app, login_as, _user_with_default_role(app, A, "warehouse"), A)
    w.post("/finance/expenses/new", base_url=host(A), data=_form(app, A, reference=reference))
    with app.app_context():
        eid = Expense.query.filter_by(reference=reference).one().id
        db.session.remove()
    return w, eid


def test_the_list_lets_the_approver_act_and_only_the_approver(eapp, world, login_as):
    A = world["A"]
    w, eid = _pending(eapp, login_as, A)
    url = "/finance/expenses?start=2026-01-01&end=2026-12-31"
    body = w.get(url, base_url=host(A)).get_data(as_text=True)
    assert "بانتظار الاعتماد" in body and f"/finance/expenses/{hid(eid)}/approve" not in body
    assert w.post(f"/finance/expenses/{hid(eid)}/approve", base_url=host(A)).status_code == 403
    acc = _client(eapp, login_as, _user_with_default_role(eapp, A, "accountant"), A)
    body = acc.get(url, base_url=host(A)).get_data(as_text=True)
    assert f"/finance/expenses/{hid(eid)}/approve" in body and f"/finance/expenses/{hid(eid)}/reject" in body
    r = acc.post(f"/finance/expenses/{hid(eid)}/approve", base_url=host(A), follow_redirects=True)
    assert r.status_code == 200 and "تم اعتماد المصروف" in r.get_data(as_text=True)
    assert _row(eapp, eid)["status"] == "approved"


def test_a_pending_expense_without_a_voucher_can_still_be_deleted(eapp, world, login_as):
    from app.extensions import db
    from app.models import Expense
    A = world["A"]
    _w, eid = _pending(eapp, login_as, A)
    acc = _client(eapp, login_as, _user_with_default_role(eapp, A, "accountant"), A)
    with foreign_keys_on(eapp):
        assert acc.post(f"/finance/expenses/{hid(eid)}/delete", base_url=host(A)).status_code == 302
    with eapp.app_context():
        assert db.session.get(Expense, eid) is None
        db.session.remove()


def test_pending_expenses_are_not_counted_as_spent(eapp, world, login_as):
    A = world["A"]
    _w, _eid = _pending(eapp, login_as, A)
    acc = _client(eapp, login_as, _user_with_default_role(eapp, A, "accountant"), A)
    body = acc.get("/finance/expenses?start=2026-02-01&end=2026-02-28", base_url=host(A)).get_data(as_text=True)
    i = body.index("إجمالي المصروفات")
    assert "500.00" not in body[i:i + 500]
    from datetime import date
    from app.blueprints.dashboard.routes import _expenses_sum
    from app.extensions import db
    from app.services.reports import cost_per_student
    with eapp.app_context():
        assert _expenses_sum(A["school"].id, date(2026, 2, 1)) == 0
        assert cost_per_student(A["school"].id, start=date(2026, 2, 1), end=date(2026, 2, 28))["total_expense"] == 0
        db.session.remove()


def test_a_quote_in_the_description_cannot_break_into_the_script(eapp, world, login_as):
    A = world["A"]
    w = _client(eapp, login_as, _user_with_default_role(eapp, A, "warehouse"), A)
    w.post("/finance/expenses/new", base_url=host(A), data=_form(eapp, A, description="x');alert(1);('"))
    acc = _client(eapp, login_as, _user_with_default_role(eapp, A, "accountant"), A)
    body = acc.get("/finance/expenses?start=2026-01-01&end=2026-12-31", base_url=host(A)).get_data(as_text=True)
    import re
    assert "alert(1)" not in "".join(re.findall(r'onsubmit="([^"]*)"', body))


@pytest.mark.parametrize("role", ["teacher", "student", "parent"])
def test_without_the_permission_it_is_403(eapp, expense, login_as, role):
    _c, A, eid = expense
    c = _client(eapp, login_as, A["users"][role], A)
    before = _row(eapp, eid)
    assert c.get(f"/finance/expenses/{hid(eid)}/edit", base_url=host(A)).status_code == 403
    assert c.post(f"/finance/expenses/{hid(eid)}/edit", base_url=host(A), data=_form(eapp, A)).status_code == 403
    assert _row(eapp, eid) == before


def test_foreign_keys_are_really_on_in_these_tests(eapp):
    from app.extensions import db
    with foreign_keys_on(eapp), eapp.app_context():
        assert db.session.execute(text("PRAGMA foreign_keys")).scalar() == 1
        db.session.remove()
