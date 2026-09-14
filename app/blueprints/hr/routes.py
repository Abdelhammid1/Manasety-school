from datetime import datetime, date
from decimal import Decimal

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import Account, Employee, Payroll, User
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


@bp.route("/employees/new", methods=["GET", "POST"])
@login_required
@require_permission("payroll", "edit")
def employee_new():
    users = User.query.filter_by(school_id=_sid()).order_by(User.full_name).all()
    if request.method == "POST":
        e = Employee(
            school_id=_sid(),
            full_name=request.form["full_name"].strip(),
            job_title=request.form["job_title"].strip(),
            base_salary=Decimal(request.form.get("base_salary") or "0"),
            national_id=(request.form.get("national_id") or "").strip() or None,
            phone=(request.form.get("phone") or "").strip() or None,
            email=(request.form.get("email") or "").strip() or None,
            hire_date=_parse_date(request.form.get("hire_date")),
            bank_account=(request.form.get("bank_account") or "").strip() or None,
            user_id=int(request.form["user_id"]) if request.form.get("user_id") else None,
        )
        db.session.add(e)
        db.session.commit()
        flash(f"تم إضافة الموظف {e.full_name}.", "success")
        return redirect(url_for("hr.employee_detail", employee_id=e.id))
    return render_template("hr/employee_form.html", employee=None, users=users)


@bp.route("/employees/<int:employee_id>")
@login_required
@require_permission("payroll", "view")
def employee_detail(employee_id):
    e = _get(Employee, employee_id)
    return render_template("hr/employee_detail.html", employee=e)


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

    if request.method == "POST":
        employee_id = int(request.form["employee_id"])
        e = _get(Employee, employee_id)
        period_year = int(request.form["period_year"])
        period_month = int(request.form["period_month"])
        base = Decimal(request.form.get("base_salary") or str(e.base_salary or 0))
        allowances = Decimal(request.form.get("allowances") or "0")
        deductions = Decimal(request.form.get("deductions") or "0")
        net = base + allowances - deductions

        dup = Payroll.query.filter_by(
            employee_id=e.id, period_year=period_year, period_month=period_month,
        ).first()
        if dup:
            flash("راتب هذا الشهر مسجَّل بالفعل لهذا الموظف.", "warning")
            return redirect(url_for("hr.payroll_list"))

        cash = _get(Account, int(request.form["cash_account_id"]))
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


def _parse_date(s):
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d").date()
