"""SAAS-036 — platform team management, own sessions, the audit viewer,
and the server-only emergency commands.

Users (owner only): invite (a one-time set-password link; TOTP is
enrolled at first login), change role, deactivate / activate, new
password link, reset TOTP. The last active owner can never be
deactivated or demoted. Resetting someone's TOTP needs a fresh TOTP from
a *different* owner; with a single owner it is CLI-only. Every change is
audited, and role / user / TOTP changes mail every owner.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

import click
from flask import Response, abort, flash, make_response, redirect, render_template, request, session, url_for

from . import bp, current_platform_user, end_platform_session
from ...extensions import db
from ...models import PLATFORM_ROLES, PlatformAuditLog, PlatformSession, PlatformUser
from ...services import platform_actions as pact
from ...services import platform_auth as pa
from ...services import platform_security as psec

PAGE = 50


def _link(raw):
    return url_for("superadmin.setup", token=raw, _external=True)


def _show_link(user, raw, title):
    r = make_response(render_template("superadmin/platform_link.html", target=user, link=_link(raw), title=title))
    r.headers["Cache-Control"] = "no-store"
    return r


@bp.route("/users", methods=["GET", "POST"], endpoint="users")
def users():
    me = current_platform_user()
    if request.method == "POST":                     # invite
        email = (request.form.get("email") or "").strip().lower()
        name = (request.form.get("full_name") or "").strip()
        role = request.form.get("role") or ""
        try:
            if "@" not in email or not name or role not in PLATFORM_ROLES:
                raise pact.ActionRefused("الإيميل والاسم والدور مطلوبين.")
            if PlatformUser.query.filter_by(email=email).first() is not None:
                raise pact.ActionRefused("الإيميل مستخدم.")
            if role == "owner":
                _no_pending_purge_owner_change(None, new_role="owner")
            if not pact.fresh_totp(me):
                raise pact.ActionRefused("أدخل رمز التحقق (TOTP) الحالي.")
        except pact.StepUpLocked:
            end_platform_session(revoke_user=me)
            db.session.commit()
            return redirect(url_for("superadmin.login"))
        except pact.ActionRefused as e:
            flash(str(e), "danger")
            return redirect(url_for("superadmin.users"))
        import secrets
        u = PlatformUser(email=email, full_name=name, role=role, is_active=True)
        u.set_password(secrets.token_urlsafe(48))       # unknown until the link is used
        db.session.add(u)
        db.session.flush()
        raw = psec.issue_setup_link(u, purpose="invite")
        pa.audit("platform_user_invited", me, invited_id=u.id, role=role)
        pact.notify_owners("منصتي — مستخدم منصة جديد", f"{me.email} أضاف {email} بدور {role}.")
        db.session.commit()
        return _show_link(u, raw, "رابط الدعوة")
    rows = PlatformUser.query.order_by(PlatformUser.id).all()
    return render_template("superadmin/users.html", rows=rows, roles=PLATFORM_ROLES)


@bp.route("/users/<int:user_id>/<action>", methods=["POST"], endpoint="user_action")
def user_action(user_id, action):
    me = current_platform_user()
    u = db.session.get(PlatformUser, user_id) or abort(404)
    if action not in ("role", "deactivate", "activate", "reset_password", "reset_totp", "end_sessions"):
        abort(404)
    try:
        if action in ("reset_password", "reset_totp") and u.role == "owner":
            raise pact.ActionRefused("حسابات owner: إعادة تعيين كلمة المرور أو TOTP من السيرفر بس "
                                     "(flask platform-user-reset-link / platform-user-reset-2fa).")
        if action in ("role", "deactivate"):
            # 2. two owners demoting each other at once must not leave none
            from ...services.locks import transaction_lock
            transaction_lock("platform-owners")
        if not pact.fresh_totp(me):
            raise pact.ActionRefused("أدخل رمز التحقق (TOTP) الحالي.")
        raw = None
        audit_extra = {}
        if action == "role":
            new = request.form.get("role") or ""
            if new not in PLATFORM_ROLES:
                raise pact.ActionRefused("دور غير معروف.")
            if u.role == "owner" and new != "owner" and u.is_active and psec.active_owner_count(exclude_id=u.id) == 0:
                raise pact.ActionRefused("لا يمكن تنزيل آخر owner نشط.")
            _no_pending_purge_owner_change(u, new_role=new)
            old, u.role = u.role, new
            audit_extra["old_role"] = old
            psec.revoke_sessions(u.id)
            pact.notify_owners("منصتي — تغيير دور", f"{me.email} غيّر دور {u.email} من {old} إلى {new}.")
        elif action == "deactivate":
            if u.role == "owner" and psec.active_owner_count(exclude_id=u.id) == 0:
                raise pact.ActionRefused("لا يمكن تعطيل آخر owner نشط.")
            _no_pending_purge_owner_change(u)
            u.is_active = False
            psec.revoke_sessions(u.id)
            from ...services.support_policy import end_for_platform_user
            end_for_platform_user(u.id, "deactivated")
        elif action == "activate":
            u.is_active = True
        elif action == "reset_password":
            raw = psec.issue_setup_link(u, purpose="reset")
            psec.revoke_sessions(u.id)
        elif action == "reset_totp":
            if u.id == me.id:
                raise pact.ActionRefused("إعادة تعيين TOTP لنفسك لازم من owner تاني أو من السيرفر.")
            if not pact.fresh_totp(me, force=True):
                raise pact.ActionRefused("أدخل رمز TOTP جديد للتأكيد.")
            u.totp_secret_encrypted, u.totp_enabled, u.totp_last_counter = None, False, None
            from ...models import PlatformRecoveryCode
            PlatformRecoveryCode.query.filter_by(platform_user_id=u.id).delete()
            u.session_version = (u.session_version or 1) + 1
            psec.revoke_sessions(u.id)
            pact.notify_owners("منصتي — إعادة تعيين TOTP", f"{me.email} أعاد تعيين TOTP لـ{u.email}.")
        elif action == "end_sessions":
            psec.revoke_sessions(u.id)
            u.session_version = (u.session_version or 1) + 1
        pa.audit(f"platform_user_{action}", me, target_user_id=u.id, role=u.role, **audit_extra)
    except pact.StepUpLocked:
        end_platform_session(revoke_user=me)
        db.session.commit()
        return redirect(url_for("superadmin.login"))
    except pact.ActionRefused as e:
        db.session.rollback()
        flash(str(e), "danger")
        return redirect(url_for("superadmin.users"))
    db.session.commit()
    if raw:
        return _show_link(u, raw, "رابط ضبط كلمة المرور")
    flash("تم.", "success")
    return redirect(url_for("superadmin.users"))


def _no_pending_purge_owner_change(u, new_role=None):
    """SAAS-035 review: no owner churn (losing one or gaining one) while a
    purge waits for approval."""
    from ...models import SchoolOffboarding
    touches_owner = (u is not None and u.role == "owner") or new_role == "owner"
    if touches_owner and SchoolOffboarding.query.filter(
            SchoolOffboarding.purge_requested_at.isnot(None), SchoolOffboarding.purged_at.is_(None)).first():
        raise pact.ActionRefused("فيه طلب حذف مدرسة معلّق: تغيير الـowners ممنوع لحد ما يتنفذ أو يتلغي.")


# ─── one-time set-password link (public endpoint) ───────────────────

_SETUP_KEY = "sa_setup_hash"


@bp.route("/setup", defaults={"token": None}, methods=["GET", "POST"], endpoint="setup")
@bp.route("/setup/<token>", methods=["GET", "POST"], endpoint="setup")
def setup(token):
    if token is not None:
        # first hit: keep only the hash, in the session, and drop the raw
        # token from the address bar / history / later log lines
        session[_SETUP_KEY] = psec.hash_token(token)
        resp = redirect(url_for("superadmin.setup"))
        resp.headers["Referrer-Policy"] = "no-referrer"
        return resp
    row = psec.redeem_setup_hash(session.get(_SETUP_KEY))
    if row is None:
        session.pop(_SETUP_KEY, None)
        return make_response(render_template("superadmin/setup.html", invalid=True), 404)
    if request.method == "POST":
        pw = request.form.get("password") or ""
        problem = pa.password_problem(pw)
        if pw != (request.form.get("confirm") or ""):
            problem = "كلمتا المرور غير متطابقتين."
        if problem:
            flash(problem, "danger")
            return render_template("superadmin/setup.html", invalid=False, user=row.user), 400
        # 4. claim the link atomically: two parallel POSTs, one winner
        if not psec.claim_setup_token(row.id):
            session.pop(_SETUP_KEY, None)
            return make_response(render_template("superadmin/setup.html", invalid=True), 404)
        session.pop(_SETUP_KEY, None)
        u = row.user
        u.set_password(pw)
        u.password_changed_at = pa.utcnow()
        u.failed_attempts, u.locked_until = 0, None
        psec.revoke_sessions(u.id)
        pa.audit("platform_setup_link_used", u, purpose=row.purpose)
        db.session.commit()
        flash("تم ضبط كلمة المرور. سجّل الدخول (وفعّل TOTP لو لسه).", "success")
        return redirect(url_for("superadmin.login"))
    resp = make_response(render_template("superadmin/setup.html", invalid=False, user=row.user))
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


# ─── own sessions ───────────────────────────────────────────────────

@bp.route("/me/sessions", methods=["GET"], endpoint="my_sessions")
def my_sessions():
    me = current_platform_user()
    rows = (PlatformSession.query.filter_by(platform_user_id=me.id)
            .order_by(PlatformSession.created_at.desc()).limit(50).all())
    return render_template("superadmin/my_sessions.html", rows=rows, current=session.get("sa_sid"))


@bp.route("/me/sessions/<sid>/revoke", methods=["POST"], endpoint="my_session_revoke")
def my_session_revoke(sid):
    me = current_platform_user()
    row = PlatformSession.query.filter_by(id=sid, platform_user_id=me.id).first() or abort(404)
    row.revoked_at = datetime.now(timezone.utc)
    pa.audit("platform_session_revoked", me, session=sid[:8])
    db.session.commit()
    return redirect(url_for("superadmin.my_sessions"))


# ─── audit viewer (owner) ───────────────────────────────────────────

def _audit_query():
    q = PlatformAuditLog.query
    a = request.args
    if a.get("user"):
        q = q.filter(PlatformAuditLog.platform_user_id == int(a["user"])) if a["user"].isdigit() else q
    if a.get("school") and a["school"].isdigit():
        q = q.filter(PlatformAuditLog.target_school_id == int(a["school"]))
    if a.get("action"):
        q = q.filter(PlatformAuditLog.action == a["action"])
    for key, op in (("from", "__ge__"), ("to", "__le__")):
        if a.get(key):
            try:
                d = datetime.fromisoformat(a[key])
            except ValueError:
                continue
            if key == "to" and len(a[key]) == 10:
                d = d.replace(hour=23, minute=59, second=59)
            q = q.filter(getattr(PlatformAuditLog.created_at, op)(d))
    return q.order_by(PlatformAuditLog.id.desc())


@bp.route("/audit", methods=["GET"], endpoint="audit")
def audit_view():
    me = current_platform_user()
    q = _audit_query()
    if request.args.get("format") == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id", "created_at", "platform_user_id", "action", "target_school_id", "ip", "meta"])
        for r in q.limit(50000):
            w.writerow([r.id, r.created_at, r.platform_user_id, r.action, r.target_school_id, r.ip,
                        "" if r.meta is None else __import__("json").dumps(r.meta, ensure_ascii=False)])
        pa.audit("audit_exported", me, filters=dict(request.args))
        db.session.commit()
        return Response("﻿" + buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="platform-audit.csv"'})
    page = max(int(request.args.get("page") or 1), 1)
    rows = q.offset((page - 1) * PAGE).limit(PAGE + 1).all()
    users = {u.id: u.email for u in PlatformUser.query.all()}
    actions = [a for (a,) in db.session.query(PlatformAuditLog.action).distinct().order_by(PlatformAuditLog.action)]
    return render_template("superadmin/audit.html", rows=rows[:PAGE], more=len(rows) > PAGE, page=page,
                           users=users, actions=actions, args=request.args)


# ─── server-only emergency commands (all audited) ───────────────────

def _cli_user(email):
    u = PlatformUser.query.filter_by(email=(email or "").strip().lower()).first()
    if u is None:
        raise click.ClickException("no such platform user")
    return u


@bp.cli.command("platform-user-reset-2fa")
@click.option("--email", required=True)
def platform_user_reset_2fa(email):
    """Clear a platform user's TOTP (they enrol again at next login)."""
    from ...models import PlatformRecoveryCode
    u = _cli_user(email)
    u.totp_secret_encrypted, u.totp_enabled, u.totp_last_counter = None, False, None
    PlatformRecoveryCode.query.filter_by(platform_user_id=u.id).delete()
    u.session_version = (u.session_version or 1) + 1
    psec.revoke_sessions(u.id)
    pa.audit("platform_user_reset_2fa_cli", None, target_user_id=u.id)
    pact.notify_owners("منصتي — إعادة تعيين TOTP من السيرفر", f"تمت إعادة تعيين TOTP لـ{u.email} من سطر الأوامر.")
    db.session.commit()
    click.echo(f"TOTP cleared for {u.email}; enrolment required at next login")


