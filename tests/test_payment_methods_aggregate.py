"""Payment methods left on an aggregate account (after 1120 became one):
the migration moves each onto the single postable account under it (or
logs it), the screens show such a method disabled with the reason, and
it can't be created on or switched back on to an aggregate."""

from __future__ import annotations

import importlib.util
import pathlib
from datetime import date
from decimal import Decimal

import pytest
import sqlalchemy as sa

from isolation_harness import hid, host
from test_banks_1120 import _acct, _admin, _bank_with_account, bapp  # noqa: F401

MIGRATION = pathlib.Path(__file__).parent.parent / "migrations/versions/j1e3f5a7b9c1_payment_methods_off_aggregates.py"


def _migration():
    spec = importlib.util.spec_from_file_location("m_pm", MIGRATION)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def _method(app, sid, name, account_code, kind="immediate_bank", active=True):
    from app.extensions import db
    from app.models import Account, PaymentMethod
    with app.app_context():
        acct = Account.query.filter_by(school_id=sid, code=account_code).one() if account_code else None
        pm = PaymentMethod(school_id=sid, name=name, kind=kind, account_id=acct.id if acct else None,
                           is_active=active)
        db.session.add(pm); db.session.commit(); pid = pm.id
        db.session.remove()
    return pid


# ─── the migration (raw SQL, like production) ───────────────────────

@pytest.fixture
def mdb():
    eng = sa.create_engine("sqlite://")
    with eng.begin() as conn:
        conn.execute(sa.text("CREATE TABLE accounts (id INTEGER PRIMARY KEY, school_id INTEGER, code VARCHAR(30), "
                             "parent_id INTEGER, is_postable BOOLEAN)"))
        conn.execute(sa.text("CREATE TABLE payment_methods (id INTEGER PRIMARY KEY, school_id INTEGER, "
                             "account_id INTEGER, deleted_at TIMESTAMP)"))
        conn.execute(sa.text(
            "INSERT INTO accounts VALUES "
            # school 1: 1120 → one bank → one account
            "(1,1,'1120',NULL,0),(2,1,'1120-01',1,0),(3,1,'4501237789',2,1),"
            # school 2: 1120 → two accounts (ambiguous)
            "(10,2,'1120',NULL,0),(11,2,'1120-01',10,0),(12,2,'111',11,1),(13,2,'222',11,1),"
            # school 3: 1120 with nothing under it
            "(20,3,'1120',NULL,0),"
            # school 4: no 1120 at all; a postable cash account
            "(30,4,'1110',NULL,1)"))
        conn.execute(sa.text(
            "INSERT INTO payment_methods VALUES (1,1,1,NULL),(2,2,10,NULL),(3,3,20,NULL),(4,4,30,NULL),"
            "(5,1,1,'2026-01-01')"))                                   # deleted: left alone
    return eng


def test_the_migration_moves_one_logs_the_rest_and_runs_twice(mdb, caplog):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    import alembic.op as op_mod
    mod = _migration()
    with mdb.begin() as conn:
        op_mod._proxy = Operations(MigrationContext.configure(conn))
        with caplog.at_level("INFO", logger="alembic.runtime.migration"):
            mod.upgrade()
            mod.upgrade()
        rows = dict(conn.execute(sa.text("SELECT id, account_id FROM payment_methods")).all())
        mod.downgrade()                                                # a documented no-op
        assert dict(conn.execute(sa.text("SELECT id, account_id FROM payment_methods")).all()) == rows
    assert rows == {1: 3, 2: 10, 3: 20, 4: 30, 5: 1}
    text = " | ".join(caplog.messages)
    assert "school_id=2 payment_method_id=2" in text and "2 postable accounts" in text
    assert "school_id=3 payment_method_id=3" in text and "no postable account" in text
    assert text.count("payment method moved") == 1                    # the second run changed nothing


# ─── the screens ────────────────────────────────────────────────────

