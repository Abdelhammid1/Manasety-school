from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import bp
from ..utils import require_permission
from ...extensions import db
from ...models import Role, User, AuditLog, School
from ...models.user import PERMISSION_MODULES, PERMISSION_ACTIONS



# Ticket #1 (2026-09-25) — /admin/users and /admin/roles are for the
# school's administrative staff only. teacher / student / parent users
# are managed from their own module pages (teachers/, students/,
# guardians/) so they never surface here. Same list is used to reject
# a POST that tries to create/edit a user with one of those roles.
ADMIN_ROLE_NAMES = frozenset({
    "admin", "admin_full", "system_admin",
    "accountant", "student_affairs", "warehouse",
})


def _save_school_logo(school, file_storage):
    """Ticket #2 — save a logo file uploaded from the settings form.

    Stored via services.file_storage (kind "logo"); returns the
    /files/ URL that should be stored in `school.logo_url`.
    Returns None on validation failure (message flashed by caller).
    """
    from ...services import file_storage as fs
    if not file_storage or not file_storage.filename:
        return None
    try:
        return fs.save(file_storage, "logo", school.id)
    except fs.UploadRejected as e:
        flash(f"ملف الشعار: {e}", "danger")
        return None


# ---------- Ticket 6 — Audit log viewer ----------

@bp.route("/settings", methods=["GET", "POST"])
@login_required
@require_permission("users", "edit")
def school_settings():
    """Ticket H — 6-tab school-wide settings screen (org info, banks,
    finance, academic, prints, notifications)."""
    from ...models import Account, PaymentMethod
    from decimal import Decimal, InvalidOperation
    school = db.session.get(School, current_user.school_id)
    if not school:
        abort(404)

    from ...services import finance_settings as fin
    fin_locked = fin.has_financial_activity(school.id)

    if request.method == "POST":
        # The financial tab first: invalid values, or any change to a
        # locked field (even from a hand-made request), refuse the WHOLE
        # save — nothing changes.
        fin_changes, fin_errors = fin.parse_form(request.form, school)
        if fin_changes and fin_locked:
            flash(fin.LOCKED_MESSAGE, "danger")
            return redirect(url_for("admin.school_settings"))
        if fin_errors:
            for e in fin_errors:
                flash(e, "danger")
            return redirect(url_for("admin.school_settings"))
        # Simple field-map covering every tab. Only whitelisted keys.
        s = school
        get = lambda k: (request.form.get(k) or "").strip() or None

        # Ticket #13 (2026-09-21) — hard cap every text field at its
        # column length so a too-long paste from the browser can't hit
        # PostgreSQL's VARCHAR limit and 500 the whole save.
        def clip(val, n):
            return (val[:n] if val else val)

        try:
            # Tab 1 — establishment
            s.name = clip(get("name"), 255) or s.name
            s.legal_name_ar = clip(get("legal_name_ar"), 255)
            s.legal_name_en = clip(get("legal_name_en"), 255)
            # Ticket #2 — file upload takes precedence over a manually
            # typed URL. When neither is provided, keep the old value.
            file_storage = request.files.get("logo_file")
            if file_storage and file_storage.filename:
                saved_url = _save_school_logo(s, file_storage)
                if saved_url:
                    s.logo_url = saved_url
            else:
                typed = get("logo_url")
                if typed is not None:
                    s.logo_url = typed
            s.license_number = clip(get("license_number"), 64)
            s.tax_number = clip(get("tax_number"), 64)
            s.address = clip(get("address"), 255)
            s.phone = clip(get("phone"), 32)
            s.email = clip(get("email"), 128)
            s.website = clip(get("website"), 255)
            # Tab 3 — finance: services/finance_settings (validated, and
            # closed to the school once the year has financial activity)
            for field, value in fin_changes.items():
                setattr(s, field, value)
            # Tab 4 — academic
            mode = (request.form.get("attendance_mode") or "daily").strip()
            if mode in ("daily", "per_period", "both"):
                s.attendance_mode = mode
            # Tab 5 — prints
            s.invoice_header_text = get("invoice_header_text")
            s.invoice_footer_text = get("invoice_footer_text")
            s.invoice_policy_text = get("invoice_policy_text")
            s.show_logo_on_prints = bool(request.form.get("show_logo_on_prints"))
            # Tab 6 — notifications
            s.reminder_days_before = get("reminder_days_before") or "7,3"
            channels = request.form.getlist("notify_channels")
            s.notify_channels = ",".join(channels) if channels else "in_app,email"
            # Tab 7 — SMTP (per-school outbound email).
            from ...services import mailer as _mailer
            s.smtp_host = get("smtp_host") or None
            try:
                s.smtp_port = int(request.form.get("smtp_port") or 587)
            except (TypeError, ValueError):
                s.smtp_port = 587
            s.smtp_username = get("smtp_username") or None
            # Only re-encrypt the password if the admin typed a fresh
            # value — the input renders as "••••••" when a password is
            # already stored, and blanking-out means "keep as-is".
            raw_pw = (request.form.get("smtp_password") or "").strip()
            if raw_pw and raw_pw != "••••••••":
                s.smtp_password_encrypted = _mailer.encrypt(raw_pw)
            s.smtp_use_tls = bool(request.form.get("smtp_use_tls"))
            s.smtp_from_name = get("smtp_from_name") or None
            s.smtp_from_email = get("smtp_from_email") or None
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception("school settings save failed")
            flash(
                "تعذّر حفظ الإعدادات — راجع الحقول المرقّمة (النسب/التواريخ) "
                "أو حاول لاحقًا. تم تسجيل الخطأ للدعم الفني.",
                "danger",
            )
            bank_methods = (
                PaymentMethod.query.filter_by(
                    school_id=current_user.school_id, kind="immediate_bank",
                ).order_by(PaymentMethod.name).all()
            )
            return render_template("admin/school_settings.html",
                                   school=school, bank_methods=bank_methods, fin_locked=fin_locked)
        flash("تم حفظ الإعدادات.", "success")
        return redirect(url_for("admin.school_settings"))

    # Tab 2 — bank accounts derived from PaymentMethod(kind=immediate_bank).
    bank_methods = (
        PaymentMethod.query.filter_by(
            school_id=current_user.school_id, kind="immediate_bank",
        ).order_by(PaymentMethod.name).all()
    )
    return render_template("admin/school_settings.html",
                           school=school, bank_methods=bank_methods, fin_locked=fin_locked,
                           fin_locked_message=fin.LOCKED_MESSAGE)


