"""SAAS-033 — platform billing: invoices, payments, renewal from payment,
PDF, notices, and the finance reports.

Money is Decimal everywhere. An issued invoice is frozen: corrections
are void (with a reason) + a new invoice; nothing is ever deleted. The
"overdue" status is computed (issued / partially_paid past due_date),
never stored. Numbers are MNS-<year>-<NNNN>, sequential without gaps,
taken under a named lock at issue time.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from ..extensions import db

CENT = Decimal("0.01")
OPEN = ("issued", "partially_paid")


MAX_AMOUNT = Decimal("1000000000000")      # 10^12: far above any real invoice


class BillingError(ValueError):
    """Arabic, shown on the console."""


def money(v) -> Decimal:
    from decimal import InvalidOperation
    try:
        d = Decimal(str(v if v not in (None, "") else "0"))
    except (InvalidOperation, ValueError):
        raise BillingError("قيمة مالية غير صالحة.") from None
    if not d.is_finite() or abs(d) >= MAX_AMOUNT:
        raise BillingError("قيمة مالية غير صالحة.")
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


def lock_invoice(inv) -> None:
    """Serialise every write on one invoice and re-read it, so two
    parallel submits can't both pass the status / outstanding checks."""
    from .locks import transaction_lock
    transaction_lock(f"platform-invoice-{inv.id}")
    db.session.refresh(inv)
    for p in inv.payments:
        db.session.refresh(p)


# ─── invoices ───────────────────────────────────────────────────────

def recompute(inv) -> None:
    subtotal = Decimal("0")
    for line in inv.lines:
        line.amount = money(Decimal(str(line.qty)) * money(line.unit_price))
        subtotal += line.amount
    inv.subtotal = money(subtotal)
    inv.tax_amount = money(inv.subtotal * Decimal(str(inv.tax_rate or 0)) / 100)
    inv.total = money(inv.subtotal + inv.tax_amount)


def create_invoice(school, user, *, currency: str, lines: list[dict], tax_rate=0, notes=None):
    """A draft. lines: [{description, qty, unit_price, plan_id?, period_start?, period_end?}]"""
    from ..models import PlatformInvoice, PlatformInvoiceLine
    if not lines:
        raise BillingError("الفاتورة محتاجة سطر واحد على الأقل.")
    currency = (currency or "").strip().upper()
    if not currency or len(currency) > 8:
        raise BillingError("العملة مطلوبة.")
    rate = money(tax_rate)
    if not Decimal("0") <= rate <= Decimal("100"):
        raise BillingError("نسبة الضريبة من 0 إلى 100.")
    inv = PlatformInvoice(school_id=school.id, status="draft", currency=currency, tax_rate=rate,
                          notes=notes, created_by_platform_user_id=getattr(user, "id", None))
    for spec in lines:
        qty, price = money(spec.get("qty") or 1), money(spec.get("unit_price"))
        if qty <= 0 or price < 0 or not (spec.get("description") or "").strip():
            raise BillingError("كل سطر محتاج وصف وكمية موجبة وسعر غير سالب.")
        ps, pe = spec.get("period_start"), spec.get("period_end")
        if (ps is None) != (pe is None) or (ps and pe < ps):
            raise BillingError("فترة الاشتراك غير صحيحة.")
        inv.lines.append(PlatformInvoiceLine(description=spec["description"].strip()[:255], qty=qty,
                                             unit_price=price, plan_id=spec.get("plan_id"),
                                             period_start=ps, period_end=pe))
    recompute(inv)
    db.session.add(inv)
    db.session.flush()
    return inv


def subscription_line(school, plan, today: date | None = None) -> dict:
    """A line pre-filled from the plan and the next period."""
    from .subscriptions import add_months, current_subscription, get_settings, platform_today
    today = today or platform_today(get_settings())
    cur = current_subscription(school.id)
    start = today if cur is None or cur.ends_on is None or cur.ends_on < today else cur.ends_on + timedelta(days=1)
    months = 12 if plan.billing_cycle == "yearly" else 1
    end = add_months(start, months) - timedelta(days=1)
    return {"description": f"اشتراك {plan.name_ar} ({start} → {end})", "qty": 1,
            "unit_price": plan.price_amount or 0, "plan_id": plan.id,
            "period_start": start, "period_end": end}


