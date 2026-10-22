"""SAAS-046 — the school backup package: one documented format and one
engine (export + verify) that every backup / restore feature uses.
Format reference: docs/BACKUP_FORMAT.md.

    <slug>-<id>-<UTC stamp>.tar.gz
      manifest.json          format + schema version, school, per table
                             {rows, columns, sha256}, per file {bytes, sha256}
      school.json            the school's own settings (never slug / status /
                             SMTP / auth_epoch — see SCHOOL_ROW_EXCLUDED)
      data/<table>.copy      PostgreSQL COPY text format, columns in the
                             manifest's order, rows by primary key
      files/<key>            the school's uploads, same keys as the storage
      checksums.sha256       sha256 of every other member (sha256sum format)

Tables are found from the schema (every table with a school_id column);
platform tables and short-lived tokens are excluded with a written
reason (BACKUP_EXCLUDED). The export reads everything inside one
transaction (REPEATABLE READ READ ONLY on PostgreSQL), so the package is
one consistent instant.

A package that leaves the server is encrypted with a passphrase the
admin chooses (>= 12 characters; scrypt-derived key, AES-256-GCM in
authenticated chunks — see encrypt_file). The passphrase is never stored.

verify_package() is the gate for every later use (restore, extract): it
refuses a package whose checksums, format, schema revision, tables or
any row's school_id don't match.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import secrets
import shutil
import struct
import tarfile
import tempfile
import zlib
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable, Iterable, Optional

from flask import current_app
from sqlalchemy import select, text

from ..extensions import db

FORMAT = "manasety-school-backup"
SCHEMA_VERSION = 1                      # of the package format, not the DB
SUPPORTED_SCHEMA_VERSIONS = {1}

# Tables with a school_id that a backup leaves out, and why. Platform
# tables (tenant_guard.PLATFORM_TABLES) are excluded on top of these.
BACKUP_EXCLUDED: dict[str, str] = {
    "account_setup_tokens": "short-lived account set-up links — reissued, never restored",
    "device_tokens": "push tokens of signed-in devices (sessions) — re-registered on next login",
    "school_backups": "the list of the school's backups itself — a restore must not rewrite it",
    "school_restores": "the restore history itself (and its undo links) — never rewritten by a restore",
}


def backup_columns(table):
    """The columns a package carries: every column except secrets
    (password hashes, TOTP secrets, tokens — audit.is_secret_field). A
    package goes to a personal device; credentials never leave the server.
    A restored account that didn't exist gets an unusable password."""
    from .audit import is_secret_field
    return [c for c in table.c if not is_secret_field(c.name)]

# Columns of the school's own row that never travel in a package: the
# tenant's identity, plan / state, mail credentials and session epoch.
# (Plan, subscription and billing live in platform tables, excluded above.)
SCHOOL_ROW_EXCLUDED = frozenset({
    "id", "code", "slug", "status", "is_active", "auth_epoch", "blocked_message",
    "smtp_host", "smtp_port", "smtp_username", "smtp_password_encrypted",
    "smtp_use_tls", "smtp_from_name", "smtp_from_email", "created_at",
})

# The school-row fields a package carries and a restore may write: exactly
# what the school admin can already change on the settings page (minus the
# SMTP credentials). An allowlist, not a denylist: a package is a file the
# admin can edit, so nothing else may ride in on it (security review).
SCHOOL_ROW_RESTORABLE = frozenset({
    "name", "phone", "address", "email", "website", "legal_name_ar", "legal_name_en",
    "license_number", "tax_number", "logo_url", "attendance_mode", "default_tax_rate", "currency",
    "currency_symbol", "fiscal_year_start_month", "invoice_prefix", "invoice_start_number",
    "rounding_policy", "invoice_header_text", "invoice_footer_text", "invoice_policy_text",
    "show_logo_on_prints", "reminder_days_before", "notify_channels",
})

MIN_PASSPHRASE = 12
DEFAULT_MAX_MB = 2048


class BackupError(Exception):
    """A package that can't be made, opened or trusted. The message is
    safe to show (no data, no paths outside the package)."""


# ─── what goes in ───────────────────────────────────────────────────

def _platform_tables() -> frozenset:
    from .tenant_guard import PLATFORM_TABLES
    return PLATFORM_TABLES


def backup_tables():
    """Every table a school owns, parents before children."""
    skip = _platform_tables() | set(BACKUP_EXCLUDED) | {"schools"}
    return [t for t in db.metadata.sorted_tables if "school_id" in t.c and t.name not in skip]


