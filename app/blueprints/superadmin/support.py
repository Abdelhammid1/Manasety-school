"""SAAS-031 — starting, listing and revoking support sessions (console).

Start needs owner/support, a TOTP checked within the last 10 minutes
(step-up: the form asks for a code when it's older), and a written
reason. Write mode is owner-only and always asks for a fresh code plus
the school's name typed back.
"""
from __future__ import annotations

import time

from flask import abort, flash, redirect, render_template, request, session, url_for

from . import bp, current_platform_user, require_platform_role
from ...extensions import db
from ...models import School, SupportSession, SupportSessionEvent
from ...services import platform_auth as pa
from ...services import support_policy as sp


def _step_up(user, *, force: bool) -> bool:
    """Shared, throttled step-up (services/platform_actions.fresh_totp)."""
    from ...services.platform_actions import fresh_totp
    return fresh_totp(user, force=force)


def school_enter_url(school, token):
    from flask import current_app
    base = current_app.config.get("BASE_DOMAIN") or "manasety.ai"
    return f"https://{school.slug}.{base}/_support/enter?t={token}"


@bp.route("/schools/<int:school_id>/support/start", methods=["POST"], endpoint="support_start")
@require_platform_role("owner", "support")
def support_start(school_id):
    school = db.session.get(School, school_id) or abort(404)
    user = current_platform_user()
    mode = request.form.get("mode") or "read_only"
    back = url_for("superadmin.school_detail", school_id=school.id) + "#support"
    from ...services.platform_actions import StepUpLocked
    try:
        stepped_up = _step_up(user, force=(mode == "write"))
    except StepUpLocked as e:
        from . import end_platform_session
        flash(str(e), "danger")
        end_platform_session(revoke_user=user)
        db.session.commit()
        return redirect(url_for("superadmin.login"))
    if not stepped_up:
        pa.audit("support_step_up_failed", user, school_id=school.id)
        db.session.commit()
        flash("أدخل رمز التحقق (TOTP) الحالي لبدء جلسة الدعم.", "danger")
        return redirect(back)
    try:
        minutes = int(request.form.get("minutes") or sp.DEFAULT_MINUTES)
        row, token = sp.start(user, school, mode=mode, reason=request.form.get("reason") or "",
                              minutes=minutes, confirm_name=request.form.get("confirm_name") or "")
    except (sp.SupportError, ValueError) as e:
        db.session.rollback()
        flash(str(e) if isinstance(e, sp.SupportError) else "مدة غير صحيحة.", "danger")
        return redirect(back)
    db.session.commit()
    resp = redirect(school_enter_url(school, token))
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


@bp.route("/support", methods=["GET"], endpoint="support_sessions")
@require_platform_role("owner")
def support_sessions():
    rows = SupportSession.query.order_by(SupportSession.id.desc()).limit(200).all()
    schools = {s.id: s for s in School.query.filter(School.id.in_({r.school_id for r in rows}))} if rows else {}
    return render_template("superadmin/support_sessions.html", rows=rows, schools=schools)


@bp.route("/support/<int:sid>", methods=["GET"], endpoint="support_session_detail")
@require_platform_role("owner")
def support_session_detail(sid):
    row = db.session.get(SupportSession, sid) or abort(404)
    events = (SupportSessionEvent.query.filter_by(support_session_id=row.id)
              .order_by(SupportSessionEvent.ts).limit(1000).all())
    return render_template("superadmin/support_session.html", row=row, events=events,
                           school=db.session.get(School, row.school_id))


@bp.route("/support/<int:sid>/revoke", methods=["POST"], endpoint="support_revoke")
@require_platform_role("owner")
def support_revoke(sid):
    row = db.session.get(SupportSession, sid) or abort(404)
    if row.ended_at is None:
        sp.revoke(row, current_platform_user())
        db.session.commit()
        flash("تم إنهاء جلسة الدعم.", "success")
    return redirect(url_for("superadmin.support_session_detail", sid=row.id))
