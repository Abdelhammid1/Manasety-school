from datetime import datetime, date, timedelta
from decimal import Decimal
from io import BytesIO

from flask import (
    abort, current_app, flash, redirect, render_template, request, Response, url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import func

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import (
    Account, AcademicYear, Enrollment, Expense, FeeType, Grade,
    Installment, Invoice, InvoiceLine, JournalEntry, JournalLine,
    Payment, Section, Student, Vendor,
)
from ...services.accounting import post_journal
from ...services.notifications import send_notification


def _sid():
    return current_user.school_id


def _get(model, oid):
    obj = model.query.filter_by(id=oid, school_id=_sid()).first()
    if not obj:
        abort(404)
    return obj


def _role_account(role: str) -> Account:
    """Ticket A — resolve a school's default account for a semantic role
    (ar_default, cash_default, discount_default, payroll_salary_default …)
    instead of looking up a hardcoded numeric code. The role is set on
    the account row itself and is admin-editable, so schools that use a
    different code numbering scheme still work."""
    return Account.query.filter_by(
        school_id=_sid(), account_role=role,
    ).first()


def _ar_account() -> Account:
    return _role_account("ar_default")


def _default_cash_account() -> Account:
    return _role_account("cash_default")


def _discount_account() -> Account:
    """Ticket #17 — sibling-discount / scholarship line lives on the
    Contra-Revenue leaf tagged with role=discount_default."""
    return _role_account("discount_default")


# ---------- T-8.1 Chart of accounts ----------

# Ticket A — semantic account-role catalogue. Rendered as a dropdown on
# each account row so the admin can pin the school's defaults without
# touching the code.
ACCOUNT_ROLES = [
    ("ar_default",             "ذمم مدينة — افتراضي (Accounts Receivable)"),
    ("cash_default",           "النقدية — افتراضي"),
    ("discount_default",       "خصومات — افتراضي"),
    ("payroll_salary_default", "رواتب المعلمين — افتراضي"),
    ("tuition_default",        "إيرادات رسوم دراسية — افتراضي"),
    ("ap_default",             "ذمم دائنة — افتراضي (Accounts Payable)"),
    ("vat_payable_default",    "ضريبة القيمة المضافة المستحقة"),
    ("employee_advance_default", "سلف الموظفين — افتراضي"),
    ("retained_earnings_default", "أرباح/خسائر مرحّلة (لإقفال السنة)"),
]


@bp.route("/accounts")
@login_required
@require_permission("finance", "view")
def accounts():
    items = (
        Account.query.filter_by(school_id=_sid())
        .order_by(Account.code).all()
    )
    roots = [a for a in items if a.parent_id is None]
    return render_template(
        "finance/accounts.html",
        accounts=items, roots=roots, account_roles=ACCOUNT_ROLES,
    )


@bp.route("/accounts/<int:account_id>/role", methods=["POST"])
@login_required
@require_permission("finance", "edit")
def account_set_role(account_id):
    """Ticket A — pin a semantic role (ar_default, cash_default, …) on
    a postable account. Enforces the (school_id, account_role) UNIQUE:
    clearing any prior owner in the same school before applying."""
    acc = Account.query.filter_by(id=account_id, school_id=_sid()).first_or_404()
    role = (request.form.get("account_role") or "").strip() or None
    if role and not acc.is_postable:
        flash(
            "لا يمكن تعيين دور افتراضي على حساب تجميعي — اختر حساباً فرعياً (مستوى 3).",
            "danger",
        )
        return redirect(url_for("finance.accounts"))
    if role and role not in {k for k, _ in ACCOUNT_ROLES}:
        flash("دور غير معروف.", "danger")
        return redirect(url_for("finance.accounts"))
    if role:
        prior = Account.query.filter_by(
            school_id=_sid(), account_role=role,
        ).filter(Account.id != acc.id).first()
        if prior:
            prior.account_role = None
    acc.account_role = role
    db.session.commit()
    flash("تم تحديث الدور الافتراضي للحساب.", "success")
    return redirect(url_for("finance.accounts"))


@bp.route("/accounts/new", methods=["GET", "POST"])
@login_required
@require_permission("finance", "edit")
def account_new():
    # Ticket B — parents dropdown only lists aggregate accounts
    # (is_postable=False); a postable leaf can never be a parent.
    parents = (
        Account.query.filter_by(school_id=_sid(), is_postable=False)
        .order_by(Account.code).all()
    )
    if request.method == "POST":
        parent_id = int(request.form["parent_id"]) if request.form.get("parent_id") else None
        # Row directly under a root (Level 1) → aggregate.
        # Row under a Level-2 aggregate → postable Level-3 leaf.
        parent = Account.query.get(parent_id) if parent_id else None
        is_postable = bool(parent and parent.parent_id is not None)
        a = Account(
            school_id=_sid(),
            code=request.form["code"].strip(),
            name=request.form["name"].strip(),
            type=request.form["type"],
            parent_id=parent_id, is_postable=is_postable,
        )
        db.session.add(a)
        db.session.commit()
        flash(f"تم إضافة الحساب {a.code} — {a.name}.", "success")
        return redirect(url_for("finance.accounts"))
    return render_template("finance/account_form.html", parents=parents)


# ---------- T-8.1 Journal view ----------

@bp.route("/journal")
@login_required
@require_permission("finance", "view")
def journal():
    end = _parse_date(request.args.get("end")) or date.today()
    start = _parse_date(request.args.get("start")) or (end - timedelta(days=365))
    account_id = request.args.get("account_id", type=int)
    accounts = Account.query.filter_by(school_id=_sid()).order_by(Account.code).all()

    q = JournalEntry.query.filter(
        JournalEntry.school_id == _sid(),
        JournalEntry.entry_date >= start,
        JournalEntry.entry_date <= end,
    )
    if account_id:
        q = q.join(JournalLine).filter(JournalLine.account_id == account_id)
    entries = q.order_by(JournalEntry.entry_date.desc(), JournalEntry.id.desc()).limit(200).all()
    return render_template(
        "finance/journal.html",
        entries=entries, accounts=accounts,
        start=start, end=end, account_id=account_id,
    )


# ---------- T-8.2 Fee types ----------

@bp.route("/fee-types")
@login_required
@require_permission("finance", "view")
def fee_types():
    items = FeeType.query.filter_by(school_id=_sid()).order_by(FeeType.name).all()
    return render_template("finance/fee_types.html", fee_types=items)


@bp.route("/fee-types/new", methods=["GET", "POST"])
@login_required
@require_permission("finance", "edit")
def fee_type_new():
    revenues = (
        Account.query.filter_by(school_id=_sid(), type="revenue")
        .order_by(Account.code).all()
    )
    if not revenues:
        flash("لا توجد حسابات إيرادات — أضف حساباً نوعه \"إيراد\" في دليل الحسابات أولاً.", "warning")
        return redirect(url_for("finance.accounts"))
    if request.method == "POST":
        rev_id = request.form.get("revenue_account_id", type=int)
        name = (request.form.get("name") or "").strip()
        if not name or rev_id not in [r.id for r in revenues]:
            flash("اسم الرسم وحساب الإيراد مطلوبان.", "danger")
            return render_template("finance/fee_type_form.html", revenues=revenues, fee_type=None)
        f = FeeType(
            school_id=_sid(),
            name=name,
            default_amount=Decimal(request.form.get("default_amount") or "0"),
            installable=bool(request.form.get("installable")),
            is_taxable=bool(request.form.get("is_taxable")),
            revenue_account_id=rev_id,
        )
        db.session.add(f)
        db.session.commit()
        flash("تم إضافة نوع الرسم.", "success")
        return redirect(url_for("finance.fee_types"))
    return render_template("finance/fee_type_form.html", revenues=revenues, fee_type=None)


@bp.route("/fee-types/<int:ft_id>/edit", methods=["GET", "POST"])
@login_required
@require_permission("finance", "edit")
def fee_type_edit(ft_id):
    f = _get(FeeType, ft_id)
    revenues = (
        Account.query.filter_by(school_id=_sid(), type="revenue")
        .order_by(Account.code).all()
    )
    if request.method == "POST":
        rev_id = request.form.get("revenue_account_id", type=int)
        name = (request.form.get("name") or "").strip()
        if not name or rev_id not in [r.id for r in revenues]:
            flash("اسم الرسم وحساب الإيراد مطلوبان.", "danger")
            return render_template("finance/fee_type_form.html", revenues=revenues, fee_type=f)
        f.name = name
        f.default_amount = Decimal(request.form.get("default_amount") or "0")
        f.installable = bool(request.form.get("installable"))
        f.is_taxable = bool(request.form.get("is_taxable"))
        f.revenue_account_id = rev_id
        db.session.commit()
        flash("تم تعديل نوع الرسم.", "success")
        return redirect(url_for("finance.fee_types"))
    return render_template("finance/fee_type_form.html", revenues=revenues, fee_type=f)


@bp.route("/fee-types/<int:ft_id>/toggle", methods=["POST"])
@login_required
@require_permission("finance", "edit")
def fee_type_toggle(ft_id):
    f = _get(FeeType, ft_id)
    f.is_active = not f.is_active
    db.session.commit()
    flash(
        f"تم {'تفعيل' if f.is_active else 'إيقاف'} نوع الرسم ({f.name}).",
        "success",
    )
    return redirect(url_for("finance.fee_types"))


@bp.route("/fee-types/<int:ft_id>/delete", methods=["POST"])
@login_required
@require_permission("finance", "delete")
def fee_type_delete(ft_id):
    """Delete a fee-type. Refuses if it's ever been billed on an
    invoice — InvoiceLine.fee_type_id is NOT NULL so a real delete
    would either 500 on the FK or strand invoice history."""
    f = _get(FeeType, ft_id)
    n_lines = InvoiceLine.query.filter_by(fee_type_id=f.id).count()
    if n_lines:
        flash(
            f"لا يمكن حذف نوع الرسم ({f.name}) — استُخدم على {n_lines} بند فاتورة. "
            "أوقفه بدلاً من الحذف.",
            "danger",
        )
        return redirect(url_for("finance.fee_types"))
    db.session.delete(f); db.session.commit()
    flash("تم حذف نوع الرسم نهائياً.", "success")
    return redirect(url_for("finance.fee_types"))


# ---------- T-8.3 / T-8.4 / T-8.5 Invoices ----------

@bp.route("/invoices")
@login_required
@require_permission("finance", "view")
def invoices_list():
    year = AcademicYear.query.filter_by(school_id=_sid(), status="active").first()
    q = (
        Invoice.query.filter_by(school_id=_sid())
        .join(Enrollment).join(Student)
        .order_by(Invoice.issue_date.desc())
    )
    if year:
        q = q.filter(Enrollment.year_id == year.id)
    invoices = q.limit(500).all()
    return render_template("finance/invoices_list.html", invoices=invoices, year=year)


@bp.route("/invoices/new", methods=["GET", "POST"])
@login_required
@require_permission("finance", "edit")
def invoice_new():
    year = AcademicYear.query.filter_by(school_id=_sid(), status="active").first()
    if not year:
        flash("لا توجد سنة دراسية نشطة.", "warning")
        return redirect(url_for("finance.invoices_list"))

    enrollments = (
        Enrollment.query.filter_by(school_id=_sid(), year_id=year.id, status="active")
        .join(Student).order_by(Student.full_name).all()
    )
    fee_types = FeeType.query.filter_by(school_id=_sid(), is_active=True).order_by(FeeType.name).all()
    # Ticket "Full financial automation" — invoice creation no longer
    # asks for an AR account. The AR sub-account for the student is
    # lazy-created inside `post_invoice_to_ledger`; a header 1210 has
    # is_postable=False. We still surface a friendly error if the
    # chart of accounts is empty on this school.
    from ...models import Account
    if not Account.query.filter_by(school_id=_sid()).first():
        flash("لم يُهيّأ دليل الحسابات. أنشئ الحسابات الأساسية أولاً.", "danger")
        return redirect(url_for("finance.accounts"))
    if not enrollments:
        flash("لا يوجد طلاب مسجّلون في السنة الحالية — سجّل طالباً قبل إنشاء الفاتورة.", "warning")
        return redirect(url_for("finance.invoices_list"))
    if not fee_types:
        flash("لا يوجد أنواع رسوم مفعّلة — أضف نوع رسم واحد على الأقل.", "warning")
        return redirect(url_for("finance.fee_types"))

    # Ticket C — pre-select the enrollment when the CTA on the student
    # detail / enroll flow passed ?enrollment_id=…
    preselect_id = request.args.get("enrollment_id", type=int)
    if preselect_id and preselect_id not in [e.id for e in enrollments]:
        preselect_id = None

    if request.method == "POST":
        enrollment_id = request.form.get("enrollment_id", type=int)
        if enrollment_id not in [e.id for e in enrollments]:
            flash("اختر طالباً صحيحاً من القائمة.", "danger")
            return redirect(url_for("finance.invoice_new"))
        issue = _parse_date(request.form.get("issue_date")) or date.today()
        due = _parse_date(request.form.get("due_date")) or (issue + timedelta(days=30))
        installments_count = int(request.form.get("installments_count") or "1")

        fee_ids = request.form.getlist("fee_type_id", type=int)
        amounts = request.form.getlist("amount")
        if not fee_ids:
            flash("أضف نوع رسم واحد على الأقل.", "danger")
            return redirect(url_for("finance.invoice_new"))

        # Invoice number
        n = Invoice.query.filter_by(school_id=_sid()).count() + 1
        number = f"INV-{year.name}-{n:05d}"

        inv = Invoice(
            school_id=_sid(),
            enrollment_id=enrollment_id,
            number=number,
            issue_date=issue,
            due_date=due,
            status="sent",
        )
        db.session.add(inv)
        db.session.flush()

        # Ticket "Additional 9" — read school's default VAT rate. If
        # any of the picked fee types are is_taxable, we accumulate tax
        # on their subtotals; the invoice's total_amount stays GROSS
        # (net + tax) so downstream paid/remaining math is unchanged.
        from ...models import School
        school = db.session.get(School, _sid())
        default_rate = Decimal(str(school.default_tax_rate or 0))

        subtotal = Decimal(0)
        taxable_subtotal = Decimal(0)
        for fid, amt_raw in zip(fee_ids, amounts):
            amt = Decimal(amt_raw or "0")
            if amt <= 0:
                continue
            ft = FeeType.query.filter_by(school_id=_sid(), id=fid).first()
            if not ft:
                continue
            line = InvoiceLine(
                invoice_id=inv.id, fee_type_id=ft.id,
                description=ft.name, amount=amt,
            )
            db.session.add(line)
            subtotal += amt
            if ft.is_taxable:
                taxable_subtotal += amt

        tax_amount = (taxable_subtotal * default_rate / Decimal(100)).quantize(Decimal("0.01"))
        inv.tax_rate = default_rate
        inv.tax_amount = tax_amount
        total = subtotal + tax_amount

        # Ticket #17 — auto-apply approved StudentDiscount rows on this
        # enrollment. Written as negative InvoiceLine rows so the parent
        # sees the breakdown; ledger service handles the contra-revenue.
        from ...services.discounts import applicable_discounts_for
        applied = applicable_discounts_for(enrollment_id, total)
        for label, amount, _sd in applied:
            db.session.add(InvoiceLine(
                invoice_id=inv.id, fee_type_id=fee_ids[0] if fee_ids else None,
                description=f"خصم: {label}",
                amount=-amount,     # negative line
            ))
            total -= amount

        inv.total_amount = total

        # Split installments
        if installments_count < 1:
            installments_count = 1
        per = (total / installments_count).quantize(Decimal("0.01"))
        accum = Decimal(0)
        for i in range(installments_count):
            d = due if installments_count == 1 else due + timedelta(days=30 * i)
            amt = per if i < installments_count - 1 else total - accum
            db.session.add(Installment(
                invoice_id=inv.id, due_date=d, amount=amt,
            ))
            accum += amt

        db.session.flush()   # so `inv.lines` is queryable inside ledger
        # Ticket "Full financial automation" — one call, no account choices.
        # The service resolves the student's AR sub-account, splits credits
        # per fee_type, and books the discount contra-line automatically.
        from ...services.ledger import post_invoice_to_ledger, LedgerError
        try:
            post_invoice_to_ledger(inv, entry_date=issue)
        except LedgerError as e:
            db.session.rollback()
            flash(str(e), "danger")
            return redirect(url_for("finance.invoice_new"))
        db.session.commit()

        # T-8.5: notify parent on issue
        e = inv.enrollment
        phone = (e.student.parent_phone or "").strip()
        if phone:
            send_notification(
                school_id=_sid(),
                kind="invoice_issued",
                payload={
                    "student": e.student.full_name,
                    "invoice_number": number,
                    "amount": float(total),
                    "due_date": due.isoformat(),
                    "message": (
                        f"إشعار فاتورة: صدرت فاتورة برقم {number} للطالب "
                        f"{e.student.full_name} بمبلغ {total} مستحقة بتاريخ {due.isoformat()}."
                    ),
                },
                target_phone=phone,
                student_id=e.student_id,  # Sprint 11: parent-scoping FK
                related_kind="invoice", related_id=inv.id,
            )

        flash(f"تم إنشاء الفاتورة {number} وقيدها محاسبيًا.", "success")
        return redirect(url_for("finance.invoice_detail", invoice_id=inv.id))

    return render_template(
        "finance/invoice_form.html", year=year, enrollments=enrollments,
        fee_types=fee_types, preselect_enrollment_id=preselect_id,
    )


@bp.route("/invoices/<int:invoice_id>")
@login_required
@require_permission("finance", "view")
def invoice_detail(invoice_id):
    inv = _get(Invoice, invoice_id)
    # Ticket "Full financial automation" — payment methods replace the
    # raw cash-account picker. `deferred` PMs are hidden here because
    # they don't apply to collecting an invoice.
    from ...models import PaymentMethod
    payment_methods = (
        PaymentMethod.query.filter_by(school_id=_sid(), is_active=True)
        .filter(PaymentMethod.kind != "deferred")
        .order_by(PaymentMethod.name).all()
    )
    return render_template("finance/invoice_detail.html", inv=inv,
                           payment_methods=payment_methods)


@bp.route("/invoices/<int:invoice_id>/print")
@login_required
@require_permission("finance", "view")
def invoice_print(invoice_id):
    """Sprint 9 TC-8.3.1 — print-optimized invoice view.

    ?download=1 pipes through WeasyPrint to return a PDF.
    Default: renders HTML with @media print styles + auto window.print().
    """
    inv = _get(Invoice, invoice_id)
    download = request.args.get("download") == "1"
    if download:
        html = render_template("finance/invoice_print.html", inv=inv, download=True)
        try:
            from weasyprint import HTML
            pdf_bytes = HTML(string=html, base_url=request.host_url).write_pdf()
        except Exception as e:  # noqa: BLE001
            current_app.logger.exception("WeasyPrint invoice PDF failed: %s", e)
            # Fallback: return the printable HTML so the browser can Save-as-PDF
            return Response(html, mimetype="text/html")
        return Response(
            pdf_bytes,
            mimetype="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="invoice_{inv.number}.pdf"',
            },
        )
    return render_template("finance/invoice_print.html", inv=inv, download=False)


