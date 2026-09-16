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
    e = _get(Employee, employee_id)
    return render_template("hr/employee_detail.html", employee=e)


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
    salary_account = Account.query.filter_by(school_id=_sid(), code="5100").first()
    cash_accounts = Account.query.filter_by(school_id=_sid(), type="asset").order_by(Account.code).all()

    # Every FK on Payroll is NOT NULL. Empty dropdowns would 500 on POST.
    if not employees:
        flash("لا يوجد موظفون نشطون — أضف موظفاً قبل صرف الراتب.", "warning")
        return redirect(url_for("hr.employees_list"))
    if not salary_account:
        flash("حساب مصروف الرواتب (5100) غير موجود في دليل الحسابات.", "danger")
        return redirect(url_for("finance.accounts"))
    if not cash_accounts:
        flash("لا يوجد حساب نقدي (Asset) لصرف الراتب منه.", "danger")
        return redirect(url_for("finance.accounts"))

    if request.method == "POST":
        employee_id = request.form.get("employee_id", type=int)
        cash_id     = request.form.get("cash_account_id", type=int)
        if employee_id not in [x.id for x in employees] or cash_id not in [c.id for c in cash_accounts]:
            flash("اختر موظفاً وحساباً نقدياً صحيحين.", "danger")
            return render_template(
                "hr/payroll_form.html", employees=employees, cash_accounts=cash_accounts,
            )
        e = _get(Employee, employee_id)
        period_year = int(request.form["period_year"])
        period_month = int(request.form["period_month"])
        base = Decimal(request.form.get("base_salary") or str(e.base_salary or 0))
        allowances = Decimal(request.form.get("allowances") or "0")
        # Ticket #9 — auto-compute deductions from StaffAttendance
        # (unpaid absences) unless the user overrode the field manually.
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
            flash("راتب هذا الشهر مسجَّل بالفعل لهذا الموظف.", "warning")
            return redirect(url_for("hr.payroll_list"))

        cash = _get(Account, cash_id)
        pay_date = _parse_date(request.form.get("paid_at")) or date.today()
        je = post_journal(
            school_id=_sid(),
            entry_date=pay_date,
            description=f"راتب {e.full_name} — {period_year}/{period_month:02d}",
            reference=f"PR-{period_year}{period_month:02d}-{e.id}",
            lines=[
                (salary_account.id, net, Decimal(0), "مصروف رواتب"),
                (cash.id, Decimal(0), net, "صرف راتب"),
            ],
            related_kind="payroll", related_id=None,
        )

        p = Payroll(
            school_id=_sid(),
            employee_id=e.id,
            period_year=period_year, period_month=period_month,
            base_salary=base, allowances=allowances, deductions=deductions,
            net_pay=net, paid_at=pay_date, journal_entry_id=je.id,
        )
        db.session.add(p)
        db.session.commit()
        flash(f"تم صرف راتب {e.full_name} بمبلغ صافي {net} وقيده محاسبيًا.", "success")
        return redirect(url_for("hr.payroll_list"))

    return render_template(
        "hr/payroll_form.html",
        employees=employees, cash_accounts=cash_accounts,
        today=date.today(),
    )


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