@bp.route("/audit")
@login_required
@require_permission("users", "view")   # admin-tier permission reuse
def audit_log():
    """School-wide audit trail. Filterable by user + entity type."""
    sid = current_user.school_id
    # Strict tenant scope: NULL-school rows are not "global", they are
    # rows nobody can attribute, so no school's admin should see them.
    q = AuditLog.query.filter(AuditLog.school_id == sid)
    user_id = request.args.get("user_id", type=int)
    entity_type = (request.args.get("entity_type") or "").strip()
    action = (request.args.get("action") or "").strip()
    if user_id: q = q.filter(AuditLog.user_id == user_id)
    if entity_type: q = q.filter(AuditLog.entity_type == entity_type)
    if action: q = q.filter(AuditLog.action == action)
    from sqlalchemy.orm import joinedload
    entries = (q.options(joinedload(AuditLog.user).joinedload(User.role))
               .order_by(AuditLog.created_at.desc()).limit(300).all())

    from ...services import audit_display as ad
    types = sorted(t[0] for t in db.session.query(AuditLog.entity_type)
                   .filter(AuditLog.school_id == sid).distinct().all())
    actions = sorted(a[0] for a in db.session.query(AuditLog.action)
                     .filter(AuditLog.school_id == sid).distinct().all())
    users = User.query.filter_by(school_id=sid).order_by(User.full_name).all()
    # only readable rows reach the template — no raw value, no secret
    return render_template(
        "admin/audit_log.html",
        rows=ad.display_rows(entries, sid),
        entity_types=[(t, ad.entity_label(t)) for t in types],
        actions=[(a, ad.action_label(a)) for a in actions],
        users=users,
        selected={"user_id": user_id, "entity_type": entity_type, "action": action},
    )


# ---------- Roles & Permissions (T-1.2) ----------

@bp.route("/roles")
@login_required
@require_permission("roles", "view")
def roles_list():
    # Ticket #1 — surface only administrative-staff roles here. The
    # `teacher` / `parent` / `student` rows keep existing in the DB
    # (provision_user still looks them up by name) but are hidden
    # from this admin listing.
    roles = (
        Role.query.filter_by(school_id=current_user.school_id)
        .filter(Role.name.in_(ADMIN_ROLE_NAMES))
        .order_by(Role.id).all()
    )
    return render_template("admin/roles_list.html", roles=roles)


