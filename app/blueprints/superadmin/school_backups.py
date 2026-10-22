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
    from ...models import SchoolBackup
    rows = (SchoolBackup.query.filter_by(school_id=school_id)
            .order_by(SchoolBackup.created_at.desc()).limit(30).all())
    return {"school_backups": rows, "backup_policy": svc.policy(school_id)}


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
