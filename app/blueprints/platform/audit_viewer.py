"""Ticket T6 — AuditLog viewer.

Filters (user, entity_type, action, date range), pagination, per-row
diff of old_value vs new_value (JSON keys), and CSV export."""

import csv
import io
from datetime import datetime, time

from flask import (
    Response, render_template, request,
)
from flask_login import current_user, login_required

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import AuditLog, User


def _sid():
    return current_user.school_id


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _base_query():
    """Every query the viewer runs starts from this — school scope +
    parsed filters. Returns (query, filter_dict) so the template can
    echo the current selection back."""
    q = AuditLog.query.filter_by(school_id=_sid())

    filters = {
        "user_id":     request.args.get("user_id", type=int),
        "entity_type": (request.args.get("entity_type") or "").strip(),
        "action":      (request.args.get("action") or "").strip(),
        "start":       _parse_date(request.args.get("start")),
        "end":         _parse_date(request.args.get("end")),
        "q":           (request.args.get("q") or "").strip(),
    }
    if filters["user_id"]:
        q = q.filter(AuditLog.user_id == filters["user_id"])
    if filters["entity_type"]:
        q = q.filter(AuditLog.entity_type == filters["entity_type"])
    if filters["action"]:
        q = q.filter(AuditLog.action == filters["action"])
    if filters["start"]:
        q = q.filter(
            AuditLog.created_at >= datetime.combine(filters["start"], time.min),
        )
    if filters["end"]:
        q = q.filter(
            AuditLog.created_at <= datetime.combine(filters["end"], time.max),
        )
    return q, filters


@bp.route("/audit-log", endpoint="audit_log_viewer")
@login_required
@require_permission("platform_admin", "view")
def audit_log_viewer():
    q, filters = _base_query()
    page = max(1, request.args.get("page", type=int) or 1)
    per_page = 50
    total = q.count()
    rows = (
        q.order_by(AuditLog.created_at.desc())
        .offset((page - 1) * per_page).limit(per_page)
        .all()
    )
    # Compute per-row diff (only the keys whose values differ).
    row_diffs = []
    for r in rows:
        row_diffs.append({
            "row":  r,
            "diff": _compute_diff(r.old_value or {}, r.new_value or {}),
        })

    # Filter dropdown data.
    users = (
        User.query.filter_by(school_id=_sid())
        .order_by(User.full_name).all()
    )
    entity_types = [
        et for (et,) in db.session.query(AuditLog.entity_type)
        .filter(AuditLog.school_id == _sid())
        .distinct().order_by(AuditLog.entity_type).all()
    ]
    return render_template(
        "platform/audit_log_viewer.html",
        row_diffs=row_diffs, filters=filters,
        users=users, entity_types=entity_types,
        page=page, per_page=per_page, total=total,
        pages=(total + per_page - 1) // per_page,
    )


@bp.route("/audit-log/export.csv", endpoint="audit_log_export")
@login_required
@require_permission("platform_admin", "view")
def audit_log_export():
    q, filters = _base_query()
    rows = q.order_by(AuditLog.created_at.desc()).all()
    buf = io.StringIO()
    buf.write("﻿")   # BOM so Excel opens as UTF-8
    w = csv.writer(buf)
    w.writerow(["id", "created_at", "user", "action",
                "entity_type", "entity_id",
                "old_value", "new_value",
                "ip_address", "user_agent"])
    for r in rows:
        w.writerow([
            r.id,
            r.created_at.isoformat() if r.created_at else "",
            (r.user.full_name if r.user else ""),
            r.action, r.entity_type, r.entity_id or "",
            _json_str(r.old_value), _json_str(r.new_value),
            r.ip_address or "", (r.user_agent or "")[:200],
        ])
    fname = f"audit_log_{(filters['start'] or '')}_{(filters['end'] or '')}.csv"
    return Response(
        buf.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


def _compute_diff(old, new):
    """Return {field: (old_val, new_val)} for keys whose values differ.
    Handles missing keys on either side (create → old empty; delete →
    new empty)."""
    if not isinstance(old, dict):
        old = {}
    if not isinstance(new, dict):
        new = {}
    keys = set(old.keys()) | set(new.keys())
    out = {}
    for k in sorted(keys):
        ov = old.get(k)
        nv = new.get(k)
        if ov != nv:
            out[k] = (ov, nv)
    return out


def _json_str(v):
    import json
    try:
        return json.dumps(v, ensure_ascii=False) if v is not None else ""
    except (TypeError, ValueError):
        return str(v)
