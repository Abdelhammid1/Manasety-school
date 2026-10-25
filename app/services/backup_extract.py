"""SAAS-049 — look inside an old backup and take out what you need (a
student's grades, a month's invoices) as CSV / Excel, WITHOUT restoring
anything.

The package is read straight from its file (school_backup's verified
format): nothing is loaded into the database — not into the live tables,
not into a scratch schema — so the live data can't change. An uploaded
package is decrypted once into the school's private browse folder and
removed after BROWSE_TTL (or at once when it fails verification).

A browse session is a signed token bound to the user and the school;
another school's package is refused at verification.
"""
from __future__ import annotations

import csv
import io
import secrets
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from flask import current_app

from ..extensions import db
from . import school_backup as engine
from .school_restore import MODULES, Package, RestoreError, module_of_table

BROWSE_DIR = "browse"
BROWSE_TTL = 3600                 # seconds a browse session (and an uploaded copy) lives
PREVIEW_ROWS = 50
EXPORT_MAX_ROWS = 50_000

# Arabic names for the tables people look for most; the rest show their
# module + table name.
TABLE_LABELS = {
    "students": "الطلاب", "guardians": "أولياء الأمور", "enrollments": "قيد الطلاب في الفصول",
    "attendance": "الحضور والغياب", "grade_entries": "الدرجات", "assessment_components": "مكوّنات التقييم",
    "year_results": "النتائج السنوية", "invoices": "الفواتير", "invoice_lines": "بنود الفواتير",
    "payments": "المدفوعات", "installments": "الأقساط", "journal_entries": "القيود المحاسبية",
    "journal_lines": "بنود القيود", "subjects": "المواد", "sections": "الفصول", "grades": "الصفوف",
    "teachers": "المعلمون", "employees": "الموظفون", "payrolls": "الرواتب", "users": "المستخدمون",
    "lms_quiz_attempts": "محاولات الاختبارات", "lms_submissions": "تسليمات الواجبات",
    "messages": "الرسائل", "schedule_slots": "حصص الجدول",
}


def _browse_dir(school_id: int) -> Path:
    d = engine.backups_dir(school_id) / BROWSE_DIR
    d.mkdir(exist_ok=True)
    return d


def _signer():
    from itsdangerous import URLSafeTimedSerializer
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="school-backup-browse")


def sweep(school_id: Optional[int] = None) -> int:
    root = engine.backups_root()
    dirs = [root / str(int(school_id)) / BROWSE_DIR] if school_id else list(root.glob(f"*/{BROWSE_DIR}"))
    now, n = datetime.now().timestamp(), 0
    for d in dirs:
        for f in d.glob("*.tar.gz") if d.is_dir() else []:
            if now - f.stat().st_mtime > BROWSE_TTL:
                f.unlink(missing_ok=True)
                n += 1
    return n


def open_session(school_id: int, user, *, backup=None, upload=None, passphrase: str = "") -> str:
    """Verify the package for THIS school and return a browse token."""
    sweep(school_id)
    if backup is not None:
        if backup.school_id != school_id or backup.status != "succeeded" or not backup.file_name:
            raise RestoreError("النسخة دي مش متاحة.")
        rel = backup.file_name
        path = engine.backups_dir(school_id) / rel
    else:
        stage = _browse_dir(school_id)
        raw = stage / f"upload-{secrets.token_hex(8)}.bin"
        upload.save(str(raw))
        path = stage / f"upload-{secrets.token_hex(8)}.tar.gz"
        try:
            if raw.stat().st_size > engine.max_bytes():
                raise RestoreError("حجم الملف أكبر من الحد المسموح.")
            if engine.is_encrypted(raw):
                try:
                    engine.decrypt_file(raw, path, passphrase or "")
                except engine.BackupError as e:
                    raise RestoreError(str(e)) from None
            else:
                shutil.copyfile(raw, path)
        finally:
            raw.unlink(missing_ok=True)
        rel = f"{BROWSE_DIR}/{path.name}"
    rep = engine.verify_package(path, expect_school_id=school_id)
    if not rep.ok:
        if backup is None:
            path.unlink(missing_ok=True)
        raise RestoreError("الحزمة مرفوضة: " + "؛ ".join(rep.problems[:3]))
    _audit("backup_browse", school_id, user, file=rel)
    db.session.commit()
    return _signer().dumps({"s": school_id, "u": user.id, "f": rel})


def resolve(token: str, school_id: int, user) -> Optional[Path]:
    from itsdangerous import BadSignature, SignatureExpired
    try:
        data = _signer().loads(token, max_age=BROWSE_TTL)
    except (BadSignature, SignatureExpired):
        return None
    if data.get("s") != school_id or data.get("u") != user.id:
        return None
    base = engine.backups_dir(school_id)
    p = (base / str(data.get("f") or "")).resolve()
    if not p.is_relative_to(base.resolve()) or not p.is_file():
        return None
    return p


