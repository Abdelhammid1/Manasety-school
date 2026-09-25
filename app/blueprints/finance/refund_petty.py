"""Ticket T5 — Refund approval workflow + Petty Cash management.

Refund workflow (SoD)
---------------------
- Any user with `finance_transactions.add` can FILE a RefundRequest.
- Only a user with `finance_transactions.approve` (a new fine-grained
  perm) can APPROVE it. A requester who also happens to hold the
  approve perm is still refused on their own row — segregation of
  duties in policy, enforced in code.

Petty cash
----------
- issue_petty_cash: DR 1170 (petty cash) / CR pay method or account.
- settle_petty_cash: DR expense account / CR 1170.
- No standalone "close petty box" needed for v1.
"""

from datetime import date, datetime
from decimal import Decimal

from flask import (
    abort, flash, redirect, render_template, request, url_for,
)
from flask_login import current_user, login_required

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import (
    Account, Employee, Invoice, PaymentMethod,
    PettyCashTransaction, RefundRequest,
)
from ...services.accounting import post_journal
from ...services.ledger import issue_refund, LedgerError


def _sid():
    return current_user.school_id


def _can_approve_refund(u) -> bool:
    """Approver is anyone with an explicit approve permission, or the
    admin fallback so a fresh school without refined permissions still
    works. Requester != approver: enforced separately at the callsite."""
    try:
        if u.can("finance_transactions", "approve"):
            return True
    except Exception:
        pass
    role_name = getattr(getattr(u, "role", None), "name", None)
    return role_name in ("admin", "admin_full", "system_admin")


# ─── Refund requests ──────────────────────────────────────────────
@bp.route("/refunds", endpoint="refunds_list")
@login_required
@require_permission("finance_transactions", "view")
def refunds_list():
    status = (request.args.get("status") or "").strip()
    q = RefundRequest.query.filter_by(school_id=_sid())
    if status:
        q = q.filter(RefundRequest.status == status)
    rows = q.order_by(RefundRequest.created_at.desc()).limit(200).all()
    return render_template(
        "finance/refunds_list.html",
        rows=rows, status=status,
        can_approve=_can_approve_refund(current_user),
    )


@bp.route("/invoices/<int:invoice_id>/refund-request",
          methods=["POST"], endpoint="refund_request_new")
@login_required
@require_permission("finance_transactions", "add")
def refund_request_new(invoice_id):
    inv = Invoice.query.filter_by(id=invoice_id, school_id=_sid()).first_or_404()
    try:
        amount = Decimal(request.form.get("amount") or "0")
    except Exception:
        flash("المبلغ غير صالح.", "danger")
        return redirect(url_for("finance.invoice_detail", invoice_id=inv.id))
    if amount <= 0:
        flash("المبلغ يجب أن يكون موجبًا.", "danger")
        return redirect(url_for("finance.invoice_detail", invoice_id=inv.id))
    if amount > (inv.paid_amount or 0):
        flash(
            f"المبلغ المطلوب ({amount}) أكبر من المدفوع فعليًا "
            f"({inv.paid_amount}).",
            "danger",
        )
        return redirect(url_for("finance.invoice_detail", invoice_id=inv.id))
    db.session.add(RefundRequest(
        school_id=_sid(), invoice_id=inv.id, amount=amount,
        reason=(request.form.get("reason") or "").strip() or None,
        payment_method_id=request.form.get("payment_method_id", type=int) or None,
        override_account_id=request.form.get("override_account_id", type=int) or None,
        requested_by_user_id=current_user.id,
    ))
    db.session.commit()
    flash("تم تسجيل طلب الاسترداد (بانتظار الاعتماد).", "success")
    return redirect(url_for("finance.refunds_list"))


@bp.route("/refunds/<int:req_id>/approve",
          methods=["POST"], endpoint="refund_request_approve")
