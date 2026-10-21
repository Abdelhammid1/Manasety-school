"""SAAS-033 — platform billing screens (owner + finance; support sees
nothing financial)."""
from __future__ import annotations

import csv
import io
from datetime import date

from flask import Response, abort, flash, redirect, render_template, request, url_for

from . import bp, current_platform_user, require_platform_role
from ...extensions import db
from ...models import Plan, PlatformInvoice, PlatformPayment, PlatformSetting, School
from ...services import billing
from ...services import subscriptions as subs

FIN = ("owner", "finance")


def _inv(invoice_id):
    return db.session.get(PlatformInvoice, invoice_id) or abort(404)


def _date(raw, default=None):
    try:
        return date.fromisoformat(raw) if raw else default
    except ValueError:
        raise billing.BillingError("تاريخ غير صحيح.") from None


@bp.route("/billing", methods=["GET"], endpoint="billing")
@require_platform_role(*FIN)
def billing_home():
    today = subs.platform_today(subs.get_settings())
    rows = PlatformInvoice.query.order_by(PlatformInvoice.id.desc()).limit(300).all()
    return render_template("superadmin/billing.html", rows=rows, today=today, billing=billing)


@bp.route("/schools/<int:school_id>/invoices/new", methods=["GET", "POST"], endpoint="invoice_new")
@require_platform_role(*FIN)
def invoice_new(school_id):
    school = db.session.get(School, school_id) or abort(404)
    settings = subs.get_settings()
    plans = Plan.query.filter_by(is_active=True).order_by(Plan.code).all()
    if request.method == "POST":
        try:
            lines = []
            if request.form.get("plan_id"):
                plan = db.session.get(Plan, int(request.form["plan_id"])) or abort(400)
                lines.append(billing.subscription_line(school, plan))
            descs = request.form.getlist("desc")
            for i, d in enumerate(descs):
                if d.strip():
                    lines.append({"description": d, "qty": request.form.getlist("qty")[i] or 1,
                                  "unit_price": request.form.getlist("price")[i] or 0})
            cur = request.form.get("currency") or school.currency
            inv = billing.create_invoice(school, current_platform_user(), currency=cur, lines=lines,
                                         tax_rate=request.form.get("tax_rate") or settings.get("company_default_tax_rate") or 0,
                                         notes=(request.form.get("notes") or "").strip() or None)
        except (billing.BillingError, ValueError, IndexError) as e:
            db.session.rollback()
            flash(str(e) if isinstance(e, billing.BillingError) else "بيانات غير صحيحة.", "danger")
            return render_template("superadmin/invoice_new.html", school=school, plans=plans,
                                   settings=settings), 400
        db.session.commit()
        return redirect(url_for("superadmin.invoice_detail", invoice_id=inv.id))
    return render_template("superadmin/invoice_new.html", school=school, plans=plans, settings=settings)


@bp.route("/invoices/<int:invoice_id>", methods=["GET"], endpoint="invoice_detail")
@require_platform_role(*FIN)
def invoice_detail(invoice_id):
    inv = _inv(invoice_id)
    today = subs.platform_today(subs.get_settings())
    from ...models.platform_billing import PAYMENT_METHODS
    return render_template("superadmin/invoice.html", inv=inv, billing=billing, today=today,
                           methods=PAYMENT_METHODS)


def _act(invoice_id, fn, ok_msg):
    inv = _inv(invoice_id)
    try:
        fn(inv)
    except billing.BillingError as e:
        db.session.rollback()
        flash(str(e), "danger")
    else:
        db.session.commit()
        flash(ok_msg, "success")
    return redirect(url_for("superadmin.invoice_detail", invoice_id=inv.id))


@bp.route("/invoices/<int:invoice_id>/issue", methods=["POST"], endpoint="invoice_issue")
@require_platform_role(*FIN)
def invoice_issue(invoice_id):
    def go(inv):
        billing.issue(inv, current_platform_user(), due_days=int(request.form.get("due_days") or 14))
        billing.store_pdf(inv)
    return _act(invoice_id, go, "تم إصدار الفاتورة.")