# ---------- Bulk payment (Ticket "Additional 5") ---------------------

@bp.route("/bulk-payment", methods=["GET", "POST"], endpoint="bulk_payment")
@login_required
@require_permission("finance_transactions", "add")
def bulk_payment():
    """Cover multiple unpaid/partial invoices with a single receipt.

    UX:
      GET — pick a guardian (or a student) → lists their unpaid invoices
            oldest-due first, with a "auto FIFO" checkbox + per-line
            amount inputs.
      POST — validates + delegates to services.ledger.record_bulk_payment
             which produces one balanced journal entry.
    """
    from ...models import PaymentMethod, Guardian, StudentGuardian
    from ...services.ledger import (
        record_bulk_payment, distribute_fifo, LedgerError,
    )
    guardian_id = request.values.get("guardian_id", type=int)
    guardian = (
        Guardian.query.filter_by(id=guardian_id, school_id=_sid()).first()
        if guardian_id else None
    )

    invoices = []
    if guardian:
        student_ids = [
            l.student_id for l in
            StudentGuardian.query.filter_by(guardian_id=guardian.id).all()
        ]
        if student_ids:
            invoices = (
                Invoice.query
                .join(Enrollment, Enrollment.id == Invoice.enrollment_id)
                .filter(
                    Invoice.school_id == _sid(),
                    Enrollment.student_id.in_(student_ids),
                    Invoice.status.in_(("sent", "partial", "overdue")),
                )
                .order_by(Invoice.due_date, Invoice.id).all()
            )

    payment_methods = (
        PaymentMethod.query.filter_by(school_id=_sid(), is_active=True)
        .filter(PaymentMethod.kind != "deferred")
        .order_by(PaymentMethod.name).all()
    )
    guardians = (
        Guardian.query.filter_by(school_id=_sid()).order_by(Guardian.full_name).all()
    )

    if request.method == "POST":
        pm_id = request.form.get("payment_method_id", type=int)
        auto_fifo = request.form.get("auto_fifo") == "1"
        total = Decimal(request.form.get("total_amount") or "0")
        try:
            if auto_fifo:
                if total <= 0:
                    flash("أدخل الإجمالي المطلوب توزيعه.", "danger")
                    return redirect(url_for("finance.bulk_payment",
                                            guardian_id=guardian_id))
                allocations = distribute_fifo(invoices, total)
            else:
                allocations = []
                for inv in invoices:
                    amt = Decimal(request.form.get(f"amt_{inv.id}") or "0")
                    if amt > 0:
                        allocations.append((inv, amt))
            if not allocations:
                flash("لم يتم تخصيص أي مبلغ.", "danger")
                return redirect(url_for("finance.bulk_payment",
                                        guardian_id=guardian_id))
            _, payments = record_bulk_payment(
                allocations, pm_id,
                notes=(request.form.get("notes") or "").strip() or None,
                reference=(request.form.get("reference") or "").strip() or None,
            )
        except LedgerError as e:
            db.session.rollback()
            flash(str(e), "danger")
            return redirect(url_for("finance.bulk_payment",
                                    guardian_id=guardian_id))
        db.session.commit()
        flash(f"تم تسجيل الدفعة على {len(payments)} فاتورة.", "success")
        return redirect(url_for("finance.invoices_list"))

    return render_template(
        "finance/bulk_payment.html",
        guardian=guardian, invoices=invoices,
        guardians=guardians, payment_methods=payment_methods,
    )