def _next_number(year: int) -> str:
    from ..models import PlatformInvoice
    prefix = f"MNS-{year}-"
    nums = [int(n.rsplit("-", 1)[1]) for (n,) in db.session.query(PlatformInvoice.number)
            .filter(PlatformInvoice.number.like(prefix + "%"))
            if n and n.rsplit("-", 1)[1].isdigit()]
    n = max(nums) + 1 if nums else 1
    return f"{prefix}{n:04d}"


def issue(inv, user, *, issue_date: date | None = None, due_days: int = 14) -> None:
    """Freeze the invoice and give it its number (gapless, under a lock)."""
    from .locks import transaction_lock
    from .platform_auth import audit
    from .subscriptions import get_settings, platform_today
    if int(due_days) < 0 or int(due_days) > 365:
        raise BillingError("مدة السداد لازم تكون بين 0 و365 يوم.")
    # Held until the caller's commit: the next issuer waits and then sees
    # this number (no duplicates, no gaps). Status is checked after the
    # lock, on a fresh read, so a double submit can't issue twice.
    transaction_lock("platform-invoice-number")
    lock_invoice(inv)
    if inv.status != "draft":
        raise BillingError("الفاتورة صادرة بالفعل.")
    issue_date = issue_date or platform_today(get_settings())
    inv.number = _next_number(issue_date.year)
    inv.issue_date = issue_date
    inv.due_date = issue_date + timedelta(days=int(due_days))
    inv.status = "issued" if inv.total > 0 else "paid"       # free / grant invoice
    db.session.flush()
    audit("invoice_issued", user, school_id=inv.school_id, invoice=inv.number, total=str(inv.total))
    defer(_notice_new_invoice, inv)


def void(inv, user, reason: str) -> None:
    from .platform_auth import audit
    if not (reason or "").strip():
        raise BillingError("سبب الإلغاء مطلوب.")
    lock_invoice(inv)
    if inv.status == "void":
        raise BillingError("الفاتورة ملغاة بالفعل.")
    if paid_amount(inv) > 0:
        raise BillingError("ألغِ الدفعات بدفعة عكسية قبل إلغاء الفاتورة.")
    inv.status = "void"
    inv.void_reason = reason.strip()
    audit("invoice_voided", user, school_id=inv.school_id, invoice=inv.number or inv.id, reason=reason.strip())


def paid_amount(inv) -> Decimal:
    return money(sum((money(p.amount) for p in inv.payments), Decimal("0")))


def outstanding(inv) -> Decimal:
    return money(money(inv.total) - paid_amount(inv))


def is_overdue(inv, today: date) -> bool:
    return inv.status in OPEN and inv.due_date is not None and today > inv.due_date


def _refresh_status(inv) -> None:
    paid = paid_amount(inv)
    if inv.status == "void":
        return
    inv.status = "paid" if paid >= money(inv.total) else ("partially_paid" if paid > 0 else "issued")


# ─── payments (+ renewal, atomically) ───────────────────────────────

def record_payment(inv, user, *, amount, paid_on: date, method: str, reference=None, notes=None,
                   renew: bool = False, today: date | None = None):
    """One transaction: the payment and (optionally) the renewal the
    invoice's subscription line describes. The caller commits; any
    failure rolls both back."""
    from ..models import PlatformPayment
    from ..models.platform_billing import PAYMENT_METHODS
    from .platform_auth import audit
    lock_invoice(inv)
    if inv.status not in OPEN:
        raise BillingError("الفاتورة مش مفتوحة للدفع.")
    amount = money(amount)
    if amount <= 0:
        raise BillingError("المبلغ لازم يكون موجب.")
    if amount > outstanding(inv):
        raise BillingError(f"المبلغ أكبر من المتبقي ({outstanding(inv)}).")
    if method not in PAYMENT_METHODS:
        raise BillingError("طريقة دفع غير معروفة.")
    p = PlatformPayment(invoice_id=inv.id, amount=amount, paid_on=paid_on, method=method,
                        reference=(reference or None), notes=notes,
                        recorded_by_platform_user_id=getattr(user, "id", None))
    db.session.add(p)
    inv.payments.append(p)
    _refresh_status(inv)
    audit("payment_recorded", user, school_id=inv.school_id, invoice=inv.number, amount=str(amount))
    if renew:
        renew_from_invoice(inv, user, today=today)
    db.session.flush()
    defer(_notice, inv.school, "payment_confirmed",
          f"تم استلام دفعة {amount} {inv.currency} للفاتورة {inv.number}.", day=paid_on)
    return p


