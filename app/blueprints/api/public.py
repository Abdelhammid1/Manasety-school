"""SAAS-037 — public, unauthenticated API for the mobile apps.

GET /api/public/school-info  — what the "enter your school code" screen
    shows before login: name, logo, access state, support contacts.
    Answers for a blocked school too (state = blocked) so the app can
    show a clear message; unknown / archived host → 404.
GET /api/public/app-config   — minimum app version per app.

Every /api request that carries X-App-Version (+ X-App-Name) older than
that app's minimum gets 426 {"error": "upgrade_required"}. Requests
without the header are not checked (no published app sends it yet).

Contract: docs/api-error-codes.md (tests/test_saas037_api_contract.py).
"""
from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict, deque

from flask import abort, g, jsonify, request

from . import bp

API_VERSION = "1"
APPS = ("student", "teacher", "parent")
PUBLIC_ENDPOINTS = frozenset({"api.public_school_info", "api.public_app_config"})

# Per-IP, per-process: enough to stop the endpoint being a slug
# enumeration tool (nginx can add a global limit on top).
SCHOOL_INFO_PER_MINUTE = 20
MAX_TRACKED_IPS = 10_000
_hits: "OrderedDict[str, deque]" = OrderedDict()
_hits_lock = threading.Lock()

UPGRADE_MESSAGE_AR = "نسخة التطبيق قديمة. حدّث التطبيق من المتجر للمتابعة."

_VERSION_RE = re.compile(r"^\d{1,4}(\.\d{1,4}){0,3}$")


def _rate_limited(ip: str) -> bool:
    now = time.monotonic()
    with _hits_lock:
        key = ip or "-"
        q = _hits.get(key)
        if q is None:
            q = _hits[key] = deque()
        _hits.move_to_end(key)           # least recently seen first
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= SCHOOL_INFO_PER_MINUTE:
            return True
        q.append(now)
        # Hard cap: the table never passes MAX_TRACKED_IPS. Dropping the
        # least recently seen IP only forgets a window older than the
        # rest (security review: emptiness-based eviction never fired).
        while len(_hits) > MAX_TRACKED_IPS:
            _hits.popitem(last=False)
    return False


def _version_tuple(v: str | None) -> tuple[int, ...] | None:
    v = (v or "").strip()
    if not _VERSION_RE.match(v):
        return None
    parts = tuple(int(p) for p in v.split("."))
    return parts + (0,) * (4 - len(parts))


def valid_version(v: str | None) -> bool:
    return _version_tuple(v) is not None


def min_versions(settings: dict | None = None) -> dict[str, str | None]:
    from ...services.tenancy import _request_settings
    settings = settings if settings is not None else _request_settings()
    out = {}
    for app_name in APPS:
        v = (settings.get(f"min_app_version_{app_name}") or "").strip()
        out[app_name] = v if _version_tuple(v) else None
    return out


def upgrade_refusal():
    """(json, 426) when the calling app is older than its minimum."""
    sent = request.headers.get("X-App-Version")
    if sent is None or request.endpoint in PUBLIC_ENDPOINTS:
        return None
    app_name = (request.headers.get("X-App-Name") or "").strip().lower()
    minimum = min_versions().get(app_name)
    if minimum is None:
        return None
    have = _version_tuple(sent)
    if have is not None and have >= (_version_tuple(minimum) or ()):
        return None
    return jsonify({"error": "upgrade_required", "app": app_name, "min_version": minimum,
                    "message_ar": UPGRADE_MESSAGE_AR}), 426


@bp.before_request
def _app_version_gate():
    return upgrade_refusal()


def _state(resolved):
    from ...services.subscription_enforcement import MESSAGES_AR
    if resolved.blocked:
        sub = getattr(resolved, "subscription", None)
        reason = sub.state if sub is not None else "suspended"
        return "blocked", reason, MESSAGES_AR.get(reason, MESSAGES_AR["suspended"])
    if resolved.read_only:
        return "read_only", "grace", MESSAGES_AR["read_only"]
    return "ok", None, ""


def _logo(school, state: str):
    # A blocked school's /files/ answer 404 (SAAS-027), so a link would
    # not load anyway.
    if state == "blocked" or not school.logo_url:
        return None
    from ...services import file_storage as fs
    from ...services.tenancy import tenant_context
    with tenant_context(school.id):
        return fs.signed_url(school.logo_url, "logo", school.id, ttl_seconds=600)


@bp.route("/public/school-info", methods=["GET"], endpoint="public_school_info")
def public_school_info():
    resolved = getattr(g, "tenant_resolved", None)
    if resolved is None or resolved.school is None or \
            resolved.kind not in ("tenant", "suspended", "blocked"):
        abort(404)
    if _rate_limited(request.remote_addr or ""):
        return jsonify({"error": "rate_limited", "message_ar": "محاولات كثيرة، انتظر دقيقة."}), 429
    from ...services.tenancy import _request_settings
    settings = _request_settings()
    school = resolved.school
    state, reason, message = _state(resolved)
    r = jsonify({
        "name_ar": school.name,
        "logo_url": _logo(school, state),
        "state": state,
        "reason": reason,
        "message_ar": message,
        "api_version": API_VERSION,
        "support": {"email": settings.get("support_email") or "",
                    "phone": settings.get("support_phone") or ""},
    })
    r.headers["Cache-Control"] = "no-store"
    return r


@bp.route("/public/app-config", methods=["GET"], endpoint="public_app_config")
def public_app_config():
    resolved = getattr(g, "tenant_resolved", None)
    if resolved is None or resolved.school is None or \
            resolved.kind not in ("tenant", "suspended", "blocked"):
        abort(404)
    r = jsonify({"api_version": API_VERSION, "min_app_version": min_versions()})
    r.headers["Cache-Control"] = "no-store"
    return r