@bp.route("/invoices/<int:invoice_id>/void", methods=["POST"])
@login_required
@require_permission("finance_transactions", "add")
def invoice_void(invoice_id):
    """Ticket "Additional 2" — void an untouched invoice (paid_amount == 0)
    by posting a symmetric reversal of the original journal and marking
    it cancelled."""
    from ...services.ledger import void_invoice, LedgerError
    inv = _get(Invoice, invoice_id)
    reason = (request.form.get("reason") or "").strip() or "بدون سبب مذكور"
    try:
        void_invoice(inv, reason)
    except LedgerError as e:
        db.session.rollback()
        flash(str(e), "danger")
        return redirect(url_for("finance.invoice_detail", invoice_id=inv.id))
    db.session.commit()
    flash(f"تم إلغاء الفاتورة {inv.number}.", "success")
    return redirect(url_for("finance.invoice_detail", invoice_id=inv.id))


@bp.route("/invoices/<int:invoice_id>/pay", methods=["POST"])
@login_required
@require_permission("finance_transactions", "add")
def invoice_pay(invoice_id):
    """Ticket "Full financial automation" — the UI asks only "استلمت
    الفلوس فين؟" (payment_method_id). Everything else — student sub-
    account, journal, installment distribution — is handled inside
    services.ledger.record_payment / issue_refund."""
    from ...services.ledger import record_payment, issue_refund, LedgerError
    inv = _get(Invoice, invoice_id)
    try:
        amount = Decimal(request.form.get("amount") or "0")
    except Exception:
        flash("المبلغ غير صالح.", "danger")
        return redirect(url_for("finance.invoice_detail", invoice_id=inv.id))

    is_refund = request.form.get("is_refund") == "1"
    payment_method_id = request.form.get("payment_method_id", type=int)
    if not payment_method_id:
        flash("اختر طريقة الدفع.", "danger")
        return redirect(url_for("finance.invoice_detail", invoice_id=inv.id))

    pay_date = _parse_date(request.form.get("payment_date")) or date.today()
    reference = (request.form.get("reference") or "").strip() or None
    notes = (request.form.get("notes") or "").strip() or None

    try:
        if is_refund:
            issue_refund(inv, amount, payment_method_id,
                         reason=notes or "استرداد",
                         refund_date=pay_date)
            flash(f"تم استرداد {amount} من الفاتورة {inv.number}.", "success")
        else:
            record_payment(inv, amount, payment_method_id,
                           payment_date=pay_date,
                           reference=reference, notes=notes)
            flash(f"تم تسجيل دفعة {amount} على الفاتورة {inv.number}.", "success")
    except LedgerError as e:
        db.session.rollback()
        flash(str(e), "danger")
        return redirect(url_for("finance.invoice_detail", invoice_id=inv.id))

    db.session.commit()

    # Reload the last-added Payment row for the notification hook below.
    payment = inv.payments[-1] if inv.payments else None

    # T-8.5: notify on payment
    phone = (inv.enrollment.student.parent_phone or "").strip()
    if phone:
        kind = "refund" if is_refund else "payment"
        send_notification(
            school_id=_sid(),
            kind=kind,
            payload={
                "student": inv.enrollment.student.full_name,
                "invoice_number": inv.number,
                "amount": float(amount),
                "remaining": float(inv.remaining),
                "message": (
                    f"إشعار {'استرداد' if is_refund else 'دفع'}: "
                    f"تم تسجيل {amount} على الفاتورة {inv.number}. "
                    f"المتبقّي: {inv.remaining}."
                ),
            },
            target_phone=phone,
            student_id=inv.enrollment.student_id,  # Sprint 11: parent-scoping FK
            related_kind="payment", related_id=payment.id if payment else inv.id,
        )

    return redirect(url_for("finance.invoice_detail", invoice_id=inv.id))


