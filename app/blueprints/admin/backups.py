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
from ...services import school_restore as restore
from ...extensions import db
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


# ─── SAAS-048 — restore ─────────────────────────────────────────────

@bp.route("/backups/restore", endpoint="restore_home")
@login_required
@admin_only
def restore_home():
    from ...models import SchoolRestore
    sid = current_school_id()
    restores = (SchoolRestore.query.filter_by(school_id=sid)
                .order_by(SchoolRestore.created_at.desc(), SchoolRestore.id.desc()).limit(20).all())
    backups = (SchoolBackup.query.filter_by(school_id=sid, status="succeeded")
               .order_by(SchoolBackup.created_at.desc()).all())
    return render_template("admin/restore_home.html", restores=restores, backups=backups,
                           max_mb=restore.engine.max_bytes() // (1024 * 1024))


@bp.route("/backups/restore/new", methods=["POST"], endpoint="restore_new")
@login_required
@admin_only
def restore_new():
    sid = current_school_id()
    try:
        upload = request.files.get("package")
        if upload and upload.filename:
            r = restore.create_from_upload(sid, upload, request.form.get("passphrase") or "", user=current_user)
        else:
            b = owned_or_404(SchoolBackup, request.form.get("backup_id", type=int))
            r = restore.create_from_backup(sid, b, user=current_user)
    except restore.RestoreError as e:
        flash(str(e), "danger")
        return redirect(url_for("admin.restore_home"))
    flash("جاري تجهيز المعاينة — الصفحة هتتحدث لوحدها.", "info")
    return redirect(url_for("admin.restore_detail", rid=r.id))


@bp.route("/backups/restore/<int:rid>", endpoint="restore_detail")
@login_required
@admin_only
def restore_detail(rid):
    from ...models import School, SchoolRestore
    r = owned_or_404(SchoolRestore, rid)
    school = db.session.get(School, r.school_id)
    deps = {k: sorted(v) for k, v in restore.hard_dependencies().items()}
    return render_template("admin/restore_detail.html", r=r, school=school, modules=restore.MODULES,
                           deps=deps, labels={m.key: m.label for m in restore.MODULES})


@bp.route("/backups/restore/<int:rid>/status.json", endpoint="restore_status")
@login_required
@admin_only
def restore_status(rid):
    from ...models import SchoolRestore
    r = owned_or_404(SchoolRestore, rid)
    return jsonify({"id": r.id, "status": r.status, "error": r.error})


@bp.route("/backups/restore/<int:rid>/confirm", methods=["POST"], endpoint="restore_confirm")
@login_required
@admin_only
def restore_confirm(rid):
    from ...models import SchoolRestore
    r = owned_or_404(SchoolRestore, rid)
    try:
        restore.confirm(r, modules=request.form.getlist("modules"), mode=request.form.get("mode") or "",
                        typed_name=request.form.get("school_name") or "", user=current_user,
                        password=request.form.get("account_password") or "")
        flash("تم التأكيد — الاسترجاع هيبدأ خلال دقيقة. المدرسة هتكون في صيانة قصيرة.", "success")
    except restore.RestoreError as e:
        flash(str(e), "danger")
    return redirect(url_for("admin.restore_detail", rid=r.id))


@bp.route("/backups/restore/<int:rid>/undo", methods=["POST"], endpoint="restore_undo")
@login_required
@admin_only
def restore_undo(rid):
    from ...models import SchoolRestore
    r = owned_or_404(SchoolRestore, rid)
    try:
        undo = restore.request_undo(r, user=current_user, password=request.form.get("account_password") or "")
    except restore.RestoreError as e:
        flash(str(e), "danger")
        return redirect(url_for("admin.restore_detail", rid=r.id))
    flash("تم طلب التراجع — هيرجّع الحالة اللي كانت قبل الاسترجاع.", "success")
    return redirect(url_for("admin.restore_detail", rid=undo.id))


# ─── SAAS-049 — browse an old backup, export without restoring ──────

@bp.route("/backups/browse", methods=["GET", "POST"], endpoint="browse_home")
@login_required
@admin_only
def browse_home():
    from ...services import backup_extract as bx
    sid = current_school_id()
    if request.method == "POST":
        try:
            upload = request.files.get("package")
            if upload and upload.filename:
                token = bx.open_session(sid, current_user, upload=upload,
                                        passphrase=request.form.get("passphrase") or "")
            else:
                b = owned_or_404(SchoolBackup, request.form.get("backup_id", type=int))
                token = bx.open_session(sid, current_user, backup=b)
        except restore.RestoreError as e:
            flash(str(e), "danger")
            return redirect(url_for("admin.browse_home"))
        return redirect(url_for("admin.browse_view", token=token))
    backups = (SchoolBackup.query.filter_by(school_id=sid, status="succeeded")
               .order_by(SchoolBackup.created_at.desc()).all())
    return render_template("admin/browse_home.html", backups=backups)


def _browse_path(token):
    from ...services import backup_extract as bx
    path = bx.resolve(token, current_school_id(), current_user)
    if path is None:
        abort(404)
    return path


@bp.route("/backups/browse/<token>", endpoint="browse_view")
@login_required
@admin_only
def browse_view(token):
    from ...services import backup_extract as bx
    path = _browse_path(token)
    q = (request.args.get("q") or "").strip()
    return render_template("admin/browse_view.html", token=token, info=bx.overview(path), q=q,
                           students=bx.find_students(path, q) if q else [])


@bp.route("/backups/browse/<token>/t/<table>", endpoint="browse_table")
@login_required
@admin_only
def browse_table(token, table):
    from ...services import backup_extract as bx
    path = _browse_path(token)
    student = request.args.get("student", type=int)
    try:
        cols, data = bx.rows(path, table, student, limit=bx.PREVIEW_ROWS)
    except restore.RestoreError:
        abort(404)
    return render_template("admin/browse_table.html", token=token, table=table,
                           label=bx.TABLE_LABELS.get(table, table), cols=cols, data=data,
                           student=student, preview_rows=bx.PREVIEW_ROWS)


@bp.route("/backups/browse/<token>/t/<table>/export", methods=["POST"], endpoint="browse_export")
@login_required
@admin_only
def browse_export(token, table):
    from flask import Response
    from ...services import backup_extract as bx
    path = _browse_path(token)
    student = request.form.get("student", type=int)
    fmt = "xlsx" if request.form.get("format") == "xlsx" else "csv"
    try:
        bx.check_export_password(current_user, request.form.get("account_password") or "", current_school_id())
        cols, data = bx.rows(path, table, student)
    except restore.RestoreError as e:
        flash(str(e), "danger")
        return redirect(url_for("admin.browse_table", token=token, table=table, student=student))
    body, ext, mime = bx.export_bytes(cols, data, fmt)
    bx._audit("backup_extract", current_school_id(), current_user, table=table, student=student,
              rows=len(data), format=ext)
    db.session.commit()
    name = f"{table}{'-student-' + str(student) if student else ''}.{ext}"
    return Response(body, mimetype=mime, headers={
        "Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})
