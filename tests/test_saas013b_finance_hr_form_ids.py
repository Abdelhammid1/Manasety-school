"""SAAS-013B — the last finance / HR form ids. The attacks (B's ids in A's
forms) live in FORM_ID_MATRIX (test_saas002); here: the same six
endpoints still work on A's own records (no regression), a foreign id
and a missing id look the same, and refused attempts leave the books of
both schools untouched."""

from __future__ import annotations

import pytest

from isolation_harness import host


@pytest.fixture
def fapp(app, monkeypatch):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    return app


def _client(app, login_as, A):
    c = app.test_client()
    login_as(c, A["users"]["admin"], base_url=host(A))
    return c


def _count(app, model, **kw):
    from app import models as M
    from app.extensions import db
    with app.app_context():
        n = getattr(M, model).query.filter_by(**kw).count()
        db.session.remove()
        return n


def test_fee_type_new_and_edit_work_on_own_records(fapp, world, login_as):
    A = world["A"]
    c = _client(fapp, login_as, A)
    before = _count(fapp, "FeeType", school_id=A["school"].id)
    r = c.post("/finance/fee-types/new", base_url=host(A),
               data={"name": "رسوم A جديدة", "default_amount": "5", "revenue_account_id": A["revenue_account"]})
    assert r.status_code == 302
    assert _count(fapp, "FeeType", school_id=A["school"].id) == before + 1
    r = c.post(f"/finance/fee-types/{A['fee_type']}/edit", base_url=host(A),
               data={"name": "رسوم A معدلة", "default_amount": "7", "revenue_account_id": A["revenue_account"]})
    assert r.status_code == 302
    from app.extensions import db
    from app.models import FeeType
    with fapp.app_context():
        assert db.session.get(FeeType, A["fee_type"]).name == "رسوم A معدلة"
        db.session.remove()


def test_payroll_new_works_for_own_employee(fapp, world, login_as):
    from app.extensions import db
    from app.models import Account
    A = world["A"]
    with fapp.app_context():          # the salary system account the view needs
        if not Account.query.filter_by(school_id=A["school"].id, code="5110").first():
            db.session.add(Account(school_id=A["school"].id, code="5110", name="رواتب", type="expense",
                                   is_postable=True))
            db.session.commit()
        db.session.remove()
    c = _client(fapp, login_as, A)
    before = _count(fapp, "Payroll", school_id=A["school"].id)
    r = c.post("/hr/payroll/new", base_url=host(A),
               data={"employee_id": A["employee"], "period_year": "2026", "period_month": "11",
                     "base_salary": "5000", "deductions": "0"})
    assert r.status_code in (200, 302)
    assert _count(fapp, "Payroll", school_id=A["school"].id) == before + 1


def test_foreign_and_missing_ids_look_the_same(fapp, world, login_as):
    """No enumeration: B's fee type and a fee type that doesn't exist give
    the same status and the same page."""
    A, B = world["A"], world["B"]
    c = _client(fapp, login_as, A)
    foreign = c.get(f"/finance/fee-types/{B['fee_type']}/edit", base_url=host(A))
    missing = c.get("/finance/fee-types/987654321/edit", base_url=host(A))
    assert foreign.status_code == missing.status_code == 404
    # the page echoes the requested path (canonical link) — the id itself is
    # the only difference allowed
    same = lambda r, i: r.get_data(as_text=True).replace(f"/fee-types/{i}/", "/fee-types/ID/")  # noqa: E731
    assert same(foreign, B["fee_type"]) == same(missing, 987654321)


@pytest.mark.parametrize("path,data", [
    ("/finance/fee-types/new", lambda A, B: {"name": "x", "revenue_account_id": B["revenue_account"]}),
    ("/finance/invoices/new", lambda A, B: {"enrollment_id": B["enrollment"].id,
                                            "fee_type_id": A["fee_type"], "amount": "10"}),
    ("/hr/payroll/new", lambda A, B: {"employee_id": B["employee"], "period_year": "2026",
                                      "period_month": "12", "base_salary": "1"}),
    ("/finance/quick-journal/capital_increase", lambda A, B: {"amount": "10",
                                                              "counter_account_id": B["account"]}),
])
def test_refused_attempts_leave_both_ledgers_untouched(fapp, world, login_as, path, data):
    from app.extensions import db
    from world import ledger_state
    A, B = world["A"], world["B"]
    pair = (A["school"].id, B["school"].id)
    with fapp.app_context():
        before = ledger_state(pair)
        db.session.remove()
    c = _client(fapp, login_as, A)
    r = c.post(path, base_url=host(A), data=data(A, B))
    assert r.status_code < 500
    with fapp.app_context():
        assert ledger_state(pair) == before
        db.session.remove()


def test_scoping_helper(fapp, world):
    from werkzeug.exceptions import NotFound
    from app.extensions import db
    from app.models import FeeType
    from app.services.scoping import owned_many_or_404, owned_or_404, owned_or_none
    from app.services.tenancy import tenant_context
    A, B = world["A"], world["B"]
    with fapp.app_context(), tenant_context(A["school"].id):
        assert owned_or_404(FeeType, A["fee_type"]).id == A["fee_type"]
        assert owned_or_none(FeeType, None) is None
        for bad in (B["fee_type"], 987654321, "abc"):
            with pytest.raises(NotFound):
                owned_or_404(FeeType, bad)
        assert [f.id for f in owned_many_or_404(FeeType, [A["fee_type"]])] == [A["fee_type"]]
        with pytest.raises(NotFound):                 # one foreign id = all refused
            owned_many_or_404(FeeType, [A["fee_type"], B["fee_type"]])
        db.session.remove()
