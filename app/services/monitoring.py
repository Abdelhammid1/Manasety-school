"""SAAS-034 — monitoring: daily usage snapshots, server health, alerts.

Numbers only — never a name, phone or e-mail of anyone at a school.

- take_snapshots(): one row per (school, day), upserted (a second run the
  same day updates it), failures isolated per school, one summary row
  in platform_audit_logs per run, rows older than 400 days pruned.
- health(): read-only indicators (ok / warn / error / unknown). A source
  that can't be read is "unknown", never "ok".
- evaluate_alerts(): every rule in one place; an open alert is updated
  (last_seen_at), not duplicated, and closes itself when its condition
  is gone. The daily digest mails owners the NEW alerts only.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from flask import current_app

from ..extensions import db

RETENTION_DAYS = 400
BACKUP_MAX_HOURS = 26
DISK_MIN_FREE = 0.15
CERT_WARN_DAYS = 21
CRON_MAX_HOURS = 24
INACTIVE_DAYS = 14
CRON_OK_KEY = "cron_tick_last_ok"


def utcnow():
    return datetime.now(timezone.utc)


def _aware(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ─── snapshots ──────────────────────────────────────────────────────

def _last_activity(school_id):
    from sqlalchemy import func
    from ..models import User
    # the global filter already hides the platform support user
    return db.session.query(func.max(User.last_login_at)).filter(User.school_id == school_id).scalar()


def _active_7d(school_id, now):
    from ..models import User
    since = (now - timedelta(days=7)).replace(tzinfo=None)
    return User.query.filter(User.school_id == school_id, User.last_login_at >= since).count()


def take_snapshots(today: date | None = None) -> dict:
    from ..models import PlatformUsageSnapshot, School
    from .limits import school_usage
    from .platform_auth import audit
    from .subscriptions import current_subscription, effective_state, get_settings, platform_today
    settings = get_settings()
    today = today or platform_today(settings)
    now = utcnow()
    ok, failed = 0, []
    for (sid,) in db.session.query(School.id).order_by(School.id).all():
        try:
            school = db.session.get(School, sid)
            usage = school_usage(sid)
            row = PlatformUsageSnapshot.query.filter_by(school_id=sid, day=today).first() \
                or PlatformUsageSnapshot(school_id=sid, day=today)
            row.students_active = usage.students
            row.staff_users = usage.users
            row.storage_bytes = usage.storage_bytes
            row.last_activity_at = _last_activity(sid)
            row.active_users_7d = _active_7d(sid, now)
            row.subscription_state = effective_state(school, current_subscription(sid), today, settings).state
            db.session.add(row)
            db.session.commit()
            ok += 1
        except Exception:  # noqa: BLE001 — one school never stops the rest
            db.session.rollback()
            current_app.logger.exception("usage snapshot failed for school %s", sid)
            failed.append(sid)
    pruned = PlatformUsageSnapshot.query.filter(
        PlatformUsageSnapshot.day < today - timedelta(days=RETENTION_DAYS)).delete(synchronize_session=False)
    audit("usage_snapshot_run", None, day=today.isoformat(), ok=ok, failed=failed, pruned=pruned)
    db.session.commit()
    return {"day": today.isoformat(), "ok": ok, "failed": failed, "pruned": pruned}


def record_cron_ok(school_id: int) -> None:
    """Called by cron after a school's tick succeeded (SAAS-010)."""
    from ..models import PlatformSetting
    row = db.session.get(PlatformSetting, CRON_OK_KEY) or PlatformSetting(key=CRON_OK_KEY, value="{}")
    data = json.loads(row.value or "{}")
    data[str(school_id)] = utcnow().isoformat()
    row.value = json.dumps(data)
    db.session.add(row)


# ─── health ─────────────────────────────────────────────────────────

@dataclass
class Indicator:
    key: str
    label: str
    status: str            # ok | warn | error | unknown
    detail: str = ""


def _newest_file_age_hours(folder: str):
    p = Path(folder)
    files = [f for f in p.iterdir() if f.is_file()]
    if not files:
        raise FileNotFoundError(folder)
    newest = max(f.stat().st_mtime for f in files)
    return (time.time() - newest) / 3600


def _free_ratio(path: str):
    u = shutil.disk_usage(path)
    return u.free / u.total