def reverse_payment(payment, user, reason: str):
    from ..models import PlatformPayment
    from .platform_auth import audit
    if not (reason or "").strip():
        raise BillingError("سبب الإلغاء مطلوب.")
    lock_invoice(payment.invoice)
    if money(payment.amount) <= 0 or payment.reverses_payment_id is not None:
        raise BillingError("الدفعة دي مش قابلة للعكس.")
    if PlatformPayment.query.filter_by(reverses_payment_id=payment.id).first() is not None:
        raise BillingError("الدفعة اتعكست قبل كده.")
    inv = payment.invoice
    from .subscriptions import get_settings, platform_today
    r = PlatformPayment(invoice_id=inv.id, amount=-money(payment.amount),
                        paid_on=max(payment.paid_on, platform_today(get_settings())),
                        method=payment.method, notes=reason.strip(), reverses_payment_id=payment.id,
                        recorded_by_platform_user_id=getattr(user, "id", None))
    db.session.add(r)
    inv.payments.append(r)
    _refresh_status(inv)
    audit("payment_reversed", user, school_id=inv.school_id, invoice=inv.number, payment_id=payment.id)
    return r


def renew_from_invoice(inv, user, today: date | None = None):
    """Extend from the current end (or from today if it already ended)
    by the length of the invoice's subscription period."""
    from . import subscriptions as subs
    line = next((ln for ln in inv.lines if ln.period_start and ln.period_end), None)
    if line is None:
        raise BillingError("الفاتورة مفيهاش سطر اشتراك.")
    school = inv.school
    from ..models import SchoolSubscriptionEvent
    if SchoolSubscriptionEvent.query.filter_by(school_id=school.id, kind="renewed",
                                               reason=f"invoice {inv.number}").first() is not None:
        return                      # this invoice already renewed once
    today = today or subs.platform_today(subs.get_settings())
    cur = subs.current_subscription(school.id)
    if cur is None:
        raise BillingError("لا يوجد اشتراك حالي.")
    start, period_from = subs.renewal_dates(cur, today)
    length = (line.period_end - line.period_start).days
    new_end = period_from + timedelta(days=length)
    fields = {"starts_on": start, "ends_on": new_end, "trial_ends_on": None}
    if line.plan_id:
        fields["plan_id"] = line.plan_id
    subs._replace(school.id, user, **fields)
    subs._event(school.id, "renewed", str(cur.ends_on or "∞"), str(new_end), f"invoice {inv.number}", user)


# ─── PDF ────────────────────────────────────────────────────────────

def platform_dir():
    from pathlib import Path
    from .file_storage import upload_root
    d = Path(upload_root()) / "_platform" / "invoices"
    d.mkdir(parents=True, exist_ok=True)
    return d


def render_pdf(inv) -> tuple[bytes, str]:
    """(bytes, mimetype). WeasyPrint like the school invoices; printable
    HTML when it isn't available."""
    from flask import render_template
    from .subscriptions import get_settings
    html = render_template("superadmin/invoice_pdf.html", inv=inv, company=company_settings(get_settings()),
                           paid=paid_amount(inv), outstanding=outstanding(inv))
    try:
        from weasyprint import HTML
        return HTML(string=html).write_pdf(), "application/pdf"
    except Exception:  # noqa: BLE001 — missing native deps
        return html.encode("utf-8"), "text/html"