# ---------- Payment methods (Ticket "Full financial automation") -----
#
# A tiny CRUD scoped to the school: name + kind + linked account. This
# is the ONE place account IDs still show up in the UI — because the
# admin is deliberately mapping "نقدي" → 1110 here at setup time so
# the daily UI never has to.

# ---------- Bank reconciliation (Ticket "Additional 10") ------------
#
# Import CSV of statement lines, auto-suggest matches against unmatched
# JournalLines by (date, |amount|) — the admin confirms or edits per row.

@bp.route("/bank-rec", endpoint="bank_rec")
@login_required
@require_permission("finance", "view")
def bank_rec():
    from ...models import BankStatementLine
    bank_accounts = (
        Account.query.filter_by(school_id=_sid(), type="asset", is_postable=True)
        .order_by(Account.code).all()
    )
    account_id = request.args.get("account_id", type=int) or (bank_accounts[0].id if bank_accounts else None)
    lines = []
    suggestions: dict[int, list] = {}
    if account_id:
        lines = (
            BankStatementLine.query.filter_by(school_id=_sid(), bank_account_id=account_id)
            .order_by(BankStatementLine.statement_date, BankStatementLine.id).all()
        )
        # For unmatched lines, propose 5 candidate JournalLines by
        # nearest (date, |amount|) on the same account.
        from datetime import timedelta
        for l in lines:
            if l.is_matched:
                continue
            candidates = (
                JournalLine.query
                .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
                .filter(
                    JournalLine.account_id == account_id,
                    JournalEntry.entry_date >= l.statement_date - timedelta(days=5),
                    JournalEntry.entry_date <= l.statement_date + timedelta(days=5),
                    ((JournalLine.debit == abs(l.amount))
                     | (JournalLine.credit == abs(l.amount))),
                )
                .order_by(JournalEntry.entry_date).limit(5).all()
            )
            suggestions[l.id] = candidates
    return render_template(
        "finance/bank_rec.html",
        bank_accounts=bank_accounts, account_id=account_id,
        lines=lines, suggestions=suggestions,
    )