def health() -> list[Indicator]:
    from ..models import PlatformJob, PlatformSetting, School
    from .file_storage import upload_root
    cfg = current_app.config
    out: list[Indicator] = []

    last = (PlatformJob.query.filter(PlatformJob.kind == "nginx_sync",
                                     PlatformJob.status.in_(("succeeded", "failed")))
            .order_by(PlatformJob.id.desc()).first())
    days = (last.result or {}).get("cert_days_left") if last is not None else None
    if days is None:
        out.append(Indicator("cert", "شهادة *.manasety.ai", "unknown", "لا توجد قراءة من nginx-sync"))
    else:
        out.append(Indicator("cert", "شهادة *.manasety.ai",
                             "error" if days < 7 else ("warn" if days < CERT_WARN_DAYS else "ok"),
                             f"متبقي {days} يوم"))

    try:
        hours = _newest_file_age_hours(cfg.get("BACKUP_DIR") or "")
        out.append(Indicator("backup", "آخر نسخة احتياطية", "warn" if hours > BACKUP_MAX_HOURS else "ok",
                             f"منذ {hours:.0f} ساعة"))
    except (OSError, ValueError):
        out.append(Indicator("backup", "آخر نسخة احتياطية", "unknown", "تعذّرت قراءة فولدر النسخ"))

    for key, label, path in (("disk_uploads", "مساحة القرص (الملفات)", lambda: str(upload_root())),
                             ("disk_backups", "مساحة القرص (النسخ)", lambda: cfg.get("BACKUP_DIR") or "")):
        try:
            ratio = _free_ratio(path())
            out.append(Indicator(key, label, "warn" if ratio < DISK_MIN_FREE else "ok", f"متاح {ratio:.0%}"))
        except (OSError, ValueError):
            out.append(Indicator(key, label, "unknown", "تعذّرت القراءة"))

    if last is None:
        out.append(Indicator("nginx", "مزامنة nginx", "unknown", "لم تُشغَّل بعد"))
    else:
        out.append(Indicator("nginx", "مزامنة nginx", "ok" if last.status == "succeeded" else "error",
                             f"آخر نتيجة: {last.status}"))

    row = db.session.get(PlatformSetting, CRON_OK_KEY)
    try:
        seen = {int(k): datetime.fromisoformat(v) for k, v in json.loads(row.value or "{}").items()} if row else {}
    except (ValueError, TypeError):
        seen = None
    active = [s for (s,) in db.session.query(School.id).filter(School.status == "active")]
    if seen is None or not seen:
        out.append(Indicator("cron", "cron-tick", "unknown", "لا يوجد تشغيل ناجح مسجّل"))
    else:
        stale = [sid for sid in active if sid not in seen
                 or utcnow() - _aware(seen[sid]) > timedelta(hours=CRON_MAX_HOURS)]
        out.append(Indicator("cron", "cron-tick", "warn" if stale else "ok",
                             f"{len(stale)} مدرسة بدون تشغيل خلال 24 ساعة" if stale else "كل المدارس"))
    return out


# ─── alerts ─────────────────────────────────────────────────────────

def _conditions(today: date) -> dict[tuple[str, int | None], tuple[str, str]]:
    """{(kind, school_id): (severity, message_ar)} for everything wrong now."""
    from ..models import PlatformUsageSnapshot, School
    from .limits import effective_limits
    from .subscriptions import current_subscription, effective_state, get_settings
    settings = get_settings()
    found = {}
    latest = {s.school_id: s for s in PlatformUsageSnapshot.query.filter_by(day=today)}
    for school in School.query.filter(School.status != "archived").all():
        st = effective_state(school, current_subscription(school.id), today, settings)
        if st.state in ("active", "trial") and st.days_left is not None and st.days_left <= 14:
            found[("expiring", school.id)] = ("warn", f"اشتراك {school.name} ينتهي خلال {st.days_left} يوم")
        if st.state in ("grace", "expired"):
            found[("expired", school.id)] = ("error", f"اشتراك {school.name} منتهي ({st.state})")
        snap = latest.get(school.id)
        if snap is not None:
            limits = effective_limits(school.id)
            for kind, used in (("students", snap.students_active), ("users", snap.staff_users),
                               ("storage", (snap.storage_bytes or 0) / (1024 * 1024))):
                lim = limits[kind]
                if lim:
                    ratio = used / lim
                    if ratio >= 1:
                        found[(f"limit_{kind}_100", school.id)] = ("error", f"{school.name} وصلت 100% من حد {kind}")
                    elif ratio >= 0.9:
                        found[(f"limit_{kind}_90", school.id)] = ("warn", f"{school.name} فوق 90% من حد {kind}")
            last = _aware(snap.last_activity_at)
            if school.status == "active" and (last is None or utcnow() - last > timedelta(days=INACTIVE_DAYS)):
                found[("inactive", school.id)] = ("warn", f"{school.name} بلا نشاط {INACTIVE_DAYS} يوم")
    for ind in health():
        if ind.status in ("warn", "error"):
            found[(f"health_{ind.key}", None)] = (ind.status, f"{ind.label}: {ind.detail}")
    return found


