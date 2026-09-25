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
    Payment, School, Section, Student, Vendor,
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
    from ...services.system_codes import SYSTEM_ACCOUNT_CODES
    items = (
        Account.query.filter_by(school_id=_sid())
        .order_by(Account.code).all()
    )
    roots = [a for a in items if a.parent_id is None]
    return render_template(
        "finance/accounts.html",
        accounts=items, roots=roots,
        system_codes=SYSTEM_ACCOUNT_CODES,
    )


@bp.route("/accounts/<int:aid>/statement")
@login_required
@require_permission("finance", "view")
def account_statement(aid):
    """Ticket F — كشف حساب تفصيلي: every JournalLine on a postable
    account, sorted by entry_date, with a running balance column
    that walks the same DR/CR side rule Account.balance uses.

    Header accounts (is_postable=False) have no direct lines — we
    show a friendly info panel and link back to the tree instead."""
    from ...models import JournalEntry
    from ...models.finance import JournalLine
    acct = Account.query.filter_by(id=aid, school_id=_sid()).first_or_404()

    # Try to resolve a linked Student / Employee / Vendor for a nicer
    # header block on the party sub-accounts.
    party = None
    party_kind = None
    from ...models import Student, Vendor
    from ...models.hr import Employee
    st = Student.query.filter_by(ar_account_id=acct.id).first()
    if st:
        party, party_kind = st, "student"
    else:
        emp = Employee.query.filter_by(ap_account_id=acct.id).first()
        if emp:
            party, party_kind = emp, "employee"
        else:
            v = Vendor.query.filter_by(ap_account_id=acct.id).first()
            if v:
                party, party_kind = v, "vendor"

    lines = []
    if acct.is_postable:
        lines = (
            db.session.query(JournalLine, JournalEntry)
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .filter(JournalLine.account_id == acct.id)
            .order_by(JournalEntry.entry_date.asc(),
                      JournalEntry.id.asc(),
                      JournalLine.id.asc())
            .all()
        )
    # Running balance walks DR/CR side per account type.
    running = 0.0
    is_debit_side = acct.type in ("asset", "expense")
    rows = []
    for ln, en in lines:
        d = float(ln.debit or 0); c = float(ln.credit or 0)
        delta = (d - c) if is_debit_side else (c - d)
        running += delta
        rows.append({
            "entry_id": en.id, "date": en.entry_date,
            "reference": en.reference,
            "description": ln.description or en.description,
            "debit": d, "credit": c, "running": running,
        })
    totals = {
        "debit":  sum(r["debit"]  for r in rows),
        "credit": sum(r["credit"] for r in rows),
        "count":  len(rows),
    }
    return render_template(
        "finance/account_statement.html",
        account=acct, rows=rows, totals=totals,
        party=party, party_kind=party_kind,
        current_balance=acct.balance,
    )


def _suggest_next_child_code(school_id: int, parent: Account) -> str:
    """Ticket B — propose the next-free child code under `parent`.

    Under a top-level root (parent.parent_id is None, code ends in 000):
      step by 100 → 1100, 1200, … until unused.
    Under a Level-2 aggregate (parent.parent_id is not None):
      step by 10  → parent+10, +20, +30 … until unused.
    Falls back to appending a numeric suffix when both step patterns are
    exhausted (extremely rare)."""
    used = {
        r[0] for r in db.session.query(Account.code)
        .filter(Account.school_id == school_id).all()
    }
    try:
        base = int(parent.code)
    except (TypeError, ValueError):
        return f"{parent.code}-1"
    if parent.parent_id is None:
        # Level 1 root — step by 100 within its thousand-range.
        step = 100
        for candidate in range(base + step, base + 1000, step):
            if str(candidate) not in used:
                return str(candidate)
    else:
        step = 10
        for candidate in range(base + step, base + 100, step):
            if str(candidate) not in used:
                return str(candidate)
    return f"{parent.code}-1"