@login_required
def refund_request_approve(req_id):
    if not _can_approve_refund(current_user):
        abort(403)
    r = RefundRequest.query.filter_by(
        id=req_id, school_id=_sid()).first_or_404()
    if r.status != "pending":
        flash("الطلب معالج بالفعل.", "danger")
        return redirect(url_for("finance.refunds_list"))
    # SoD — requester cannot approve their own refund.
    if r.requested_by_user_id == current_user.id:
        flash("لا يمكنك اعتماد طلب سجلته بنفسك — يتطلب معتمدًا مختلفًا.",
              "danger")
        return redirect(url_for("finance.refunds_list"))
    inv = r.invoice
    try:
        issue_refund(
            inv, r.amount, r.payment_method_id or 0,
            reason=r.reason or "استرداد",
            refund_date=date.today(),
            override_account_id=r.override_account_id,
        )
    except LedgerError as e:
        db.session.rollback()
        flash(str(e), "danger")
        return redirect(url_for("finance.refunds_list"))
    # Pin the produced Payment row for audit.
    r.payment_id = inv.payments[-1].id if inv.payments else None
    r.status = "approved"
    r.approved_by_user_id = current_user.id
    r.approved_at = datetime.utcnow()
    db.session.commit()
    flash(f"تم اعتماد الاسترداد وإنشاء القيد المحاسبي.", "success")
    return redirect(url_for("finance.refunds_list"))


@bp.route("/refunds/<int:req_id>/reject",
          methods=["POST"], endpoint="refund_request_reject")
@login_required
def refund_request_reject(req_id):
    if not _can_approve_refund(current_user):
        abort(403)
    r = RefundRequest.query.filter_by(
        id=req_id, school_id=_sid()).first_or_404()
    if r.status != "pending":
        flash("الطلب معالج بالفعل.", "danger")
        return redirect(url_for("finance.refunds_list"))
    r.status = "rejected"
    r.reject_reason = (request.form.get("reason") or "").strip() or None
    r.approved_by_user_id = current_user.id
    r.approved_at = datetime.utcnow()
    db.session.commit()
    flash("تم رفض الطلب.", "success")
    return redirect(url_for("finance.refunds_list"))


# ─── Petty cash ───────────────────────────────────────────────────
def _petty_cash_account():
    """Return the 1170 (petty-cash / cash-under-settlement) Account
    row for the current school; None when the tree isn't seeded."""
    return Account.query.filter_by(school_id=_sid(), code="1170").first()


@bp.route("/petty-cash", endpoint="petty_cash_home")
@login_required
@require_permission("finance_transactions", "view")
def petty_cash_home():
    rows = (
        PettyCashTransaction.query.filter_by(school_id=_sid())
        .order_by(PettyCashTransaction.tx_date.desc()).limit(200).all()
    )
    balance = sum(
        (Decimal(str(r.amount)) if r.kind == "issue"
         else -Decimal(str(r.amount)))
        for r in PettyCashTransaction.query.filter_by(school_id=_sid()).all()
    )
    employees = (
        Employee.query.filter_by(school_id=_sid(), is_active=True)
        .order_by(Employee.full_name).all()
    )
    methods = PaymentMethod.query.filter_by(school_id=_sid()).all()
    expense_accounts = (
        Account.query.filter_by(school_id=_sid())
        .filter(Account.code.like("5%"))  # المصروفات
        .order_by(Account.code).all()
    )
    return render_template(
        "finance/petty_cash.html",
        rows=rows, balance=balance,
        employees=employees, methods=methods,
        expense_accounts=expense_accounts,
        has_account=(_petty_cash_account() is not None),
    )


