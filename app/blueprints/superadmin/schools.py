"""SAAS-025 — read-only school list and per-school statistics.

Counts and dates only: no names of students, phones, invoices or user
e-mails. Every cross-school read goes through platform_read_scope().
"""
from __future__ import annotations

import os
from pathlib import Path

from flask import abort, current_app, redirect, render_template, request, url_for
from sqlalchemy import func

from . import bp, current_platform_user, require_platform_role
from ...extensions import db
from ...models import (
    Course, Plan, School, SchoolLimitOverride, SchoolSubscription, SchoolSubscriptionEvent,
    Section, Student,
    Teacher, User,
)
from ...services import subscriptions as subs
from ...services.platform_scope import platform_read_scope


def _storage_bytes(school_id: int) -> int:
    from ...services.file_storage import upload_root
    root = Path(upload_root()) / str(int(school_id))
    total = 0
    if root.is_dir():
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                try:
                    total += (Path(dirpath) / f).stat().st_size
                except OSError:
                    pass
    return total


def _grouped(column_query):
    return {sid: val for sid, val in column_query}


def school_stats():
    """{school_id: stats} for every school — one grouped query per
    metric, independent of the number of schools."""
    students = _grouped(db.session.query(Student.school_id, func.count(Student.id))
                        .group_by(Student.school_id))
    active_users = _grouped(db.session.query(User.school_id, func.count(User.id))
                            .filter(User.is_active.is_(True)).group_by(User.school_id))
    last_login = _grouped(db.session.query(User.school_id, func.max(User.last_login_at))
                          .group_by(User.school_id))
    return students, active_users, last_login


@bp.route("/", endpoint="home")
def home():
    return redirect(url_for("superadmin.dashboard"))      # SAAS-034


@bp.route("/schools", endpoint="schools")
def schools():
    user = current_platform_user()
    state_filter = (request.args.get("state") or "").strip()
    sort = (request.args.get("sort") or "").strip()
    q = (request.args.get("q") or "").strip().lower()
    tag_filter = (request.args.get("tag") or "").strip()
    with platform_read_scope("schools_listed", user):
        rows = School.query.order_by(School.id).all()
        students, active_users, last_login = school_stats()
        current = {s.school_id: s for s in SchoolSubscription.query.filter_by(is_current=True)}
        settings = subs.get_settings()
        today = subs.platform_today(settings)
        from ...models import SchoolTag
        tags_by_school: dict[int, list[str]] = {}
        for t in SchoolTag.query.order_by(SchoolTag.tag):
            tags_by_school.setdefault(t.school_id, []).append(t.tag)
        items = []
        for s in rows:
            st = subs.effective_state(s, current.get(s.id), today, settings)
            if state_filter and st.state != state_filter:
                continue
            if q and q not in s.name.lower() and q not in s.slug:
                continue
            if tag_filter and tag_filter not in tags_by_school.get(s.id, ()):
                continue
            items.append({
                "school": s,
                "students": students.get(s.id, 0),
                "active_users": active_users.get(s.id, 0),
                "last_login": last_login.get(s.id),
                "storage": _storage_bytes(s.id),
                "state": st,
                "ends_on": current[s.id].ends_on if s.id in current else None,
            })
    if sort == "ends_on":
        items.sort(key=lambda it: (it["ends_on"] is None, it["ends_on"] or today))
    all_tags = sorted({t for ts in tags_by_school.values() for t in ts})
    return render_template("superadmin/schools.html", items=items, states=subs.STATES,
                           state_filter=state_filter, sort=sort, q=q, tag_filter=tag_filter,
                           all_tags=all_tags, tags_by_school=tags_by_school)


