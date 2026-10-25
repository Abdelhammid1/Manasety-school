"""The school's financial settings take effect everywhere and lock after
the first financial activity (services/finance_settings)."""

from __future__ import annotations

import time
from datetime import date
from decimal import Decimal

import pytest

from isolation_harness import host
from test_saas026_subscriptions import CONSOLE, _console_client, console  # noqa: F401

SETTINGS_FORM = {"name": "x"}           # the settings page always posts the school name


@pytest.fixture
def fapp(console):
    console.config["WTF_CSRF_ENABLED"] = False
    return console


def _set(app, school_id, **values):
    from app.extensions import db
    from app.models import School
    with app.app_context():
        s = db.session.get(School, school_id)
        assert s is not None
        for k, v in values.items():
            setattr(s, k, v)
        db.session.commit(); db.session.remove()


def _school(app, school_id):
    from app.extensions import db
    from app.models import School
    with app.app_context():
        s = db.session.get(School, school_id)
        assert s is not None
        out = {k: getattr(s, k) for k in ("currency", "currency_symbol", "default_tax_rate",
                                           "fiscal_year_start_month", "invoice_prefix",
                                           "invoice_start_number", "rounding_policy", "name")}
        db.session.remove()
    return out


def _invoice(app, bundle, amount="100", installments=1):
    """Issue an invoice through the one creation path (ledger.create_invoice)."""
    from app.extensions import db
    from app.models import Account, FeeType
    from app.services import ledger
    from app.services.tenancy import tenant_context
    sid = bundle["school"].id
    with app.app_context(), tenant_context(sid):
        ft = FeeType.query.filter_by(school_id=sid, name="رسوم اختبار الإعدادات").first()
        if ft is None:
            acc = Account.query.filter_by(school_id=sid, code="4991").first()
            if acc is None:
                acc = Account(school_id=sid, code="4991", name="إيراد اختبار الإعدادات", type="revenue")
                db.session.add(acc); db.session.flush()
            ft = FeeType(school_id=sid, name="رسوم اختبار الإعدادات", is_taxable=True, revenue_account_id=acc.id)
            db.session.add(ft); db.session.flush()
        inv = ledger.create_invoice(school_id=sid, enrollment_id=bundle["enrollment"].id,
                                    year_name=bundle["year"].name, fee_lines=[(ft.id, Decimal(amount))],
                                    issue_date=date.today(), due_date=date.today(),
                                    installments_count=installments)
        db.session.commit()
        out = {"id": inv.id, "number": inv.number, "tax_rate": inv.tax_rate, "tax_amount": inv.tax_amount,
               "total": inv.total_amount, "rounding": inv.rounding_policy,
               "installments": sorted(i.amount for i in inv.installments)}
        db.session.remove()
    return out


def _admin(app, login_as, bundle):
    c = app.test_client()
    login_as(c, bundle["users"]["admin"], base_url=host(bundle))
    return c


# ─── settings take effect ───────────────────────────────────────────

def test_a_currency_change_shows_on_every_invoice_without_touching_amounts(fapp, two_schools, login_as):
    A, B = two_schools["A"], two_schools["B"]
    c = _admin(fapp, login_as, A)
    r = c.post("/admin/settings", base_url=host(A), data={**SETTINGS_FORM, "currency": "SAR", "currency_symbol": "ر.س"})
    assert r.status_code == 302 and _school(fapp, A["school"].id)["currency"] == "SAR"
    inv = _invoice(fapp, A)
    from flask import url_for
    with fapp.test_request_context():
        pages = [url_for("finance.invoice_detail", invoice_id=inv["id"]),
                 url_for("finance.invoice_print", invoice_id=inv["id"]),
                 url_for("finance.invoices_list")]
    for path in pages:
        body = c.get(path, base_url=host(A)).get_data(as_text=True)
        assert "ر.س" in body and "ج.م" not in body, path
    assert _school(fapp, B["school"].id)["currency"] != "SAR"                  # B untouched


def test_prefix_and_first_number_number_the_next_invoices(fapp, two_schools):
    A = two_schools["A"]
    _set(fapp, A["school"].id, invoice_prefix="TA-INV", invoice_start_number=1)
    old = _invoice(fapp, A)
    assert old["number"].startswith("TA-INV-")
    _set(fapp, A["school"].id, invoice_prefix="SCH", invoice_start_number=100)
    first, second = _invoice(fapp, A), _invoice(fapp, A)
    assert first["number"].startswith("SCH-") and first["number"].endswith("00100")
    assert second["number"].endswith("00101")
    from app.extensions import db
    from app.models import Invoice
    with fapp.app_context():
        assert db.session.get(Invoice, old["id"]).number == old["number"]       # old keeps its number
        db.session.remove()


