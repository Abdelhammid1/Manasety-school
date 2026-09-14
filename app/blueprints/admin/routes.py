from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import Role, User
from ...models.user import PERMISSION_MODULES, PERMISSION_ACTIONS


# ---------- Roles & Permissions (T-1.2) ----------

@bp.route("/roles")
@login_required
@require_permission("roles", "view")
def roles_list():
    roles = Role.query.filter_by(school_id=current_user.school_id).order_by(Role.id).all()
    return render_template("admin/roles_list.html", roles=roles)


@bp.route("/roles/new", methods=["GET", "POST"])
@login_required
@require_permission("roles", "add")
def role_new():
    if request.method == "POST":
        role = Role(
            school_id=current_user.school_id,
            name=request.form["name"].strip(),
            name_ar=request.form["name_ar"].strip(),
            permissions=_parse_permissions(request.form),
        )
        db.session.add(role)
        db.session.commit()
        flash("تم إنشاء الدور بنجاح.", "success")
        return redirect(url_for("admin.roles_list"))
    return render_template(
        "admin/role_form.html",
        role=None,
        modules=PERMISSION_MODULES,
        actions=PERMISSION_ACTIONS,
    )


@bp.route("/roles/<int:role_id>/edit", methods=["GET", "POST"])
@login_required
@require_permission("roles", "edit")
def role_edit(role_id):
    role = _get_role(role_id)
    if request.method == "POST":
        role.name = request.form["name"].strip()
        role.name_ar = request.form["name_ar"].strip()
        role.permissions = _parse_permissions(request.form)
        db.session.commit()
        flash("تم تحديث الدور.", "success")
        return redirect(url_for("admin.roles_list"))
    return render_template(
        "admin/role_form.html",
        role=role,
        modules=PERMISSION_MODULES,
        actions=PERMISSION_ACTIONS,
    )


@bp.route("/roles/<int:role_id>/delete", methods=["POST"])
@login_required
@require_permission("roles", "delete")
def role_delete(role_id):
    role = _get_role(role_id)
    if role.is_system:
        flash("لا يمكن حذف دور نظامي.", "danger")
    elif role.users:
        flash("لا يمكن حذف دور مرتبط بمستخدمين.", "danger")
    else:
        db.session.delete(role)
        db.session.commit()
        flash("تم حذف الدور.", "success")
    return redirect(url_for("admin.roles_list"))


# ---------- Users (T-1.3) ----------

@bp.route("/users")
@login_required
@require_permission("users", "view")
def users_list():
    users = (
        User.query.filter_by(school_id=current_user.school_id)
        .order_by(User.full_name)
        .all()
    )
    return render_template("admin/users_list.html", users=users)


@bp.route("/users/new", methods=["GET", "POST"])
@login_required
@require_permission("users", "add")
def user_new():
    roles = Role.query.filter_by(school_id=current_user.school_id).all()
    if request.method == "POST":
        password = request.form["password"]
        if len(password) < 8:
            flash("كلمة المرور يجب ألا تقل عن 8 أحرف.", "danger")
            return render_template("admin/user_form.html", user=None, roles=roles)
        user = User(
            school_id=current_user.school_id,
            role_id=int(request.form["role_id"]),
            username=request.form["username"].strip(),
            full_name=request.form["full_name"].strip(),
            email=request.form.get("email") or None,
            phone=request.form.get("phone") or None,
            is_active=bool(request.form.get("is_active")),
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash("تم إنشاء المستخدم.", "success")
        return redirect(url_for("admin.users_list"))
    return render_template("admin/user_form.html", user=None, roles=roles)


@bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@require_permission("users", "edit")
def user_edit(user_id):
    user = _get_user(user_id)
    roles = Role.query.filter_by(school_id=current_user.school_id).all()
    if request.method == "POST":
        user.role_id = int(request.form["role_id"])
        user.full_name = request.form["full_name"].strip()
        user.email = request.form.get("email") or None
        user.phone = request.form.get("phone") or None
        user.is_active = bool(request.form.get("is_active"))
        new_password = request.form.get("password")
        if new_password:
            if len(new_password) < 8:
                flash("كلمة المرور يجب ألا تقل عن 8 أحرف.", "danger")
                return render_template("admin/user_form.html", user=user, roles=roles)
            user.set_password(new_password)
        db.session.commit()
        flash("تم تحديث المستخدم.", "success")
        return redirect(url_for("admin.users_list"))
    return render_template("admin/user_form.html", user=user, roles=roles)


@bp.route("/users/<int:user_id>/toggle", methods=["POST"])
@login_required
@require_permission("users", "edit")
def user_toggle(user_id):
    user = _get_user(user_id)
    user.is_active = not user.is_active
    user.locked_until = None
    user.failed_attempts = 0
    db.session.commit()
    flash("تم تحديث حالة الحساب.", "success")
    return redirect(url_for("admin.users_list"))


# ---------- helpers ----------

def _get_role(role_id):
    role = Role.query.filter_by(id=role_id, school_id=current_user.school_id).first()
    if not role:
        abort(404)
    return role


def _get_user(user_id):
    user = User.query.filter_by(id=user_id, school_id=current_user.school_id).first()
    if not user:
        abort(404)
    return user


def _parse_permissions(form) -> dict:
    perms = {}
    for module in PERMISSION_MODULES:
        granted = [a for a in PERMISSION_ACTIONS if form.get(f"perm_{module}_{a}")]
        if granted:
            perms[module] = granted
    return perms