@bp.cli.command("platform-user-reset-link")
@click.option("--email", required=True)
def platform_user_reset_link(email):
    """Print a one-time set-password link (72 h) — the only way to reset an
    owner's password. Give it to the person directly, never in a chat."""
    u = _cli_user(email)
    raw = psec.issue_setup_link(u, purpose="reset")
    psec.revoke_sessions(u.id)
    pa.audit("platform_user_reset_link_cli", None, target_user_id=u.id)
    pact.notify_owners("منصتي — رابط كلمة مرور من السيرفر", f"اتعمل رابط ضبط كلمة مرور لـ{u.email} من سطر الأوامر.")
    db.session.commit()
    from flask import current_app
    host = (current_app.config.get("PLATFORM_HOSTS") or ["console.manasety.ai"])[0]
    click.echo(f"https://{host}/superadmin/setup/{raw}")


@bp.cli.command("platform-user-unlock")
@click.option("--email", required=True)
def platform_user_unlock(email):
    u = _cli_user(email)
    u.failed_attempts, u.locked_until = 0, None
    pa.audit("platform_user_unlock_cli", None, target_user_id=u.id)
    db.session.commit()
    click.echo(f"unlocked {u.email}")


@bp.cli.command("platform-user-deactivate")
@click.option("--email", required=True)
def platform_user_deactivate(email):
    u = _cli_user(email)
    u.is_active = False
    psec.revoke_sessions(u.id)
    pa.audit("platform_user_deactivate_cli", None, target_user_id=u.id)
    db.session.commit()
    click.echo(f"deactivated {u.email}")


@bp.cli.command("platform-audit-prune")
@click.option("--months", type=int, default=psec.AUDIT_RETENTION_MONTHS, show_default=True)
def platform_audit_prune(months):
    """Retention: delete platform audit rows / support events older than N
    months — the only path past the immutability triggers."""
    out = psec.prune_audit(months)
    pa.audit("platform_audit_pruned", None, **out, months=months)
    db.session.commit()
    click.echo(f"pruned {out}")
