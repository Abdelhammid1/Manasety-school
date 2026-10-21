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
    Course, Plan, School, SchoolSubscription, SchoolSubscriptionEvent, Section, Student,
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
    return redirect(url_for("superadmin.schools"))


@bp.route("/schools", endpoint="schools")
def schools():
    user = current_platform_user()
    state_filter = (request.args.get("state") or "").strip()
    sort = (request.args.get("sort") or "").strip()
    with platform_read_scope("schools_listed", user):
        rows = School.query.order_by(School.id).all()
        students, active_users, last_login = school_stats()
        current = {s.school_id: s for s in SchoolSubscription.query.filter_by(is_current=True)}
        settings = subs.get_settings()
        today = subs.platform_today(settings)
        items = []
        for s in rows:
            st = subs.effective_state(s, current.get(s.id), today, settings)
            if state_filter and st.state != state_filter:
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
    return render_template("superadmin/schools.html", items=items, states=subs.STATES,
                           state_filter=state_filter, sort=sort)


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
                           subdomain=school_subdomain_status(school.id), jobs=latest_jobs(5))


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
