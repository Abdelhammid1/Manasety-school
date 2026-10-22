"""SAAS-047 — «النسخ الاحتياطي» for the school owner (role "admin").

Every row is loaded school-scoped (owned_or_404: another school's backup
and a missing one get the same 404). The package itself is built by the
server CLI from the queue; the download is encrypted with a passphrase
the admin chooses and needs the admin's account password.
"""
from flask import abort, flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from . import bp
from ..utils import admin_only
from ...models import SchoolBackup
from ...services import school_backups as svc
from ...services.scoping import owned_or_404
from ...services.tenancy import current_school_id


def _row(b) -> dict:
    return {"id": b.id, "status": b.status, "progress": b.progress or 0,
            "size_bytes": b.size_bytes, "error": b.error,
            "created_at": b.created_at.isoformat() if b.created_at else None}


@bp.route("/backups", endpoint="backups_home")
@login_required
@admin_only
def backups_home():
    sid = current_school_id()
    rows = (SchoolBackup.query.filter_by(school_id=sid)
            .order_by(SchoolBackup.created_at.desc(), SchoolBackup.id.desc()).all())
    return render_template("admin/backups.html", backups=rows, policy=svc.policy(sid),
                           daily_limit=svc.DAILY_LIMIT, min_passphrase=svc.engine.MIN_PASSPHRASE)


@bp.route("/backups/new", methods=["POST"], endpoint="backup_new")
@login_required
@admin_only
def backup_new():
    try:
        svc.request_backup(current_school_id(), current_user)
        flash("تم طلب النسخة الاحتياطية — هتظهر في القائمة أول ما تجهز.", "success")
    except svc.BackupRefused as e:
        flash(str(e), "danger")
    return redirect(url_for("admin.backups_home"))


@bp.route("/backups/<int:bid>/status.json", endpoint="backup_status")
@login_required
@admin_only
def backup_status(bid):
    return jsonify(_row(owned_or_404(SchoolBackup, bid)))


@bp.route("/backups/<int:bid>/delete", methods=["POST"], endpoint="backup_delete")
@login_required
@admin_only
def backup_delete(bid):
    b = owned_or_404(SchoolBackup, bid)
    try:
        svc.delete_backup(b, current_user)
        flash("تم حذف النسخة.", "success")
    except svc.BackupRefused as e:
        flash(str(e), "danger")
    return redirect(url_for("admin.backups_home"))


@bp.route("/backups/<int:bid>/download", methods=["POST"], endpoint="backup_download_prepare")
@login_required
@admin_only
def backup_download_prepare(bid):
    b = owned_or_404(SchoolBackup, bid)
    passphrase = request.form.get("passphrase") or ""
    if passphrase != (request.form.get("passphrase_confirm") or ""):
        flash("تأكيد كلمة مرور التشفير غير مطابق.", "danger")
        return redirect(url_for("admin.backups_home"))
    try:
        token = svc.prepare_download(b, current_user, request.form.get("account_password") or "", passphrase)
    except svc.BackupRefused as e:
        flash(str(e), "danger")
        return redirect(url_for("admin.backups_home"))
    return render_template("admin/backup_download.html", backup=b,
                           url=url_for("admin.backup_download", token=token), ttl=svc.DOWNLOAD_TTL // 60)


@bp.route("/backups/download/<token>", endpoint="backup_download")
@login_required
@admin_only
def backup_download(token):
    found = svc.open_download(token, current_user, current_school_id())
    if found is None:
        abort(404)
    path, name, _backup = found
    resp = send_file(path, as_attachment=True, download_name=name, mimetype="application/octet-stream",
                     max_age=0)
    resp.headers["Cache-Control"] = "no-store"
    resp.call_on_close(lambda: svc.remove_after_send(path))     # single use
    return resp
