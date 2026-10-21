"""SAAS-029 — the web side of nginx-sync: queue a request, read status.

The web process never runs docker or touches nginx files; it only adds
a `platform_jobs` row. `flask nginx-sync --from-queue` (systemd timer,
every minute) picks it up — see services/nginx_sync.py.
"""
from __future__ import annotations

from ..extensions import db


def request_nginx_sync(reason: str, school_id: int | None = None, user=None):
    """Add a pending nginx_sync job unless one is already pending (one run
    applies everything). Caller commits."""
    from ..models import PlatformJob
    pending = PlatformJob.query.filter_by(kind="nginx_sync", status="pending").first()
    if pending is not None:
        return pending
    job = PlatformJob(kind="nginx_sync", status="pending", school_id=school_id,
                      reason=(reason or "")[:255],
                      requested_by_platform_user_id=getattr(user, "id", None))
    db.session.add(job)
    db.session.flush()
    return job


def latest_jobs(limit: int = 10):
    from ..models import PlatformJob
    return (PlatformJob.query.filter_by(kind="nginx_sync")
            .order_by(PlatformJob.id.desc()).limit(limit).all())


def school_subdomain_status(school_id: int) -> str:
    """active   — the last finished sync deployed this school's block
       queued   — a sync is pending / running
       failed   — the last sync failed
       pending_sync — nothing has deployed it yet"""
    from ..models import PlatformJob, School
    school = db.session.get(School, school_id)
    if school is None:
        return "pending_sync"
    open_job = PlatformJob.query.filter(PlatformJob.kind == "nginx_sync",
                                        PlatformJob.status.in_(("pending", "running"))).first()
    last = (PlatformJob.query.filter(PlatformJob.kind == "nginx_sync",
                                     PlatformJob.status.in_(("succeeded", "failed")))
            .order_by(PlatformJob.id.desc()).first())
    if last is not None and last.status == "succeeded" and \
            school.slug in ((last.result or {}).get("slugs") or []):
        return "active" if open_job is None else "queued"
    if open_job is not None:
        return "queued"
    if last is not None and last.status == "failed":
        return "failed"
    return "pending_sync"