@bp.route("/invoices/<int:invoice_id>/void", methods=["POST"], endpoint="invoice_void")
@require_platform_role(*FIN)
def invoice_void(invoice_id):
    return _act(invoice_id, lambda inv: billing.void(inv, current_platform_user(), request.form.get("reason")),
                "تم إلغاء الفاتورة.")


@bp.route("/invoices/<int:invoice_id>/payments", methods=["POST"], endpoint="invoice_payment")
@require_platform_role(*FIN)
def invoice_payment(invoice_id):
    def go(inv):
        billing.record_payment(
            inv, current_platform_user(), amount=request.form.get("amount"),
            paid_on=_date(request.form.get("paid_on"), subs.platform_today(subs.get_settings())),
            method=request.form.get("method") or "", reference=(request.form.get("reference") or "").strip(),
            notes=(request.form.get("notes") or "").strip() or None, renew=bool(request.form.get("renew")))
    return _act(invoice_id, go, "تم تسجيل الدفعة.")


@bp.route("/payments/<int:payment_id>/reverse", methods=["POST"], endpoint="payment_reverse")
@require_platform_role(*FIN)
def payment_reverse(payment_id):
    p = db.session.get(PlatformPayment, payment_id) or abort(404)
    return _act(p.invoice_id, lambda inv: billing.reverse_payment(p, current_platform_user(),
                                                                  request.form.get("reason")),
                "تم عكس الدفعة.")


@bp.route("/invoices/<int:invoice_id>/pdf", methods=["GET"], endpoint="invoice_pdf")
@require_platform_role(*FIN)
def invoice_pdf(invoice_id):
    inv = _inv(invoice_id)
    data, mime = billing.render_pdf(inv)
    ext = "pdf" if mime == "application/pdf" else "html"
    return Response(data, mimetype=mime, headers={
        "Content-Disposition": f'attachment; filename="{inv.number or inv.id}.{ext}"'})


@bp.route("/schools/<int:school_id>/statement", methods=["GET"], endpoint="school_statement")
@require_platform_role(*FIN)
def school_statement(school_id):
    school = db.session.get(School, school_id) or abort(404)
    return render_template("superadmin/statement.html", school=school, rows=billing.statement(school.id))


@bp.route("/billing/report", methods=["GET"], endpoint="billing_report")
@require_platform_role(*FIN)
def billing_report():
    today = subs.platform_today(subs.get_settings())
    rep = billing.report(today)
    if request.args.get("format") == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["section", "currency", "key", "value"])
        for cur, b in rep["aging"].items():
            for k, v in b.items():
                w.writerow(["aging", cur, k, v])
        for cur, months in rep["collected"].items():
            for m, v in months.items():
                w.writerow(["collected", cur, m, v])
        for cur, v in rep["mrr"].items():
            w.writerow(["mrr", cur, "", v])
            w.writerow(["arr", cur, "", rep["arr"][cur]])
        for inv, age in rep["overdue"]:
            w.writerow(["overdue", inv.currency, inv.number, f"{billing.outstanding(inv)} ({age}d)"])
        from ...services import platform_auth as pa
        pa.audit("billing_report_exported", current_platform_user())
        db.session.commit()
        return Response("﻿" + buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="billing-report.csv"'})
    return render_template("superadmin/billing_report.html", rep=rep, today=today, billing=billing)


@bp.route("/settings/company", methods=["GET", "POST"], endpoint="company_settings")
@require_platform_role(*FIN)
def company_settings():
    if request.method == "POST":
        from ...services import platform_auth as pa
        for key in billing.COMPANY_KEYS:
            row = db.session.get(PlatformSetting, key) or PlatformSetting(key=key)
            row.value = (request.form.get(key) or "").strip() or None
            row.updated_by = current_platform_user().id
            db.session.add(row)
        pa.audit("company_settings_changed", current_platform_user())
        db.session.commit()
        flash("تم الحفظ.", "success")
        return redirect(url_for("superadmin.company_settings"))
    return render_template("superadmin/company_settings.html",
                           values=billing.company_settings(subs.get_settings()))
