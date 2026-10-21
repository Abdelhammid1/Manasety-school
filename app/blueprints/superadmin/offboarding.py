"""SAAS-035 — the offboarding path on the console (owner only):

  start (reason) → [suspend] → export (job, verified) → archive (032) →
  retention → request purge → second owner approves → `flask
  school-purge` on the server.

Every step except the purge itself is reversible (unarchive). There is
no web button that deletes data.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import click
from flask import abort, flash, redirect, render_template, request, send_file, url_for

from . import bp, current_platform_user, require_platform_role
from ...extensions import db
from ...models import PlatformJob, School, SchoolOffboarding
from ...services import platform_actions as pact
from ...services import platform_auth as pa
from ...services import school_export, school_purge

RETENTION_DAYS = 90       # proposed; Abdelhamid's decision (SAAS-035)
OWNER_LOSS_WINDOW = timedelta(days=30)


def approvals_required(now) -> int:
    """Two approvals unless the platform really has one owner. Counted so
    the requester can't lower it first (security review): inactive owner
    accounts count, and an owner demoted / deactivated in the last 30
    days forces two as well."""
    from ...models import PlatformAuditLog, PlatformUser
    if PlatformUser.query.filter_by(role="owner").count() > 1:
        return 2
    recent = PlatformAuditLog.query.filter(
        PlatformAuditLog.action.in_(("platform_user_role", "platform_user_role_cli",
                                     "platform_user_deactivate", "platform_user_deactivate_cli")),
        PlatformAuditLog.created_at >= now - OWNER_LOSS_WINDOW).all()
    for row in recent:
        meta = row.meta or {}
        if meta.get("old_role", meta.get("role")) == "owner":
            return 2
    return 1


def _aware(d):
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


def _school(school_id):
    return db.session.get(School, school_id) or abort(404)


def _row(school):
    return SchoolOffboarding.query.filter_by(school_id=school.id).first()


def _guard(school):
    """Owner, fresh TOTP, reason (no slug typing for the non-destructive steps)."""
    user = current_platform_user()
    reason = (request.form.get("reason") or "").strip()
    if not reason:
        raise pact.ActionRefused("السبب مطلوب.")
    if not pact.fresh_totp(user):
        raise pact.ActionRefused("أدخل رمز التحقق (TOTP) الحالي.")
    return user, reason


def _back(school):
    return redirect(url_for("superadmin.offboarding", school_id=school.id))


@bp.route("/schools/<int:school_id>/offboarding", methods=["GET"], endpoint="offboarding")
@require_platform_role("owner")
def offboarding(school_id):
    school = _school(school_id)
    row = _row(school)
    jobs = (PlatformJob.query.filter_by(kind="school_export", school_id=school.id)
            .order_by(PlatformJob.id.desc()).limit(10).all())
    return render_template("superadmin/offboarding.html", school=school, row=row, jobs=jobs,
                           now=datetime.now(timezone.utc), retention_days=RETENTION_DAYS)


@bp.route("/schools/<int:school_id>/offboarding/<step>", methods=["POST"], endpoint="offboarding_step")
@require_platform_role("owner")
def offboarding_step(school_id, step):
    school = _school(school_id)
    row = (SchoolOffboarding.query.filter_by(school_id=school.id).with_for_update().first())
    try:
        user, reason = _guard(school)
        if step == "start":
            if row is not None and row.purged_at is None:
                raise pact.ActionRefused("مسار المغادرة بدأ بالفعل.")
            row = SchoolOffboarding(school_id=school.id, requested_by=user.id, reason=reason,
                                    requested_at=datetime.now(timezone.utc))
            db.session.add(row)
        elif row is None:
            raise pact.ActionRefused("ابدأ مسار المغادرة الأول.")
        elif step == "export":
            db.session.add(PlatformJob(kind="school_export", status="pending", school_id=school.id,
                                       reason=reason[:255], requested_by_platform_user_id=user.id))
        elif step == "retention":
            if school.status != "archived":
                raise pact.ActionRefused("أرشف المدرسة الأول (من صفحة المدرسة).")
            row.archived_at = row.archived_at or datetime.now(timezone.utc)
            row.retention_until = row.archived_at + timedelta(days=RETENTION_DAYS)
        elif step == "request_purge":
            if row.export_verified_at is None:
                raise pact.ActionRefused("لازم تصدير متحقَّق منه قبل طلب الحذف.")
            if school.status != "archived" or row.retention_until is None:
                raise pact.ActionRefused("المدرسة لازم تكون مؤرشفة وفترة الاحتفاظ محددة.")
            if (request.form.get("confirm_slug") or "").strip() != school.slug:
                raise pact.ActionRefused("اكتب الاسم المختصر للتأكيد.")
            now = datetime.now(timezone.utc)
            row.purge_requested_by, row.purge_requested_at = user.id, now
            row.purge_approved_by = row.purge_approved_at = None
            # fixed now: later owner changes can't lower it
            row.approvals_required = approvals_required(now)
        elif step == "approve_purge":
            if row.purge_requested_by is None:
                raise pact.ActionRefused("مفيش طلب حذف.")
            if row.purge_requested_by == user.id:
                raise pact.ActionRefused("الموافقة لازم تكون من owner تاني.")
            # an account made after the request can't be the second owner
            if _aware(user.created_at) >= _aware(row.purge_requested_at):
                raise pact.ActionRefused("الموافقة لازم تكون من owner كان موجود قبل طلب الحذف.")
            row.purge_approved_by, row.purge_approved_at = user.id, datetime.now(timezone.utc)
        elif step == "cancel":
            if row.purged_at is not None:
                raise pact.ActionRefused("الحذف تم بالفعل ولا يمكن التراجع عنه.")
            db.session.delete(row)
        else:
            abort(404)
        pa.audit(f"offboarding_{step}", user, school_id=school.id, reason=reason)
    except pact.StepUpLocked:
        from . import end_platform_session
        end_platform_session(revoke_user=current_platform_user())
        db.session.commit()
        return redirect(url_for("superadmin.login"))
    except pact.ActionRefused as e:
        db.session.rollback()
        flash(str(e), "danger")
        return _back(school)
    db.session.commit()
    flash("تم.", "success")
    return _back(school)


@bp.route("/exports/<int:job_id>/download", methods=["POST"], endpoint="export_download")
@require_platform_role("owner")
def export_download(job_id):
    """Owner + fresh TOTP + reason, every time; the file is streamed in
    the response — no reusable link, nothing in a URL or a log."""
    job = db.session.get(PlatformJob, job_id) or abort(404)
    if job.kind != "school_export" or job.status != "succeeded" or not (job.result or {}).get("file"):
        abort(404)
    school = _school(job.school_id)
    try:
        _guard(school)
    except pact.StepUpLocked:
        from . import end_platform_session
        end_platform_session(revoke_user=current_platform_user())
        db.session.commit()
        return redirect(url_for("superadmin.login"))
    except pact.ActionRefused as e:
        flash(str(e), "danger")
        return _back(school)
    path = school_export.exports_dir() / job.result["file"]
    if not path.is_file():
        flash("الملف اتمسح (بعد 7 أيام). اطلب تصدير جديد.", "danger")
        return _back(school)
    pa.audit("export_downloaded", current_platform_user(), school_id=school.id, job_id=job.id)
    db.session.commit()
    return send_file(path, as_attachment=True, download_name=path.name, mimetype="application/zip")


# ─── server-side commands ───────────────────────────────────────────

@bp.cli.command("school-export")
@click.argument("slug", required=False)
@click.option("--verify", "verify_file", default=None, help="Re-count against this zip's manifest.")
@click.option("--from-queue", is_flag=True)
def school_export_command(slug, verify_file, from_queue):
    """SAAS-035 — export a school (zip under UPLOAD_ROOT/_platform/exports)."""
    if from_queue:
        click.echo(f"processed {school_export.run_export_queue()} export job(s)")
        return
    if verify_file:
        problems = school_export.verify(verify_file)
        for p in problems:
            click.echo(f"MISMATCH {p}")
        if problems:
            raise SystemExit(1)
        import json
        import zipfile
        with zipfile.ZipFile(verify_file) as z:
            sid = json.loads(z.read("manifest.json"))["school_id"]
        from pathlib import Path as _P
        school_export.mark_verified(sid, None, _P(verify_file).name)
        db.session.commit()
        click.echo("verified")
        return
    school = School.query.filter_by(slug=slug).first()
    if school is None:
        raise click.ClickException("unknown school")
    res = school_export.export_school(school.id)
    click.echo(f"{res['path']}  ({len(res['manifest']['tables'])} tables)")


@bp.cli.command("school-purge")
@click.argument("slug")
@click.option("--confirm", "confirm_slug", required=True, help="Type the slug again.")
@click.option("--backup-file", required=True, help="A dump made in the last hour.")
@click.option("--execute", is_flag=True, help="Actually delete (default: dry run).")
def school_purge_command(slug, confirm_slug, backup_file, execute):
    """SAAS-035 — permanently delete an offboarded school's data."""
    school = School.query.filter_by(slug=slug).first()
    if school is None:
        raise click.ClickException("unknown school")
    try:
        rep = school_purge.purge(school, confirm_slug=confirm_slug, backup_file=backup_file, execute=execute)
    except school_purge.PurgeRefused as e:
        raise click.ClickException(str(e)) from None
    for table, n in rep["plan"]:
        if n:
            click.echo(f"{table:40} {n}")
    for p in rep["problems"]:
        click.echo(f"REFUSED: {p}")
    if rep["problems"]:
        raise SystemExit(1)
    click.echo("purged" if rep["executed"] else "dry run — nothing deleted (add --execute)")