@bp.route("/petty-cash/issue", methods=["POST"], endpoint="petty_cash_issue")
@login_required
@require_permission("finance_transactions", "add")
def petty_cash_issue():
    """DR 1170 / CR pay method or account — cash going out to custodian."""
    pca = _petty_cash_account()
    if pca is None:
        flash("حساب العهدة النقدية (1170) غير موجود في دليل الحسابات.", "danger")
        return redirect(url_for("finance.petty_cash_home"))
    try:
        amount = Decimal(request.form.get("amount") or "0")
    except Exception:
        amount = Decimal(0)
    if amount <= 0:
        flash("المبلغ غير صالح.", "danger")
        return redirect(url_for("finance.petty_cash_home"))

    pm_id = request.form.get("payment_method_id", type=int)
    if not pm_id:
        flash("اختر طريقة صرف العهدة (كاش/بنك).", "danger")
        return redirect(url_for("finance.petty_cash_home"))
    pm = PaymentMethod.query.filter_by(id=pm_id, school_id=_sid()).first_or_404()

    counter_account_id = pm.account_id
    if not counter_account_id:
        flash("طريقة الدفع غير مرتبطة بحساب في دليل الحسابات.", "danger")
        return redirect(url_for("finance.petty_cash_home"))

    je = post_journal(
        school_id=_sid(),
        entry_date=date.today(),
        description=(request.form.get("reason") or "صرف عهدة نقدية"),
        lines=[
            (pca.id, amount, Decimal(0), "صرف عهدة"),
            (counter_account_id, Decimal(0), amount, "من الصندوق/البنك"),
        ],
        related_kind="petty_cash", related_id=None,
    )
    tx = PettyCashTransaction(
        school_id=_sid(), kind="issue",
        custodian_employee_id=request.form.get("custodian_employee_id", type=int) or None,
        amount=amount,
        tx_date=date.today(),
        reason=(request.form.get("reason") or "").strip() or None,
        journal_entry_id=je.id,
        counter_account_id=counter_account_id,
        recorded_by_user_id=getattr(current_user, "id", None),
    )
    db.session.add(tx); db.session.commit()
    flash(f"تم صرف عهدة نقدية بمبلغ {amount}.", "success")
    return redirect(url_for("finance.petty_cash_home"))


@bp.route("/petty-cash/settle",
          methods=["POST"], endpoint="petty_cash_settle")
@login_required
@require_permission("finance_transactions", "add")
def petty_cash_settle():
    """DR expense / CR 1170 — cash spent, tie-off with an expense account."""
    pca = _petty_cash_account()
    if pca is None:
        flash("حساب العهدة النقدية (1170) غير موجود.", "danger")
        return redirect(url_for("finance.petty_cash_home"))
    try:
        amount = Decimal(request.form.get("amount") or "0")
    except Exception:
        amount = Decimal(0)
    if amount <= 0:
        flash("المبلغ غير صالح.", "danger")
        return redirect(url_for("finance.petty_cash_home"))
    expense_account_id = request.form.get("expense_account_id", type=int)
    if not expense_account_id:
        flash("اختر حساب المصروف.", "danger")
        return redirect(url_for("finance.petty_cash_home"))

    je = post_journal(
        school_id=_sid(),
        entry_date=date.today(),
        description=(request.form.get("reason") or "تسوية عهدة نقدية"),
        lines=[
            (expense_account_id, amount, Decimal(0), "مصروف مسدّد من العهدة"),
            (pca.id, Decimal(0), amount, "تسوية العهدة"),
        ],
        related_kind="petty_cash", related_id=None,
    )
    tx = PettyCashTransaction(
        school_id=_sid(), kind="settle",
        custodian_employee_id=request.form.get("custodian_employee_id", type=int) or None,
        amount=amount,
        tx_date=date.today(),
        reason=(request.form.get("reason") or "").strip() or None,
        journal_entry_id=je.id,
        counter_account_id=expense_account_id,
        recorded_by_user_id=getattr(current_user, "id", None),
    )
    db.session.add(tx); db.session.commit()
    flash(f"تم تسوية {amount} من العهدة كمصروف.", "success")
    return redirect(url_for("finance.petty_cash_home"))
