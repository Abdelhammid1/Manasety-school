"""SAAS-030 — modules & limits on the console's school page.
owner: everything · finance: limits only · support: read only."""
from __future__ import annotations

from flask import abort, flash, redirect, request, url_for

from . import bp, current_platform_user, require_platform_role
from ...extensions import db
from ...models import School, SchoolLimitOverride
from ...services import platform_auth as pa
from ...services.subscriptions import SubscriptionError, _event


@bp.route("/schools/<int:school_id>/modules", methods=["POST"], endpoint="school_module_set")
@require_platform_role("owner")
def school_module_set(school_id):
    from ...services.modules import set_override
    school = db.session.get(School, school_id) or abort(404)
    state = request.form.get("state") or ""
    enabled = {"on": True, "off": False, "plan": None}.get(state, "bad")
    if enabled == "bad":
        abort(400)
    try:
        set_override(school, request.form.get("module") or "", enabled,
                     request.form.get("reason") or "", current_platform_user())
    except SubscriptionError as e:
        db.session.rollback()
        flash(str(e), "danger")
    else:
        db.session.commit()
        flash("تم تحديث الموديول.", "success")
    return redirect(url_for("superadmin.school_detail", school_id=school.id) + "#modules")


def _opt_limit(name):
    raw = (request.form.get(name) or "").strip()
    if not raw:
        return None
    if not raw.isdigit():
        raise SubscriptionError("الحد يجب أن يكون رقمًا صحيحًا موجبًا أو فاضي (حد الباقة).")
    return int(raw)


@bp.route("/schools/<int:school_id>/limits", methods=["POST"], endpoint="school_limits_set")
@require_platform_role("owner", "finance")
def school_limits_set(school_id):
    school = db.session.get(School, school_id) or abort(404)
    user = current_platform_user()
    reason = (request.form.get("reason") or "").strip()
    try:
        if not reason:
            raise SubscriptionError("السبب مطلوب.")
        values = {c: _opt_limit(c) for c in ("max_students", "max_users", "max_storage_mb")}
    except SubscriptionError as e:
        flash(str(e), "danger")
        return redirect(url_for("superadmin.school_detail", school_id=school.id) + "#limits")
    row = db.session.get(SchoolLimitOverride, school.id)
    before = None if row is None else {c: getattr(row, c) for c in values}
    if all(v is None for v in values.values()):
        if row is not None:
            db.session.delete(row)
    else:
        if row is None:
            row = SchoolLimitOverride(school_id=school.id)
            db.session.add(row)
        for c, v in values.items():
            setattr(row, c, v)
        row.reason = reason
        row.updated_by_platform_user_id = user.id
    _event(school.id, "limits_override", str(before), str(values), reason, user)
    pa.audit("limits_override", user, school_id=school.id, before=before, after=values)
    db.session.commit()
    flash("تم تحديث الحدود.", "success")
    return redirect(url_for("superadmin.school_detail", school_id=school.id) + "#limits")
