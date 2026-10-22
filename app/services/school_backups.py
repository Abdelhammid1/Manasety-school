"""SAAS-047 — a school admin's own backups: request, the queue the server
CLI runs, retention, delete and the protected (encrypted) download.

The package format and the export / encryption engine are in
school_backup (SAAS-046). The web process only queues a row; the
server's `flask school-backup --from-queue` (every minute, from the cron
file) builds it.

Rules (ticket):
  * school owner (role "admin") only — enforced by the views;
  * at most DAILY_LIMIT new backups a day, refused when the disk is low;
  * keep the last `keep` (default 5, console-adjustable per school),
    older ones are deleted automatically after a successful backup;
  * the console can switch the feature off for a school;
  * downloading needs the admin's account password + an encryption
    passphrase; the link is signed, bound to that user, and short-lived;
  * every create / download / delete is in audit_log; no email — an
    in-app notification only.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Optional

from flask import current_app, has_request_context, request

from ..extensions import db
from . import school_backup as engine

DAILY_LIMIT = 3
DEFAULT_KEEP = 5
POLICY_KEY = "school_backup_policy"
DOWNLOAD_TTL = 600          # seconds a prepared download stays valid


class BackupRefused(Exception):
    """A request the school can't make right now; the message is shown."""


# ─── policy (console) ───────────────────────────────────────────────

def _policies() -> dict:
    from ..models import PlatformSetting
    row = db.session.get(PlatformSetting, POLICY_KEY)
    try:
        return json.loads(row.value) if row and row.value else {}
    except ValueError:
        return {}


def policy(school_id: int) -> dict:
    p = _policies().get(str(int(school_id))) or {}
    keep = p.get("keep")
    return {"enabled": p.get("enabled", True) is not False,
            "keep": int(keep) if isinstance(keep, int) and 1 <= keep <= 30 else
            int(current_app.config.get("SCHOOL_BACKUP_KEEP") or DEFAULT_KEEP)}


def set_policy(school_id: int, *, enabled: bool, keep: int, platform_user) -> dict:
    from ..models import PlatformSetting
    from .platform_auth import audit
    if not 1 <= int(keep) <= 30:
        raise BackupRefused("عدد النسخ المحفوظة لازم يكون من 1 لـ 30.")
    all_ = _policies()
    before = policy(school_id)
    all_[str(int(school_id))] = {"enabled": bool(enabled), "keep": int(keep)}
    row = db.session.get(PlatformSetting, POLICY_KEY) or PlatformSetting(key=POLICY_KEY)
    row.value = json.dumps(all_)
    row.updated_by = getattr(platform_user, "id", None)
    db.session.add(row)
    audit("school_backup_policy", platform_user, school_id=school_id, before=before,
          after={"enabled": bool(enabled), "keep": int(keep)})
    db.session.commit()
    return policy(school_id)


# ─── audit (school trail) ───────────────────────────────────────────

def _audit(action: str, backup, user=None, **meta) -> None:
    from ..models import AuditLog
    ip = ua = None
    if has_request_context():
        ip = request.remote_addr
        ua = (request.user_agent.string or "")[:255] if request.user_agent else None
    db.session.add(AuditLog(
        school_id=backup.school_id, user_id=getattr(user, "id", None), action=action,
        entity_type="SchoolBackup", entity_id=backup.id,
        new_value={"file": backup.file_name, "status": backup.status, **meta},
        ip_address=ip, user_agent=ua))


# ─── request ────────────────────────────────────────────────────────

def _today_start() -> datetime:
    return datetime.combine(datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc)


def disk_ok() -> bool:
    need = int(current_app.config.get("SCHOOL_BACKUP_MIN_FREE_MB") or 1024) * 1024 * 1024
    return shutil.disk_usage(engine.backups_root()).free >= need


def request_backup(school_id: int, user):
    from ..models import SchoolBackup
    if not policy(school_id)["enabled"]:
        raise BackupRefused("النسخ الاحتياطي مقفول لمدرستك من إدارة المنصة.")
    q = SchoolBackup.query.filter(SchoolBackup.school_id == school_id)
    if q.filter(SchoolBackup.status.in_(("pending", "running"))).first():
        raise BackupRefused("فيه نسخة جاري تجهيزها بالفعل.")
    if q.filter(SchoolBackup.created_at >= _today_start()).count() >= DAILY_LIMIT:
        raise BackupRefused(f"الحد الأقصى {DAILY_LIMIT} نسخ في اليوم.")
    if not disk_ok():
        raise BackupRefused("المساحة على السيرفر غير كافية حاليًا — تواصل مع الدعم.")
    b = SchoolBackup(school_id=school_id, status="pending", requested_by_user_id=getattr(user, "id", None))
    db.session.add(b)
    db.session.flush()
    _audit("backup_create", b, user)
    db.session.commit()
    return b


# ─── the queue (server CLI) ─────────────────────────────────────────

def _path(b) -> Optional[Path]:
    if not b.file_name or "/" in b.file_name or "\\" in b.file_name:
        return None
    return engine.backups_dir(b.school_id) / b.file_name