def test_vat_applies_to_new_invoices_and_issued_ones_keep_theirs(fapp, two_schools):
    A = two_schools["A"]
    _set(fapp, A["school"].id, default_tax_rate=Decimal("14"))
    inv = _invoice(fapp, A, amount="200")
    assert inv["tax_rate"] == Decimal("14") and inv["tax_amount"] == Decimal("28.00") and inv["total"] == Decimal("228.00")
    _set(fapp, A["school"].id, default_tax_rate=Decimal("5"))
    from app.extensions import db
    from app.models import Invoice
    with fapp.app_context():
        again = db.session.get(Invoice, inv["id"])
        assert again.tax_rate == Decimal("14") and again.total_amount == Decimal("228.00")
        db.session.remove()


def test_the_rounding_policy_drives_every_split_and_is_kept_on_the_invoice(fapp, two_schools):
    from app.services.finance_settings import round_money
    assert round_money(Decimal("10.005"), "normal") == Decimal("10.01")
    assert round_money(Decimal("10.001"), "up") == Decimal("10.01")
    assert round_money(Decimal("10.009"), "down") == Decimal("10.00")
    A = two_schools["A"]
    _set(fapp, A["school"].id, rounding_policy="up", default_tax_rate=Decimal("0"))
    inv = _invoice(fapp, A, amount="100", installments=3)
    assert inv["rounding"] == "up"
    assert inv["installments"] == [Decimal("33.32"), Decimal("33.34"), Decimal("33.34")]   # sorted: the last absorbs the rest
    assert sum(inv["installments"]) == inv["total"]


def test_reports_start_at_the_fiscal_year(fapp, two_schools, login_as):
    from app.services.finance_settings import fiscal_year_start
    assert fiscal_year_start(date(2026, 10, 24), 9) == date(2026, 9, 1)
    assert fiscal_year_start(date(2026, 3, 1), 9) == date(2025, 9, 1)
    assert fiscal_year_start(date(2026, 3, 1), 1) == date(2026, 1, 1)
    A = two_schools["A"]
    _set(fapp, A["school"].id, fiscal_year_start_month=1)
    body = _admin(fapp, login_as, A).get("/finance/reports/trial-balance?end=2026-10-24",
                                         base_url=host(A)).get_data(as_text=True)
    assert "2026-01-01" in body


def test_invalid_values_are_refused_and_nothing_changes(fapp, two_schools, login_as):
    A = two_schools["A"]
    c = _admin(fapp, login_as, A)
    before = _school(fapp, A["school"].id)
    for bad in ({"currency": "TOOLONGISO"}, {"invoice_prefix": "P" * 17}, {"default_tax_rate": "-1"},
                {"default_tax_rate": "101"}, {"invoice_start_number": "0"}, {"rounding_policy": "sideways"}):
        r = c.post("/admin/settings", base_url=host(A), data={**SETTINGS_FORM, "name": "Changed", **bad},
                   follow_redirects=True)
        assert r.status_code == 200
        assert _school(fapp, A["school"].id) == before, bad                     # not even the name


def test_notifications_use_the_current_currency(fapp, two_schools, monkeypatch):
    from app.services import notifications as n
    A = two_schools["A"]
    _set(fapp, A["school"].id, currency_symbol="ر.س")
    sent = []
    monkeypatch.setattr(n, "send_push", lambda *a, **k: sent.append(k.get("body") or (a[2] if len(a) > 2 else "")) or 1)
    monkeypatch.setattr(n, "_push_to_parent_of", lambda *a, **k: sent.append(k.get("body") or a[3]) or 1, raising=False)
    with fapp.app_context():
        try:
            n._dispatch_push_for("invoice_issued", {"amount": 150, "student": "x"}, None, A["school"].id, 1)
        except Exception:  # noqa: BLE001 — only the text matters here
            pass
    assert any("150.00 ر.س" in str(s) for s in sent), sent
    assert not any("ج.س" in str(s) for s in sent)


# ─── the lock ───────────────────────────────────────────────────────

def test_before_any_activity_the_fields_are_open(fapp, two_schools, login_as):
    A = two_schools["A"]
    page = _admin(fapp, login_as, A).get("/admin/settings", base_url=host(A)).get_data(as_text=True)
    assert "<fieldset  data-fin-fields" in page or '<fieldset data-fin-fields' in page or "data-fin-fields" in page
    assert "disabled data-fin-fields" not in page and "مقفولة" not in page