@bp.route("/bank-rec/import", methods=["POST"], endpoint="bank_rec_import")
@login_required
@require_permission("finance", "edit")
def bank_rec_import():
    """CSV: statement_date (YYYY-MM-DD), description, amount, reference?
    First row treated as header. Amount is signed (positive = DR to
    bank account = money in, negative = CR = money out)."""
    from ...models import BankStatementLine
    import csv, io
    account_id = request.form.get("account_id", type=int)
    if not account_id:
        flash("اختر الحساب البنكي أولاً.", "danger")
        return redirect(url_for("finance.bank_rec"))
    f = request.files.get("statement")
    if not f or not f.filename:
        flash("ارفع ملف الكشف (.csv).", "danger")
        return redirect(url_for("finance.bank_rec", account_id=account_id))

    text = f.read().decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        flash("الملف فارغ.", "danger")
        return redirect(url_for("finance.bank_rec", account_id=account_id))
    inserted = 0
    for i, row in enumerate(rows):
        if i == 0:
            # Skip header if the first cell isn't parsable as a date.
            try:
                _parse_date(row[0])
            except Exception:
                continue
        if len(row) < 3:
            continue
        try:
            d = _parse_date(row[0])
            desc = (row[1] or "").strip()
            amt = Decimal((row[2] or "0").replace(",", "").strip())
        except Exception:
            continue
        reference = (row[3].strip() if len(row) > 3 else "") or None
        db.session.add(BankStatementLine(
            school_id=_sid(), bank_account_id=account_id,
            statement_date=d, description=desc, amount=amt,
            reference=reference,
        ))
        inserted += 1
    db.session.commit()
    flash(f"تم استيراد {inserted} سطر من كشف الحساب.", "success")
    return redirect(url_for("finance.bank_rec", account_id=account_id))


@bp.route("/bank-rec/<int:line_id>/match", methods=["POST"], endpoint="bank_rec_match")
@login_required
@require_permission("finance_transactions", "add")
def bank_rec_match(line_id):
    from ...models import BankStatementLine
    line = BankStatementLine.query.filter_by(id=line_id, school_id=_sid()).first_or_404()
    jl_id = request.form.get("journal_line_id", type=int)
    if not jl_id:
        flash("اختر سطر قيد للربط.", "danger")
        return redirect(url_for("finance.bank_rec", account_id=line.bank_account_id))
    jl = JournalLine.query.get(jl_id)
    if not jl:
        abort(404)
    line.matched_journal_line_id = jl.id
    line.is_matched = True
    db.session.commit()
    flash("تم ربط السطر بقيد النظام.", "success")
    return redirect(url_for("finance.bank_rec", account_id=line.bank_account_id))


@bp.route("/bank-rec/<int:line_id>/unmatch", methods=["POST"], endpoint="bank_rec_unmatch")
@login_required
@require_permission("finance_transactions", "add")
def bank_rec_unmatch(line_id):
    from ...models import BankStatementLine
    line = BankStatementLine.query.filter_by(id=line_id, school_id=_sid()).first_or_404()
    line.matched_journal_line_id = None
    line.is_matched = False
    db.session.commit()
    return redirect(url_for("finance.bank_rec", account_id=line.bank_account_id))


# ---------- Recurring fee schedules (Ticket "Additional 8") ---------

@bp.route("/recurring", endpoint="recurring_list")
@login_required
@require_permission("finance", "view")
def recurring_list():
    from ...models import RecurringFeeSchedule
    items = (
        RecurringFeeSchedule.query.filter_by(school_id=_sid())
        .order_by(RecurringFeeSchedule.id.desc()).all()
    )
    fee_types = FeeType.query.filter_by(school_id=_sid(), is_active=True).order_by(FeeType.name).all()
    grades = Grade.query.filter_by(school_id=_sid()).order_by(Grade.order_index).all()
    return render_template(
        "finance/recurring_list.html",
        items=items, fee_types=fee_types, grades=grades,
    )


@bp.route("/recurring/new", methods=["POST"], endpoint="recurring_new")
@login_required
@require_permission("finance", "edit")
def recurring_new():
    from ...models import RecurringFeeSchedule, RECURRING_FREQUENCIES
    fee_type_id = request.form.get("fee_type_id", type=int)
    freq = (request.form.get("frequency") or "monthly").strip()
    day = request.form.get("day_of_period", type=int) or 1
    grade_id = request.form.get("applies_to_grade_id", type=int) or None
    if not fee_type_id:
        flash("اختر نوع الرسم.", "danger")
        return redirect(url_for("finance.recurring_list"))
    if freq not in RECURRING_FREQUENCIES:
        flash("تكرار غير معروف.", "danger")
        return redirect(url_for("finance.recurring_list"))
    if not (1 <= day <= 28):
        flash("اليوم يجب أن يكون بين 1 و 28.", "danger")
        return redirect(url_for("finance.recurring_list"))
    db.session.add(RecurringFeeSchedule(
        school_id=_sid(), fee_type_id=fee_type_id, frequency=freq,
        day_of_period=day, applies_to_grade_id=grade_id,
    ))
    db.session.commit()
    flash("تمت إضافة جدول رسوم متكرّر.", "success")
    return redirect(url_for("finance.recurring_list"))


@bp.route("/recurring/<int:rid>/toggle", methods=["POST"], endpoint="recurring_toggle")
@login_required
@require_permission("finance", "edit")
def recurring_toggle(rid):
    from ...models import RecurringFeeSchedule
    r = RecurringFeeSchedule.query.filter_by(id=rid, school_id=_sid()).first_or_404()
    r.is_active = not r.is_active
    db.session.commit()
    flash("تم تحديث حالة الجدول.", "success")
    return redirect(url_for("finance.recurring_list"))


@bp.route("/recurring/<int:rid>/delete", methods=["POST"], endpoint="recurring_delete")
@login_required
@require_permission("finance", "delete")
def recurring_delete(rid):
    from ...models import RecurringFeeSchedule
    r = RecurringFeeSchedule.query.filter_by(id=rid, school_id=_sid()).first_or_404()
    db.session.delete(r); db.session.commit()
    flash("تم حذف الجدول.", "success")
    return redirect(url_for("finance.recurring_list"))


@bp.route("/payment-methods", endpoint="payment_methods_list")
@login_required
@require_permission("finance", "view")
def payment_methods_list():
    from ...models import PaymentMethod
    methods = (
        PaymentMethod.query.filter_by(school_id=_sid())
        .order_by(PaymentMethod.kind, PaymentMethod.name).all()
    )
    postable_assets = (
        Account.query.filter_by(school_id=_sid(), is_postable=True)
        .filter(Account.type.in_(("asset", "liability")))
        .order_by(Account.code).all()
    )
    return render_template(
        "finance/payment_methods.html",
        methods=methods, postable_assets=postable_assets,
    )


@bp.route("/payment-methods/new", methods=["POST"], endpoint="payment_method_new")
@login_required
@require_permission("finance", "edit")
def payment_method_new():
    from ...models import PaymentMethod, PAYMENT_METHOD_KINDS
    name = (request.form.get("name") or "").strip()
    kind = (request.form.get("kind") or "immediate_cash").strip()
    account_id = request.form.get("account_id", type=int)
    if not name:
        flash("اسم طريقة الدفع مطلوب.", "danger")
        return redirect(url_for("finance.payment_methods_list"))
    if kind not in PAYMENT_METHOD_KINDS:
        flash("نوع طريقة الدفع غير معروف.", "danger")
        return redirect(url_for("finance.payment_methods_list"))
    if kind != "deferred" and not account_id:
        flash("لا بد من ربط طريقة الدفع بحساب (اختر أي حساب قابل للترحيل).", "danger")
        return redirect(url_for("finance.payment_methods_list"))
    pm = PaymentMethod(
        school_id=_sid(), name=name, kind=kind,
        account_id=(account_id if kind != "deferred" else None),
    )
    db.session.add(pm)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash("طريقة دفع بنفس الاسم موجودة بالفعل.", "danger")
        return redirect(url_for("finance.payment_methods_list"))
    flash(f"تمت إضافة طريقة الدفع ({pm.name}).", "success")
    return redirect(url_for("finance.payment_methods_list"))


