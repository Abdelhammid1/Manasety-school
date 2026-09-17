from datetime import datetime, date
from decimal import Decimal

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import Account, Employee, JournalEntry, Payroll, User
from ...services.accounting import post_journal


def _sid():
    return current_user.school_id


def _get(model, oid):
    obj = model.query.filter_by(id=oid, school_id=_sid()).first()
    if not obj:
        abort(404)
    return obj


# ---------- T-9.3 Employees ----------

@bp.route("/employees")
@login_required
@require_permission("payroll", "view")
def employees_list():
    items = Employee.query.filter_by(school_id=_sid()).order_by(Employee.full_name).all()
    return render_template("hr/employees_list.html", employees=items)


def _employee_bind(e):
    """Copy the employee-form fields onto `e`. Shared new + edit."""
    e.full_name    = (request.form.get("full_name")    or "").strip()
    e.job_title    = (request.form.get("job_title")    or "").strip()
    e.base_salary  = Decimal(request.form.get("base_salary") or "0")
    e.national_id  = (request.form.get("national_id")  or "").strip() or None
    e.phone        = (request.form.get("phone")        or "").strip() or None
    e.email        = (request.form.get("email")        or "").strip() or None
    e.bank_account = (request.form.get("bank_account") or "").strip() or None
    e.hire_date    = _parse_date(request.form.get("hire_date"))
    e.user_id      = request.form.get("user_id", type=int) or None


@bp.route("/employees/new", methods=["GET", "POST"])
@login_required
@require_permission("payroll", "edit")
def employee_new():
    users = User.query.filter_by(school_id=_sid()).order_by(User.full_name).all()
    if request.method == "POST":
        e = Employee(school_id=_sid())
        _employee_bind(e)
        if not e.full_name or not e.job_title:
            flash("الاسم والمسمّى الوظيفي مطلوبان.", "danger")
            return render_template("hr/employee_form.html", employee=None, users=users)
        db.session.add(e); db.session.commit()
        flash(f"تم إضافة الموظف {e.full_name}.", "success")
        return redirect(url_for("hr.employee_detail", employee_id=e.id))
    return render_template("hr/employee_form.html", employee=None, users=users)


@bp.route("/employees/<int:employee_id>")
@login_required
@require_permission("payroll", "view")
def employee_detail(employee_id):
    from ...models import PaymentMethod, EmployeeAdvance
    e = _get(Employee, employee_id)
    payment_methods = (
        PaymentMethod.query.filter_by(school_id=_sid(), is_active=True)
        .filter(PaymentMethod.kind != "deferred")
        .order_by(PaymentMethod.name).all()
    )
    advances = (
        EmployeeAdvance.query.filter_by(employee_id=e.id)
        .order_by(EmployeeAdvance.date_given.desc()).all()
    )
    return render_template("hr/employee_detail.html",
                           employee=e, payment_methods=payment_methods,
                           advances=advances)


@bp.route("/employees/<int:employee_id>/advances/new", methods=["POST"])
@login_required
@require_permission("finance_transactions", "add")
def employee_advance_new(employee_id):
    """Ticket "Additional 12" — hand out a cash advance to an employee."""
    from ...services.ledger import issue_employee_advance, LedgerError
    e = _get(Employee, employee_id)
    try:
        amount = Decimal(request.form.get("amount") or "0")
    except Exception:
        flash("المبلغ غير صالح.", "danger")
        return redirect(url_for("hr.employee_detail", employee_id=e.id))
    pm_id = request.form.get("payment_method_id", type=int)
    plan = (request.form.get("deduction_plan") or "full_next_month").strip()
    installment_count = request.form.get("installment_count", type=int) or None
    notes = (request.form.get("notes") or "").strip() or None
    if not pm_id:
        flash("اختر طريقة الدفع.", "danger")
        return redirect(url_for("hr.employee_detail", employee_id=e.id))
    try:
        issue_employee_advance(
            e, amount, pm_id,
            deduction_plan=plan,
            installment_count=installment_count,
            notes=notes,
        )
    except LedgerError as ex:
        db.session.rollback()
        flash(str(ex), "danger")
        return redirect(url_for("hr.employee_detail", employee_id=e.id))
    db.session.commit()
    flash(
        f"تم صرف سلفة بمبلغ {amount} — هتُخصم من راتب "
        + ("الشهر القادم." if plan == "full_next_month" else f"على {installment_count} أشهر."),
        "success",
    )
    return redirect(url_for("hr.employee_detail", employee_id=e.id))