def store_pdf(inv) -> str:
    import os
    data, mime = render_pdf(inv)
    name = f"{inv.number or inv.id}.{'pdf' if mime == 'application/pdf' else 'html'}"
    path = platform_dir() / name
    path.write_bytes(data)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    inv.pdf_path = name
    return name


COMPANY_KEYS = ("company_legal_name", "company_tax_number", "company_address", "company_bank_details",
                "company_default_tax_rate")


def company_settings(settings: dict) -> dict:
    return {k: settings.get(k) or "" for k in COMPANY_KEYS}


# ─── notices (SAAS-033 §3) ──────────────────────────────────────────

def recipients(school) -> list[str]:
    from ..models import SchoolContact
    billing = [c.email for c in SchoolContact.query.filter_by(school_id=school.id, is_billing_contact=True)
               if c.email]
    if billing:
        return billing
    return [school.email] if school.email else []


def emails_enabled() -> bool:
    from flask import current_app
    return bool(current_app.config.get("PLATFORM_EMAILS_ENABLED"))


def allowed(addr: str) -> bool:
    """Outside production only the allow-list may receive anything."""
    from flask import current_app
    allow = current_app.config.get("PLATFORM_EMAIL_ALLOWLIST")
    if allow is None:
        return True
    return addr.strip().lower() in allow


def _notice(school, kind: str, body: str, *, day: date | None = None) -> bool:
    """Send one notice kind per school per day (idempotent); every send or
    failure is a reminder_sent / reminder_failed event."""
    from ..models import SchoolSubscriptionEvent
    from . import platform_mailer
    from .subscriptions import _event, get_settings, platform_today
    day = day or platform_today(get_settings())
    key = f"{kind}:{day.isoformat()}"
    if SchoolSubscriptionEvent.query.filter_by(school_id=school.id, kind="reminder_sent", to_value=key).first():
        return False
    if not emails_enabled() or not platform_mailer.is_configured():
        return False
    targets = [a for a in recipients(school) if allowed(a)]
    if not targets:
        return False
    ok = True
    for addr in targets:
        one = f"{key}|{addr.strip().lower()}"
        if SchoolSubscriptionEvent.query.filter_by(school_id=school.id, kind="reminder_sent",
                                                   to_value=one).first():
            continue                # this recipient already got it today
        try:
            platform_mailer.send(addr, f"منصتي — {school.name}", body)
        except platform_mailer.PlatformMailError:
            ok = False
            continue
        _event(school.id, "reminder_sent", None, one, None, None)
    _event(school.id, "reminder_sent" if ok else "reminder_failed", None, key, None, None)
    return ok


def defer(fn, *args, **kw) -> None:
    """Queue a notice for after the commit (send_deferred)."""
    db.session.info.setdefault("_billing_deferred", []).append((fn, args, kw))


def drop_deferred() -> None:
    db.session.info.pop("_billing_deferred", None)


def send_deferred() -> None:
    """Call right after the commit: sends the queued notices (each one
    records its own event) and commits those events. A failure is logged,
    never surfaced — the money transaction is already safe."""
    from flask import current_app
    queued = db.session.info.pop("_billing_deferred", [])
    for fn, args, kw in queued:
        try:
            fn(*args, **kw)
            db.session.commit()
        except Exception:  # noqa: BLE001
            db.session.rollback()
            current_app.logger.exception("billing — deferred notice failed")


def _notice_new_invoice(inv):
    _notice(inv.school, f"invoice_new_{inv.number}",
            f"صدرت فاتورة جديدة {inv.number} بمبلغ {inv.total} {inv.currency}، تستحق في {inv.due_date}.")


REMINDER_TEXT = {
    "expiring": "اشتراك مدرستك على منصتي بينتهي خلال {days} يوم.",
    "expires_today": "اشتراك مدرستك على منصتي بينتهي النهارده.",
    "grace": "اشتراك مدرستك انتهى، والنظام للقراءة فقط. متبقي {days} يوم قبل الإيقاف.",
    "blocked": "اشتراك مدرستك متوقف. تواصل مع الدعم للتجديد.",
}


