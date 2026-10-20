"""SAAS-013 — finance / HR isolation extras on top of the route matrix:
negative ids and a single-school regression run of the money paths."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from isolation_harness import host


@pytest.fixture
def fin_app(app, monkeypatch):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    return app


def _get_row(app, model, rid):
    from app import models as M
    from app.extensions import db
    from sqlalchemy import select
    cls = getattr(M, model)
    with app.app_context():
        row = db.session.execute(
            select(cls.__table__).where(cls.__table__.c.id == rid)).mappings().first()
        db.session.remove()
        return dict(row) if row else None


def _ledger(app, pair):
    from app.extensions import db
    from world import ledger_state
    with app.app_context():
        try:
            return ledger_state(pair)
        finally:
            db.session.remove()


# ─── Negatives ───────────────────────────────────────────────────────

def test_soft_deleted_record_of_other_school_is_404(fin_app, world, login_as):
    from app.extensions import db
    from app.models import Vendor
    A, B = world["A"], world["B"]
    with fin_app.app_context():
        v = db.session.get(Vendor, B["vendor"])
        assert v is not None
        v.deleted_at = datetime.now(timezone.utc)
        db.session.commit()
        db.session.remove()
    with fin_app.test_client() as c:
        login_as(c, A["users"]["admin"], base_url=host(A))
        for path in (f"/finance/vendors/{B['vendor']}",
                     f"/finance/vendors/{B['vendor']}/edit"):
            assert c.get(path, base_url=host(A)).status_code == 404, path


@pytest.mark.parametrize("path", [
    "/finance/invoices/999999", "/finance/vendors/999999",
    "/hr/employees/999999", "/hr/payroll/999999",
])
def test_nonexistent_id_is_404(fin_app, world, login_as, path):
    A = world["A"]
    with fin_app.test_client() as c:
        login_as(c, A["users"]["admin"], base_url=host(A))
        assert c.get(path, base_url=host(A)).status_code == 404


# ─── Regression: one school's money paths still work ─────────────────

def test_single_school_finance_flow(fin_app, world, login_as):
    """Pay, print and inspect inside school A. A's books move as
    expected and B's books do not move at all."""
    A, B = world["A"], world["B"]
    b_before = _ledger(fin_app, (B["school"].id,))
    a_before = _ledger(fin_app, (A["school"].id,))

    with fin_app.test_client() as c:
        login_as(c, A["users"]["admin"], base_url=host(A))

        r = c.post(f"/finance/invoices/{A['invoice']}/pay", base_url=host(A),
                   data={"amount": "40", "payment_method_id": A["payment_method"]})
        assert r.status_code == 302, r.status_code
        inv = _get_row(fin_app, "Invoice", A["invoice"])
        assert inv is not None
        assert Decimal(str(inv["paid_amount"])) == Decimal("40")

        r = c.get(f"/finance/invoices/{A['invoice']}/print", base_url=host(A))
        assert r.status_code == 200
        assert f"INV-{A['school'].slug}" in r.get_data(as_text=True)

        r = c.get(f"/finance/invoices/{A['invoice']}", base_url=host(A))
        assert r.status_code == 200

        r = c.get(f"/hr/payroll/{A['payroll']}", base_url=host(A))
        assert r.status_code == 200
        r = c.get(f"/hr/employees/{A['employee']}", base_url=host(A))
        assert r.status_code == 200

    a_after = _ledger(fin_app, (A["school"].id,))
    counts_before = a_before[0][3]
    counts_after = a_after[0][3]
    assert a_after[-1] == ("foreign_lines", 0)
    assert counts_after[0] > counts_before[0], "payment posted no journal entry"
    assert counts_after[1] == counts_before[1] + 1, "payment row not created"
    assert _ledger(fin_app, (B["school"].id,)) == b_before, "school B books moved"


def test_payment_journal_is_balanced(fin_app, world, login_as):
    A = world["A"]
    with fin_app.test_client() as c:
        login_as(c, A["users"]["admin"], base_url=host(A))
        c.post(f"/finance/invoices/{A['invoice']}/pay", base_url=host(A),
               data={"amount": "25", "payment_method_id": A["payment_method"]})
    from app.extensions import db
    from app.models import JournalEntry, JournalLine, Payment
    with fin_app.app_context():
        pay = Payment.query.filter_by(invoice_id=A["invoice"]).one()
        lines = JournalLine.query.filter_by(entry_id=pay.journal_entry_id).all()
        je = db.session.get(JournalEntry, pay.journal_entry_id)
        assert je is not None and je.school_id == A["school"].id
        assert sum(l.debit for l in lines) == sum(l.credit for l in lines) == Decimal("25")
        db.session.remove()


# ─── Central ledger guard ────────────────────────────────────────────

def test_post_journal_refuses_other_schools_account(fin_app, world):
    """Defence in depth under every route: a journal line may only hit
    the posting school's own accounts, and the error never names them."""
    from datetime import date
    from app.extensions import db
    from app.models import JournalEntry
    from app.services.accounting import post_journal
    A, B = world["A"], world["B"]
    with fin_app.test_request_context(base_url=host(A)):
        before = JournalEntry.query.count()
        with pytest.raises(ValueError) as exc:
            post_journal(A["school"].id, date(2026, 9, 9), "x", [
                (A["account"], Decimal("5"), Decimal("0"), None),
                (B["account"], Decimal("0"), Decimal("5"), None),
            ])
        db.session.rollback()
        assert "beta" not in str(exc.value)
        assert JournalEntry.query.count() == before
        db.session.remove()


def test_recurring_schedule_create_works(fin_app, world, login_as):
    """Was a 500 for every school: RECURRING_FREQUENCIES was not
    exported from app.models."""
    from app.models import RecurringFeeSchedule
    A = world["A"]
    with fin_app.test_client() as c:
        login_as(c, A["users"]["admin"], base_url=host(A))
        r = c.post("/finance/recurring/new", base_url=host(A),
                   data={"fee_type_id": A["fee_type"], "frequency": "termly",
                         "day_of_period": "3"})
        assert r.status_code == 302
    with fin_app.app_context():
        assert RecurringFeeSchedule.query.filter_by(
            school_id=A["school"].id, frequency="termly").count() == 1
