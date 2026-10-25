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
        from ...services.ai_quota import parse_cap
        try:
            values["max_ai_tokens_month"] = parse_cap(request.form.get("max_ai_tokens_month"))
        except ValueError as e:
            raise SubscriptionError(str(e)) from None
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


# ─── modules + pages in one save (features ticket B) ─────────────────
# The form sends every toggleable module's state (plan / on / off), the
# page keys it showed as editable (`known`) and a checkbox per page. A
# page becomes an exception only when it differs from its default;
# going back to the default removes the exception. One reason, one
# transaction, one event and one audit line.

FEATURES_FORM_KEY = "school_features_form"


@bp.route("/schools/<int:school_id>/features", methods=["POST"], endpoint="school_features_set")
@require_platform_role("owner")
def school_features_set(school_id):
    from flask import session
    from ...services.modules import (FEATURES_BY_KEY, ESSENTIAL_FEATURES, TOGGLEABLE,
                                     set_school_access)
    school = db.session.get(School, school_id) or abort(404)
    back = redirect(url_for("superadmin.school_detail", school_id=school.id) + "#modules")
    form = request.form
    try:
        posted = {k[len("module_"):] for k in form if k.startswith("module_")}
        if posted - set(TOGGLEABLE):
            raise SubscriptionError("موديولات أساسية أو غير معروفة: " + ", ".join(sorted(posted - set(TOGGLEABLE))))
        modules = {}
        for key in TOGGLEABLE:
            raw = form.get(f"module_{key}")
            if raw is None:
                continue
            if raw not in ("plan", "on", "off"):
                raise SubscriptionError("حالة موديول غير صحيحة.")
            modules[key] = {"plan": None, "on": True, "off": False}[raw]
        known = [k.strip() for k in form.getlist("known") if k.strip()]
        bad = sorted({k for k in known if k not in FEATURES_BY_KEY or k in ESSENTIAL_FEATURES})
        if bad:
            raise SubscriptionError(f"صفحات غير معروفة أو أساسية: {', '.join(bad)}")
        from ...models import SchoolFeatureOverride
        stored = {o.feature_key: o.enabled for o in SchoolFeatureOverride.query.filter_by(school_id=school.id)}
        features = {}
        for key in known:
            want = form.get(f"feature_{key}") == "1"
            now = stored.get(key, FEATURES_BY_KEY[key].default_on)
            if want != now:
                features[key] = None if want == FEATURES_BY_KEY[key].default_on else want
        diff = set_school_access(school, modules, features, form.get("reason") or "",
                                 current_platform_user())
    except SubscriptionError as e:
        db.session.rollback()
        # keep what the owner chose on the page
        session[FEATURES_FORM_KEY] = {"school_id": school.id, "form": form.to_dict(flat=False)}
        flash(f"لم يُحفظ أي تغيير: {e}", "danger")
        return back
    db.session.commit()
    session.pop(FEATURES_FORM_KEY, None)
    m, f = len(diff["modules"]), len(diff["features"])
    flash(f"تم تعديل {m} وحدة و{f} صفحة." if (m or f) else "لا توجد تغييرات.", "success")
    return back