def _non_staff_role_problem(name, permissions, existing=None):
    """SAAS-030 security review — users of the student / parent roles
    don't count against the plan's staff limit, so those names are
    reserved for the school's own two roles and can only carry portal
    permissions (no staff powers hidden under a non-staff name)."""
    from ...services.limits import NON_STAFF_ROLES
    name = (name or "").strip().lower()
    if name in NON_STAFF_ROLES and (existing is None or existing.name != name):
        return "اسم الدور محجوز للنظام."
    if name in NON_STAFF_ROLES and set((permissions or {}).keys()) - {"portal"}:
        return "دور الطالب / ولي الأمر يقتصر على صلاحيات البوابة."
    return None


@bp.route("/roles/new", methods=["GET", "POST"])
@login_required
@require_permission("roles", "add")
def role_new():
    if request.method == "POST":
        perms = _parse_permissions(request.form)
        problem = _non_staff_role_problem(request.form["name"], perms)
        if problem:
            flash(problem, "danger")
            return render_template("admin/role_form.html", role=None,
                                   modules=PERMISSION_MODULES, actions=PERMISSION_ACTIONS)
        role = Role(
            school_id=current_user.school_id,
            name=request.form["name"].strip(),
            name_ar=request.form["name_ar"].strip(),
            permissions=perms,
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


@bp.route("/roles/<hid:role_id>/edit", methods=["GET", "POST"])
@login_required
@require_permission("roles", "edit")
def role_edit(role_id):
    role = _get_role(role_id)
    if request.method == "POST":
        perms = _parse_permissions(request.form)
        problem = _non_staff_role_problem(request.form["name"], perms, existing=role)
        if problem:
            flash(problem, "danger")
            return render_template("admin/role_form.html", role=role,
                                   modules=PERMISSION_MODULES, actions=PERMISSION_ACTIONS)
        role.name = request.form["name"].strip()
        role.name_ar = request.form["name_ar"].strip()
        role.permissions = perms
        db.session.commit()
        flash("تم تحديث الدور.", "success")
        return redirect(url_for("admin.roles_list"))
    return render_template(
        "admin/role_form.html",
        role=role,
        modules=PERMISSION_MODULES,
        actions=PERMISSION_ACTIONS,
    )


@bp.route("/roles/<hid:role_id>/delete", methods=["POST"])
@login_required
@require_permission("roles", "delete")
def role_delete(role_id):
    role = _get_role(role_id)
    if role.is_system:
        flash("لا يمكن حذف دور نظامي.", "danger")
    elif role.users:
        flash("لا يمكن حذف دور مرتبط بمستخدمين.", "danger")
    else:
        role.soft_delete(getattr(current_user, "id", None))
        db.session.commit()
        flash("تم حذف الدور.", "success")
    return redirect(url_for("admin.roles_list"))


# ---------- Users (T-1.3) ----------

@bp.route("/users")
@login_required
@require_permission("users", "view")
def users_list():
    # Ticket #1 — same scope as /admin/roles: administrative-staff
    # users only. Teacher / parent / student accounts are managed
    # from the teachers, students, and guardians modules.
    users = (
        User.query
        .join(Role, Role.id == User.role_id)
        .filter(User.school_id == current_user.school_id)
        .filter(Role.name.in_(ADMIN_ROLE_NAMES))
        .order_by(User.full_name)
        .all()
    )
    return render_template("admin/users_list.html", users=users)


def _admin_roles_or_reject():
    """Load the school's admin-staff roles, or None if the school has
    none provisioned. Shared between user_new and user_edit."""
    return (
        Role.query.filter_by(school_id=current_user.school_id)
        .filter(Role.name.in_(ADMIN_ROLE_NAMES))
        .order_by(Role.id).all()
    )


def _reject_non_admin_role(submitted_role_id: int, roles) -> bool:
    """Ticket #1 — backend guardrail. Anyone who bypasses the UI and
    posts a `role_id` that maps to teacher / parent / student is
    turned away here, before the User row is written."""
    if submitted_role_id not in {r.id for r in roles}:
        flash("لا يمكن إنشاء/تعديل المستخدمين بأدوار طالب/معلم/ولي أمر من هنا.",
              "danger")
        return True
    return False


@bp.route("/users/new", methods=["GET", "POST"])
@login_required
@require_permission("users", "add")
def user_new():
    roles = _admin_roles_or_reject()
    if request.method == "POST":
        password = request.form["password"]
        if len(password) < 8:
            flash("كلمة المرور يجب ألا تقل عن 8 أحرف.", "danger")
            return render_template("admin/user_form.html", user=None, roles=roles)
        role_id = int(request.form["role_id"])
        if _reject_non_admin_role(role_id, roles):
            return render_template("admin/user_form.html", user=None, roles=roles)
        from ...services.support_policy import username_reserved
        if username_reserved(request.form["username"]):
            flash("اسم المستخدم محجوز.", "danger")
            return render_template("admin/user_form.html", user=None, roles=roles)
        # SAAS-030 — staff accounts count against the plan's user limit.
        from ...services.limits import LimitReached, check_and_reserve
        try:
            check_and_reserve(current_user.school_id, "users")
        except LimitReached as e:
            flash(str(e), "danger")
            return render_template("admin/user_form.html", user=None, roles=roles)
        user = User(
            school_id=current_user.school_id,
            role_id=role_id,
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


@bp.route("/users/<hid:user_id>/edit", methods=["GET", "POST"])
@login_required
@require_permission("users", "edit")
def user_edit(user_id):
    user = _get_user(user_id)
    roles = _admin_roles_or_reject()
    # If somehow an admin lands on the edit page of a teacher/student/
    # parent user (e.g. via a bookmarked URL), redirect back to the
    # module page rather than let them change it here.
    if user.role and user.role.name not in ADMIN_ROLE_NAMES:
        flash("عدّل حسابات المعلمين/الطلاب/أولياء الأمور من صفحاتهم الخاصة.",
              "danger")
        return redirect(url_for("admin.users_list"))
    if request.method == "POST":
        role_id = int(request.form["role_id"])
        if _reject_non_admin_role(role_id, roles):
            return render_template("admin/user_form.html", user=user, roles=roles)
        user.role_id = role_id
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


@bp.route("/users/<hid:user_id>/toggle", methods=["POST"])
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


# ── SMTP test connection endpoint ──────────────────────────────────
@bp.route("/settings/smtp/test", methods=["POST"], endpoint="smtp_test")
@login_required
def smtp_test_connection():
    """Fires an SMTP connect + login round-trip against the currently
    saved settings and reports success/failure without sending mail."""
    from ...services import mailer as _mailer
    from ...models import School
    school = db.session.get(School, current_user.school_id)
    ok, msg = _mailer.test_connection(school)
    flash(msg, "success" if ok else "danger")
    return redirect(url_for("admin.school_settings") + "#smtp")


# ── Trash / restore centre ────────────────────────────────────────
@bp.route("/trash")
@login_required
@require_permission("users", "edit")
def trash_home():
    """Everything the school has soft-deleted, grouped by kind. Uses
    the escape hatch on the global filter so the rows actually appear."""
    from ...models import Vendor, PaymentMethod, FeeType, CostCenter, Role
    from ...models.hr import Employee
    from sqlalchemy import select

    sid = current_user.school_id
    groups = []

    def _load(cls, label, icon, endpoint):
        stmt = (select(cls)
                .execution_options(include_deleted=True)
                .filter(cls.school_id == sid)
                .filter(cls.deleted_at.isnot(None))
                .order_by(cls.deleted_at.desc()))
        rows = db.session.execute(stmt).scalars().all()
        if rows:
            groups.append({
                "label": label, "icon": icon,
                "endpoint": endpoint, "rows": rows,
            })

    _load(Vendor,        "الموردون",       "storefront",      "vendors")
    _load(PaymentMethod, "طرق الدفع",      "credit_card",    "payment_methods")
    _load(FeeType,       "أنواع الرسوم",   "receipt",        "fee_types")
    _load(CostCenter,    "مراكز التكلفة", "hub",            "cost_centers")
    _load(Role,          "الأدوار",         "admin_panel_settings", "roles")
    _load(Employee,      "الموظفون",       "badge",          "employees")

    return render_template("admin/trash.html", groups=groups)


@bp.route("/trash/<kind>/<hid:oid>/restore", methods=["POST"], endpoint="trash_restore")
@login_required
@require_permission("users", "edit")
def trash_restore(kind, oid):
    from sqlalchemy import select
    from ...models import Vendor, PaymentMethod, FeeType, CostCenter, Role
    from ...models.hr import Employee
    cls_map = {
        "vendors": Vendor, "payment_methods": PaymentMethod,
        "fee_types": FeeType, "cost_centers": CostCenter,
        "roles": Role, "employees": Employee,
    }
    cls = cls_map.get(kind)
    if not cls:
        abort(404)
    obj = db.session.execute(
        select(cls).execution_options(include_deleted=True)
        .filter(cls.id == oid, cls.school_id == current_user.school_id)
    ).scalar_one_or_none()
    if not obj:
        abort(404)
    obj.restore()
    db.session.commit()
    flash("تم استرجاع الصف.", "success")
    return redirect(url_for("admin.trash_home"))
