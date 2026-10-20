"""SAAS-011 — protected file storage.

Files live under UPLOAD_ROOT (outside app/static) at
    <UPLOAD_ROOT>/<school_id>/<kind>/<owner_id>/<uuid>_<secure_name>
and are referenced in the DB as "/files/<key>". They are served only by
the `files.download` route, which checks the school and a per-kind
access policy (app/blueprints/files). The school_id in a key always
comes from current_school_id(), never from the client.

Mobile apps open files in an external browser (no cookie, no JWT), so
API responses hand out short-lived HMAC-signed URLs via `signed_url`.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from flask import current_app
from werkzeug.utils import secure_filename

URL_PREFIX = "/files/"

_IMAGES = {"png", "jpg", "jpeg", "gif", "webp"}
_MB = 1024 * 1024


@dataclass(frozen=True)
class Kind:
    exts: frozenset
    max_bytes: int


KINDS: dict[str, Kind] = {
    "logo":            Kind(frozenset({"png", "jpg", "jpeg", "svg", "webp"}), 5 * _MB),
    "materials":       Kind(frozenset({"pdf", "jpg", "jpeg", "png"}), 10 * _MB),
    "excuse":          Kind(frozenset({"pdf", "png", "jpg", "jpeg", "webp"}), 10 * _MB),
    "lessons":         Kind(frozenset({"pdf"}), 10 * _MB),
    "submissions":     Kind(frozenset({"pdf", "doc", "docx", "zip", "txt", "mp3", "wav",
                                       "m4a", "ogg", "mp4", "webm", "mov"} | _IMAGES), 10 * _MB),
    "messages":        Kind(frozenset({"pdf"} | _IMAGES), 8 * _MB),
    "student_photo":   Kind(frozenset(_IMAGES), 5 * _MB),
    "previous_school": Kind(frozenset({"pdf", "png", "jpg", "jpeg", "webp"}), 10 * _MB),
    "student_docs":    Kind(frozenset({"pdf", "doc", "docx"} | _IMAGES), 10 * _MB),
}


class UploadRejected(ValueError):
    """Shown to the user (Arabic)."""


# ─── content sniffing ───────────────────────────────────────────────

def _sniff_ok(ext: str, head: bytes) -> bool:
    if ext == "pdf":
        return head.startswith(b"%PDF")
    if ext == "png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in ("jpg", "jpeg"):
        return head.startswith(b"\xff\xd8\xff")
    if ext == "gif":
        return head.startswith(b"GIF87a") or head.startswith(b"GIF89a")
    if ext == "webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    if ext == "wav":
        return head[:4] == b"RIFF" and head[8:12] == b"WAVE"
    if ext in ("docx", "zip"):
        return head.startswith(b"PK\x03\x04")
    if ext == "doc":
        return head.startswith(b"\xd0\xcf\x11\xe0")
    if ext in ("mp4", "m4a", "mov"):
        return head[4:8] == b"ftyp"
    if ext == "mp3":
        return head.startswith(b"ID3") or head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")
    if ext == "ogg":
        return head.startswith(b"OggS")
    if ext == "webm":
        return head.startswith(b"\x1a\x45\xdf\xa3")
    if ext == "txt":
        return b"\x00" not in head
    if ext == "svg":
        text = head.decode("utf-8", errors="ignore").lower()
        return "<svg" in text
    return False


# ─── paths ──────────────────────────────────────────────────────────

def upload_root() -> Path:
    root = current_app.config.get("UPLOAD_ROOT") or os.path.join(
        current_app.instance_path, "uploads")
    return Path(root).resolve()


def _current_school() -> int:
    from .tenancy import current_school_id
    return int(current_school_id())


def save(file, kind: str, owner_id: int) -> str:
    """Validate and store an uploaded FileStorage. Returns "/files/<key>"."""
    spec = KINDS[kind]
    if not file or not file.filename:
        raise UploadRejected("لم يتم اختيار ملف.")
    original = file.filename
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    name = secure_filename(original)
    # secure_filename drops non-ASCII (Arabic names) — keep the extension.
    if not name or not name.lower().endswith("." + ext):
        name = f"file.{ext}"
    if ext not in spec.exts:
        raise UploadRejected(f"صيغة الملف .{ext} غير مدعومة.")
    stream = file.stream
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(0)
    if size == 0:
        raise UploadRejected("الملف فارغ.")
    if size > spec.max_bytes:
        raise UploadRejected(f"حجم الملف يتجاوز {spec.max_bytes // _MB} MB.")
    head = stream.read(1024 if ext in ("svg", "txt") else 16)
    stream.seek(0)
    if not _sniff_ok(ext, head):
        raise UploadRejected(f"محتوى الملف لا يطابق الامتداد .{ext}.")

    key = f"{_current_school()}/{kind}/{int(owner_id)}/{uuid.uuid4().hex[:12]}_{name}"
    dest = upload_root() / key
    dest.parent.mkdir(parents=True, exist_ok=True)
    file.save(str(dest))
    return URL_PREFIX + key


def key_from_url(url: Optional[str]) -> Optional[str]:
    if not url or not url.startswith(URL_PREFIX):
        return None
    return url[len(URL_PREFIX):].split("?", 1)[0]


@dataclass(frozen=True)
class FileKey:
    school_id: int
    kind: str
    owner_id: int
    path: Path


def parse_key(key: str) -> Optional[FileKey]:
    """Parse and confine a key. None for anything malformed, absolute,
    traversing, of an unknown kind, or not on disk."""
    if not key or key.startswith(("/", "\\")) or "\\" in key or ":" in key:
        return None
    parts = key.split("/")
    if len(parts) != 4 or any(p in ("", ".", "..") for p in parts):
        return None
    school, kind, owner, fname = parts
    if not (school.isdigit() and owner.isdigit()) or kind not in KINDS:
        return None
    if secure_filename(fname) != fname:
        return None
    root = upload_root()
    path = (root / key).resolve()
    if root not in path.parents or not path.is_file():
        return None
    return FileKey(int(school), kind, int(owner), path)


def delete(url: Optional[str]) -> None:
    key = key_from_url(url)
    fk = parse_key(key) if key else None
    if fk is not None and fk.school_id == _current_school():
        fk.path.unlink(missing_ok=True)


# ─── signed URLs (mobile / external viewers) ────────────────────────

def _sig_key() -> bytes:
    secret = current_app.config["SECRET_KEY"]
    return hashlib.sha256(f"files-v1|{secret}".encode()).digest()


def _sign(key: str, exp: int) -> str:
    return hmac.new(_sig_key(), f"{key}|{exp}".encode(), hashlib.sha256).hexdigest()


def signed_url(url: Optional[str], ttl_seconds: int = 3600) -> Optional[str]:
    """Return `url` with ?exp=&sig= if it is a stored file; other URLs
    (external links, empty) pass through unchanged."""
    key = key_from_url(url)
    if key is None:
        return url
    exp = int(time.time()) + ttl_seconds
    return f"{URL_PREFIX}{key}?exp={exp}&sig={_sign(key, exp)}"


def signature_valid(key: str, exp: Optional[str], sig: Optional[str]) -> bool:
    if not exp or not sig or not exp.isdigit() or int(exp) < time.time():
        return False
    return hmac.compare_digest(_sign(key, int(exp)), sig)


# ─── WeasyPrint: read our own files from disk ───────────────────────

def pdf_url_fetcher(school_id: int):
    """WeasyPrint fetches images over HTTP without the user's session,
    which the protected route refuses. Serve /files/ keys of this
    school straight from disk; everything else uses the default."""
    from urllib.parse import urlparse
    from weasyprint import default_url_fetcher

    def fetch(url, *args, **kwargs):
        path = urlparse(url).path
        key = key_from_url(path)
        if key is not None:
            fk = parse_key(key)
            if fk is None or fk.school_id != school_id:
                raise ValueError("file not available")
            return {"file_obj": open(fk.path, "rb"), "filename": fk.path.name}
        return default_url_fetcher(url, *args, **kwargs)
    return fetch


# ─── one-off import of legacy /static/uploads files ─────────────────

def import_legacy_file(static_path: Path, school_id: int, kind: str, owner_id: int) -> str:
    """Copy a file that used to live under app/static into storage.
    Content and type rules are not re-applied — the file was accepted
    by the old code and is moved as-is."""
    import shutil
    name = secure_filename(static_path.name) or "file"
    key = f"{int(school_id)}/{kind}/{int(owner_id)}/{uuid.uuid4().hex[:12]}_{name}"
    dest = upload_root() / key
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(static_path, dest)
    return URL_PREFIX + key