@bp.route("/employees/<int:employee_id>/edit", methods=["GET", "POST"])
@login_required
@require_permission("payroll", "edit")
def employee_edit(employee_id):
    e = _get(Employee, employee_id)
    users = User.query.filter_by(school_id=_sid()).order_by(User.full_name).all()
    if request.method == "POST":
        _employee_bind(e)
        if not e.full_name or not e.job_title:
            flash("الاسم والمسمّى الوظيفي مطلوبان.", "danger")
            return render_template("hr/employee_form.html", employee=e, users=users)
        db.session.commit()
        flash("تم تعديل بيانات الموظف.", "success")
        return redirect(url_for("hr.employee_detail", employee_id=e.id))
    return render_template("hr/employee_form.html", employee=e, users=users)


@bp.route("/employees/<int:employee_id>/toggle", methods=["POST"])
@login_required
@require_permission("payroll", "edit")
def employee_toggle(employee_id):
    e = _get(Employee, employee_id)
    e.is_active = not e.is_active
    db.session.commit()
    flash(
        f"تم {'تفعيل' if e.is_active else 'إيقاف'} الموظف ({e.full_name}).",
        "success",
    )
    return redirect(url_for("hr.employees_list"))


@bp.route("/employees/<int:employee_id>/delete", methods=["POST"])
@login_required
@require_permission("payroll", "delete")
def employee_delete(employee_id):
    """Delete an employee. Refuses if any payroll has been issued —
    Payroll.employee_id is NOT NULL, and deleting one would corrupt
    the accounting history. Deactivate instead when the employee left."""
    e = _get(Employee, employee_id)
    n_payrolls = Payroll.query.filter_by(employee_id=e.id).count()
    if n_payrolls:
        flash(
            f"لا يمكن حذف الموظف ({e.full_name}) — له {n_payrolls} راتب مسجّل. "
            "أوقفه بدلاً من الحذف.",
            "danger",
        )
        return redirect(url_for("hr.employees_list"))
    db.session.delete(e); db.session.commit()
    flash("تم حذف الموظف نهائياً.", "success")
    return redirect(url_for("hr.employees_list"))


# ---------- T-9.3 Payroll ----------

@bp.route("/payroll")
@login_required
@require_permission("payroll", "view")
def payroll_list():
    items = (
        Payroll.query.filter_by(school_id=_sid())
        .order_by(Payroll.period_year.desc(), Payroll.period_month.desc(), Payroll.id.desc())
        .limit(200).all()
    )
    return render_template("hr/payroll_list.html", payrolls=items)


@bp.route("/payroll/new", methods=["GET", "POST"])
@login_required
@require_permission("payroll", "edit")
def payroll_new():
    employees = (
        Employee.query.filter_by(school_id=_sid(), is_active=True)
        .order_by(Employee.full_name).all()
    )
    # Ticket "Full financial automation" — payroll now creates an
    # ACCRUAL (DR expense / CR employee 2210 sub-account). Actual
    # payment (via PaymentMethod) happens on a separate settle route.
    salary_account = Account.query.filter_by(
        school_id=_sid(), account_role="payroll_salary_default",
    ).first()

    if not employees:
        flash("لا يوجد موظفون نشطون — أضف موظفاً قبل استحقاق الراتب.", "warning")
        return redirect(url_for("hr.employees_list"))
    if not salary_account:
        flash(
            "لا يوجد حساب مُعيَّن كـ «افتراضي رواتب المعلمين». افتح دليل "
            "الحسابات وحدّد حساب مصروف الرواتب.",
            "danger",
        )
        return redirect(url_for("finance.accounts"))

    if request.method == "POST":
        employee_id = request.form.get("employee_id", type=int)
        if employee_id not in [x.id for x in employees]:
            flash("اختر موظفاً صحيحاً.", "danger")
            return render_template("hr/payroll_form.html",
                                   employees=employees, today=date.today())
        e = _get(Employee, employee_id)
        period_year = int(request.form["period_year"])
        period_month = int(request.form["period_month"])
        base = Decimal(request.form.get("base_salary") or str(e.base_salary or 0))
        allowances = Decimal(request.form.get("allowances") or "0")
        override = request.form.get("deductions")
        if override and override.strip():
            deductions = Decimal(override)
        else:
            from ...services.payroll_calc import compute_absence_deduction
            deductions = compute_absence_deduction(e, period_year, period_month, base)
        net = base + allowances - deductions

        dup = Payroll.query.filter_by(
            employee_id=e.id, period_year=period_year, period_month=period_month,
        ).first()
        if dup:
            flash("استحقاق هذا الشهر مسجَّل بالفعل لهذا الموظف.", "warning")
            return redirect(url_for("hr.payroll_list"))

        accrual_date = _parse_date(request.form.get("paid_at")) or date.today()
        p = Payroll(
            school_id=_sid(),
            employee_id=e.id,
            period_year=period_year, period_month=period_month,
            base_salary=base, allowances=allowances, deductions=deductions,
            net_pay=net,
        )
        db.session.add(p); db.session.flush()

        from ...services.ledger import (
            post_payroll_accrual, apply_advance_deductions, LedgerError,
        )
        try:
            je = post_payroll_accrual(p, salary_account, entry_date=accrual_date)
            p.journal_entry_id = je.id
            # Ticket "Additional 12" — auto-deduct any active advances.
            deducted = apply_advance_deductions(p)
        except LedgerError as ex:
            db.session.rollback()
            flash(str(ex), "danger")
            return redirect(url_for("hr.payroll_new"))
        db.session.commit()
        msg = f"تم تسجيل استحقاق راتب {e.full_name} بمبلغ صافي {net}."
        if deducted:
            msg += f" خُصم من الاستحقاق {deducted:.2f} سداداً لسلف نشطة."
        msg += " افتح صف الراتب لصرفه (كامل أو جزئي)."
        flash(msg, "success")
        return redirect(url_for("hr.payroll_detail", payroll_id=p.id))

    return render_template(
        "hr/payroll_form.html",
        employees=employees,
        today=date.today(),
    )