def send_due_notices(today: date | None = None) -> dict:
    """Called by `flask subscriptions-tick`: subscription reminders and
    overdue invoices. A failure for one school never stops the rest."""
    from flask import current_app
    from ..models import PlatformInvoice, School
    from .subscriptions import (current_subscription, due_reminder, effective_state, get_settings,
                                platform_today)
    settings = get_settings()
    today = today or platform_today(settings)
    out = {"sent": 0, "failed": 0}
    for school in School.query.filter(School.status != "archived").all():
        try:
            st = effective_state(school, current_subscription(school.id), today, settings)
            rem = due_reminder(st, settings)
            sent = False
            if rem:
                days = rem.get("days_left", rem.get("grace_days_left"))
                sent = _notice(school, rem["kind"], REMINDER_TEXT[rem["kind"]].format(days=days), day=today)
            elif st.blocked and st.state in ("expired",):
                sent = _notice(school, "blocked", REMINDER_TEXT["blocked"], day=today)
            for inv in PlatformInvoice.query.filter(PlatformInvoice.school_id == school.id,
                                                    PlatformInvoice.status.in_(OPEN)):
                if is_overdue(inv, today):
                    sent = _notice(school, f"invoice_overdue_{inv.number}",
                                   f"الفاتورة {inv.number} متأخرة (تستحق {inv.due_date}). المتبقي "
                                   f"{outstanding(inv)} {inv.currency}.", day=today) or sent
            db.session.commit()
            out["sent"] += int(bool(sent))
        except Exception:  # noqa: BLE001
            db.session.rollback()
            current_app.logger.exception("billing notices failed for school %s", school.id)
            out["failed"] += 1
    return out


# ─── reports (§4) ───────────────────────────────────────────────────

def report(today: date) -> dict:
    """Everything per currency — no conversion in this version."""
    from collections import defaultdict
    from ..models import PlatformInvoice, PlatformPayment, School, SchoolSubscription
    from .subscriptions import current_subscription
    rows = PlatformInvoice.query.filter(PlatformInvoice.status != "void").all()
    aging = defaultdict(lambda: {"0-30": Decimal("0"), "31-60": Decimal("0"), "60+": Decimal("0")})
    overdue = []
    for inv in rows:
        if is_overdue(inv, today):
            age = (today - inv.due_date).days
            bucket = "0-30" if age <= 30 else ("31-60" if age <= 60 else "60+")
            aging[inv.currency][bucket] += outstanding(inv)
            overdue.append((inv, age))
    collected = defaultdict(lambda: defaultdict(Decimal))
    for p in PlatformPayment.query.all():
        collected[p.invoice.currency][p.paid_on.strftime("%Y-%m")] += money(p.amount)
    mrr = defaultdict(Decimal)
    for sub in SchoolSubscription.query.filter_by(is_current=True).all():
        plan = sub.plan
        if plan is None or not plan.price_amount or (sub.ends_on is not None and sub.ends_on < today):
            continue
        monthly = money(plan.price_amount) / (12 if plan.billing_cycle == "yearly" else 1)
        mrr[plan.currency or "—"] += money(monthly)
    expiring = {}
    for days in (30, 60):
        lim = today + timedelta(days=days)
        expiring[days] = [s for s in School.query.filter(School.status != "archived").all()
                          if (cur := current_subscription(s.id)) is not None and cur.ends_on is not None
                          and today <= cur.ends_on <= lim]
    return {"aging": {k: dict(v) for k, v in aging.items()}, "overdue": overdue,
            "collected": {k: dict(sorted(v.items())) for k, v in collected.items()},
            "mrr": dict(mrr), "arr": {k: money(v * 12) for k, v in mrr.items()}, "expiring": expiring}


def statement(school_id: int):
    from ..models import PlatformInvoice
    invs = (PlatformInvoice.query.filter_by(school_id=school_id)
            .order_by(PlatformInvoice.id).all())
    return [{"invoice": i, "paid": paid_amount(i), "outstanding": outstanding(i)} for i in invs]
