"""SAAS-047 — a school's backups on the console's school page: the list
(dates, sizes, status — never the content) and the policy (feature on /
off, how many to keep). owner edits; everyone else reads."""
from __future__ import annotations

from flask import abort, flash, redirect, request, url_for

from . import bp, current_platform_user, require_platform_role
from ...extensions import db
from ...models import School
from ...services import school_backups as svc


def backups_view(school_id: int) -> dict:
    from ...models import SchoolBackup, SchoolRestore
    from ...services import school_restore as sr
    rows = (SchoolBackup.query.filter_by(school_id=school_id)
            .order_by(SchoolBackup.created_at.desc()).limit(30).all())
    restores = (SchoolRestore.query.filter_by(school_id=school_id)
                .order_by(SchoolRestore.created_at.desc()).limit(10).all())
    return {"school_backups": rows, "backup_policy": svc.policy(school_id), "school_restores": restores,
            "restore_modules": sr.MODULES}


@bp.route("/schools/<int:school_id>/backup-policy", methods=["POST"], endpoint="school_backup_policy")
@require_platform_role("owner")
def school_backup_policy(school_id):
    school = db.session.get(School, school_id) or abort(404)
    try:
        keep = int(request.form.get("keep") or 0)
        svc.set_policy(school.id, enabled=request.form.get("enabled") == "1", keep=keep,
                       platform_user=current_platform_user())
        flash("تم تحديث سياسة النسخ الاحتياطي.", "success")
    except (ValueError, svc.BackupRefused) as e:
        db.session.rollback()
        flash(str(e) if isinstance(e, svc.BackupRefused) else "عدد غير صالح.", "danger")
    return redirect(url_for("superadmin.school_detail", school_id=school.id) + "#backups")


# ─── SAAS-048 — restore on behalf of the school (owner, reason required) ─

def _reason() -> str:
    reason = (request.form.get("reason") or "").strip()
    if len(reason) < 5:
        raise svc.BackupRefused("اكتب سبب الاسترجاع (5 أحرف على الأقل).")
    return reason[:255]


@bp.route("/schools/<int:school_id>/restore", methods=["POST"], endpoint="school_restore_new")
@require_platform_role("owner")
def school_restore_new(school_id):
    from ...models import SchoolBackup
    from ...services import platform_auth as pa
    from ...services import school_restore as sr
    school = db.session.get(School, school_id) or abort(404)
    user = current_platform_user()
    try:
        reason = _reason()
        b = SchoolBackup.query.filter_by(id=request.form.get("backup_id", type=int),
                                         school_id=school.id).first()
        if b is None:
            abort(404)
        r = sr.create_from_backup(school.id, b, platform_user=user, reason=reason)
        pa.audit("school_restore_requested", user, school_id=school.id, restore_id=r.id, reason=reason)
        db.session.commit()
        flash("جاري تجهيز المعاينة.", "success")
    except (svc.BackupRefused, sr.RestoreError) as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("superadmin.school_detail", school_id=school.id) + "#backups")


@bp.route("/schools/<int:school_id>/restore/<int:rid>/confirm", methods=["POST"],
          endpoint="school_restore_confirm")
@require_platform_role("owner")
def school_restore_confirm(school_id, rid):
    from ...models import SchoolRestore
    from ...services import platform_auth as pa
    from ...services import school_restore as sr
    school = db.session.get(School, school_id) or abort(404)
    r = SchoolRestore.query.filter_by(id=rid, school_id=school.id).first() or abort(404)
    user = current_platform_user()
    try:
        reason = _reason()
        r.reason = reason
        sr.confirm(r, modules=request.form.getlist("modules"), mode=request.form.get("mode") or "",
                   typed_name=request.form.get("school_name") or "", platform_user=user)
        pa.audit("school_restore_confirmed", user, school_id=school.id, restore_id=r.id, reason=reason,
                 modules=r.modules, mode=r.mode)
        db.session.commit()
        flash("تم التأكيد — الاسترجاع هيبدأ خلال دقيقة.", "success")
    except (svc.BackupRefused, sr.RestoreError) as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("superadmin.school_detail", school_id=school.id) + "#backups")