def unclassified_tables() -> list[str]:
    """school_id tables that are neither backed up nor excluded with a
    reason (the coverage test keeps this empty)."""
    known = {t.name for t in backup_tables()} | set(BACKUP_EXCLUDED) | _platform_tables() | {"schools"}
    return sorted(t.name for t in db.metadata.sorted_tables if "school_id" in t.c and t.name not in known)


def _row_filter(table):
    """Rows of a backed-up table that still stay out (none but platform
    support accounts, which the platform creates per support session)."""
    if table.name == "users" and "is_platform_support" in table.c:
        return table.c.is_platform_support.is_(False)
    return None


def max_bytes() -> int:
    return int(current_app.config.get("SCHOOL_BACKUP_MAX_MB") or DEFAULT_MAX_MB) * 1024 * 1024


def max_unpacked_bytes() -> int:
    """Cap on a package's UNCOMPRESSED size (a small file must not unpack
    into gigabytes): SCHOOL_BACKUP_MAX_UNPACKED_MB, default 4 x the cap."""
    mb = current_app.config.get("SCHOOL_BACKUP_MAX_UNPACKED_MB")
    return int(mb) * 1024 * 1024 if mb else 4 * max_bytes()


def current_revision(conn=None) -> Optional[str]:
    """The database's migration revision (None on a create_all test DB).
    Checked first: a failed SELECT would abort a Postgres transaction."""
    from sqlalchemy import inspect
    c = conn if conn is not None else db.session.connection()
    if not inspect(c).has_table("alembic_version"):
        return None
    return c.execute(text("SELECT version_num FROM alembic_version")).scalar()


def known_revisions() -> Optional[set]:
    """Every revision this code knows (None when migrations aren't found)."""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        root = Path(current_app.root_path).parent / "migrations"
        cfg = Config()
        cfg.set_main_option("script_location", str(root))
        return {r.revision for r in ScriptDirectory.from_config(cfg).walk_revisions()}
    except Exception:                        # noqa: BLE001
        return None


# ─── COPY text format ───────────────────────────────────────────────

def _copy_value(v) -> str:
    if v is None:
        return r"\N"
    if isinstance(v, bool):
        return "t" if v else "f"
    if isinstance(v, (bytes, bytearray, memoryview)):
        return "\\\\x" + bytes(v).hex()
    if isinstance(v, datetime):
        s = v.isoformat(sep=" ")
    elif isinstance(v, date):
        s = v.isoformat()
    elif isinstance(v, (dict, list)):
        s = json.dumps(v, ensure_ascii=False, sort_keys=True)
    elif isinstance(v, Decimal):
        s = format(v, "f")
    else:
        s = str(v)
    return (s.replace("\\", "\\\\").replace("\t", "\\t")
             .replace("\n", "\\n").replace("\r", "\\r"))


def copy_line(values: Iterable) -> str:
    return "\t".join(_copy_value(v) for v in values) + "\n"


def parse_copy_line(line: str) -> list[Optional[str]]:
    """One COPY text line back to raw strings (None for \\N)."""
    out = []
    for raw in line.rstrip("\n").split("\t"):
        if raw == r"\N":
            out.append(None)
            continue
        buf, i = [], 0
        while i < len(raw):
            ch = raw[i]
            if ch == "\\" and i + 1 < len(raw):
                nxt = raw[i + 1]
                buf.append({"t": "\t", "n": "\n", "r": "\r", "\\": "\\"}.get(nxt, nxt))
                i += 2
            else:
                buf.append(ch)
                i += 1
        out.append("".join(buf))
    return out


# ─── export ─────────────────────────────────────────────────────────

def backups_root() -> Path:
    root = Path(current_app.config.get("SCHOOL_BACKUP_DIR")
                or Path(current_app.instance_path) / "school_backups")
    root.mkdir(parents=True, exist_ok=True)
    return root


def backups_dir(school_id: int) -> Path:
    d = backups_root() / str(int(school_id))
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _snapshot_conn():
    """One connection, one transaction, one instant."""
    conn = db.engine.connect()
    if conn.dialect.name == "postgresql":
        conn = conn.execution_options(isolation_level="REPEATABLE READ")
        conn.begin()
        conn.execute(text("SET TRANSACTION READ ONLY"))
    else:
        conn.begin()
    return conn