@bp.route("/payment-methods/<int:pm_id>/toggle",
          methods=["POST"], endpoint="payment_method_toggle")
@login_required
@require_permission("finance", "edit")
def payment_method_toggle(pm_id):
    from ...models import PaymentMethod
    pm = PaymentMethod.query.filter_by(id=pm_id, school_id=_sid()).first_or_404()
    pm.is_active = not pm.is_active
    db.session.commit()
    flash("تم تحديث حالة طريقة الدفع.", "success")
    return redirect(url_for("finance.payment_methods_list"))


@bp.route("/payment-methods/<int:pm_id>/delete",
          methods=["POST"], endpoint="payment_method_delete")
@login_required
@require_permission("finance", "delete")
def payment_method_delete(pm_id):
    from ...models import PaymentMethod
    pm = PaymentMethod.query.filter_by(id=pm_id, school_id=_sid()).first_or_404()
    db.session.delete(pm); db.session.commit()
    flash("تم حذف طريقة الدفع.", "success")
    return redirect(url_for("finance.payment_methods_list"))


# ---------- T-9.1 Vendors + Expenses ----------

@bp.route("/vendors")
@login_required
@require_permission("expenses", "view")
def vendors_list():
    items = Vendor.query.filter_by(school_id=_sid()).order_by(Vendor.name).all()
    return render_template("finance/vendors_list.html", vendors=items)


def _vendor_bind(v):
    """Copy the vendor form's plain-text fields onto `v`."""
    v.name           = (request.form.get("name")           or "").strip()
    v.phone          = (request.form.get("phone")          or "").strip() or None
    v.email          = (request.form.get("email")          or "").strip() or None
    v.address        = (request.form.get("address")        or "").strip() or None
    v.tax_number     = (request.form.get("tax_number")     or "").strip() or None
    v.contact_person = (request.form.get("contact_person") or "").strip() or None
    v.notes          = (request.form.get("notes")          or "").strip() or None


@bp.route("/vendors/new", methods=["GET", "POST"])
@login_required
@require_permission("expenses", "edit")
def vendor_new():
    if request.method == "POST":
        v = Vendor(school_id=_sid())
        _vendor_bind(v)
        if not v.name:
            flash("اسم المورد مطلوب.", "danger")
            return render_template("finance/vendor_form.html", vendor=None)
        db.session.add(v); db.session.commit()
        flash("تم إضافة المورد.", "success")
        return redirect(url_for("finance.vendors_list"))
    return render_template("finance/vendor_form.html", vendor=None)


@bp.route("/vendors/<int:vendor_id>", endpoint="vendor_detail")
@login_required
@require_permission("expenses", "view")
def vendor_detail(vendor_id):
    """Ticket "Additional 7" — vendor profile + open-balance statement.

    Statement reads the vendor's AP sub-account (if any) via JournalLine
    so both original expense postings AND later settlements show up.
    Falls back to an empty statement when no AP sub-account exists yet.
    """
    v = _get(Vendor, vendor_id)
    lines = []
    balance = Decimal(0)
    if v.ap_account_id:
        rows = (
            db.session.query(JournalLine, JournalEntry)
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .filter(JournalLine.account_id == v.ap_account_id)
            .order_by(JournalEntry.entry_date, JournalLine.id).all()
        )
        for jl, je in rows:
            debit = Decimal(str(jl.debit or 0))
            credit = Decimal(str(jl.credit or 0))
            balance += credit - debit  # AP is liability — credit positive
            lines.append({
                "date": je.entry_date, "description": je.description,
                "reference": je.reference, "debit": debit, "credit": credit,
                "balance": balance,
            })
    return render_template(
        "finance/vendor_detail.html",
        vendor=v, lines=lines, balance=balance,
    )


@bp.route("/vendors/<int:vendor_id>/edit", methods=["GET", "POST"])
@login_required
@require_permission("expenses", "edit")
def vendor_edit(vendor_id):
    v = _get(Vendor, vendor_id)
    if request.method == "POST":
        _vendor_bind(v)
        if not v.name:
            flash("اسم المورد مطلوب.", "danger")
            return render_template("finance/vendor_form.html", vendor=v)
        db.session.commit()
        flash("تم تعديل المورد.", "success")
        return redirect(url_for("finance.vendors_list"))
    return render_template("finance/vendor_form.html", vendor=v)


@bp.route("/vendors/<int:vendor_id>/toggle", methods=["POST"])
@login_required
@require_permission("expenses", "edit")
def vendor_toggle(vendor_id):
    v = _get(Vendor, vendor_id)
    v.is_active = not v.is_active
    db.session.commit()
    flash(
        f"تم {'تفعيل' if v.is_active else 'إيقاف'} المورد ({v.name}).",
        "success",
    )
    return redirect(url_for("finance.vendors_list"))


@bp.route("/vendors/<int:vendor_id>/delete", methods=["POST"])
@login_required
@require_permission("expenses", "delete")
def vendor_delete(vendor_id):
    """Hard-delete a vendor. Guarded — Expense.vendor_id is nullable so
    we could null the link, but historical expenses need the vendor
    name for auditing, so we refuse when any expense still points here."""
    v = _get(Vendor, vendor_id)
    n_expenses = Expense.query.filter_by(vendor_id=v.id, school_id=_sid()).count()
    if n_expenses:
        flash(
            f"لا يمكن حذف المورد ({v.name}) — مرتبط بـ {n_expenses} مصروف مسجّل. "
            "اعطّله بدلاً من الحذف للحفاظ على التاريخ المحاسبي.",
            "danger",
        )
        return redirect(url_for("finance.vendors_list"))
    db.session.delete(v); db.session.commit()
    flash("تم حذف المورد نهائياً.", "success")
    return redirect(url_for("finance.vendors_list"))


@bp.route("/expenses")
@login_required
@require_permission("expenses", "view")
def expenses_list():
    end = _parse_date(request.args.get("end")) or date.today()
    start = _parse_date(request.args.get("start")) or (end - timedelta(days=90))
    items = (
        Expense.query.filter_by(school_id=_sid())
        .filter(Expense.date >= start, Expense.date <= end)
        .order_by(Expense.date.desc()).all()
    )
    total = sum((Decimal(str(e.amount)) for e in items), Decimal(0))
    return render_template(
        "finance/expenses_list.html",
        expenses=items, total=total, start=start, end=end,
    )


