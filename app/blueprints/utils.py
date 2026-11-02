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
                # BUG-008 — leave a trace of a refused attempt (no request data)
                from flask import current_app, request
                current_app.logger.warning(
                    "permission denied: user=%s school=%s needs %s.%s at %s %s",
                    current_user.id, getattr(current_user, "school_id", None),
                    module, action, request.method, request.path)
                abort(403)
            return view(*args, **kwargs)
        # read by can_open() — what a link shows and what the route lets in
        # come from this one declaration
        wrapped.required_permissions = getattr(view, "required_permissions", ()) + ((module, action),)
        return wrapped
    return decorator


# {blueprint name: fn(endpoint) -> bool} — a blueprint-wide guard
# (before_request) that can_open() must honour too.
BLUEPRINT_GATES = {}


def can_open(endpoint: str) -> bool:
    """Would this user get past the route's own permission checks? For
    showing a link: a page they'd get 403 on isn't offered. Doesn't replace
    the route's checks, and knows only the declared ones (a route with a
    check of its own in the body needs that condition at the link)."""
    from flask import current_app
    view = current_app.view_functions.get(endpoint)
    if view is None or not current_user.is_authenticated:
        return False
    if getattr(view, "admin_only", False):
        if getattr(getattr(current_user, "role", None), "name", None) != "admin":
            return False
    if not all(current_user.can(m, a) for m, a in getattr(view, "required_permissions", ())):
        return False
    gate = BLUEPRINT_GATES.get(endpoint.split(".", 1)[0])
    return gate(endpoint) if gate else True


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
    wrapped.admin_only = True
    return wrapped