def _table_bytes(conn, table, school_id) -> tuple[bytes, int, list[str]]:
    cols = backup_columns(table)
    cond = table.c.school_id == school_id
    extra = _row_filter(table)
    if extra is not None:
        cond = cond & extra
    order = list(table.primary_key.columns) or cols[:1]
    buf = io.StringIO()
    n = 0
    for row in conn.execute(select(*cols).where(cond).order_by(*order)):
        buf.write(copy_line(row))
        n += 1
    return buf.getvalue().encode("utf-8"), n, [c.name for c in cols]


def _school_json(conn, school_id) -> dict:
    from ..models import School
    t = School.__table__
    cols = [c for c in t.c if c.name in SCHOOL_ROW_RESTORABLE and c.name not in SCHOOL_ROW_EXCLUDED]
    r = conn.execute(select(*cols).where(t.c.id == school_id)).first()
    if r is None:
        raise BackupError("المدرسة غير موجودة.")
    return {c.name: (v.isoformat() if hasattr(v, "isoformat") else
                     (format(v, "f") if isinstance(v, Decimal) else v)) for c, v in zip(cols, r)}


def _add_bytes(tar: tarfile.TarFile, name: str, data: bytes, mtime: int) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mtime = mtime
    info.mode = 0o600
    tar.addfile(info, io.BytesIO(data))


@dataclass
class ExportResult:
    path: Path
    manifest: dict
    bytes: int


def export_school(school_id: int, out_path: Optional[Path] = None, *,
                  progress: Optional[Callable[[int, int, str], None]] = None,
                  user=None) -> ExportResult:
    """Write the package (unencrypted .tar.gz, mode 600). Never inside a
    web request — CLI or the job queue."""
    from ..models import School
    from .school_export import school_files
    from .platform_scope import platform_read_scope
    school = db.session.get(School, school_id)
    if school is None:
        raise BackupError("المدرسة غير موجودة.")
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    out_path = Path(out_path or backups_dir(school.id)
                    / f"{school.slug}-{school.id}-{stamp}-{secrets.token_hex(3)}.tar.gz")
    tables = backup_tables()
    files = school_files(school.id)     # symlinks out of the folder are skipped
    total = len(tables) + len(files)
    mtime = int(now.timestamp())
    limit = max_bytes()
    manifest = {
        "format": FORMAT, "schema_version": SCHEMA_VERSION,
        "alembic_version": None, "school_id": school.id, "slug": school.slug, "name": school.name,
        "created_at": now.isoformat(), "tables": {}, "files": [],
    }
    checksums: list[tuple[str, str]] = []
    fd = os.open(out_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "wb") as raw, tarfile.open(fileobj=raw, mode="w:gz") as tar, \
                platform_read_scope("school_backup_read", user, school_id=school.id):
            conn = _snapshot_conn()
            try:
                manifest["alembic_version"] = current_revision(conn)
                sj = json.dumps(_school_json(conn, school.id), ensure_ascii=False, indent=1,
                                sort_keys=True).encode("utf-8")
                _add_bytes(tar, "school.json", sj, mtime)
                checksums.append(("school.json", _sha(sj)))
                done = 0
                for t in tables:
                    data, n, cols = _table_bytes(conn, t, school.id)
                    name = f"data/{t.name}.copy"
                    _add_bytes(tar, name, data, mtime)
                    digest = _sha(data)
                    manifest["tables"][t.name] = {"rows": n, "columns": cols, "sha256": digest}
                    checksums.append((name, digest))
                    done += 1
                    if progress:
                        progress(done, total, t.name)
                    if raw.tell() > limit:
                        raise BackupError("حجم النسخة تجاوز الحد المسموح.")
            finally:
                conn.rollback()
                conn.close()
            for f, rel in files:
                name = f"files/{rel}"
                info = tar.gettarinfo(str(f), arcname=name)
                info.mode, info.uid, info.gid, info.uname, info.gname = 0o600, 0, 0, "", ""
                with open(f, "rb") as fh:
                    tar.addfile(info, fh)
                digest = _file_sha(f)
                manifest["files"].append({"path": rel, "bytes": info.size, "sha256": digest})
                checksums.append((name, digest))
                done += 1
                if progress:
                    progress(done, total, rel)
                if raw.tell() > limit:
                    raise BackupError("حجم النسخة تجاوز الحد المسموح.")
            mj = json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8")
            _add_bytes(tar, "manifest.json", mj, mtime)
            checksums.append(("manifest.json", _sha(mj)))
            sums = "".join(f"{h}  {n}\n" for n, h in checksums).encode("utf-8")
            _add_bytes(tar, "checksums.sha256", sums, mtime)
    except BaseException:
        out_path.unlink(missing_ok=True)
        raise
    return ExportResult(path=out_path, manifest=manifest, bytes=out_path.stat().st_size)