def test_after_an_invoice_the_school_can_not_change_them(fapp, two_schools, login_as):
    A = two_schools["A"]
    _invoice(fapp, A)
    c = _admin(fapp, login_as, A)
    page = c.get("/admin/settings", base_url=host(A)).get_data(as_text=True)
    assert "disabled data-fin-fields" in page and "الإعدادات المالية مقفولة" in page
    before = _school(fapp, A["school"].id)
    r = c.post("/admin/settings", base_url=host(A), data={**SETTINGS_FORM, "currency": "USD"}, follow_redirects=True)
    assert "الإعدادات المالية مقفولة" in r.get_data(as_text=True)
    assert _school(fapp, A["school"].id) == before
    # the other tabs still save (the disabled fields aren't posted)
    r = c.post("/admin/settings", base_url=host(A), data={"name": "Alpha Renamed Locked"})
    assert r.status_code == 302 and _school(fapp, A["school"].id)["name"] == "Alpha Renamed Locked"
    _set(fapp, A["school"].id, name=before["name"])


def test_only_the_year_end_process_reopens_the_settings(fapp, two_schools):
    """Editable dates and statuses never unlock: a year flipped to "closed"
    or with its dates moved, an invoice back-dated. Only activity created
    before the last YEAR-CLOSE entry is left behind; new activity after
    it locks again."""
    from datetime import datetime, timedelta
    from app.extensions import db
    from app.models import AcademicYear, Invoice, JournalEntry
    from app.services.finance_settings import has_financial_activity
    A = two_schools["A"]
    inv = _invoice(fapp, A)
    sid = A["school"].id
    with fapp.app_context():
        assert has_financial_activity(sid)
        y = db.session.get(AcademicYear, A["year"].id)
        y.start_date, y.end_date, y.status = date(2020, 1, 1), date(2020, 1, 2), "closed"
        db.session.get(Invoice, inv["id"]).issue_date = date(2019, 1, 1)
        db.session.flush()
        assert has_financial_activity(sid)                          # nothing editable unlocks
        db.session.add(JournalEntry(school_id=sid, entry_date=date.today(), reference="YEAR-CLOSE-x",
                                    description="إقفال", related_kind="year_close", related_id=y.id,
                                    created_at=datetime.utcnow() + timedelta(seconds=1)))
        db.session.flush()
        assert not has_financial_activity(sid)                      # closed by the process
        db.session.add(JournalEntry(school_id=sid, entry_date=date(2019, 1, 1), reference="later",
                                    description="قيد", created_at=datetime.utcnow() + timedelta(seconds=5)))
        db.session.flush()
        assert has_financial_activity(sid)                          # new activity locks again
        db.session.rollback(); db.session.remove()


def test_manasety_changes_them_after_the_lock_and_it_is_audited(fapp, two_schools):
    from app.extensions import db
    from app.models import PlatformAuditLog
    A = two_schools["A"]
    _invoice(fapp, A)
    c, _uid = _console_client(fapp, "owner")
    with c.session_transaction(base_url=CONSOLE) as s:
        s["sa_totp_at"] = time.time()
    cur = _school(fapp, A["school"].id)
    form = {"name": cur["name"], "currency": "SAR", "currency_symbol": "ر.س",
            "invoice_prefix": cur["invoice_prefix"], "fiscal_year_start_month": str(cur["fiscal_year_start_month"]),
            "default_tax_rate": str(cur["default_tax_rate"]), "attendance_mode": "daily",
            "invoice_start_number": str(cur["invoice_start_number"]), "rounding_policy": cur["rounding_policy"]}
    r = c.post(f"/superadmin/schools/{A['school'].id}/edit", base_url=CONSOLE, data=form)
    assert r.status_code == 302
    assert _school(fapp, A["school"].id)["currency"] == "SAR"
    with fapp.app_context():
        log = (PlatformAuditLog.query.filter_by(action="school_edited", target_school_id=A["school"].id)
               .order_by(PlatformAuditLog.id.desc()).first())
        assert log.meta["after"]["currency"] == "SAR" and log.meta["before"]["currency"] == cur["currency"]
        db.session.remove()
    # rounding policy and first number are console-editable too
    bad = c.post(f"/superadmin/schools/{A['school'].id}/edit", base_url=CONSOLE,
                 data={**form, "rounding_policy": "sideways"})
    assert bad.status_code == 400
