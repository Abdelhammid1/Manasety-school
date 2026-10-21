"""SAAS-033 — platform billing: gapless numbering (also concurrent),
frozen issued invoices, partial / excess payments, reversal, payment +
renewal atomicity with boundary dates, notice idempotence and the e-mail
allow-list, role access, and no billing data on a school host."""

from __future__ import annotations

import secrets
import threading
from datetime import date, timedelta
from decimal import Decimal

import pytest

from isolation_harness import host
from test_saas026_subscriptions import CONSOLE, _console_client, console  # noqa: F401


@pytest.fixture(autouse=True)
def _clean(console):
    yield
    from app.extensions import db
    from app.models import PlatformInvoice, PlatformInvoiceLine, PlatformPayment, SchoolContact
    with console.app_context():
        PlatformPayment.query.filter(PlatformPayment.reverses_payment_id.isnot(None)).delete()
        PlatformPayment.query.delete()
        PlatformInvoiceLine.query.delete()
        PlatformInvoice.query.delete()
        SchoolContact.query.delete()
        db.session.commit()
        db.session.remove()


def _school(app, bundle):
    from app.extensions import db
    from app.models import School
    return db.session.get(School, bundle["school"].id)


def _draft(app, bundle, amount="1000", **kw):
    from app.services import billing
    return billing.create_invoice(_school(app, bundle), None, currency="EGP",
                                  lines=[{"description": "اشتراك", "qty": 1, "unit_price": amount}], **kw)


def test_totals_are_decimal(console, two_schools):
    with console.app_context():
        inv = _draft(console, two_schools["A"], amount="333.33", tax_rate="14")
        assert inv.subtotal == Decimal("333.33") and inv.tax_amount == Decimal("46.67")
        assert inv.total == Decimal("380.00")


def test_numbering_sequential_and_frozen(console, two_schools):
    from app.extensions import db
    from app.services import billing
    with console.app_context():
        a, b = _draft(console, two_schools["A"]), _draft(console, two_schools["B"])
        billing.issue(a, None, issue_date=date(2027, 1, 5))
        billing.issue(b, None, issue_date=date(2027, 2, 1))
        assert (a.number, b.number) == ("MNS-2027-0001", "MNS-2027-0002")
        with pytest.raises(billing.BillingError):
            billing.issue(a, None)
        c = _draft(console, two_schools["A"])
        billing.issue(c, None, issue_date=date(2028, 1, 1))
        assert c.number == "MNS-2028-0001"
        db.session.commit()


def test_concurrent_issue_never_duplicates(console, two_schools):
    from app.extensions import db
    from app.services import billing
    with console.app_context():
        ids = [_draft(console, two_schools["A"]).id for _ in range(4)]
        db.session.commit()
        db.session.remove()
    errors, barrier = [], threading.Barrier(4)

    def worker(iid):
        from app.models import PlatformInvoice
        with console.app_context():
            try:
                barrier.wait()
                billing.issue(db.session.get(PlatformInvoice, iid), None, issue_date=date(2029, 3, 1))
                db.session.commit()
            except Exception as e:  # noqa: BLE001
                db.session.rollback()
                errors.append(e)
            finally:
                db.session.remove()
    ts = [threading.Thread(target=worker, args=(i,)) for i in ids]
    for t in ts:
        t.start()
    for t in ts:
        t.join(30)
    from app.models import PlatformInvoice
    with console.app_context():
        numbers = sorted(i.number for i in PlatformInvoice.query.filter(PlatformInvoice.id.in_(ids)))
    assert not errors, errors
    assert numbers == [f"MNS-2029-{n:04d}" for n in range(1, 5)]


def test_partial_excess_and_reversal(console, two_schools):
    from app.extensions import db
    from app.services import billing
    with console.app_context():
        inv = _draft(console, two_schools["A"])
        billing.issue(inv, None)
        with pytest.raises(billing.BillingError):
            billing.record_payment(inv, None, amount="1000.01", paid_on=date.today(), method="cash")
        p = billing.record_payment(inv, None, amount="400", paid_on=date.today(), method="bank_transfer")
        assert inv.status == "partially_paid" and billing.outstanding(inv) == Decimal("600.00")
        billing.record_payment(inv, None, amount="600", paid_on=date.today(), method="cash")
        assert inv.status == "paid"
        with pytest.raises(billing.BillingError):
            billing.record_payment(inv, None, amount="1", paid_on=date.today(), method="cash")
        billing.reverse_payment(p, None, "wrong amount")
        assert inv.status == "partially_paid" and billing.outstanding(inv) == Decimal("400.00")
        with pytest.raises(billing.BillingError):
            billing.reverse_payment(p, None, "twice")
        with pytest.raises(billing.BillingError):
            billing.void(inv, None, "x")           # still has payments
        db.session.commit()