# ─── encryption ─────────────────────────────────────────────────────
#
#   MAGIC (8) | scrypt n_log2 (1) r (1) p (1) | salt (16) | nonce prefix (8)
#   then chunks: length (4, big endian) | AES-256-GCM(chunk) (len + 16 tag)
#   chunk i nonce = prefix + i (4 bytes BE); AAD = header + i + last-flag,
#   so a reordered, dropped or truncated chunk fails authentication.

MAGIC = b"MNSTBK1\x00"
_CHUNK = 1 << 20
_SCRYPT = (15, 8, 1)          # n = 2**15 (~32 MB, ~0.1 s), r, p


def is_encrypted(path) -> bool:
    with open(path, "rb") as fh:
        return fh.read(len(MAGIC)) == MAGIC


def _key(passphrase: str, salt: bytes, n_log2: int, r: int, p: int) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    return Scrypt(salt=salt, length=32, n=2 ** n_log2, r=r, p=p).derive(passphrase.encode("utf-8"))


def check_passphrase(passphrase: str) -> None:
    if not passphrase or len(passphrase) < MIN_PASSPHRASE:
        raise BackupError(f"كلمة مرور التشفير لازم تكون {MIN_PASSPHRASE} حرف على الأقل.")


def encrypt_file(src, dst, passphrase: str) -> None:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    check_passphrase(passphrase)
    n_log2, r, p = _SCRYPT
    salt, prefix = secrets.token_bytes(16), secrets.token_bytes(8)
    header = MAGIC + bytes([n_log2, r, p]) + salt + prefix
    aes = AESGCM(_key(passphrase, salt, n_log2, r, p))
    fd = os.open(dst, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with open(src, "rb") as fin, os.fdopen(fd, "wb") as fout:
            fout.write(header)
            i = 0
            chunk = fin.read(_CHUNK)
            while True:
                nxt = fin.read(_CHUNK)
                last = not nxt
                aad = header + struct.pack(">IB", i, int(last))
                ct = aes.encrypt(prefix + struct.pack(">I", i), chunk, aad)
                fout.write(struct.pack(">I", len(ct)) + ct)
                if last:
                    break
                chunk, i = nxt, i + 1
    except BaseException:
        Path(dst).unlink(missing_ok=True)
        raise


_BAD_PASS = "تعذّر فتح النسخة: كلمة المرور غير صحيحة أو الملف تالف."


def decrypt_file(src, dst, passphrase: str) -> None:
    """Raises BackupError with one generic message for a wrong passphrase
    and for a damaged / truncated file alike (no oracle)."""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    fd = os.open(dst, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with open(src, "rb") as fin, os.fdopen(fd, "wb") as fout:
            header = fin.read(len(MAGIC) + 3 + 16 + 8)
            if len(header) != len(MAGIC) + 27 or header[:len(MAGIC)] != MAGIC:
                raise BackupError(_BAD_PASS)
            n_log2, r, p = header[8], header[9], header[10]
            if not (10 <= n_log2 <= 20 and 1 <= r <= 16 and 1 <= p <= 4):
                raise BackupError(_BAD_PASS)
            salt, prefix = header[11:27], header[27:35]
            aes = AESGCM(_key(passphrase or "", salt, n_log2, r, p))
            i, saw_last = 0, False
            while True:
                head = fin.read(4)
                if not head:
                    break
                if saw_last or len(head) != 4:
                    raise BackupError(_BAD_PASS)
                (size,) = struct.unpack(">I", head)
                if size > _CHUNK + 16:
                    raise BackupError(_BAD_PASS)
                ct = fin.read(size)
                if len(ct) != size:
                    raise BackupError(_BAD_PASS)
                pos = fin.tell()
                saw_last = not fin.read(1)
                fin.seek(pos)
                aad = header + struct.pack(">IB", i, int(saw_last))
                try:
                    fout.write(aes.decrypt(prefix + struct.pack(">I", i), ct, aad))
                except InvalidTag:
                    raise BackupError(_BAD_PASS) from None
                i += 1
            if not saw_last:
                raise BackupError(_BAD_PASS)
    except BaseException:
        Path(dst).unlink(missing_ok=True)
        raise


# ─── verify ─────────────────────────────────────────────────────────

@dataclass
class VerifyReport:
    ok: bool
    problems: list = field(default_factory=list)
    school_id: Optional[int] = None
    slug: Optional[str] = None
    name: Optional[str] = None
    created_at: Optional[str] = None
    alembic_version: Optional[str] = None
    tables: dict = field(default_factory=dict)     # name -> rows
    files: int = 0

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in ("ok", "problems", "school_id", "slug", "name", "created_at",
                                              "alembic_version", "tables", "files")}


def _safe_members(tar: tarfile.TarFile) -> dict[str, tarfile.TarInfo]:
    out = {}
    for m in tar.getmembers():
        name = m.name
        if (not m.isfile() or name.startswith(("/", "\\")) or "\\" in name or ":" in name
                or any(part in ("", ".", "..") for part in name.split("/"))):
            raise BackupError("الحزمة فيها مسار غير مسموح.")
        if name in out:
            raise BackupError("الحزمة فيها ملف مكرر.")
        out[name] = m
    return out


def _member_sha(tar, m) -> str:
    h = hashlib.sha256()
    fh = tar.extractfile(m)
    for chunk in iter(lambda: fh.read(1 << 20), b""):
        h.update(chunk)
    return h.hexdigest()


def verify_package(path, passphrase: Optional[str] = None, *,
                   expect_school_id: Optional[int] = None) -> VerifyReport:
    """Check a package end to end; nothing is written to the database.
    An encrypted package needs its passphrase (decrypted to a private
    temp file that is always removed)."""
    path = Path(path)
    if not path.is_file():
        return VerifyReport(ok=False, problems=["الملف غير موجود."])
    if path.stat().st_size > max_bytes() + 1024 * 1024:
        return VerifyReport(ok=False, problems=["حجم الملف أكبر من الحد المسموح."])
    tmpdir = None
    try:
        if is_encrypted(path):
            tmpdir = Path(tempfile.mkdtemp(prefix="mnst-verify-"))
            plain = tmpdir / "package.tar.gz"
            decrypt_file(path, plain, passphrase or "")
            path = plain
        return _verify_plain(path, expect_school_id)
    except BackupError as e:
        return VerifyReport(ok=False, problems=[str(e)])
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


def _verify_plain(path: Path, expect_school_id: Optional[int]) -> VerifyReport:
    try:
        tar = tarfile.open(path, mode="r:gz")
    except (tarfile.TarError, OSError, EOFError):
        raise BackupError("الملف مش حزمة نسخة احتياطية صالحة.") from None
    with tar:
        try:
            members = _safe_members(tar)
        except (tarfile.TarError, EOFError, OSError):
            raise BackupError("الملف مش حزمة نسخة احتياطية صالحة.") from None
        if sum(m.size for m in members.values()) > max_unpacked_bytes():
            raise BackupError("محتوى الحزمة بعد فك الضغط أكبر من الحد المسموح.")
        for need in ("manifest.json", "checksums.sha256", "school.json"):
            if need not in members:
                raise BackupError("الحزمة ناقصة (manifest / checksums).")
        problems: list[str] = []
        sums = {}
        for line in tar.extractfile(members["checksums.sha256"]).read().decode("utf-8").splitlines():
            if not line.strip():
                continue
            digest, _, name = line.partition("  ")
            sums[name] = digest
        listed = set(members) - {"checksums.sha256"}
        if set(sums) != listed:
            problems.append("قائمة الـ checksums لا تطابق محتوى الحزمة.")
        try:
            for name in sorted(listed & set(sums)):
                if _member_sha(tar, members[name]) != sums[name]:
                    problems.append(f"checksum غير مطابق: {name}")
        except (tarfile.TarError, EOFError, OSError, zlib.error):
            raise BackupError("الملف مش حزمة نسخة احتياطية صالحة.") from None
        try:
            manifest = json.loads(tar.extractfile(members["manifest.json"]).read())
        except ValueError:
            raise BackupError("manifest غير صالح.") from None
        rep = VerifyReport(ok=False, school_id=manifest.get("school_id"), slug=manifest.get("slug"),
                           name=manifest.get("name"), created_at=manifest.get("created_at"),
                           alembic_version=manifest.get("alembic_version"),
                           files=len(manifest.get("files") or []))
        if problems:                        # tampered: report it, read nothing else from it
            rep.problems = problems
            return rep
        _check_manifest(tar, members, manifest, rep, expect_school_id)
        rep.ok = not rep.problems
        return rep


def _check_manifest(tar, members, manifest, rep: VerifyReport, expect_school_id) -> None:
    problems = rep.problems
    if manifest.get("format") != FORMAT:
        problems.append("الملف مش نسخة احتياطية من منصتي.")
        return
    if manifest.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
        problems.append("إصدار صيغة الحزمة غير مدعوم.")
        return
    sid = manifest.get("school_id")
    if not isinstance(sid, int):
        problems.append("الحزمة بدون مدرسة.")
        return
    if expect_school_id is not None and sid != int(expect_school_id):
        problems.append("الحزمة تخص مدرسة أخرى.")
        return
    try:
        school_keys = set(json.loads(tar.extractfile(members["school.json"]).read()))
    except (ValueError, TypeError):
        problems.append("school.json غير صالح.")
        return
    if school_keys - SCHOOL_ROW_RESTORABLE:
        problems.append("school.json فيه حقول غير مسموحة: " + ", ".join(sorted(school_keys - SCHOOL_ROW_RESTORABLE)[:5]))
        return
    rev = manifest.get("alembic_version")
    known = known_revisions()
    if rev and known is not None and rev not in known:
        problems.append("الحزمة من إصدار أحدث من النظام الحالي.")
        return
    allowed = {t.name: t for t in backup_tables()}
    tables = manifest.get("tables") or {}
    data_members = {n for n in members if n.startswith("data/")}
    if data_members != {f"data/{n}.copy" for n in tables}:
        problems.append("ملفات البيانات لا تطابق الـ manifest.")
        return
    for name, meta in sorted(tables.items()):
        table = allowed.get(name)
        if table is None:
            problems.append(f"جدول غير مسموح: {name}")
            continue
        cols = meta.get("columns") or []
        allowed_cols = {c.name for c in backup_columns(table)}
        unknown = [c for c in cols if c not in allowed_cols]      # secrets / unknown columns
        if unknown or "school_id" not in cols:
            problems.append(f"أعمدة غير معروفة في {name}")
            continue
        sid_at = cols.index("school_id")
        # A real export never carries platform support accounts.
        support_at = cols.index("is_platform_support") if name == "users" and "is_platform_support" in cols else None
        n = 0
        fh = io.TextIOWrapper(tar.extractfile(members[f"data/{name}.copy"]), encoding="utf-8", newline="\n")
        for line in fh:
            vals = parse_copy_line(line)
            if len(vals) != len(cols):
                problems.append(f"صف غير صالح في {name}")
                break
            if vals[sid_at] != str(sid):
                # One foreign row refuses the whole package (never skipped).
                problems.append(f"صف يخص مدرسة أخرى في {name}")
                break
            if support_at is not None and vals[support_at] == "t":
                problems.append("الحزمة فيها حساب دعم من المنصة")
                break
            n += 1
        else:
            if n != meta.get("rows"):
                problems.append(f"عدد الصفوف في {name} لا يطابق الـ manifest")
        rep.tables[name] = n
    file_members = {n[len("files/"):] for n in members if n.startswith("files/")}
    listed = {f.get("path") for f in manifest.get("files") or []}
    if file_members != listed:
        problems.append("الملفات المرفوعة لا تطابق الـ manifest.")


# ─── jobs ───────────────────────────────────────────────────────────

def run_backup_job(job) -> None:
    """Process one queued `school_backup` PlatformJob (server CLI only)."""
    job.status, job.started_at = "running", datetime.now(timezone.utc)
    job.result = {"progress": 0}
    db.session.commit()

    def progress(done, total, _what):
        job.result = {**(job.result or {}), "progress": int(done * 100 / max(total, 1))}
        db.session.commit()
    try:
        res = export_school(job.school_id, progress=progress)
        job.status = "succeeded"
        job.result = {"progress": 100, "file": res.path.name, "bytes": res.bytes,
                      "tables": len(res.manifest["tables"]), "files": len(res.manifest["files"])}
    except Exception as e:                   # noqa: BLE001 — the job records the failure type only
        db.session.rollback()
        job.status = "failed"
        job.result = {**(job.result or {}),
                      "error": str(e) if isinstance(e, BackupError) else type(e).__name__}
    job.finished_at = datetime.now(timezone.utc)
    db.session.commit()


def run_backup_queue(limit: int = 10) -> int:
    from ..models import PlatformJob
    jobs = (PlatformJob.query.filter_by(kind="school_backup", status="pending")
            .order_by(PlatformJob.id).limit(limit).all())
    for job in jobs:
        run_backup_job(job)
    return len(jobs)