@bp.route("/expenses/new", methods=["GET", "POST"])
@login_required
@require_permission("expenses", "edit")
def expense_new():
    """Ticket "Full financial automation" + "Additional 1" — an expense
    is booked as DR expense / CR payment_method.account. When the picked
    method is `kind=deferred` the CR flips to the school's AP header
    (role=ap_default) so the money is recorded as a liability instead."""
    from ...models import PaymentMethod
    vendors = Vendor.query.filter_by(school_id=_sid(), is_active=True).order_by(Vendor.name).all()
    exp_accounts = Account.query.filter_by(school_id=_sid(), type="expense", is_postable=True).order_by(Account.code).all()
    payment_methods = (
        PaymentMethod.query.filter_by(school_id=_sid(), is_active=True)
        .order_by(PaymentMethod.name).all()
    )
    if request.method == "POST":
        amount = Decimal(request.form["amount"])
        d = _parse_date(request.form.get("date")) or date.today()
        ex_account = _get(Account, int(request.form["expense_account_id"]))
        pm_id = request.form.get("payment_method_id", type=int)
        pm = PaymentMethod.query.filter_by(
            id=pm_id, school_id=_sid(), is_active=True,
        ).first() if pm_id else None
        if not pm:
            flash("اختر طريقة دفع صالحة.", "danger")
            return redirect(url_for("finance.expense_new"))

        vendor_id = request.form.get("vendor_id", type=int)
        vendor = Vendor.query.filter_by(id=vendor_id, school_id=_sid()).first() \
            if vendor_id else None
        if pm.kind == "deferred":
            # Ticket "Additional 7" — deferred expense books against the
            # chosen vendor's AP sub-account (lazy-created here). Falls
            # back to ap_default header only when no vendor is picked;
            # if that header is is_postable=False on a later upgrade,
            # the caller must pick a vendor.
            if vendor:
                from ...services.subsidiary import party_ap_account
                credit_account = party_ap_account(vendor)
            else:
                credit_account = Account.query.filter_by(
                    school_id=_sid(), account_role="ap_default",
                ).first()
                if not credit_account:
                    flash(
                        "لا يوجد حساب افتراضي لذمم الموردين — اختر مورداً أو "
                        "حدّد حساباً افتراضياً من دليل الحسابات.",
                        "danger",
                    )
                    return redirect(url_for("finance.expense_new"))
            note = f"التزام مورد (آجل){' — ' + vendor.name if vendor else ''}"
        else:
            if not pm.account_id:
                flash("طريقة الدفع غير مرتبطة بحساب.", "danger")
                return redirect(url_for("finance.expense_new"))
            credit_account = _get(Account, pm.account_id)
            note = f"خروج — {pm.name}"

        je = post_journal(
            school_id=_sid(),
            entry_date=d,
            description=f"مصروف: {request.form['description'].strip()}",
            reference=(request.form.get("reference") or "").strip() or None,
            lines=[
                (ex_account.id, amount, Decimal(0), "مصروف"),
                (credit_account.id, Decimal(0), amount, note),
            ],
            related_kind="expense", related_id=None,
        )
        e = Expense(
            school_id=_sid(),
            vendor_id=vendor.id if vendor else None,
            expense_account_id=ex_account.id,
            cash_account_id=credit_account.id,
            date=d, amount=amount,
            description=request.form["description"].strip(),
            reference=(request.form.get("reference") or "").strip() or None,
            journal_entry_id=je.id,
        )
        db.session.add(e)
        db.session.commit()
        flash(
            f"تم تسجيل المصروف ({amount}) — "
            + ("مستحق على المورد (آجل)." if pm.kind == "deferred" else "تم القيد المحاسبي."),
            "success",
        )
        return redirect(url_for("finance.expenses_list"))
    return render_template(
        "finance/expense_form.html",
        vendors=vendors, exp_accounts=exp_accounts,
        payment_methods=payment_methods, expense=None,
    )


@bp.route("/expenses/<int:exp_id>/edit", methods=["GET", "POST"])
@login_required
@require_permission("expenses", "edit")
def expense_edit(exp_id):
    """Edit an expense. The journal entry is regenerated on save so that
    accounts, amount, and cash flow stay consistent — we delete the
    original entry (cascades lines) and post a fresh one, keeping the
    Expense row's identity."""
    from ...models import PaymentMethod
    e = _get(Expense, exp_id)
    vendors = Vendor.query.filter_by(school_id=_sid(), is_active=True).order_by(Vendor.name).all()
    exp_accounts = Account.query.filter_by(school_id=_sid(), type="expense", is_postable=True).order_by(Account.code).all()
    payment_methods = (
        PaymentMethod.query.filter_by(school_id=_sid(), is_active=True)
        .order_by(PaymentMethod.name).all()
    )

    if request.method == "POST":
        amount = Decimal(request.form["amount"])
        d = _parse_date(request.form.get("date")) or date.today()
        ex_account = _get(Account, int(request.form["expense_account_id"]))
        desc = request.form["description"].strip()
        pm_id = request.form.get("payment_method_id", type=int)
        pm = PaymentMethod.query.filter_by(
            id=pm_id, school_id=_sid(), is_active=True,
        ).first() if pm_id else None
        if not pm:
            flash("اختر طريقة دفع صالحة.", "danger")
            return redirect(url_for("finance.expense_edit", exp_id=e.id))
        vendor_id = request.form.get("vendor_id", type=int)
        vendor = Vendor.query.filter_by(id=vendor_id, school_id=_sid()).first() \
            if vendor_id else None
        if pm.kind == "deferred":
            if vendor:
                from ...services.subsidiary import party_ap_account
                credit_account = party_ap_account(vendor)
            else:
                credit_account = Account.query.filter_by(
                    school_id=_sid(), account_role="ap_default",
                ).first()
                if not credit_account:
                    flash("لا يوجد حساب افتراضي لذمم الموردين.", "danger")
                    return redirect(url_for("finance.accounts"))
            note = f"التزام مورد (آجل){' — ' + vendor.name if vendor else ''}"
        else:
            credit_account = _get(Account, pm.account_id) if pm.account_id else None
            if not credit_account:
                flash("طريقة الدفع غير مرتبطة بحساب.", "danger")
                return redirect(url_for("finance.expense_edit", exp_id=e.id))
            note = f"خروج — {pm.name}"

        # Replace the old journal entry with a fresh one.
        if e.journal_entry_id:
            old_je = JournalEntry.query.get(e.journal_entry_id)
            if old_je:
                db.session.delete(old_je)
                db.session.flush()

        je = post_journal(
            school_id=_sid(),
            entry_date=d,
            description=f"مصروف: {desc}",
            reference=(request.form.get("reference") or "").strip() or None,
            lines=[
                (ex_account.id, amount, Decimal(0), "مصروف"),
                (credit_account.id, Decimal(0), amount, note),
            ],
            related_kind="expense", related_id=e.id,
        )
        e.vendor_id = int(request.form["vendor_id"]) if request.form.get("vendor_id") else None
        e.expense_account_id = ex_account.id
        e.cash_account_id = credit_account.id
        e.date = d
        e.amount = amount
        e.description = desc
        e.reference = (request.form.get("reference") or "").strip() or None
        e.journal_entry_id = je.id
        db.session.commit()
        flash("تم تعديل المصروف وإعادة قيده محاسبياً.", "success")
        return redirect(url_for("finance.expenses_list"))

    return render_template(
        "finance/expense_form.html",
        vendors=vendors, exp_accounts=exp_accounts, payment_methods=payment_methods,
        expense=e,
    )


