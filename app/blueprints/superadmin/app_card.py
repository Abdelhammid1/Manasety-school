"""SAAS-037 — the console side of the mobile contract:

- a printable "app card" per school: QR to the school's /app link, the
  school code and the sign-in steps, to hand out to parents and
  teachers. Any console role may print it (name + code only).
- app settings (owner): minimum app version per app, the download
  link, and the support contacts the apps show.
"""
from __future__ import annotations

from flask import abort, current_app, flash, redirect, render_template, request, url_for

from . import bp, current_platform_user
from ...extensions import db
from ...models import PlatformSetting, School
from ...services import platform_auth as pa
from ...services import subscriptions as subs

APP_SETTING_KEYS = ("min_app_version_student", "min_app_version_teacher", "min_app_version_parent",
                    "app_download_url", "support_email", "support_phone", "support_whatsapp")


def app_link(school) -> str:
    base = current_app.config.get("BASE_DOMAIN") or "manasety.ai"
    return f"https://{school.slug}.{base}/app"


@bp.route("/schools/<int:school_id>/app-card", endpoint="app_card")
def app_card(school_id):
    school = db.session.get(School, school_id)
    if school is None or school.status == "archived" or not school.slug:
        abort(404)
    link = app_link(school)
    import segno
    qr = segno.make(link, error="m").svg_inline(scale=5, border=2)
    return render_template("superadmin/app_card.html", school=school, link=link, qr=qr)


def _problem(key: str, value: str) -> str | None:
    from ..api.public import valid_version
    if not value:
        return None
    if key.startswith("min_app_version_") and not valid_version(value):
        return "رقم النسخة لازم يكون بالشكل 1.2.0"
    if key == "app_download_url" and not value.startswith("https://"):
        return "رابط التحميل لازم يبدأ بـ https://"
    if key == "support_email" and ("@" not in value or " " in value):
        return "الإيميل غير صحيح."
    if len(value) > 255:
        return "القيمة طويلة جدًا."
    return None


@bp.route("/settings/apps", methods=["GET", "POST"], endpoint="app_settings")
def app_settings():
    values = {k: subs.get_settings().get(k) or "" for k in APP_SETTING_KEYS}
    if request.method == "POST":
        new = {k: (request.form.get(k) or "").strip() for k in APP_SETTING_KEYS}
        errors = {k: e for k in APP_SETTING_KEYS if (e := _problem(k, new[k]))}
        if errors:
            for e in errors.values():
                flash(e, "danger")
            return render_template("superadmin/app_settings.html", values=new), 400
        changed = sorted(k for k in APP_SETTING_KEYS if new[k] != values[k])
        for key in changed:
            row = db.session.get(PlatformSetting, key) or PlatformSetting(key=key)
            row.value = new[key] or None
            row.updated_by = current_platform_user().id
            db.session.add(row)
        pa.audit("app_settings_changed", current_platform_user(), keys=changed)
        db.session.commit()
        flash("تم الحفظ.", "success")
        return redirect(url_for("superadmin.app_settings"))
    return render_template("superadmin/app_settings.html", values=values)