@bp.route("/accounts/suggest-code", endpoint="account_suggest_code")
@login_required
@require_permission("finance", "view")
def account_suggest_code():
    """Ajax endpoint — called by account_form.html when the parent
    dropdown changes. Returns {"code": "5150"}."""
    pid = request.args.get("parent_id", type=int)
    if not pid:
        return {"code": ""}
    parent = Account.query.filter_by(id=pid, school_id=_sid()).first()
    if not parent:
        return {"code": ""}
    return {"code": _suggest_next_child_code(_sid(), parent)}


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
        parent = Account.query.get(parent_id) if parent_id else None
        # Row directly under a root (Level 1) → aggregate.
        # Row under a Level-2 aggregate → postable Level-3 leaf.
        is_postable = bool(parent and parent.parent_id is not None)
        code = (request.form.get("code") or "").strip()
        # Ticket B — auto-fill if left blank (readonly mode).
        if not code and parent:
            code = _suggest_next_child_code(_sid(), parent)
        # Ticket B — prefix-warning check: if user typed a manual code
        # that doesn't share the parent's first digit, we warn but still
        # accept (rare edge cases might justify it).
        if parent and code and not code.startswith(parent.code[0]):
            flash(
                f"تحذير: الكود {code} لا يبدأ برقم تصنيف الأب ({parent.code[0]}). "
                "تم الحفظ لكن راجعه.",
                "warning",
            )
        a = Account(
            school_id=_sid(),
            code=code,
            name=request.form["name"].strip(),
            type=request.form["type"],
            parent_id=parent_id, is_postable=is_postable,
        )
        db.session.add(a)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash("الكود مستخدم بالفعل — اختر كوداً آخر.", "danger")
            return render_template("finance/account_form.html", parents=parents)
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
    f.soft_delete(getattr(current_user, "id", None)); db.session.commit()
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
        try:
            issue = _parse_date(request.form.get("issue_date")) or date.today()
            due = _parse_date(request.form.get("due_date")) or (issue + timedelta(days=30))
        except (ValueError, TypeError):
            flash("صيغة التاريخ غير صحيحة — استخدم YYYY-MM-DD.", "danger")
            return redirect(url_for("finance.invoice_new"))
        try:
            installments_count = int(request.form.get("installments_count") or "1")
        except (TypeError, ValueError):
            installments_count = 1

        fee_ids = request.form.getlist("fee_type_id", type=int)
        amounts = request.form.getlist("amount")
        if not fee_ids:
            flash("أضف نوع رسم واحد على الأقل.", "danger")
            return redirect(url_for("finance.invoice_new"))

        # Ticket "Race Condition في ترقيم الفاتورة" — the old
        # `count() + 1` was inherently racy: two concurrent requests
        # read the same count and both generated the same INV-YY-00007.
        # `uq_invoice_school_number` would raise IntegrityError for
        # whichever committed second. Retry against the DB constraint
        # up to 8 times, walking forward past the highest number a
        # SELECT ... FOR UPDATE returns. Any survivor after that is a
        # real concurrency storm and legitimately errors out.
        from sqlalchemy.exc import IntegrityError
        from ...services.ledger import next_invoice_number
        inv = None
        for attempt in range(8):
            number = next_invoice_number(_sid(), year.name)
            candidate = Invoice(
                school_id=_sid(),
                enrollment_id=enrollment_id,
                number=number,
                issue_date=issue,
                due_date=due,
                status="sent",
            )
            db.session.add(candidate)
            try:
                db.session.flush()
                inv = candidate
                break
            except IntegrityError:
                db.session.rollback()
                # Re-fetch the enrollment on the fresh session
                # (rollback nukes any stale identity map row).
                continue
        if inv is None:
            flash("تعذّر توليد رقم فاتورة فريد — حاول مرة أخرى.", "danger")
            return redirect(url_for("finance.invoice_new"))

        # Ticket "Additional 9" — read school's default VAT rate. If
        # any of the picked fee types are is_taxable, we accumulate tax
        # on their subtotals; the invoice's total_amount stays GROSS
        # (net + tax) so downstream paid/remaining math is unchanged.
        # (School is already imported at the module top — a nested
        # `from ...models import School` here would rebind it as a
        # local and break the GET-branch reference at line 505.)
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

        # Ticket "تضارب حساب الضريبة مع الخصومات" — explicit policy:
        # VAT is computed on the pre-discount taxable subtotal. This
        # matches how most tax authorities require the tax base to be
        # recorded (the invoice's *invoiced value* is what's taxed;
        # discounts flow through separately). The three numbers stay
        # coherent because `total_amount = subtotal + tax - discount`
        # is a linear composition; auditors can always reconstruct
        # each component from the stored fields.
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

    school = db.session.get(School, _sid())
    return render_template(
        "finance/invoice_form.html", year=year, enrollments=enrollments,
        fee_types=fee_types, preselect_enrollment_id=preselect_id,
        school=school,
    )


