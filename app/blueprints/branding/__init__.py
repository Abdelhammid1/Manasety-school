"""The school's logo, without login (the sign-in page shows it).

GET /branding/logo — the school comes from the request's host only
(g.tenant_resolved; with resolution off, the signed-in user's school):
never from the URL. Only that school's own stored logo is served; no
logo, an old external URL, the platform host or an unknown host → the
Manasety logo. Every other upload keeps its login (files.download).
`?v=` is the logo's version (services/branding.logo_version): a new
upload changes the address, so the long cache never shows a stale logo.
"""

from __future__ import annotations

import mimetypes

from flask import Blueprint, current_app, g, request, send_file, send_from_directory
from flask_login import current_user

bp = Blueprint("branding", __name__)

_DEFAULT = "img/logo.svg"


def _school():
    resolved = getattr(g, "tenant_resolved", None)
    if resolved is not None:
        return resolved.school if resolved.kind == "tenant" else None
    if getattr(current_user, "is_authenticated", False) and not getattr(current_user, "is_platform_user", False):
        from ...extensions import db
        from ...models import School
        return db.session.get(School, current_user.school_id)
    return None


def _headers(resp, *, versioned: bool):
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable" if versioned else "public, max-age=300"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    resp.headers["Cross-Origin-Resource-Policy"] = "same-site"
    return resp


@bp.route("/branding/logo", endpoint="logo")
def logo():
    from ...services import branding
    from ...services.file_storage import key_from_url, parse_key
    school = _school()
    if school is not None and branding.has_own_logo(school):
        fk = parse_key(key_from_url(school.logo_url) or "")
        if fk is not None and fk.school_id == school.id and fk.kind == "logo":
            mime = mimetypes.guess_type(fk.path.name)[0] or "application/octet-stream"
            resp = send_file(fk.path, mimetype=mime, conditional=True)
            return _headers(resp, versioned=request.args.get("v") == branding.logo_version(school))
    resp = send_from_directory(current_app.static_folder or "static", _DEFAULT, mimetype="image/svg+xml",
                               conditional=True)
    return _headers(resp, versioned=False)