@bp.route("/payroll/<int:payroll_id>", methods=["GET"])
@login_required
@require_permission("payroll", "view")
def payroll_detail(payroll_id):
    """Detail view for one payroll accrual — shows the running balance
    (net_pay − paid_amount) and lets the admin settle it fully or
    partially through any active PaymentMethod."""
    from ...models import PaymentMethod
    p = Payroll.query.filter_by(id=payroll_id, school_id=_sid()).first_or_404()
    payment_methods = (
        PaymentMethod.query.filter_by(school_id=_sid(), is_active=True)
        .filter(PaymentMethod.kind != "deferred")
        .order_by(PaymentMethod.name).all()
    )
    return render_template("hr/payroll_detail.html",
                           payroll=p, payment_methods=payment_methods,
                           today=date.today())


@bp.route("/payroll/<int:payroll_id>/settle", methods=["POST"])
@login_required
@require_permission("finance_transactions", "add")
def payroll_settle(payroll_id):
    from ...services.ledger import settle_accrual, LedgerError
    p = Payroll.query.filter_by(id=payroll_id, school_id=_sid()).first_or_404()
    try:
        amount = Decimal(request.form.get("amount") or "0")
    except Exception:
        flash("المبلغ غير صالح.", "danger")
        return redirect(url_for("hr.payroll_detail", payroll_id=p.id))
    pm_id = request.form.get("payment_method_id", type=int)
    if not pm_id:
        flash("اختر طريقة الدفع.", "danger")
        return redirect(url_for("hr.payroll_detail", payroll_id=p.id))
    settled_at = _parse_date(request.form.get("settled_at")) or date.today()
    notes = (request.form.get("notes") or "").strip() or None
    try:
        settle_accrual(p, pm_id, amount=amount if amount > 0 else None,
                       settled_at=settled_at, notes=notes)
    except LedgerError as e:
        db.session.rollback()
        flash(str(e), "danger")
        return redirect(url_for("hr.payroll_detail", payroll_id=p.id))
    db.session.commit()
    flash(
        "تم صرف الراتب بالكامل." if p.is_settled
        else f"تم صرف دفعة {amount} — المتبقّي {p.remaining:.2f}.",
        "success",
    )
    return redirect(url_for("hr.payroll_detail", payroll_id=p.id))


@bp.route("/payroll/<int:payroll_id>/delete", methods=["POST"])
@login_required
@require_permission("payroll", "delete")
def payroll_delete(payroll_id):
    """Delete a payroll row + its journal entry. Used when the payroll
    was posted by mistake; the employee/period unique constraint means
    without this we couldn't re-issue a corrected payroll for the same
    month."""
    p = Payroll.query.filter_by(id=payroll_id, school_id=_sid()).first_or_404()
    je_id = p.journal_entry_id
    employee_name = p.employee.full_name if p.employee else "—"
    db.session.delete(p)
    if je_id:
        je = JournalEntry.query.get(je_id)
        if je:
            db.session.delete(je)
    db.session.commit()
    flash(
        f"تم حذف راتب {employee_name} وإلغاء قيده المحاسبي.",
        "success",
    )
    return redirect(url_for("hr.payroll_list"))


def _parse_date(s):
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d").date()