@bp.route("/invoices/<int:invoice_id>")
@login_required
@require_permission("finance", "view")
def invoice_detail(invoice_id):
    inv = _get(Invoice, invoice_id)
    from ...models import PaymentMethod
    payment_methods = (
        PaymentMethod.query.filter_by(school_id=_sid(), is_active=True)
        .filter(PaymentMethod.kind != "deferred")
        .order_by(PaymentMethod.name).all()
    )
    # Ticket A — full postable-account picker for "حساب آخر…".
    postable_accounts = (
        Account.query.filter_by(school_id=_sid(), is_postable=True)
        .order_by(Account.code).all()
    )
    return render_template("finance/invoice_detail.html", inv=inv,
                           payment_methods=payment_methods,
                           postable_accounts=postable_accounts)


@bp.route("/invoices/<int:invoice_id>/print")
@login_required
@require_permission("finance", "view")
def invoice_print(invoice_id):
    """Sprint 9 TC-8.3.1 — print-optimized invoice view.

    ?download=1 pipes through WeasyPrint to return a PDF.
    Default: renders HTML with @media print styles + auto window.print().

    Ticket "invoice branding" — the printed sheet now pulls its brand
    strings (legal name, logo, header/footer text, currency symbol)
    from the School row instead of hard-coded literals.
    """
    from ...models import School
    inv = _get(Invoice, invoice_id)
    school = db.session.get(School, inv.school_id)
    download = request.args.get("download") == "1"
    if download:
        html = render_template("finance/invoice_print.html",
                               inv=inv, school=school, download=True)
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
    return render_template("finance/invoice_print.html",
                           inv=inv, school=school, download=False)


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


@bp.route("/invoices/<int:invoice_id>/unvoid", methods=["POST"],
          endpoint="invoice_unvoid")
@login_required
@require_permission("finance_transactions", "add")
def invoice_unvoid(invoice_id):
    """Ticket "Un-void Invoice" — undo a void_invoice by posting a
    third mirror entry. All three entries (original / void / unvoid)
    stay in the ledger for audit."""
    from ...services.ledger import unvoid_invoice, LedgerError
    inv = _get(Invoice, invoice_id)
    try:
        unvoid_invoice(inv)
    except LedgerError as e:
        db.session.rollback()
        flash(str(e), "danger")
        return redirect(url_for("finance.invoice_detail", invoice_id=inv.id))
    db.session.commit()
    flash(f"تم التراجع عن إلغاء الفاتورة {inv.number}.", "success")
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
    # Ticket A — form can send EITHER payment_method_id (shortcut) OR
    # override_account_id (free picker "حساب آخر"). At least one.
    payment_method_id = request.form.get("payment_method_id", type=int) or None
    override_account_id = request.form.get("override_account_id", type=int) or None
    if not payment_method_id and not override_account_id:
        flash("اختر طريقة الدفع أو حساب استلام.", "danger")
        return redirect(url_for("finance.invoice_detail", invoice_id=inv.id))

    pay_date = _parse_date(request.form.get("payment_date")) or date.today()
    reference = (request.form.get("reference") or "").strip() or None
    notes = (request.form.get("notes") or "").strip() or None

    try:
        if is_refund:
            issue_refund(inv, amount, payment_method_id or 0,
                         reason=notes or "استرداد",
                         refund_date=pay_date,
                         override_account_id=override_account_id)
            flash(f"تم استرداد {amount} من الفاتورة {inv.number}.", "success")
        else:
            record_payment(inv, amount, payment_method_id,
                           payment_date=pay_date,
                           reference=reference, notes=notes,
                           override_account_id=override_account_id)
            flash(f"تم تسجيل دفعة {amount} على الفاتورة {inv.number}.", "success")
    except LedgerError as e:
        db.session.rollback()
        flash(str(e), "danger")
        return redirect(url_for("finance.invoice_detail", invoice_id=inv.id))

    db.session.commit()

    # Reload the last-added Payment row for the notification hook below.
    payment = inv.payments[-1] if inv.payments else None
    # Ticket "سند قبض/صرف رسمي" — auto-generate the voucher document.
    if payment is not None:
        from ...services.vouchers import auto_create_for_payment
        auto_create_for_payment(payment)
        db.session.commit()

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

# ---------- Reports (Ticket G) --------------------------------------

