from functools import wraps
from flask import abort
from flask_login import current_user


def require_permission(module: str, action: str = "view"):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if not current_user.can(module, action):
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def owned_id(model, raw_id):
    """`raw_id` if that row belongs to the current school, else None.
    Use on every FK id that arrives in a form / query string — a bare
    id from the client may point at another school's row."""
    if not raw_id:
        return None
    from ..services.tenancy import current_school_id
    row = model.query.filter_by(id=raw_id, school_id=current_school_id()).first()
    return row.id if row is not None else None


def admin_only(view):
    """Route gate for school-admin surfaces (dashboard, tenant settings).

    Auth model note: the app has one super-privileged role per school named
    literally `admin` — there is no cross-tenant super-admin. `current_user.role`
    is the JSON-permissioned role loaded from the DB; we compare its name.
    """
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        role = getattr(current_user, "role", None)
        role_name = getattr(role, "name", None)
        if role_name != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapped
