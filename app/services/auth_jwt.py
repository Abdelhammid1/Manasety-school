"""JWT helpers for the mobile API.

Used by /api/* endpoints. Web routes keep using Flask-Login + session
cookies, which deliberately sign under a DIFFERENT key than this one
(see SAAS-007 and config._resolve_jwt_signing_key) so a credential
leak doesn't compromise both surfaces at once.
"""
from datetime import datetime, timedelta
from functools import wraps
from typing import Optional

import jwt
from flask import current_app, g, jsonify, request

from ..extensions import db
from ..models import User


# SAAS-007 — the key the API signs with. Separate from SECRET_KEY so a
# leak of one surface doesn't give the attacker the other. The config
# layer refuses to ship a shared/weak JWT_SIGNING_KEY in production.
def _jwt_key() -> str:
    return current_app.config.get("JWT_SIGNING_KEY") or current_app.config["SECRET_KEY"]


def issue_token(user: User, ttl_hours: int = 24) -> str:
    """Mint a JWT bound to the user's current tenant.

    `school` carries the school_id and `school_slug` carries the slug
    so the mobile client can display tenant identity without a
    separate round-trip. The slug is also what the request-time
    verifier checks against the resolved host.
    """
    # Deferred import avoids a module cycle at app factory time.
    from ..models import School
    if getattr(user, "is_platform_user", False):
        # SAAS-025 — platform users never get a mobile token.
        raise ValueError("platform users cannot receive API tokens")
    school = db.session.get(School, user.school_id) if user.school_id else None
    payload = {
        "sub": user.id,
        "school": user.school_id,
        "school_slug": school.slug if school is not None else None,
        # SAAS-027 kill switch: tokens older than the school's epoch die.
        "ae": int(getattr(school, "auth_epoch", 0) or 0) if school is not None else 0,
        "exp": datetime.utcnow() + timedelta(hours=ttl_hours),
        "iat": datetime.utcnow(),
        # `iss` ties the token to this platform; nothing else should
        # mint JWTs for /api/*.
        "iss": "manasety-api",
    }
    return jwt.encode(payload, _jwt_key(), algorithm="HS256")


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(
            token, _jwt_key(), algorithms=["HS256"],
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.InvalidTokenError:
        return None


def _tenant_mismatch(payload: dict) -> bool:
    """SAAS-007 — refuse a token whose `school` claim doesn't match the
    host-resolved tenant. Returns True when the mismatch should block
    the request.

    Modes:
      * off     — no host tenant on g.tenant_resolved → never block
                  (preserves single-tenant dev behaviour).
      * log /
        enforce — if the resolver attached a tenant AND the token's
                  `school` differs, block. The pre-existing resolver
                  takes care of unknown/suspended hosts separately;
                  this check protects the case where a legit host
                  resolves but the token was minted for a DIFFERENT
                  legit tenant.
    """
    resolved = getattr(g, "tenant_resolved", None)
    if resolved is None or resolved.kind != "tenant" or resolved.school is None:
        return False
    claim_sid = payload.get("school")
    if claim_sid is None:
        return True
    try:
        return int(claim_sid) != int(resolved.school.id)
    except (TypeError, ValueError):
        return True


def _epoch_stale(payload: dict, user) -> bool:
    """SAAS-027 — a token minted before the school's last suspend.
    Tokens from before the claim existed carry no `ae` (= 0)."""
    if user.school_id is None:
        return False
    from .subscription_enforcement import jwt_epoch_is_stale
    try:
        return jwt_epoch_is_stale(payload, user)
    except (TypeError, ValueError):
        return True


def user_from_bearer() -> Optional[User]:
    """The active user behind `Authorization: Bearer <jwt>`, after every
    check jwt_required applies (signature/expiry, active user, host
    tenant, user's own school). None when any check fails."""
    header = request.headers.get("Authorization", "")
    token = header[7:] if header.startswith("Bearer ") else ""
    payload = decode_token(token) if token else None
    if not payload or not str(payload.get("sub", "")).isdigit():
        return None
    user = db.session.get(User, int(payload["sub"]))
    if not user or not user.is_active or _tenant_mismatch(payload):
        return None
    if user.school_id is not None and payload.get("school") is not None:
        try:
            if int(user.school_id) != int(payload["school"]):
                return None
        except (TypeError, ValueError):
            return None
    if _epoch_stale(payload, user):
        return None
    return user


def jwt_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        token = header[7:] if header.startswith("Bearer ") else ""
        payload = decode_token(token) if token else None
        if not payload or not str(payload.get("sub", "")).isdigit():
            return jsonify({"error": "unauthorized"}), 401
        user = db.session.get(User, int(payload["sub"]))
        if not user or not user.is_active:
            return jsonify({"error": "unauthorized"}), 401
        # SAAS-007 — a token minted for school A must not work on
        # school B's /api/*. The host resolver already set
        # g.tenant_resolved by this point (both hooks run as
        # before_request).
        if _tenant_mismatch(payload):
            current_app.logger.warning(
                "jwt — cross-tenant replay blocked: token_school=%s "
                "host_school=%s user=%s path=%s",
                payload.get("school"),
                getattr(getattr(g, "tenant_resolved", None), "school", None)
                and g.tenant_resolved.school.id,
                user.id, request.path,
            )
            return jsonify({"error": "unauthorized"}), 401
        # Last check — the user's own school_id must match the token's
        # claim. A re-provisioned account (same user id, different
        # school) can't be impersonated by an old token.
        if user.school_id is not None and payload.get("school") is not None:
            try:
                if int(user.school_id) != int(payload["school"]):
                    return jsonify({"error": "unauthorized"}), 401
            except (TypeError, ValueError):
                return jsonify({"error": "unauthorized"}), 401
        if _epoch_stale(payload, user):
            return jsonify({"error": "unauthorized"}), 401
        g.api_user = user
        return view(*args, **kwargs)
    return wrapped