@bp.route("/schools/<int:school_id>", endpoint="school_detail")
def school_detail(school_id):
    user = current_platform_user()
    school = db.session.get(School, school_id)
    if school is None:
        abort(404)
    with platform_read_scope("school_viewed", user, school_id=school.id):
        def count(model):
            return db.session.query(func.count(model.id)).filter(model.school_id == school.id).scalar()
        stats = {
            "students": count(Student),
            "active_users": db.session.query(func.count(User.id)).filter(
                User.school_id == school.id, User.is_active.is_(True)).scalar(),
            "sections": count(Section),
            "teachers": count(Teacher),
            "courses": count(Course),
            "last_login": db.session.query(func.max(User.last_login_at)).filter(
                User.school_id == school.id).scalar(),
            "storage": _storage_bytes(school.id),
        }
        settings = subs.get_settings()
        current = subs.current_subscription(school.id)
        state = subs.effective_state(school, current, subs.platform_today(settings), settings)
        events = (SchoolSubscriptionEvent.query.filter_by(school_id=school.id)
                  .order_by(SchoolSubscriptionEvent.id.desc()).limit(30).all())
        plans = Plan.query.filter_by(is_active=True).order_by(Plan.code).all()
        over = []
        if current is not None and current.plan is not None:
            if current.plan.max_students is not None and stats["students"] > current.plan.max_students:
                over.append("الطلاب")
            if current.plan.max_users is not None and stats["active_users"] > current.plan.max_users:
                over.append("المستخدمين")
    from ...services.nginx_queue import latest_jobs, school_subdomain_status
    return render_template("superadmin/school_detail.html", school=school, stats=stats,
                           base_domain=current_app.config.get("BASE_DOMAIN"),
                           current=current, state=state, events=events, plans=plans, over=over,
                           can_edit=user.role in ("owner", "finance"),
                           subdomain=school_subdomain_status(school.id), jobs=latest_jobs(5),
                           modules=_modules_view(school.id), limits=_limits_view(school.id),
                           limit_override=db.session.get(SchoolLimitOverride, school.id),
                           **_control_view(school.id), **_usage_view(school.id),
                           **_backups_view(school.id), **_access_view(school.id),
                           ai=_ai_view(school.id))


def _backups_view(school_id):
    from .school_backups import backups_view
    return backups_view(school_id)


def _usage_view(school_id):
    from ...models import PlatformAlert
    from ...services.monitoring import school_series
    return {"usage": school_series(school_id, subs.platform_today(subs.get_settings())),
            "school_alerts": PlatformAlert.query.filter_by(school_id=school_id, resolved_at=None).all()}


def _control_view(school_id):
    from ...models import PlatformSchoolNote, SchoolContact, SchoolTag
    return {
        "notes": PlatformSchoolNote.query.filter_by(school_id=school_id)
                 .order_by(PlatformSchoolNote.id.desc()).limit(50).all(),
        "contacts": SchoolContact.query.filter_by(school_id=school_id).order_by(SchoolContact.id).all(),
        "tags": sorted(t.tag for t in SchoolTag.query.filter_by(school_id=school_id)),
    }


def _modules_view(school_id):
    """Each module with its pages (state, where it comes from) — one pass."""
    from ...services.modules import feature_sources
    return feature_sources(school_id)


def _ai_view(school_id):
    """This month's AI usage of the school (platform_ai_usage, read scope)."""
    from ...services.platform_ai_usage import school_usage
    return school_usage(current_platform_user(), school_id)


def _access_view(school_id):
    """The last 15 module / page changes, and — after a refused save — what
    the owner had chosen, so the tree shows it again."""
    from flask import session
    from ...models import PlatformUser, SchoolSubscriptionEvent
    from .modules_limits import FEATURES_FORM_KEY
    events = (SchoolSubscriptionEvent.query
              .filter(SchoolSubscriptionEvent.school_id == school_id,
                      SchoolSubscriptionEvent.kind.in_(("module_override", "feature_override")))
              .order_by(SchoolSubscriptionEvent.id.desc()).limit(15).all())
    ids = {e.platform_user_id for e in events if e.platform_user_id}
    names = {u.id: (u.full_name or u.email) for u in PlatformUser.query.filter(PlatformUser.id.in_(ids))}         if ids else {}
    kept = session.pop(FEATURES_FORM_KEY, None)
    kept_form = kept["form"] if kept and kept.get("school_id") == school_id else None
    return {"access_events": [{"event": e, "by": names.get(e.platform_user_id, "—")} for e in events],
            "access_form": kept_form}


def _limits_view(school_id):
    from ...services.limits import limit_report
    return limit_report(school_id)


@bp.route("/schools/<int:school_id>/nginx-sync", methods=["POST"], endpoint="school_nginx_sync")
@require_platform_role("owner", "support")
def school_nginx_sync(school_id):
    """SAAS-029 — "sync now": only queues a request; the server-side
    timer applies it."""
    from flask import flash
    from ...services import platform_auth as pa
    from ...services.nginx_queue import request_nginx_sync
    school = db.session.get(School, school_id) or abort(404)
    user = current_platform_user()
    job = request_nginx_sync("sync_now", school_id=school.id, user=user)
    pa.audit("nginx_sync_requested", user, school_id=school.id, job_id=job.id)
    db.session.commit()
    flash("تم تسجيل طلب المزامنة، وهيتنفّذ على السيرفر خلال دقيقة.", "success")
    return redirect(url_for("superadmin.school_detail", school_id=school.id))