def _audit(action: str, school_id: int, user, **meta) -> None:
    from flask import has_request_context, request
    from ..models import AuditLog
    assert len(action) <= 16, action
    ip = ua = None
    if has_request_context():
        ip = request.remote_addr
        ua = (request.headers.get("User-Agent") or "")[:255] or None
    db.session.add(AuditLog(school_id=school_id, user_id=getattr(user, "id", None), action=action,
                            entity_type="SchoolBackup", new_value=meta, ip_address=ip, user_agent=ua))


# ─── reading ────────────────────────────────────────────────────────

def overview(path: Path) -> dict:
    """Modules → tables (label, rows) from the manifest; plus when."""
    pkg = Package(path)
    try:
        owned = module_of_table()
        counts = {n: m["rows"] for n, m in (pkg.manifest.get("tables") or {}).items()}
        groups = []
        for mod in MODULES:
            tables = [{"name": n, "label": TABLE_LABELS.get(n, n), "rows": counts[n]}
                      for n in sorted(counts) if owned.get(n) == mod.key and counts[n]]
            if tables:
                groups.append({"key": mod.key, "label": mod.label, "tables": tables})
        return {"created_at": pkg.manifest.get("created_at"), "name": pkg.manifest.get("name"),
                "groups": groups}
    finally:
        pkg.close()


def _table(name: str):
    t = {t.name: t for t in engine.backup_tables()}.get(name)
    if t is None:
        raise RestoreError("جدول غير معروف.")
    return t


def find_students(path: Path, q: str, limit: int = 20) -> list[dict]:
    q = (q or "").strip()
    if not q:
        return []
    pkg = Package(path)
    try:
        rows = pkg.rows(_table("students"))
    finally:
        pkg.close()
    ql = q.casefold()
    out = [r for r in rows if ql in str(r.get("full_name") or "").casefold()
           or ql == str(r.get("permanent_code") or "").casefold() or q == str(r.get("id"))]
    return [{"id": r["id"], "full_name": r.get("full_name"), "permanent_code": r.get("permanent_code")}
            for r in out[:limit]]


def rows(path: Path, table_name: str, student_id: Optional[int] = None,
         limit: Optional[int] = None) -> tuple[list[str], list[list]]:
    """Columns and rows of one table (optionally only one student's rows:
    by student_id, or by the student's enrollments)."""
    t = _table(table_name)
    pkg = Package(path)
    try:
        data = pkg.rows(t)
        if student_id is not None:
            if "student_id" in t.c:
                data = [r for r in data if r.get("student_id") == student_id]
            elif "enrollment_id" in t.c:
                enr = {r["id"] for r in pkg.rows(_table("enrollments")) if r.get("student_id") == student_id}
                data = [r for r in data if r.get("enrollment_id") in enr]
            elif table_name == "students":
                data = [r for r in data if r.get("id") == student_id]
            else:
                data = []
    finally:
        pkg.close()
    cols = [c.name for c in engine.backup_columns(t)]
    cap = min(limit or EXPORT_MAX_ROWS, EXPORT_MAX_ROWS)
    return cols, [[r.get(c) for c in cols] for r in data[:cap]]


def _cell(v):
    from .school_export import _cell as export_cell      # formula escaping (OWASP)
    return export_cell(v)


def export_bytes(cols: list[str], data: list[list], fmt: str) -> tuple[bytes, str, str]:
    if fmt == "xlsx":
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.append(cols)
        for r in data:
            ws.append([_cell(v) if not isinstance(v, (int, float)) or isinstance(v, bool) else v for v in r])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue(), "xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for r in data:
        w.writerow([_cell(v) for v in r])
    return ("﻿" + buf.getvalue()).encode("utf-8"), "csv", "text/csv; charset=utf-8"


def check_export_password(user, password: str, school_id: int) -> None:
    """Same protection as the backup download: the account password, with
    the login lockout."""
    from datetime import timedelta
    if user.is_locked():
        raise RestoreError("الحساب مقفول مؤقتًا بعد محاولات فاشلة — حاول لاحقًا.")
    if not password or not user.check_password(password):
        user.failed_attempts = (user.failed_attempts or 0) + 1
        if user.failed_attempts >= current_app.config["LOCKOUT_MAX_ATTEMPTS"]:
            user.locked_until = datetime.utcnow() + timedelta(minutes=current_app.config["LOCKOUT_MINUTES"])
            user.failed_attempts = 0
        _audit("extract_denied", school_id, user)
        db.session.commit()
        raise RestoreError("كلمة مرور الحساب غير صحيحة.")
    user.failed_attempts = 0
