"""JWT helpers for the mobile API.

Used by /api/* endpoints. Web routes keep using Flask-Login + session cookies.
"""
from datetime import datetime, timedelta
from functools import wraps
from typing import Optional

import jwt
from flask import current_app, g, jsonify, request

from ..extensions import db
from ..models import User


def issue_token(user: User, ttl_hours: int = 24) -> str:
    payload = {
        "sub": user.id,
        "school": user.school_id,
        "exp": datetime.utcnow() + timedelta(hours=ttl_hours),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, current_app.config["SECRET_KEY"], algorithms=["HS256"])
    except jwt.InvalidTokenError:
        return None


def jwt_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        token = header[7:] if header.startswith("Bearer ") else ""
        payload = decode_token(token) if token else None
        if not payload:
            return jsonify({"error": "unauthorized"}), 401
        user = db.session.get(User, payload["sub"])
        if not user or not user.is_active:
            return jsonify({"error": "unauthorized"}), 401
        g.api_user = user
        return view(*args, **kwargs)
    return wrapped