def evaluate_alerts(today: date | None = None) -> dict:
    from ..models import PlatformAlert
    from .subscriptions import get_settings, platform_today
    today = today or platform_today(get_settings())
    now = utcnow()
    found = _conditions(today)
    open_rows = {(a.kind, a.school_id): a for a in PlatformAlert.query.filter_by(resolved_at=None)}
    new = []
    for key, (sev, msg) in found.items():
        row = open_rows.get(key)
        if row is None:
            row = PlatformAlert(kind=key[0], school_id=key[1], severity=sev, message_ar=msg,
                                first_seen_at=now, last_seen_at=now)
            db.session.add(row)
            new.append(row)
        else:
            row.last_seen_at, row.severity, row.message_ar = now, sev, msg
    for key, row in open_rows.items():
        if key not in found:
            row.resolved_at = now
    db.session.flush()
    mailed = _digest(new) if new else 0
    db.session.commit()
    return {"open": len(found), "new": len(new), "mailed": mailed}


def _digest(new) -> int:
    from .platform_actions import notify_owners
    body = "\n".join(f"- [{a.severity}] {a.message_ar}" for a in new)
    return notify_owners(f"منصتي — {len(new)} تنبيه جديد", f"التنبيهات الجديدة اليوم:\n{body}")


# ─── console home (constant query count) ────────────────────────────

def dashboard(today: date) -> dict:
    from sqlalchemy import func
    from ..models import (PlatformAlert, PlatformUsageSnapshot, School, SchoolSubscription,
                          SupportSession)
    from .subscriptions import effective_state, get_settings
    settings = get_settings()
    schools = School.query.all()
    current = {s.school_id: s for s in SchoolSubscription.query.filter_by(is_current=True)}
    by_state, expiring = {}, 0
    for s in schools:
        st = effective_state(s, current.get(s.id), today, settings)
        by_state[st.state] = by_state.get(st.state, 0) + 1
        if st.days_left is not None and st.days_left <= 30 and st.state in ("active", "trial"):
            expiring += 1
    open_alerts = PlatformAlert.query.filter_by(resolved_at=None).order_by(PlatformAlert.id.desc()).all()
    kinds = {}
    for a in open_alerts:
        kinds[a.kind] = kinds.get(a.kind, 0) + 1
    over_90 = len({a.school_id for a in open_alerts if a.kind.startswith("limit_") and a.kind.endswith("_90")})
    over_100 = len({a.school_id for a in open_alerts if a.kind.startswith("limit_") and a.kind.endswith("_100")})
    series = (db.session.query(PlatformUsageSnapshot.day, func.sum(PlatformUsageSnapshot.students_active))
              .filter(PlatformUsageSnapshot.day >= today - timedelta(days=90))
              .group_by(PlatformUsageSnapshot.day).order_by(PlatformUsageSnapshot.day).all())
    support = SupportSession.query.order_by(SupportSession.id.desc()).limit(5).all()
    return {"by_state": by_state, "expiring": expiring, "over_90": over_90, "over_100": over_100,
            "inactive": kinds.get("inactive", 0), "alerts": open_alerts[:20],
            "series": [(d, int(n or 0)) for d, n in series], "support": support}


def school_series(school_id: int, today: date):
    from ..models import PlatformUsageSnapshot
    rows = (PlatformUsageSnapshot.query.filter(PlatformUsageSnapshot.school_id == school_id,
                                               PlatformUsageSnapshot.day >= today - timedelta(days=90))
            .order_by(PlatformUsageSnapshot.day).all())
    return {"students": [(r.day, r.students_active) for r in rows],
            "storage_mb": [(r.day, round((r.storage_bytes or 0) / (1024 * 1024), 1)) for r in rows],
            "last": rows[-1] if rows else None}