@bp.route("/reports", endpoint="reports_index")
@login_required
@require_permission("finance", "view")
def reports_index():
    return render_template("finance/reports_index.html")


def _report_range():
    end = _parse_date(request.args.get("end")) or date.today()
    start = _parse_date(request.args.get("start")) or (end - timedelta(days=90))
    return start, end


@bp.route("/reports/trial-balance", endpoint="report_trial_balance")
@login_required
@require_permission("finance", "view")
def report_trial_balance():
    from ...services.reports import trial_balance
    s, e = _report_range()
    return render_template("finance/report_trial_balance.html",
                           data=trial_balance(_sid(), start=s, end=e),
                           start=s, end=e)


@bp.route("/reports/income-statement", endpoint="report_income_statement")
@login_required
@require_permission("finance", "view")
def report_income_statement():
    from ...services.reports import income_statement
    s, e = _report_range()
    return render_template("finance/report_income_statement.html",
                           data=income_statement(_sid(), start=s, end=e),
                           start=s, end=e)


@bp.route("/reports/balance-sheet", endpoint="report_balance_sheet")
@login_required
@require_permission("finance", "view")
def report_balance_sheet():
    from ...services.reports import balance_sheet
    at = _parse_date(request.args.get("at")) or date.today()
    return render_template("finance/report_balance_sheet.html",
                           data=balance_sheet(_sid(), at=at), at=at)


@bp.route("/reports/general-ledger", endpoint="report_general_ledger")
@login_required
@require_permission("finance", "view")
def report_general_ledger():
    from ...services.reports import general_ledger
    s, e = _report_range()
    account_id = request.args.get("account_id", type=int)
    accounts = Account.query.filter_by(
        school_id=_sid(), is_postable=True,
    ).order_by(Account.code).all()
    data = general_ledger(_sid(), account_id, start=s, end=e) if account_id else None
    return render_template("finance/report_general_ledger.html",
                           data=data, accounts=accounts,
                           account_id=account_id, start=s, end=e)


@bp.route("/reports/cash-flow", endpoint="report_cash_flow")
@login_required
@require_permission("finance", "view")
def report_cash_flow():
    from ...services.reports import cash_flow
    s, e = _report_range()
    return render_template("finance/report_cash_flow.html",
                           data=cash_flow(_sid(), start=s, end=e),
                           start=s, end=e)


@bp.route("/reports/aging", endpoint="report_aging")
@login_required
@require_permission("finance", "view")
def report_aging():
    from ...services.reports import aging_report
    at = _parse_date(request.args.get("at")) or date.today()
    return render_template("finance/report_aging.html",
                           data=aging_report(_sid(), at=at), at=at)


@bp.route("/reports/cost-centers", endpoint="report_cost_centers")
@login_required
@require_permission("finance", "view")
def report_cost_centers():
    from ...services.reports import cost_center_pl
    s, e = _report_range()
    return render_template("finance/report_cost_centers.html",
                           data=cost_center_pl(_sid(), start=s, end=e),
                           start=s, end=e)


@bp.route("/reports/collection", endpoint="report_collection")
@login_required
@require_permission("finance", "view")
def report_collection():
    from ...services.reports import collection_report
    s, e = _report_range()
    return render_template("finance/report_collection.html",
                           data=collection_report(_sid(), start=s, end=e),
                           start=s, end=e)


@bp.route("/reports/overdue-by-grade", endpoint="report_overdue_by_grade")
@login_required
@require_permission("finance", "view")
def report_overdue_by_grade():
    from ...services.reports import overdue_by_grade
    at = _parse_date(request.args.get("at")) or date.today()
    return render_template("finance/report_overdue_by_grade.html",
                           data=overdue_by_grade(_sid(), at=at), at=at)


@bp.route("/reports/revenue-by-fee-type", endpoint="report_revenue_by_fee_type")
@login_required
@require_permission("finance", "view")
def report_revenue_by_fee_type():
    from ...services.reports import revenue_by_fee_type
    s, e = _report_range()
    return render_template("finance/report_revenue_by_fee_type.html",
                           data=revenue_by_fee_type(_sid(), start=s, end=e),
                           start=s, end=e)


@bp.route("/reports/payroll-summary", endpoint="report_payroll_summary")
@login_required
@require_permission("finance", "view")
def report_payroll_summary():
    from ...services.reports import payroll_summary
    return render_template("finance/report_payroll_summary.html",
                           data=payroll_summary(_sid()))