def test_free_invoice_needs_no_payment(console, two_schools):
    from app.services import billing
    with console.app_context():
        inv = _draft(console, two_schools["A"], amount="0")
        billing.issue(inv, None)
        assert inv.status == "paid" and inv.total == 0


def _sub_invoice(console, bundle, start, end):
    from app.services import billing
    return billing.create_invoice(_school(console, bundle), None, currency="EGP", lines=[{
        "description": "اشتراك سنة", "qty": 1, "unit_price": "1200",
        "period_start": start, "period_end": end}])


def _set_sub(console, bundle, ends_on):
    from app.extensions import db
    from app.services.subscriptions import current_subscription
    sub = current_subscription(bundle["school"].id)
    sub.starts_on, sub.ends_on = date(2026, 1, 1), ends_on
    db.session.flush()


@pytest.mark.parametrize("cur_end,today,new_start", [
    (date(2026, 12, 31), date(2026, 12, 1), date(2027, 1, 1)),    # active: paid period from the end
    (date(2026, 12, 31), date(2026, 12, 31), date(2027, 1, 1)),   # last day
    (date(2026, 12, 31), date(2027, 1, 1), date(2027, 1, 1)),     # ended yesterday → today
    (date(2026, 10, 1), date(2026, 12, 1), date(2026, 12, 1)),    # long expired → today
])
def test_payment_renews_from_end_or_today(console, two_schools, cur_end, today, new_start):
    from app.extensions import db
    from app.services import billing
    from app.services.subscriptions import current_subscription
    A = two_schools["A"]
    with console.app_context():
        _set_sub(console, A, cur_end)
        inv = _sub_invoice(console, A, date(2027, 1, 1), date(2027, 12, 31))
        billing.issue(inv, None, issue_date=today)
        billing.record_payment(inv, None, amount="1200", paid_on=today, method="cash", renew=True, today=today)
        from app.services.subscriptions import effective_state
        cur = current_subscription(A["school"].id)
        assert cur.ends_on == new_start + timedelta(days=364)
        assert cur.starts_on <= today                          # never "not_started" after paying
        assert effective_state(A["school"], cur, today).state == "active"
        db.session.rollback()


def test_an_invoice_renews_once_across_instalments(console, two_schools):
    """Audit: every instalment with "renew" used to extend again."""
    from app.extensions import db
    from app.services import billing
    from app.services.subscriptions import current_subscription
    A = two_schools["A"]
    today = date(2026, 12, 1)
    with console.app_context():
        _set_sub(console, A, date(2026, 12, 31))
        inv = _sub_invoice(console, A, date(2027, 1, 1), date(2027, 12, 31))
        billing.issue(inv, None, issue_date=today)
        billing.record_payment(inv, None, amount="600", paid_on=today, method="cash", renew=True, today=today)
        end = current_subscription(A["school"].id).ends_on
        billing.record_payment(inv, None, amount="600", paid_on=today, method="cash", renew=True, today=today)
        assert current_subscription(A["school"].id).ends_on == end
        db.session.rollback()


@pytest.mark.parametrize("bad", ["abc", "NaN", "Infinity", "1e999999"])
def test_bad_amounts_are_a_form_error(bad):
    from app.services import billing
    with pytest.raises(billing.BillingError):
        billing.money(bad)