def run_one(b) -> None:
    from .notifications import send_notification
    from .tenancy import tenant_context
    b.status, b.started_at, b.progress = "running", datetime.now(timezone.utc), 0
    db.session.commit()

    table = type(b).__table__
    last = {"pct": 0}

    def progress(done, total, _what):
        # Own connection: the export's session is read-only (platform_read_scope).
        pct = int(done * 100 / max(total, 1))
        if pct != last["pct"]:
            last["pct"] = pct
            with db.engine.begin() as conn:
                conn.execute(table.update().where(table.c.id == b.id).values(progress=pct))
    try:
        res = engine.export_school(b.school_id, progress=progress)
        b.status, b.progress = "succeeded", 100
        b.file_name, b.size_bytes = res.path.name, res.bytes
    except Exception as e:                    # noqa: BLE001 — record the type / safe message only
        db.session.rollback()
        b.status = "failed"
        b.error = (str(e) if isinstance(e, engine.BackupError) else type(e).__name__)[:255]
    b.finished_at = datetime.now(timezone.utc)
    _audit("backup_" + b.status, b)
    db.session.commit()
    if b.status == "succeeded":
        prune(b.school_id)
    # In-app only (no target phone / email): the admin sees it in the bell.
    with tenant_context(b.school_id):
        send_notification(b.school_id, "school_backup",
                          {"title": "النسخة الاحتياطية", "status": b.status,
                           "message": "النسخة الاحتياطية جاهزة للتنزيل." if b.status == "succeeded"
                           else "تعذّر إنشاء النسخة الاحتياطية."},
                          related_kind="school_backup", related_id=b.id)


def run_queue(limit: int = 5) -> int:
    from ..models import SchoolBackup
    rows = (SchoolBackup.query.filter_by(status="pending")
            .order_by(SchoolBackup.id).limit(limit).all())
    for b in rows:
        run_one(b)
    sweep_downloads()
    return len(rows)


def prune(school_id: int) -> int:
    """Keep the newest `keep` successful backups; delete older files and rows."""
    from ..models import SchoolBackup
    keep = policy(school_id)["keep"]
    done = (SchoolBackup.query.filter_by(school_id=school_id, status="succeeded")
            .order_by(SchoolBackup.created_at.desc(), SchoolBackup.id.desc()).all())
    gone = 0
    for b in done[keep:]:
        p = _path(b)
        if p:
            p.unlink(missing_ok=True)
        _audit("backup_retention_delete", b)
        db.session.delete(b)
        gone += 1
    db.session.commit()
    return gone


def delete_backup(b, user) -> None:
    if b.status == "running":
        raise BackupRefused("النسخة جاري تجهيزها — استنى لحد ما تخلص.")
    p = _path(b)
    if p:
        p.unlink(missing_ok=True)
    _audit("backup_delete", b, user)
    db.session.delete(b)
    db.session.commit()


# ─── download ───────────────────────────────────────────────────────

def _downloads_dir(school_id: int) -> Path:
    d = engine.backups_dir(school_id) / "downloads"
    d.mkdir(exist_ok=True)
    return d


def _signer():
    from itsdangerous import URLSafeTimedSerializer
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="school-backup-download")


def prepare_download(b, user, account_password: str, passphrase: str) -> str:
    """Encrypt the package for this download; returns a signed token for
    the GET that streams it. Refuses without the right account password."""
    if b.status != "succeeded":
        raise BackupRefused("النسخة دي مش جاهزة.")
    if not account_password or not user.check_password(account_password):
        _audit("backup_download_refused", b, user, reason="wrong account password")
        db.session.commit()
        raise BackupRefused("كلمة مرور الحساب غير صحيحة.")
    try:
        engine.check_passphrase(passphrase)
    except engine.BackupError as e:
        raise BackupRefused(str(e)) from None
    src = _path(b)
    if not src or not src.is_file():
        raise BackupRefused("ملف النسخة غير موجود.")
    sweep_downloads(b.school_id)
    name = secrets.token_hex(16) + ".mbk"
    engine.encrypt_file(src, _downloads_dir(b.school_id) / name, passphrase)
    _audit("backup_download_prepared", b, user)
    db.session.commit()
    return _signer().dumps({"b": b.id, "u": user.id, "s": b.school_id, "f": name})


def open_download(token: str, user, school_id: int):
    """(path, download name, backup) for a valid token of THIS user and
    school, or None. The file is single-use: the view deletes it."""
    from itsdangerous import BadSignature, SignatureExpired
    from ..models import SchoolBackup
    try:
        data = _signer().loads(token, max_age=DOWNLOAD_TTL)
    except (BadSignature, SignatureExpired):
        return None
    if data.get("u") != user.id or data.get("s") != school_id:
        return None
    name = str(data.get("f") or "")
    if not name.endswith(".mbk") or "/" in name or "\\" in name or ".." in name:
        return None
    b = SchoolBackup.query.filter_by(id=data.get("b"), school_id=school_id).first()
    path = _downloads_dir(school_id) / name
    if b is None or not path.is_file():
        return None
    # Single use: claimed by renaming before it is sent (works even where
    # an open file can't be deleted); the view removes it after sending.
    sending = path.with_suffix(".sending")
    try:
        os.replace(path, sending)
    except OSError:
        return None
    _audit("backup_downloaded", b, user)
    db.session.commit()
    return sending, (b.file_name or "backup.tar.gz").replace(".tar.gz", ".mbk"), b


def sweep_downloads(school_id: Optional[int] = None) -> int:
    """Remove prepared downloads older than the link's life."""
    root = engine.backups_root()
    dirs = [root / str(int(school_id)) / "downloads"] if school_id else list(root.glob("*/downloads"))
    now, n = datetime.now().timestamp(), 0
    for d in dirs:
        for f in [*d.glob("*.mbk"), *d.glob("*.sending")] if d.is_dir() else []:
            if now - f.stat().st_mtime > DOWNLOAD_TTL:
                f.unlink(missing_ok=True)
                n += 1
    return n


def remove_after_send(path: Path) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