@bp.route("/reports/cost-per-student", endpoint="report_cost_per_student")
@login_required
@require_permission("finance", "view")
def report_cost_per_student():
    from ...services.reports import cost_per_student
    s, e = _report_range()
    return render_template("finance/report_cost_per_student.html",
                           data=cost_per_student(_sid(), start=s, end=e),
                           start=s, end=e)


@bp.route("/reports/discounts-grants", endpoint="report_discounts_grants")
@login_required
@require_permission("finance", "view")
def report_discounts_grants():
    from ...services.reports import discounts_grants
    s, e = _report_range()
    return render_template("finance/report_discounts_grants.html",
                           data=discounts_grants(_sid(), start=s, end=e),
                           start=s, end=e)


@bp.route("/reports/year-comparison", endpoint="report_year_comparison")
@login_required
@require_permission("finance", "view")
def report_year_comparison():
    from ...services.reports import year_comparison
    years = AcademicYear.query.filter_by(school_id=_sid()).order_by(AcademicYear.start_date.desc()).all()
    year_a = request.args.get("year_a", type=int)
    year_b = request.args.get("year_b", type=int)
    data = year_comparison(_sid(), year_a, year_b) if year_a else None
    return render_template("finance/report_year_comparison.html",
                           data=data, years=years,
                           year_a=year_a, year_b=year_b)


@bp.route("/reports/forecast", endpoint="report_forecast")
@login_required
@require_permission("finance", "view")
def report_forecast():
    from ...services.reports import forecast_report
    months = int(request.args.get("months", 6))
    return render_template("finance/report_forecast.html",
                           data=forecast_report(_sid(), months_ahead=months),
                           months=months)


# ---------- Cost Centers (Ticket F) ---------------------------------

@bp.route("/cost-centers", endpoint="cost_centers_list")
@login_required
@require_permission("finance", "view")
def cost_centers_list():
    from ...models import CostCenter
    items = (
        CostCenter.query.filter_by(school_id=_sid())
        .order_by(CostCenter.name).all()
    )
    return render_template("finance/cost_centers.html", items=items)


@bp.route("/cost-centers/new", methods=["POST"], endpoint="cost_center_new")
@login_required
@require_permission("finance", "edit")
def cost_center_new():
    from ...models import CostCenter
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("اسم مركز التكلفة مطلوب.", "danger")
        return redirect(url_for("finance.cost_centers_list"))
    db.session.add(CostCenter(
        school_id=_sid(), name=name,
        code=(request.form.get("code") or "").strip() or None,
    ))
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash("مركز تكلفة بنفس الاسم موجود بالفعل.", "danger")
        return redirect(url_for("finance.cost_centers_list"))
    flash("تمت الإضافة.", "success")
    return redirect(url_for("finance.cost_centers_list"))


@bp.route("/cost-centers/<int:cc_id>/toggle", methods=["POST"],
          endpoint="cost_center_toggle")
@login_required
@require_permission("finance", "edit")
def cost_center_toggle(cc_id):
    from ...models import CostCenter
    cc = CostCenter.query.filter_by(id=cc_id, school_id=_sid()).first_or_404()
    cc.is_active = not cc.is_active
    db.session.commit()
    return redirect(url_for("finance.cost_centers_list"))


@bp.route("/cost-centers/<int:cc_id>/delete", methods=["POST"],
          endpoint="cost_center_delete")
@login_required
@require_permission("finance", "delete")
def cost_center_delete(cc_id):
    from ...models import CostCenter
    cc = CostCenter.query.filter_by(id=cc_id, school_id=_sid()).first_or_404()
    cc.soft_delete(getattr(current_user, "id", None)); db.session.commit()
    flash("تم الحذف.", "success")
    return redirect(url_for("finance.cost_centers_list"))


# ---------- Treasury dashboard (Ticket E) ---------------------------