def test_payment_and_renewal_are_atomic(console, two_schools, monkeypatch):
    from app.extensions import db
    from app.models import PlatformPayment
    from app.services import billing
    from app.services.subscriptions import current_subscription
    A = two_schools["A"]
    with console.app_context():
        inv = _sub_invoice(console, A, date(2027, 1, 1), date(2027, 12, 31))
        billing.issue(inv, None)
        db.session.commit()
        before = current_subscription(A["school"].id).id
        monkeypatch.setattr(billing, "renew_from_invoice",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        with pytest.raises(RuntimeError):
            billing.record_payment(inv, None, amount="1200", paid_on=date.today(), method="cash", renew=True)
        db.session.rollback()
        assert PlatformPayment.query.filter_by(invoice_id=inv.id).count() == 0
        assert current_subscription(A["school"].id).id == before


# ─── notices ─────────────────────────────────────────────────────────

def test_notices_once_per_day_and_allowlist(console, two_schools, monkeypatch):
    from app.extensions import db
    from app.models import SchoolContact, SchoolSubscriptionEvent
    from app.services import billing, platform_mailer
    sent = []
    monkeypatch.setattr(platform_mailer, "is_configured", lambda: True)
    monkeypatch.setattr(platform_mailer, "send", lambda to, subj, body: sent.append(to))
    monkeypatch.setitem(console.config, "PLATFORM_EMAILS_ENABLED", True)
    monkeypatch.setitem(console.config, "PLATFORM_EMAIL_ALLOWLIST", frozenset({"ok@alpha.test"}))
    A = two_schools["A"]
    with console.app_context():
        db.session.add(SchoolContact(school_id=A["school"].id, name="x", email="ok@alpha.test",
                                     is_billing_contact=True))
        db.session.add(SchoolContact(school_id=A["school"].id, name="y", email="real-customer@else.test",
                                     is_billing_contact=True))
        _set_sub(console, A, date(2026, 12, 31))
        db.session.commit()
        day = date(2026, 12, 24)               # 7 days left → a reminder day
        billing.send_due_notices(day)
        billing.send_due_notices(day)          # second run the same day
        assert sent == ["ok@alpha.test"]
        assert SchoolSubscriptionEvent.query.filter_by(school_id=A["school"].id, kind="reminder_sent").count() == 1
        db.session.remove()


def test_notices_off_by_default(console, two_schools, monkeypatch):
    from app.services import billing, platform_mailer
    sent = []
    monkeypatch.setattr(platform_mailer, "is_configured", lambda: True)
    monkeypatch.setattr(platform_mailer, "send", lambda *a: sent.append(a))
    monkeypatch.setitem(console.config, "PLATFORM_EMAILS_ENABLED", False)
    with console.app_context():
        billing.send_due_notices(date(2026, 12, 24))
    assert sent == []


# ─── console + isolation ─────────────────────────────────────────────

def test_console_flow_and_roles(console, two_schools):
    from app.models import PlatformInvoice
    A = two_schools["A"]
    fin, _ = _console_client(console, "finance")
    r = fin.post(f"/superadmin/schools/{A['school'].id}/invoices/new", base_url=CONSOLE,
                 data={"currency": "EGP", "tax_rate": "0", "desc": ["خدمة"], "qty": ["2"], "price": ["50"]})
    assert r.status_code == 302
    with console.app_context():
        inv = PlatformInvoice.query.filter_by(school_id=A["school"].id).one()
        iid = inv.id
    fin.post(f"/superadmin/invoices/{iid}/issue", base_url=CONSOLE, data={"due_days": "10"})
    page = fin.get(f"/superadmin/invoices/{iid}", base_url=CONSOLE)
    assert page.status_code == 200 and b"MNS-" in page.data
    assert fin.get(f"/superadmin/invoices/{iid}/pdf", base_url=CONSOLE).status_code == 200
    assert fin.get("/superadmin/billing/report", base_url=CONSOLE).status_code == 200
    csv = fin.get("/superadmin/billing/report?format=csv", base_url=CONSOLE)
    assert csv.status_code == 200 and csv.mimetype == "text/csv"
    sup, _ = _console_client(console, "support")
    for path in ("/superadmin/billing", f"/superadmin/invoices/{iid}", "/superadmin/billing/report",
                 f"/superadmin/schools/{A['school'].id}/statement", "/superadmin/settings/company"):
        assert sup.get(path, base_url=CONSOLE).status_code == 403, path


def test_billing_never_on_a_school_host(console, two_schools, login_as):
    A = two_schools["A"]
    c = console.test_client()
    login_as(c, A["users"]["admin"], base_url=host(A))
    for path in ("/superadmin/billing", "/superadmin/invoices/1"):
        assert c.get(path, base_url=host(A)).status_code == 404
