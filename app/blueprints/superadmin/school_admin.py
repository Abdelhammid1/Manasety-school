"""SAAS-032 — full control of a school from its console page.

- edit non-secret school data (owner); before/after in platform audit
- lifecycle: suspend / resume / archive / unarchive / end all sessions
  (dangerous-action pattern, services/platform_actions.py)
- slug change (dangerous; old slug redirects 90 days, reserved forever)
- staff-user tools: unlock, new set-password link, deactivate / activate
  (owner + support; never shows or sets a password)
- platform-only notes, contacts (billing contact), tags
- platform announcements (owner)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import abort, flash, make_response, redirect, render_template, request, url_for

from . import bp, current_platform_user, require_platform_role
from ...extensions import db
from ...models import (PlatformAnnouncement, PlatformSchoolNote, School, SchoolContact, SchoolTag,
                       User)
from ...services import platform_actions as pact
from ...services import platform_auth as pa
from ...services import subscriptions as subs

# Non-secret fields the console may edit. SMTP and every other secret
# stay with the school itself.
EDITABLE = {
    "name": ("الاسم", str), "legal_name_en": ("الاسم بالإنجليزية", str), "phone": ("الهاتف", str),
    "email": ("الإيميل", str), "address": ("العنوان", str), "website": ("الموقع", str),
    "tax_number": ("الرقم الضريبي", str), "license_number": ("رقم الترخيص", str),
    "currency": ("العملة", str), "currency_symbol": ("رمز العملة", str),
    "fiscal_year_start_month": ("بداية السنة المالية", int), "invoice_prefix": ("بادئة الفواتير", str),
    # the financial fields a school can't change after its first financial
    # activity (services/finance_settings) — the console still can, audited
    "invoice_start_number": ("رقم الفاتورة الأولى", int), "rounding_policy": ("سياسة التقريب", str),
    "default_tax_rate": ("الضريبة الافتراضية", float), "attendance_mode": ("نمط الحضور", str),
    "notify_channels": ("قنوات الإشعار", str), "blocked_message": ("رسالة للمدرسة عند الحجب", str),
    "notify_on_support_access": ("إشعار المدرسة بدخول الدعم", bool),
}
# NOT NULL columns: blank is an error, not "clear it".
REQUIRED = {"name", "currency", "currency_symbol", "invoice_prefix", "fiscal_year_start_month",
            "default_tax_rate", "attendance_mode", "notify_channels", "invoice_start_number",
            "rounding_policy"}
MAX_LEN = {"currency": 8, "currency_symbol": 8, "invoice_prefix": 16}
SLUG_REDIRECT_DAYS = 90


def _school(school_id):
    return db.session.get(School, school_id) or abort(404)


def _back(school, anchor=""):
    return redirect(url_for("superadmin.school_detail", school_id=school.id) + anchor)


def _plain(v):
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    return str(v)


# ─── edit ────────────────────────────────────────────────────────────

# audit: what the school sees, or what silences its support-access notice
SENSITIVE = frozenset({"email", "blocked_message", "notify_on_support_access"})


@bp.route("/schools/<int:school_id>/edit", methods=["GET", "POST"], endpoint="school_edit")
@require_platform_role("owner")
def school_edit(school_id):
    school = _school(school_id)
    if request.method == "POST":
        before, after, errors = {}, {}, []
        full_form = request.form.get("_full_form") == "1"
        for field, (label, kind) in EDITABLE.items():
            if kind is bool:
                if not full_form:
                    continue          # an unchecked box only counts on the real form
                new = bool(request.form.get(field))
            elif field not in request.form:
                continue              # not sent → unchanged
            else:
                raw = (request.form.get(field) or "").strip()
                if not raw:
                    if field in REQUIRED:
                        errors.append(f"{label} مطلوب.")
                        continue
                    new = None
                else:
                    try:
                        new = kind(raw)
                    except ValueError:
                        errors.append(f"{label}: قيمة غير صحيحة.")
                        continue
            if field == "fiscal_year_start_month" and new is not None and not 1 <= new <= 12:
                errors.append("شهر بداية السنة المالية من 1 إلى 12.")
                continue
            if field == "default_tax_rate" and new is not None and not 0 <= new <= 100:
                errors.append("الضريبة من 0 إلى 100.")
                continue
            if field == "attendance_mode" and new not in ("daily", "per_period"):
                errors.append("نمط الحضور غير صحيح.")
                continue
            if field == "rounding_policy" and new not in ("normal", "up", "down"):
                errors.append("سياسة التقريب غير صحيحة.")
                continue
            if field == "invoice_start_number" and new is not None and new < 1:
                errors.append("رقم الفاتورة الأولى لازم 1 أو أكثر.")
                continue
            if field in MAX_LEN and isinstance(new, str) and len(new) > MAX_LEN[field]:
                errors.append(f"{label}: حتى {MAX_LEN[field]} حروف.")
                continue
            old = getattr(school, field)
            if field == "default_tax_rate" and old is not None:
                old = float(old)
            if old != new:
                before[field], after[field] = _plain(old), _plain(new)
        if not errors and SENSITIVE & set(after):
            try:
                if not pact.fresh_totp(current_platform_user()):
                    errors.append("تغيير الإيميل أو رسالة الحجب أو إشعار دخول الدعم يحتاج رمز TOTP.")
            except pact.StepUpLocked:
                from . import end_platform_session
                end_platform_session(revoke_user=current_platform_user())
                db.session.commit()
                return redirect(url_for("superadmin.login"))
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("superadmin/school_edit.html", school=school, fields=EDITABLE), 400
        for field, new in after.items():
            setattr(school, field, new)
        if after:
            pa.audit("school_edited", current_platform_user(), school_id=school.id, before=before, after=after)
        db.session.commit()
        flash("تم حفظ بيانات المدرسة." if after else "لا توجد تغييرات.", "success")
        return _back(school)
    return render_template("superadmin/school_edit.html", school=school, fields=EDITABLE)


# ─── lifecycle (dangerous) ───────────────────────────────────────────

def _dangerous(school):
    user = current_platform_user()
    try:
        reason = pact.check(user, school, reason=request.form.get("reason"),
                            confirm_slug=request.form.get("confirm_slug"))
    except pact.StepUpLocked:
        from . import end_platform_session
        end_platform_session(revoke_user=user)
        db.session.commit()
        raise
    return user, reason


@bp.route("/schools/<int:school_id>/lifecycle/<action>", methods=["POST"], endpoint="school_lifecycle")
@require_platform_role("owner")
def school_lifecycle(school_id, action):
    from ...services.nginx_queue import request_nginx_sync
    school = _school(school_id)
    if action not in ("suspend", "resume", "archive", "unarchive", "end_sessions"):
        abort(404)
    try:
        user, reason = _dangerous(school)
        before = school.status
        if action == "suspend":
            subs.suspend_school(school, user, reason)
            pact.record(user, school, "school_suspended", reason, from_value=before,
                        to_value="suspended", event=False)
        elif action == "resume":
            subs.resume_school(school, user, reason)
            pact.record(user, school, "school_resumed", reason, from_value=before,
                        to_value="active", event=False)
        elif action == "archive":
            if school.status == "archived":
                raise pact.ActionRefused("المدرسة مؤرشفة بالفعل.")
            subs.set_school_status(school, "archived")
            subs.bump_auth_epoch(school)
            from ...models import SchoolOffboarding
            off = SchoolOffboarding.query.filter_by(school_id=school.id, purged_at=None).first()
            if off is not None and off.archived_at is None:
                off.archived_at = datetime.now(timezone.utc)                     # SAAS-035
            request_nginx_sync("school_archived", school_id=school.id, user=user)
            pact.record(user, school, "school_archived", reason, from_value=before, to_value="archived")
        elif action == "unarchive":
            if school.status != "archived":
                raise pact.ActionRefused("المدرسة ليست مؤرشفة.")
            from ...models import SchoolOffboarding
            if SchoolOffboarding.query.filter(SchoolOffboarding.school_id == school.id,
                                              SchoolOffboarding.purged_at.isnot(None)).first():
                raise pact.ActionRefused("بيانات المدرسة اتحذفت نهائيًا.")
            subs.set_school_status(school, "suspended")     # back carefully: resume is a separate step
            off = SchoolOffboarding.query.filter_by(school_id=school.id, purged_at=None).first()
            if off is not None:
                # the school is back in use: nothing approved for the old
                # archive may carry over (SAAS-035 security review)
                for f in ("archived_at", "retention_until", "purge_requested_by", "purge_requested_at",
                          "purge_approved_by", "purge_approved_at", "approvals_required",
                          "export_verified_at", "export_job_id", "export_file"):
                    setattr(off, f, None)
            request_nginx_sync("school_unarchived", school_id=school.id, user=user)
            pact.record(user, school, "school_unarchived", reason, from_value=before, to_value="suspended")
        else:
            subs.bump_auth_epoch(school)
            pact.record(user, school, "school_sessions_ended", reason, to_value=f"epoch {school.auth_epoch}")
    except (pact.ActionRefused, subs.SubscriptionError) as e:
        db.session.rollback()
        flash(str(e), "danger")
        return _back(school, "#lifecycle")
    db.session.commit()
    flash("تم تنفيذ الإجراء.", "success")
    return _back(school, "#lifecycle")


# ─── slug change (dangerous) ─────────────────────────────────────────

@bp.route("/schools/<int:school_id>/slug", methods=["POST"], endpoint="school_slug_change")
@require_platform_role("owner")
def school_slug_change(school_id):
    from ...models import SchoolSlugHistory
    from ...services.nginx_queue import request_nginx_sync
    from ...services.provisioning import slug_available
    school = _school(school_id)
    try:
        user, reason = _dangerous(school)
        ok, new_slug = slug_available(request.form.get("new_slug"))
        if not ok:
            raise pact.ActionRefused(new_slug)
        old = school.slug
        db.session.add(SchoolSlugHistory(
            school_id=school.id, old_slug=old, changed_by_platform_user_id=user.id,
            redirect_until=datetime.now(timezone.utc) + timedelta(days=SLUG_REDIRECT_DAYS)))
        school.slug = new_slug
        subs.bump_auth_epoch(school)           # host-only cookies die anyway; tokens too
        request_nginx_sync("slug_changed", school_id=school.id, user=user)
        pact.record(user, school, "school_slug_changed", reason, from_value=old, to_value=new_slug)
    except pact.ActionRefused as e:
        db.session.rollback()
        flash(str(e), "danger")
        return _back(school, "#lifecycle")
    db.session.commit()
    flash(f"تم تغيير الرابط إلى {school.slug}. الرابط القديم بيحوّل {SLUG_REDIRECT_DAYS} يوم.", "success")
    return _back(school, "#lifecycle")


# ─── staff-user tools (owner + support) ──────────────────────────────

def _staff_query(school_id):
    from ...models import Role
    from ...services.limits import NON_STAFF_ROLES
    return (User.query.join(Role, Role.id == User.role_id)
            .filter(User.school_id == school_id, Role.name.notin_(NON_STAFF_ROLES)))


@bp.route("/schools/<int:school_id>/staff", methods=["GET"], endpoint="school_staff")
@require_platform_role("owner", "support")
def school_staff(school_id):
    school = _school(school_id)
    users = _staff_query(school.id).order_by(User.full_name).all()
    return render_template("superadmin/school_staff.html", school=school, users=users)


@bp.route("/schools/<int:school_id>/staff/<int:user_id>/<action>", methods=["POST"],
          endpoint="school_staff_action")
@require_platform_role("owner", "support")
def school_staff_action(school_id, user_id, action):
    from ...models import AccountSetupToken
    from ...services.provisioning import SETUP_TOKEN_TTL, hash_token, school_url
    school = _school(school_id)
    user = _staff_query(school.id).filter(User.id == user_id).first() or abort(404)
    who = current_platform_user()
    link = None
    if action not in ("unlock", "setup_link", "deactivate", "activate"):
        abort(404)
    if action != "unlock":
        # Security review: a set-password link is a credential and
        # (de)activation changes access — owner only, with a fresh TOTP
        # and a reason (support may only unlock).
        if who.role != "owner":
            abort(403)
        reason = (request.form.get("reason") or "").strip()
        try:
            if not reason:
                raise pact.ActionRefused("السبب مطلوب.")
            if not pact.fresh_totp(who):
                raise pact.ActionRefused("أدخل رمز التحقق (TOTP) الحالي.")
        except pact.StepUpLocked as e:
            from . import end_platform_session
            flash(str(e), "danger")
            end_platform_session(revoke_user=who)
            db.session.commit()
            return redirect(url_for("superadmin.login"))
        except pact.ActionRefused as e:
            flash(str(e), "danger")
            return redirect(url_for("superadmin.school_staff", school_id=school.id))
    if action == "unlock":
        user.locked_until, user.failed_attempts = None, 0
    elif action == "deactivate":
        user.is_active = False          # the user loader drops inactive users at once
        AccountSetupToken.query.filter(AccountSetupToken.user_id == user.id,
                                       AccountSetupToken.used_at.is_(None)) \
            .update({"used_at": datetime.utcnow()}, synchronize_session=False)
    elif action == "activate":
        user.is_active = True
    elif action == "setup_link":
        import secrets
        AccountSetupToken.query.filter(AccountSetupToken.user_id == user.id,
                                       AccountSetupToken.used_at.is_(None)) \
            .update({"used_at": datetime.utcnow()}, synchronize_session=False)
        raw = secrets.token_urlsafe(32)
        db.session.add(AccountSetupToken(user_id=user.id, token_hash=hash_token(raw),
                                         expires_at=datetime.utcnow() + SETUP_TOKEN_TTL))
        link = f"{school_url(school.slug)}/set-password/{raw}"
        _tell_school_admins(school, user)
    pa.audit(f"staff_{action}", who, school_id=school.id, target_user_id=user.id,
             reason=request.form.get("reason") or None)
    db.session.commit()
    if link:
        r = make_response(render_template("superadmin/staff_link.html", school=school, user=user,
                                          link=link))
        r.headers["Cache-Control"] = "no-store"
        return r
    flash("تم.", "success")
    return redirect(url_for("superadmin.school_staff", school_id=school.id))


def _tell_school_admins(school, target):
    """Security review: the school learns when the platform issued a
    set-password link for one of its users."""
    from ...models import Role
    from ...services import platform_mailer
    if not platform_mailer.is_configured():
        return
    admins = (User.query.join(Role, Role.id == User.role_id)
              .filter(User.school_id == school.id, Role.name == "admin", User.is_active.is_(True),
                      User.email.isnot(None)).all())
    for a in admins:
        try:
            platform_mailer.send(a.email, "منصتي — رابط ضبط كلمة مرور",
                                 f"أصدرت إدارة منصتي رابط ضبط كلمة مرور جديد للمستخدم {target.full_name} "
                                 f"في {school.name}. لو ده مش متوقع، تواصل مع الدعم.")
        except platform_mailer.PlatformMailError:
            pass


# ─── notes / contacts / tags (platform-only) ─────────────────────────

@bp.route("/schools/<int:school_id>/notes", methods=["POST"], endpoint="school_note_add")
@require_platform_role("owner", "support", "finance")
def school_note_add(school_id):
    school = _school(school_id)
    body = (request.form.get("body") or "").strip()
    if body:
        db.session.add(PlatformSchoolNote(school_id=school.id, body=body[:5000],
                                          author_platform_user_id=current_platform_user().id))
        pa.audit("school_note_added", current_platform_user(), school_id=school.id)
        db.session.commit()
    return _back(school, "#notes")


@bp.route("/schools/<int:school_id>/contacts", methods=["POST"], endpoint="school_contact_add")
@require_platform_role("owner", "finance")
def school_contact_add(school_id):
    school = _school(school_id)
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip() or None
    if not name or (email and "@" not in email):
        flash("الاسم مطلوب والإيميل لازم يكون صحيح.", "danger")
        return _back(school, "#contacts")
    db.session.add(SchoolContact(school_id=school.id, name=name[:128],
                                 role=(request.form.get("role") or "").strip()[:64] or None,
                                 phone=(request.form.get("phone") or "").strip()[:32] or None,
                                 email=email, is_billing_contact=bool(request.form.get("is_billing_contact"))))
    pa.audit("school_contact_added", current_platform_user(), school_id=school.id)
    db.session.commit()
    return _back(school, "#contacts")


@bp.route("/schools/<int:school_id>/contacts/<int:cid>/delete", methods=["POST"],
          endpoint="school_contact_delete")
@require_platform_role("owner", "finance")
def school_contact_delete(school_id, cid):
    school = _school(school_id)
    c = SchoolContact.query.filter_by(id=cid, school_id=school.id).first() or abort(404)
    db.session.delete(c)
    pa.audit("school_contact_removed", current_platform_user(), school_id=school.id)
    db.session.commit()
    return _back(school, "#contacts")


@bp.route("/schools/<int:school_id>/tags", methods=["POST"], endpoint="school_tags_set")
@require_platform_role("owner", "support", "finance")
def school_tags_set(school_id):
    school = _school(school_id)
    wanted = {t.strip()[:40] for t in (request.form.get("tags") or "").split(",") if t.strip()}
    current = {t.tag: t for t in SchoolTag.query.filter_by(school_id=school.id)}
    for tag in set(current) - wanted:
        db.session.delete(current[tag])
    for tag in wanted - set(current):
        db.session.add(SchoolTag(school_id=school.id, tag=tag))
    pa.audit("school_tags_set", current_platform_user(), school_id=school.id, tags=sorted(wanted))
    db.session.commit()
    return _back(school, "#notes")


# ─── announcements ───────────────────────────────────────────────────

def _local(raw):
    """A datetime-local form value is wall-clock time in the platform
    timezone (Africa/Cairo) → aware UTC."""
    from zoneinfo import ZoneInfo
    if not raw:
        return None
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        tz = ZoneInfo(subs.get_settings().get("platform_timezone") or "Africa/Cairo")
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(timezone.utc)

@bp.route("/announcements", methods=["GET", "POST"], endpoint="announcements")
@require_platform_role("owner")
def announcements():
    if request.method == "POST":
        msg = (request.form.get("message_ar") or "").strip()
        sev = request.form.get("severity") or "info"
        try:
            starts = _local(request.form.get("starts_at")) or datetime.now(timezone.utc)
            ends = _local(request.form["ends_at"])
            if ends is None:
                raise ValueError
        except (KeyError, ValueError):
            flash("التواريخ غير صحيحة.", "danger")
            return redirect(url_for("superadmin.announcements"))
        targets = [int(x) for x in request.form.getlist("school_ids")
                   if x.isascii() and x.isdigit() and len(x) <= 12]
        if not msg or sev not in ("info", "warning") or ends <= starts:
            flash("الرسالة مطلوبة، والنهاية لازم تكون بعد البداية.", "danger")
            return redirect(url_for("superadmin.announcements"))
        a = PlatformAnnouncement(message_ar=msg[:1000], severity=sev, starts_at=starts, ends_at=ends,
                                 target_school_ids=targets or None,
                                 created_by_platform_user_id=current_platform_user().id)
        db.session.add(a)
        db.session.flush()
        pa.audit("announcement_created", current_platform_user(), announcement_id=a.id, targets=targets)
        db.session.commit()
        flash("تم نشر الرسالة.", "success")
        return redirect(url_for("superadmin.announcements"))
    rows = PlatformAnnouncement.query.order_by(PlatformAnnouncement.id.desc()).limit(100).all()
    schools = School.query.filter(School.status != "archived").order_by(School.name).all()
    return render_template("superadmin/announcements.html", rows=rows, schools=schools)


@bp.route("/announcements/<int:aid>/delete", methods=["POST"], endpoint="announcement_delete")
@require_platform_role("owner")
def announcement_delete(aid):
    a = db.session.get(PlatformAnnouncement, aid) or abort(404)
    db.session.delete(a)
    pa.audit("announcement_deleted", current_platform_user(), announcement_id=aid)
    db.session.commit()
    return redirect(url_for("superadmin.announcements"))