@bp.route("/treasury", endpoint="treasury")
@login_required
@require_permission("finance", "view")
def treasury():
    """Ticket E — treasury dashboard: cash + bank overview with quick
    actions. Cash accounts = under 1100 with '1110' prefix / bank
    accounts under 1120."""
    all_cash_bank = (
        Account.query.filter_by(school_id=_sid(), is_postable=True, type="asset")
        .filter(Account.code.startswith("11"))
        .order_by(Account.code).all()
    )
    cash_accounts = [a for a in all_cash_bank if a.code.startswith("111")]
    bank_accounts = [a for a in all_cash_bank if a.code.startswith("112")]
    cash_total = sum((a.balance for a in cash_accounts), 0.0)
    bank_total = sum((a.balance for a in bank_accounts), 0.0)
    return render_template(
        "finance/treasury.html",
        cash_accounts=cash_accounts, bank_accounts=bank_accounts,
        cash_total=cash_total, bank_total=bank_total,
        all_accounts=cash_accounts + bank_accounts,
    )


@bp.route("/treasury/transfer", methods=["POST"], endpoint="treasury_transfer")
@login_required
@require_permission("finance_transactions", "add")
def treasury_transfer():
    from ...services.ledger import record_transfer, LedgerError
    try:
        amount = Decimal(request.form.get("amount") or "0")
    except Exception:
        flash("المبلغ غير صالح.", "danger")
        return redirect(url_for("finance.treasury"))
    from_id = request.form.get("from_account_id", type=int)
    to_id = request.form.get("to_account_id", type=int)
    description = (request.form.get("description") or "").strip()
    at = _parse_date(request.form.get("transfer_date")) or date.today()
    try:
        record_transfer(_sid(), from_id, to_id, amount,
                        transfer_date=at, description=description)
    except LedgerError as e:
        db.session.rollback()
        flash(str(e), "danger")
        return redirect(url_for("finance.treasury"))
    db.session.commit()
    flash(f"تم تحويل {amount} بنجاح.", "success")
    return redirect(url_for("finance.treasury"))


# ---------- Quick Journal templates (Ticket D) ----------------------

@bp.route("/quick-journal", endpoint="quick_journal_index")
@login_required
@require_permission("finance_transactions", "add")
def quick_journal_index():
    from ...services.quick_journal import TEMPLATES
    return render_template("finance/quick_journal_index.html", templates=TEMPLATES)


@bp.route("/quick-journal/<key>", methods=["GET", "POST"],
          endpoint="quick_journal_run")
@login_required
@require_permission("finance_transactions", "add")
def quick_journal_run(key):
    from ...services.quick_journal import TEMPLATES, apply_journal_template, QuickJournalError
    tpl = TEMPLATES.get(key)
    if tpl is None:
        abort(404)
    postable_accounts = (
        Account.query.filter_by(school_id=_sid(), is_postable=True)
        .order_by(Account.code).all()
    )
    if request.method == "POST":
        try:
            amount = Decimal(request.form.get("amount") or "0")
        except Exception:
            flash("المبلغ غير صالح.", "danger")
            return redirect(url_for("finance.quick_journal_run", key=key))
        counter_account_id = request.form.get("counter_account_id", type=int)
        extra_account_id = request.form.get("extra_account_id", type=int) or None
        description = (request.form.get("description") or "").strip()
        entry_date = _parse_date(request.form.get("entry_date")) or date.today()
        try:
            apply_journal_template(
                key, _sid(), amount, counter_account_id, description,
                entry_date=entry_date, extra_account_id=extra_account_id,
            )
        except QuickJournalError as e:
            db.session.rollback()
            flash(str(e), "danger")
            return redirect(url_for("finance.quick_journal_run", key=key))
        db.session.commit()
        flash(f"تم تنفيذ القيد ({tpl['label']}).", "success")
        return redirect(url_for("finance.quick_journal_index"))
    return render_template(
        "finance/quick_journal_run.html",
        key=key, tpl=tpl, postable_accounts=postable_accounts,
        today=date.today(),
    )


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
    # Ticket "IDOR في مطابقة كشف الحساب البنكي" — the previous
    # `JournalLine.query.get(jl_id)` skipped tenant filtering. In a
    # multi-tenant SaaS, a school could POST a journal_line_id owned
    # by a different school's row and still get matched. Fix: join
    # through JournalEntry → school_id and 404 anything not owned by
    # the current tenant.
    jl = (
        db.session.query(JournalLine)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .filter(JournalLine.id == jl_id,
                JournalEntry.school_id == _sid())
        .first()
    )
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
    pm.soft_delete(getattr(current_user, "id", None)); db.session.commit()
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
    v.soft_delete(getattr(current_user, "id", None)); db.session.commit()
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
    from ...models import PaymentMethod, CostCenter
    vendors = Vendor.query.filter_by(school_id=_sid(), is_active=True).order_by(Vendor.name).all()
    exp_accounts = Account.query.filter_by(school_id=_sid(), type="expense", is_postable=True).order_by(Account.code).all()
    payment_methods = (
        PaymentMethod.query.filter_by(school_id=_sid(), is_active=True)
        .order_by(PaymentMethod.name).all()
    )
    cost_centers = (
        CostCenter.query.filter_by(school_id=_sid(), is_active=True)
        .order_by(CostCenter.name).all()
    )
    if request.method == "POST":
        amount = Decimal(request.form["amount"])
        d = _parse_date(request.form.get("date")) or date.today()
        ex_account = _get(Account, int(request.form["expense_account_id"]))
        cost_center_id = request.form.get("cost_center_id", type=int) or None
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
                from ...services.system_codes import get_account_by_code
                credit_account = get_account_by_code(_sid(), "2110")
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

        # Ticket "Approval Workflow على المصروفات" — if the amount
        # is above the school's approval threshold, park the row as
        # `pending` with NO journal effect. Approval later runs
        # post_expense_journal + auto-creates the voucher.
        school = db.session.get(School, _sid())
        threshold = Decimal(str(school.approval_threshold or 0))
        needs_approval = threshold > 0 and amount >= threshold

        if needs_approval:
            e = Expense(
                school_id=_sid(),
                vendor_id=vendor.id if vendor else None,
                expense_account_id=ex_account.id,
                cash_account_id=credit_account.id,
                date=d, amount=amount,
                description=request.form["description"].strip(),
                reference=(request.form.get("reference") or "").strip() or None,
                cost_center_id=cost_center_id,
                approval_status="pending",
            )
            db.session.add(e); db.session.commit()
            flash(
                f"تم تسجيل المصروف ({amount}) بانتظار الاعتماد "
                "من المدير — لن يُرحّل محاسبياً قبل الموافقة.",
                "info",
            )
            return redirect(url_for("finance.expenses_list"))

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
            cost_center_id=cost_center_id,
            approval_status="approved",
        )
        db.session.add(e)
        db.session.commit()
        # Auto-create the outgoing voucher.
        from ...services.vouchers import auto_create_for_expense
        auto_create_for_expense(e)
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
        cost_centers=cost_centers,
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
                from ...services.system_codes import get_account_by_code
                credit_account = get_account_by_code(_sid(), "2110")
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


