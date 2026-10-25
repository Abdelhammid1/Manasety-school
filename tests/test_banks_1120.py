"""Banks under 1120: 1120 is an aggregate; a bank's name under it
(1120-NN, aggregate); its accounts under the bank, coded with the real
account number (postable). Banks are found by their place in the tree,
never by a 112 prefix."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from isolation_harness import host


@pytest.fixture
def bapp(app, two_schools, monkeypatch):
    from app.extensions import db
    from app.models.finance import ensure_default_chart
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    with app.app_context():
        for k in ("A", "B"):
            ensure_default_chart(two_schools[k]["school"].id)
        db.session.commit()
        db.session.remove()
    return app


def _admin(app, login_as, bundle, role="admin"):
    c = app.test_client()
    login_as(c, bundle["users"][role], base_url=host(bundle))
    return c


def _acct(app, sid, code):
    from app.extensions import db
    from app.models import Account
    with app.app_context():
        a = Account.query.filter_by(school_id=sid, code=code).first()
        out = None if a is None else {"id": a.id, "code": a.code, "is_postable": a.is_postable,
                                      "parent_id": a.parent_id, "type": a.type, "name": a.name}
        db.session.remove()
    return out


def _new(c, bundle, parent_id, name, code="", type_="asset"):
    return c.post("/finance/accounts/new", base_url=host(bundle), follow_redirects=True,
                  data={"parent_id": parent_id, "name": name, "code": code, "type": type_})


def _bank_with_account(app, c, bundle, number="4501237789"):
    sid = bundle["school"].id
    root = _acct(app, sid, "1120")
    _new(c, bundle, root["id"], "بنك CIB")
    bank = _acct(app, sid, "1120-01")
    _new(c, bundle, bank["id"], "حساب جاري", code=number)
    return bank, _acct(app, sid, number.strip().upper())


def _post(app, sid, debit_code, credit_code, amount):
    from app.extensions import db
    from app.models import Account, JournalEntry, JournalLine
    with app.app_context():
        d = Account.query.filter_by(school_id=sid, code=debit_code).one()
        cr = Account.query.filter_by(school_id=sid, code=credit_code).one()
        e = JournalEntry(school_id=sid, entry_date=date.today(), description="test")
        db.session.add(e); db.session.flush()
        db.session.add_all([JournalLine(entry_id=e.id, account_id=d.id, debit=Decimal(amount), credit=0),
                            JournalLine(entry_id=e.id, account_id=cr.id, debit=0, credit=Decimal(amount))])
        db.session.commit()
        db.session.remove()


# ─── the chart ──────────────────────────────────────────────────────

def test_1120_is_an_aggregate_and_ensure_default_chart_keeps_it(bapp, two_schools):
    from app.extensions import db
    from app.models.finance import ensure_default_chart
    sid = two_schools["A"]["school"].id
    assert _acct(bapp, sid, "1120")["is_postable"] is False
    with bapp.app_context():
        ensure_default_chart(sid); ensure_default_chart(sid)
        db.session.commit(); db.session.remove()
    assert _acct(bapp, sid, "1120")["is_postable"] is False


def test_1120_is_offered_as_a_parent(bapp, two_schools, login_as):
    A = two_schools["A"]
    body = _admin(bapp, login_as, A).get("/finance/accounts/new", base_url=host(A)).get_data(as_text=True)
    root = _acct(bapp, A["school"].id, "1120")
    assert f'value="{root["id"]}"' in body and 'data-position="bank"' in body


# ─── adding a bank and its accounts ─────────────────────────────────

def test_a_bank_then_its_account(bapp, two_schools, login_as):
    A = two_schools["A"]
    sid = A["school"].id
    c = _admin(bapp, login_as, A)
    root = _acct(bapp, sid, "1120")
    assert c.get(f"/finance/accounts/suggest-code?parent_id={root['id']}", base_url=host(A)).get_json() \
        == {"code": "1120-01", "manual": False, "position": "bank"}
    bank, acct = _bank_with_account(bapp, c, A, number=" 4501237789 ")
    assert bank["is_postable"] is False and bank["parent_id"] == root["id"] and bank["type"] == "asset"
    assert acct["is_postable"] is True and acct["parent_id"] == bank["id"] and acct["type"] == "asset"
    # under a bank: no suggestion, the number is typed
    assert c.get(f"/finance/accounts/suggest-code?parent_id={bank['id']}", base_url=host(A)).get_json() \
        == {"code": "", "manual": True, "position": "bank_account"}
    # the second bank gets 1120-02; an IBAN is upper-cased
    _new(c, A, root["id"], "بنك الراجحي")
    rajhi = _acct(bapp, sid, "1120-02")
    _new(c, A, rajhi["id"], "حساب جاري", code="sa0380000000608010167519")
    assert _acct(bapp, sid, "SA0380000000608010167519")["is_postable"] is True
    # the tree shows them nested
    page = c.get("/finance/accounts", base_url=host(A)).get_data(as_text=True)
    assert page.index("1120-01") < page.index("4501237789") < page.index("1120-02")


def test_the_type_comes_from_the_parent_not_the_form(bapp, two_schools, login_as):
    A = two_schools["A"]
    c = _admin(bapp, login_as, A)
    root = _acct(bapp, A["school"].id, "1120")
    _new(c, A, root["id"], "بنك مصر", type_="revenue")
    assert _acct(bapp, A["school"].id, "1120-01")["type"] == "asset"


@pytest.mark.parametrize("bad", ["", "   ", "4501 237789", "45012@37789", "حساب", "X" * 31])
def test_a_bad_account_number_is_refused(bapp, two_schools, login_as, bad):
    from app.extensions import db
    from app.models import Account
    A = two_schools["A"]
    c = _admin(bapp, login_as, A)
    root = _acct(bapp, A["school"].id, "1120")
    _new(c, A, root["id"], "بنك CIB")
    bank = _acct(bapp, A["school"].id, "1120-01")
    body = _new(c, A, bank["id"], "حساب جاري", code=bad).get_data(as_text=True)
    assert "رقم الحساب البنكي مطلوب" in body
    with bapp.app_context():
        assert Account.query.filter_by(school_id=A["school"].id, parent_id=bank["id"]).count() == 0
        db.session.remove()


def test_a_used_number_says_so(bapp, two_schools, login_as):
    A = two_schools["A"]
    c = _admin(bapp, login_as, A)
    bank, _ = _bank_with_account(bapp, c, A)
    body = _new(c, A, bank["id"], "حساب آخر", code="4501237789").get_data(as_text=True)
    assert "الكود مستخدم بالفعل" in body


def test_the_rest_of_the_chart_keeps_its_rules(bapp, two_schools, login_as):
    A = two_schools["A"]
    sid = A["school"].id
    c = _admin(bapp, login_as, A)
    for parent_code, type_ in (("5100", "expense"), ("4100", "revenue"), ("2100", "liability")):
        parent = _acct(bapp, sid, parent_code)
        code = c.get(f"/finance/accounts/suggest-code?parent_id={parent['id']}", base_url=host(A)).get_json()["code"]
        _new(c, A, parent["id"], f"حساب تحت {parent_code}", type_=type_)
        assert _acct(bapp, sid, code)["is_postable"] is True          # depth rule, as before
    root = _acct(bapp, sid, "1000")
    code = c.get(f"/finance/accounts/suggest-code?parent_id={root['id']}", base_url=host(A)).get_json()["code"]
    _new(c, A, root["id"], "مجموعة جديدة")
    assert _acct(bapp, sid, code)["is_postable"] is False
    # the prefix warning still fires outside the banks tree
    body = _new(c, A, _acct(bapp, sid, "5100")["id"], "كود غريب", code="9999", type_="expense").get_data(as_text=True)
    assert "لا يبدأ برقم تصنيف الأب" in body


def test_view_only_and_other_schools_cannot_add(bapp, two_schools, login_as):
    A, B = two_schools["A"], two_schools["B"]
    root_a = _acct(bapp, A["school"].id, "1120")
    t = _admin(bapp, login_as, A, role="teacher")
    assert t.get("/finance/accounts/new", base_url=host(A)).status_code in (302, 403, 404)
    assert _new(t, A, root_a["id"], "بنك").status_code in (403, 404) or _acct(bapp, A["school"].id, "1120-01") is None
    assert _acct(bapp, A["school"].id, "1120-01") is None
    # B's admin naming A's 1120 as the parent: refused, nothing in either school
    b = _admin(bapp, login_as, B)
    body = _new(b, B, root_a["id"], "بنك").get_data(as_text=True)
    assert "الحساب الأب غير موجود" in body
    assert _acct(bapp, A["school"].id, "1120-01") is None and _acct(bapp, B["school"].id, "1120-01") is None


# ─── balances: treasury, dashboard, reports ─────────────────────────

def test_a_bank_balance_shows_once_everywhere(bapp, two_schools, login_as):
    from app.extensions import db
    from app.models import Account
    from app.services import bank_accounts as banks
    from app.services.reports import cash_flow
    A = two_schools["A"]
    sid = A["school"].id
    c = _admin(bapp, login_as, A)
    _bank_with_account(bapp, c, A, number="4501237789")
    root = _acct(bapp, sid, "1120")
    _new(c, A, root["id"], "بنك الأهلي")
    ahly = _acct(bapp, sid, "1120-02")
    _new(c, A, ahly["id"], "حساب توفير", code="1100000001")      # starts with 11 by chance
    _post(bapp, sid, "4501237789", "3100", "1000")
    _post(bapp, sid, "1100000001", "3100", "250")
    _post(bapp, sid, "1110", "3100", "40")
    with bapp.test_request_context():
        assert Account.query.filter_by(school_id=sid, code="1120").one().balance == 1250
        assert Account.query.filter_by(school_id=sid, code="1120-01").one().balance == 1000
        assert [a.code for a in banks.bank_accounts(sid)] == ["1100000001", "4501237789"]
        assert "1100000001" not in [a.code for a in banks.cash_accounts(sid)]
        ids = banks.cash_and_bank_ids(sid)
        total = sum(a.balance for a in Account.query.filter(Account.id.in_(ids)).all())
        assert total == 1290                                        # not doubled
        flow = cash_flow(sid)
        assert flow["total_in"] == Decimal("1290")
        assert sorted(r["code"] for r in flow["rows"]) == ["1100000001", "1110", "4501237789"]
        from app.blueprints.dashboard.routes import _cash_on_hand
        assert _cash_on_hand(sid) == 1290
        db.session.remove()
    page = c.get("/finance/treasury", base_url=host(A)).get_data(as_text=True)
    assert page.count("4501237789") >= 1 and "1250" in page.replace(",", "")
    # B sees none of it
    with bapp.test_request_context():
        assert banks.bank_accounts(two_schools["B"]["school"].id) == []
        db.session.remove()


def test_lines_already_on_1120_still_count(bapp, two_schools, login_as):
    """1120 had postings before it became an aggregate: they stay and count."""
    from app.extensions import db
    from app.models import Account
    A = two_schools["A"]
    sid = A["school"].id
    with bapp.app_context():
        Account.query.filter_by(school_id=sid, code="1120").one().is_postable = True
        db.session.commit(); db.session.remove()
    _post(bapp, sid, "1120", "3100", "300")
    with bapp.app_context():
        Account.query.filter_by(school_id=sid, code="1120").one().is_postable = False
        db.session.commit(); db.session.remove()
    c = _admin(bapp, login_as, A)
    _bank_with_account(bapp, c, A)
    _post(bapp, sid, "4501237789", "3100", "1000")
    with bapp.test_request_context():
        assert Account.query.filter_by(school_id=sid, code="1120").one().balance == 1300
        db.session.remove()
    root = _acct(bapp, sid, "1120")
    page = c.get(f"/finance/accounts/{root['id']}/statement", base_url=host(A)).get_data(as_text=True)
    assert "300" in page


# ─── payment methods ────────────────────────────────────────────────

def test_a_bank_account_can_back_a_payment_method_and_a_header_cannot(bapp, two_schools, login_as):
    from app.extensions import db
    from app.models import PaymentMethod
    A = two_schools["A"]
    sid = A["school"].id
    c = _admin(bapp, login_as, A)
    bank, acct = _bank_with_account(bapp, c, A)
    page = c.get("/finance/payment-methods", base_url=host(A)).get_data(as_text=True)
    assert "4501237789" in page and "بنك CIB" not in page
    c.post("/finance/payment-methods/new", base_url=host(A),
           data={"name": "تحويل CIB", "kind": "immediate_bank", "account_id": acct["id"]})
    c.post("/finance/payment-methods/new", base_url=host(A),
           data={"name": "على البنك نفسه", "kind": "immediate_bank", "account_id": bank["id"]})
    with bapp.app_context():
        assert PaymentMethod.query.filter_by(school_id=sid, name="تحويل CIB").one().account_id == acct["id"]
        assert PaymentMethod.query.filter_by(school_id=sid, name="على البنك نفسه").first() is None
        db.session.remove()


# ─── the migration ──────────────────────────────────────────────────

def test_the_migration_is_idempotent_and_keeps_every_row():
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    import importlib.util
    import pathlib
    spec = importlib.util.spec_from_file_location(
        "m", pathlib.Path(__file__).parent.parent / "migrations/versions/f7a9b1c3d5e7_banks_under_1120.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    eng = sa.create_engine("sqlite://")
    with eng.begin() as conn:
        conn.execute(sa.text("CREATE TABLE accounts (id INTEGER PRIMARY KEY, school_id INTEGER, code VARCHAR(16) "
                             "NOT NULL, parent_id INTEGER, is_postable BOOLEAN NOT NULL)"))
        conn.execute(sa.text("INSERT INTO accounts VALUES (1,1,'1100',NULL,0),(2,1,'1120',1,1),(3,2,'1100',NULL,0),"
                             "(4,2,'1120',3,0),(5,3,'1110',NULL,1)"))
        import alembic.op as op_mod
        ops = Operations(MigrationContext.configure(conn))
        for _ in range(2):
            op_mod._proxy = ops                                      # alembic's `op` → this connection
            mod.upgrade()
        rows = conn.execute(sa.text("SELECT id, code, is_postable FROM accounts ORDER BY id")).all()
        assert [(r[0], r[1], bool(r[2])) for r in rows] == [
            (1, "1100", False), (2, "1120", False), (3, "1100", False), (4, "1120", False), (5, "1110", True)]
        conn.execute(sa.text("INSERT INTO accounts VALUES (6,1,'1120-01',2,0)"))
        mod.downgrade()
        rows = dict(conn.execute(sa.text("SELECT id, is_postable FROM accounts")).all())
        assert bool(rows[2]) is False and bool(rows[4]) is True      # 1120 with a child stays aggregate