@bp.route("/expenses/<int:exp_id>/delete", methods=["POST"])
@login_required
@require_permission("expenses", "delete")
def expense_delete(exp_id):
    """Delete an expense + its journal entry. Cascade on JournalEntry
    handles the lines. We keep this destructive rather than reversing —
    schools running double-entry religiously should post a corrective
    expense instead, but for typo-fix use the delete is the right tool."""
    e = _get(Expense, exp_id)
    je_id = e.journal_entry_id
    db.session.delete(e)
    if je_id:
        je = JournalEntry.query.get(je_id)
        if je:
            db.session.delete(je)
    db.session.commit()
    flash("تم حذف المصروف وإلغاء قيده المحاسبي.", "success")
    return redirect(url_for("finance.expenses_list"))


# ---------- T-9.2 Reports ----------

def _report_data(start, end):
    """Sprint 9 TC-9.2.2 — shared computation for HTML view + PDF/Excel export."""
    sums = (
        db.session.query(
            Account.type, Account.id, Account.code, Account.name,
            func.coalesce(func.sum(JournalLine.debit), 0).label("d"),
            func.coalesce(func.sum(JournalLine.credit), 0).label("c"),
        )
        .join(JournalLine, JournalLine.account_id == Account.id)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .filter(Account.school_id == _sid())
        .filter(JournalEntry.entry_date >= start, JournalEntry.entry_date <= end)
        .group_by(Account.id, Account.type, Account.code, Account.name)
        .order_by(Account.code).all()
    )

    def bal(t, d, c):
        d, c = float(d), float(c)
        return d - c if t in ("asset", "expense") else c - d

    grouped = {"asset": [], "liability": [], "equity": [], "revenue": [], "expense": []}
    totals = {k: 0.0 for k in grouped}
    for t, aid, code, name, d, c in sums:
        b = bal(t, d, c)
        grouped.setdefault(t, []).append({"id": aid, "code": code, "name": name, "balance": b})
        totals[t] = totals.get(t, 0.0) + b

    net_income = totals["revenue"] - totals["expense"]
    return grouped, totals, net_income


@bp.route("/reports")
@login_required
@require_permission("finance", "view")
def reports():
    end = _parse_date(request.args.get("end")) or date.today()
    start = _parse_date(request.args.get("start")) or (end - timedelta(days=365))
    grouped, totals, net_income = _report_data(start, end)
    return render_template(
        "finance/reports.html",
        start=start, end=end, grouped=grouped, totals=totals, net_income=net_income,
    )


@bp.route("/reports/export")
@login_required
@require_permission("finance", "view")
def reports_export():
    """Sprint 9 TC-9.2.2 — export the financial report as PDF or Excel."""
    fmt = (request.args.get("format") or "pdf").lower()
    end = _parse_date(request.args.get("end")) or date.today()
    start = _parse_date(request.args.get("start")) or (end - timedelta(days=365))
    grouped, totals, net_income = _report_data(start, end)

    label_ar = {
        "asset": "الأصول", "liability": "الالتزامات", "equity": "حقوق الملكية",
        "revenue": "الإيرادات", "expense": "المصروفات",
    }

    if fmt == "excel":
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        wb = Workbook()
        ws = wb.active
        ws.title = "التقرير المالي"
        ws.sheet_view.rightToLeft = True

        bold_navy = Font(bold=True, color="FFFFFF")
        navy_fill = PatternFill("solid", fgColor="001556")
        gold_fill = PatternFill("solid", fgColor="D4AF37")
        header_font = Font(bold=True, size=13, color="001556")

        ws["A1"] = "التقرير المالي"
        ws["A1"].font = Font(bold=True, size=16, color="001556")
        ws.merge_cells("A1:D1")
        ws["A2"] = f"من {start.isoformat()} إلى {end.isoformat()}"
        ws["A2"].alignment = Alignment(horizontal="right")

        r = 4
        for section_key in ("asset", "liability", "equity", "revenue", "expense"):
            ws.cell(row=r, column=1, value=label_ar[section_key]).font = header_font
            r += 1
            headers = ["الرمز", "الاسم", "الرصيد"]
            for c, h in enumerate(headers, start=1):
                cell = ws.cell(row=r, column=c, value=h)
                cell.font = bold_navy
                cell.fill = navy_fill
                cell.alignment = Alignment(horizontal="center")
            r += 1
            for entry in grouped[section_key]:
                ws.cell(row=r, column=1, value=entry["code"])
                ws.cell(row=r, column=2, value=entry["name"])
                ws.cell(row=r, column=3, value=round(entry["balance"], 2))
                r += 1
            tot_cell = ws.cell(row=r, column=2, value="الإجمالي")
            tot_cell.font = Font(bold=True)
            total_val_cell = ws.cell(row=r, column=3, value=round(totals[section_key], 2))
            total_val_cell.font = Font(bold=True)
            total_val_cell.fill = gold_fill
            r += 2

        ws.cell(row=r, column=1, value="صافي الدخل").font = header_font
        ws.cell(row=r, column=3, value=round(net_income, 2)).font = Font(bold=True, size=14)
        ws.column_dimensions["A"].width = 15
        ws.column_dimensions["B"].width = 35
        ws.column_dimensions["C"].width = 18

        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        return Response(
            buf.getvalue(),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="financial_report_{start}_{end}.xlsx"'
                ),
            },
        )

    # Default: PDF via WeasyPrint (renders the print-optimized template).
    #
    # Sprint 10 hotfix — WeasyPrint has native deps (Pango, Cairo, GDK-PixBuf,
    # HarfBuzz). On production servers those must be installed with the OS
    # package manager (apt install libpango-1.0-0 libpangoft2-1.0-0 …).
    # If the deps are missing, the `import weasyprint` line raises OSError.
    # We catch it and fall back to a printable HTML page + a clear Arabic
    # error message so the user isn't stuck on a bare 500.
    html = render_template(
        "finance/reports_pdf.html",
        start=start, end=end,
        grouped=grouped, totals=totals, net_income=net_income,
        label_ar=label_ar,
    )
    try:
        from weasyprint import HTML
        pdf_bytes = HTML(string=html, base_url=request.host_url).write_pdf()
    except Exception as e:  # noqa: BLE001
        current_app.logger.exception("WeasyPrint PDF export failed: %s", e)
        # Fallback: return the printable HTML with a banner asking the user
        # to use browser print (⌘/Ctrl+P → Save as PDF).
        fallback = (
            "<!doctype html><html lang='ar' dir='rtl'><head><meta charset='utf-8'>"
            "<title>تقرير مالي — عرض للطباعة</title></head><body style='font-family:sans-serif'>"
            "<div style='background:#fef3c7;border:1px solid #d4af37;padding:12px 16px;"
            "margin-bottom:16px;border-radius:6px;color:#1a2d6c'>"
            "<strong>ملاحظة:</strong> تعذّر توليد ملف PDF على السيرفر "
            "(قد تكون مكتبات WeasyPrint الأساسية غير مثبَّتة). "
            "استخدم أمر <strong>طباعة</strong> في المتصفح "
            "(⌘+P أو Ctrl+P) واختر <em>حفظ كملف PDF</em>."
            "</div>"
            + html.split("<body>", 1)[-1].split("</body>", 1)[0]
            + "</body></html>"
        )
        return Response(fallback, mimetype="text/html")

    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="financial_report_{start}_{end}.pdf"'
            ),
        },
    )


def _parse_date(s):
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d").date()