# ── Budget vs Actual (Ticket "الموازنة التخطيطية") ─────────────────
@bp.route("/budgets", endpoint="budgets_home")
@login_required
@require_permission("finance", "view")
def budgets_home():
    from ...models import Budget, AcademicYear, CostCenter
    year = _active_year()
    items = (
        Budget.query.filter_by(school_id=_sid(), year_id=year.id if year else 0)
        .all() if year else []
    )
    postable = (
        Account.query.filter_by(school_id=_sid(), is_postable=True)
        .filter(Account.type.in_(["revenue", "expense"]))
        .order_by(Account.code).all()
    )
    ccs = CostCenter.query.filter_by(school_id=_sid(), is_active=True).all()
    return render_template("finance/budgets.html",
                           budgets=items, year=year,
                           accounts=postable, cost_centers=ccs)


@bp.route("/budgets/new", methods=["POST"], endpoint="budget_new")
@login_required
@require_permission("finance", "add")
def budget_new():
    from ...models import Budget
    year = _active_year()
    if not year:
        flash("لا توجد سنة دراسية نشطة.", "danger")
        return redirect(url_for("finance.budgets_home"))
    b = Budget(
        school_id=_sid(), year_id=year.id,
        account_id=request.form.get("account_id", type=int) or None,
        cost_center_id=request.form.get("cost_center_id", type=int) or None,
        period=(request.form.get("period") or "annual").strip(),
        planned_amount=Decimal(request.form.get("planned_amount") or "0"),
        warn_pct=int(request.form.get("warn_pct") or 90),
        note=(request.form.get("note") or "").strip() or None,
    )
    if not b.account_id and not b.cost_center_id:
        flash("اختر حساباً أو مركز تكلفة.", "danger")
        return redirect(url_for("finance.budgets_home"))
    db.session.add(b); db.session.commit()
    flash("تم إضافة بند الميزانية.", "success")
    return redirect(url_for("finance.budgets_home"))


