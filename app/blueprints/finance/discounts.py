"""Sprint 17 — Ticket #17. Discount types + student discount approvals."""
from decimal import Decimal
from datetime import datetime

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import DiscountType, StudentDiscount, FeeType, Enrollment, Student


def _sid():
    return current_user.school_id


@bp.route("/discounts", endpoint="discount_types")
@login_required
@require_permission("finance", "view")
def discount_types_list():
    items = (
        DiscountType.query.filter_by(school_id=_sid())
        .order_by(DiscountType.is_active.desc(), DiscountType.name).all()
    )
    fee_types = FeeType.query.filter_by(school_id=_sid()).order_by(FeeType.name).all()
    return render_template("finance/discount_types.html", items=items, fee_types=fee_types)


@bp.route("/discounts/new", methods=["POST"], endpoint="discount_type_new")
@login_required
@require_permission("finance", "edit")
def discount_type_new():
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("اسم الخصم مطلوب.", "danger")
        return redirect(url_for("finance.discount_types"))
    d = DiscountType(
        school_id=_sid(), name=name,
        calc_method=(request.form.get("calc_method") or "percentage").strip(),
        value=Decimal(request.form.get("value") or "0"),
        applies_to_fee_type_id=request.form.get("applies_to_fee_type_id", type=int) or None,
        auto_rule=(request.form.get("auto_rule") or "").strip() or None,
        requires_approval=bool(request.form.get("requires_approval")),
    )
    db.session.add(d); db.session.commit()
    flash(f"تم إضافة نوع الخصم ({d.name}).", "success")
    return redirect(url_for("finance.discount_types"))


@bp.route("/discounts/<int:dt_id>/toggle", methods=["POST"], endpoint="discount_type_toggle")
@login_required
@require_permission("finance", "edit")
def discount_type_toggle(dt_id):
    d = DiscountType.query.filter_by(id=dt_id, school_id=_sid()).first_or_404()
    d.is_active = not d.is_active
    db.session.commit()
    flash("تم تحديث حالة الخصم.", "success")
    return redirect(url_for("finance.discount_types"))


@bp.route("/student-discounts", endpoint="student_discounts")
@login_required
@require_permission("finance", "view")
def student_discounts_list():
    items = (
        StudentDiscount.query.filter_by(school_id=_sid())
        .order_by(StudentDiscount.created_at.desc()).limit(200).all()
    )
    dtypes = DiscountType.query.filter_by(school_id=_sid(), is_active=True).all()
    return render_template(
        "finance/student_discounts.html",
        items=items, discount_types=dtypes,
    )


@bp.route("/student-discounts/new", methods=["POST"], endpoint="student_discount_new")
@login_required
@require_permission("finance", "edit")
def student_discount_new():
    en_id = request.form.get("enrollment_id", type=int)
    dt_id = request.form.get("discount_type_id", type=int)
    if not en_id or not dt_id:
        flash("اختر الطالب ونوع الخصم.", "danger")
        return redirect(url_for("finance.student_discounts"))
    sd = StudentDiscount(
        school_id=_sid(),
        enrollment_id=en_id, discount_type_id=dt_id,
        override_value=Decimal(request.form.get("override_value") or "0") or None,
        reason=(request.form.get("reason") or "").strip() or None,
        status="pending",
    )
    db.session.add(sd); db.session.commit()
    flash("تم تقديم طلب الخصم — بانتظار الاعتماد.", "success")
    return redirect(url_for("finance.student_discounts"))


@bp.route("/student-discounts/<int:sd_id>/approve", methods=["POST"], endpoint="student_discount_approve")
@login_required
@require_permission("finance", "edit")
def student_discount_approve(sd_id):
    sd = StudentDiscount.query.filter_by(id=sd_id, school_id=_sid()).first_or_404()
    sd.status = "approved"
    sd.approved_by_user_id = getattr(current_user, "id", None)
    sd.approved_at = datetime.now()
    db.session.commit()
    flash("تم اعتماد الخصم.", "success")
    return redirect(url_for("finance.student_discounts"))


@bp.route("/student-discounts/<int:sd_id>/reject", methods=["POST"], endpoint="student_discount_reject")
@login_required
@require_permission("finance", "edit")
def student_discount_reject(sd_id):
    sd = StudentDiscount.query.filter_by(id=sd_id, school_id=_sid()).first_or_404()
    sd.status = "rejected"
    sd.approved_by_user_id = getattr(current_user, "id", None)
    sd.approved_at = datetime.now()
    db.session.commit()
    flash("تم رفض الخصم.", "warning")
    return redirect(url_for("finance.student_discounts"))