def test_a_method_on_an_aggregate_shows_disabled_with_the_reason(bapp, two_schools, login_as):
    from app.extensions import db
    from app.models import Account
    A = two_schools["A"]
    sid = A["school"].id
    with bapp.app_context():
        Account.query.filter_by(school_id=sid, code="1120").one().is_postable = False
        db.session.commit(); db.session.remove()
    bad = _method(bapp, sid, "تحويل قديم", "1120")
    good = _method(bapp, sid, "نقدي", "1110", kind="immediate_cash")
    c = _admin(bapp, login_as, A)
    page = c.get(f"/finance/invoices/{hid(_invoice(bapp, A))}", base_url=host(A)).get_data(as_text=True)
    assert f'<option value="{bad}" disabled>تحويل قديم — اربطها بحساب بنك قابل للترحيل</option>' in page
    assert f'<option value="{good}">نقدي</option>' in page
    body = c.get("/finance/expenses/new", base_url=host(A)).get_data(as_text=True)
    assert f'value="{bad}" disabled' in body
    # every payment-method select (collect, refund, bulk payment, expense,
    # employee advance, payroll) carries the same guard
    tdir = pathlib.Path(__file__).parent.parent / "app" / "templates"
    for name in ("finance/invoice_detail.html", "finance/bulk_payment.html", "finance/expense_form.html",
                 "hr/employee_detail.html", "hr/payroll_detail.html"):
        text = (tdir / name).read_text(encoding="utf-8")
        assert text.count("for pm in payment_methods") == text.count("{% if not pm.usable %} disabled"), name
    listing = c.get("/finance/payment-methods", base_url=host(A)).get_data(as_text=True)
    assert "حساب تجميعي" in listing


def test_creating_or_reactivating_on_an_aggregate_is_refused(bapp, two_schools, login_as):
    from app.extensions import db
    from app.models import PaymentMethod
    A = two_schools["A"]
    sid = A["school"].id
    c = _admin(bapp, login_as, A)
    root = _acct(bapp, sid, "1120")
    body = c.post("/finance/payment-methods/new", base_url=host(A), follow_redirects=True,
                  data={"name": "على 1120", "kind": "immediate_bank", "account_id": root["id"]}).get_data(as_text=True)
    assert "قابلًا للترحيل" in body
    bad = _method(bapp, sid, "موقوفة على 1120", "1120", active=False)
    body = c.post(f"/finance/payment-methods/{hid(bad)}/toggle", base_url=host(A),
                  follow_redirects=True).get_data(as_text=True)
    assert "لا يمكن تفعيل طريقة الدفع" in body
    # a postable bank account works as before
    _, acct = _bank_with_account(bapp, c, A)
    c.post("/finance/payment-methods/new", base_url=host(A),
           data={"name": "CIB", "kind": "immediate_bank", "account_id": acct["id"]})
    with bapp.app_context():
        assert PaymentMethod.query.filter_by(school_id=sid, name="على 1120").first() is None
        assert PaymentMethod.query.filter_by(id=bad).one().is_active is False
        assert PaymentMethod.query.filter_by(school_id=sid, name="CIB").one().account_id == acct["id"]
        db.session.remove()


def test_collect_and_refund_through_a_postable_bank_account(bapp, two_schools, login_as):
    from app.extensions import db
    from app.models import Invoice, JournalLine
    A = two_schools["A"]
    sid = A["school"].id
    c = _admin(bapp, login_as, A)
    _, acct = _bank_with_account(bapp, c, A)
    pm = _method(bapp, sid, "CIB", "4501237789")
    inv = _invoice(bapp, A)
    c.post(f"/finance/invoices/{hid(inv)}/pay", base_url=host(A),
           data={"amount": "60", "payment_method_id": pm, "payment_date": date.today().isoformat()})
    c.post(f"/finance/invoices/{hid(inv)}/pay", base_url=host(A),
           data={"amount": "10", "payment_method_id": pm, "is_refund": "1",
                 "payment_date": date.today().isoformat()})
    with bapp.app_context():
        assert Decimal(db.session.get(Invoice, inv).paid_amount) == Decimal("50")
        lines = JournalLine.query.filter_by(account_id=acct["id"]).all()
        assert sum(Decimal(ln.debit or 0) - Decimal(ln.credit or 0) for ln in lines) == Decimal("50")
        db.session.remove()


def _invoice(app, bundle, amount="100"):
    """An invoice through the one creation path (ledger.create_invoice)."""
    from app.extensions import db
    from app.models import Account, FeeType
    from app.services import ledger
    from app.services.tenancy import tenant_context
    sid = bundle["school"].id
    with app.app_context(), tenant_context(sid):
        rev = Account.query.filter_by(school_id=sid, code="4110").one()
        ft = FeeType.query.filter_by(school_id=sid, name="رسوم اختبار").first()
        if ft is None:
            ft = FeeType(school_id=sid, name="رسوم اختبار", revenue_account_id=rev.id)
            db.session.add(ft); db.session.flush()
        inv = ledger.create_invoice(school_id=sid, enrollment_id=bundle["enrollment"].id,
                                    year_name=bundle["year"].name, fee_lines=[(ft.id, Decimal(amount))],
                                    issue_date=date.today(), due_date=date.today())
        db.session.commit(); iid = inv.id
        db.session.remove()
    return iid