@bp.route("/budgets/<int:bid>/delete", methods=["POST"], endpoint="budget_delete")
@login_required
@require_permission("finance", "delete")
def budget_delete(bid):
    from ...models import Budget
    b = Budget.query.filter_by(id=bid, school_id=_sid()).first_or_404()
    db.session.delete(b); db.session.commit()
    flash("تم حذف البند.", "success")
    return redirect(url_for("finance.budgets_home"))


@bp.route("/reports/budget-vs-actual", endpoint="report_budget_vs_actual")
@login_required
@require_permission("finance", "view")
def report_budget_vs_actual():
    from ...services.reports import budget_vs_actual_report
    year = _active_year()
    rows = budget_vs_actual_report(_sid(), year.id if year else 0)
    return render_template("finance/report_budget_actual.html",
                           rows=rows, year=year)


# ── Approval workflow on Expenses ─────────────────────────────────
@bp.route("/expenses/<int:eid>/approve", methods=["POST"],
          endpoint="expense_approve")
@login_required
@require_permission("finance_transactions", "add")
def expense_approve(eid):
    from ...models import Expense, School
    from ...services.ledger import post_expense_journal
    e = Expense.query.filter_by(id=eid, school_id=_sid()).first_or_404()
    if e.approval_status == "approved":
        flash("المصروف معتمد بالفعل.", "info")
        return redirect(url_for("finance.expenses"))
    try:
        post_expense_journal(e)
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        flash(f"تعذّر الاعتماد: {exc}", "danger")
        return redirect(url_for("finance.expenses"))
    e.approval_status = "approved"
    e.approved_by_id = current_user.id
    e.approved_at = datetime.utcnow()
    # Auto-generate the outgoing voucher (سند صرف).
    from ...services.vouchers import auto_create_for_expense
    auto_create_for_expense(e)
    db.session.commit()
    flash(f"تم اعتماد المصروف #{e.id} وترحيله محاسبياً.", "success")
    return redirect(url_for("finance.expenses"))


@bp.route("/expenses/<int:eid>/reject", methods=["POST"],
          endpoint="expense_reject")
@login_required
@require_permission("finance_transactions", "add")
def expense_reject(eid):
    from ...models import Expense
    e = Expense.query.filter_by(id=eid, school_id=_sid()).first_or_404()
    if e.approval_status != "pending":
        flash("لا يمكن الرفض إلا للمصروفات قيد المراجعة.", "warning")
        return redirect(url_for("finance.expenses"))
    e.approval_status = "rejected"
    e.reject_reason = (request.form.get("reason") or "").strip() or "بدون سبب"
    e.approved_by_id = current_user.id
    e.approved_at = datetime.utcnow()
    db.session.commit()
    flash(f"تم رفض المصروف #{e.id}.", "warning")
    return redirect(url_for("finance.expenses"))


# ── Unified financial dashboard ────────────────────────────────────
@bp.route("/dashboard", endpoint="dashboard")
@login_required
@require_permission("finance", "view")
def dashboard():
    """Ticket "Dashboard مالي موحّد" — aggregates the existing report
    surface (treasury, aging, collection, forecast, overdue) into one
    screen. No duplicated logic — every number links back to its full
    report."""
    from ...services.reports import (
        aging_report, collection_report, forecast_report,
    )
    from ...models import Invoice
    # Treasury
    all_cash_bank = (
        Account.query.filter_by(school_id=_sid(), is_postable=True, type="asset")
        .filter(Account.code.startswith("11")).all()
    )
    cash_total = sum(a.balance for a in all_cash_bank if a.code.startswith("111"))
    bank_total = sum(a.balance for a in all_cash_bank if a.code.startswith("112"))
    # Aging
    aging = aging_report(_sid())
    # Collection this month
    today = date.today()
    month_start = today.replace(day=1)
    collect = collection_report(_sid(), start=month_start, end=today)
    # Forecast
    forecast = forecast_report(_sid(), months_ahead=3)
    # Overdue count + total
    overdue = (
        Invoice.query.filter(Invoice.school_id == _sid(),
                              Invoice.status == "overdue").all()
    )
    overdue_total = sum(
        float(i.total_amount or 0) - float(i.paid_amount or 0)
        for i in overdue
    )
    return render_template(
        "finance/dashboard.html",
        cash_total=cash_total, bank_total=bank_total,
        aging=aging, collect=collect, forecast=forecast,
        overdue_count=len(overdue), overdue_total=overdue_total,
    )
