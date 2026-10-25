"""Console → a school's identity (logo + colour): same rules as the
school's own settings (services/branding), owner only, under the target
school, audited, no e-mail."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from isolation_harness import host
from test_saas026_subscriptions import CONSOLE, _console_client, console  # noqa: F401


@pytest.fixture
def capp(console, tmp_path):
    console.config["WTF_CSRF_ENABLED"] = False
    console.config["UPLOAD_ROOT"] = str(tmp_path / "uploads")
    return console


def _png(color=(10, 120, 90), size=(64, 32)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def _school(app, sid):
    from app.extensions import db
    from app.models import School
    with app.app_context():
        s = db.session.get(School, sid)
        out = (s.logo_url, s.primary_color)
        db.session.remove()
    return out


def _post(c, sid, data=None, file=None, name="logo.png"):
    form = dict(data or {})
    if file is not None:
        form["logo_file"] = (io.BytesIO(file), name)
    return c.post(f"/superadmin/schools/{sid}/branding", base_url=CONSOLE, data=form,
                  content_type="multipart/form-data", follow_redirects=True)


def test_an_owner_sets_the_logo_and_colour_of_one_school(capp, two_schools, login_as, monkeypatch):
    from app.services import mailer, notifications
    sent = []
    monkeypatch.setattr(mailer, "send", lambda *a, **k: sent.append(a))
    monkeypatch.setattr(notifications, "send_notification", lambda *a, **k: sent.append(a))
    A, B = two_schools["A"], two_schools["B"]
    c, _ = _console_client(capp, "owner")
    r = _post(c, A["school"].id, {"primary_color": "#0f766e"}, file=_png())
    assert "تم حفظ هوية المدرسة" in r.get_data(as_text=True)
    logo, color = _school(capp, A["school"].id)
    assert logo.startswith(f"/files/{A['school'].id}/logo/") and color == "#0F766E"   # under A, not "the console's"
    assert _school(capp, B["school"].id) == (None, None)
    # A's host shows it at once; B's doesn't
    anon = capp.test_client()
    assert anon.get("/branding/logo", base_url=host(A)).mimetype == "image/png"
    assert anon.get("/branding/logo", base_url=host(B)).mimetype == "image/svg+xml"
    # the school's own settings page sees the console's change
    sc = capp.test_client()
    login_as(sc, A["users"]["admin"], base_url=host(A))
    assert 'value="#0F766E"' in sc.get("/admin/settings", base_url=host(A)).get_data(as_text=True)
    # the console page shows the logo; no e-mail / notice went out
    page = c.get(f"/superadmin/schools/{A['school'].id}", base_url=CONSOLE).get_data(as_text=True)
    assert f"/superadmin/schools/{A['school'].id}/branding/logo" in page
    assert c.get(f"/superadmin/schools/{A['school'].id}/branding/logo", base_url=CONSOLE).mimetype == "image/png"
    assert sent == []


def test_every_change_is_audited_without_the_file(capp, two_schools):
    from app.extensions import db
    from app.models import PlatformAuditLog
    A = two_schools["A"]
    c, uid = _console_client(capp, "owner")
    _post(c, A["school"].id, {"primary_color": "#123456"}, file=_png())
    _post(c, A["school"].id, {"reset_color": "1", "remove_logo": "1"})
    with capp.app_context():
        rows = (PlatformAuditLog.query.filter_by(action="school_branding_changed", target_school_id=A["school"].id)
                .order_by(PlatformAuditLog.id).all())
        metas = [r.meta for r in rows]
        assert all(r.platform_user_id == uid for r in rows)
        db.session.remove()
    assert metas[0]["logo"] == "uploaded" and metas[0]["color"] == {"before": None, "after": "#123456"}
    assert metas[1]["logo"] == "removed" and metas[1]["color"] == {"before": "#123456", "after": None}
    assert all("PNG" not in str(m) and "logo_file" not in str(m) for m in metas)


def test_replace_and_delete_remove_the_old_files(capp, two_schools):
    A = two_schools["A"]
    sid = A["school"].id
    root = Path(capp.config["UPLOAD_ROOT"])
    c, _ = _console_client(capp, "owner")
    _post(c, sid, file=_png((1, 2, 3)))
    first, _c = _school(capp, sid)
    _post(c, sid, file=_png((200, 2, 3)))
    second, _c = _school(capp, sid)
    assert second != first and not (root / first[len("/files/"):]).exists()
    _post(c, sid, {"remove_logo": "1"})
    assert _school(capp, sid)[0] is None and not (root / second[len("/files/"):]).exists()


def test_a_light_colour_is_darkened_with_a_notice(capp, two_schools):
    A = two_schools["A"]
    c, _ = _console_client(capp, "owner")
    body = _post(c, A["school"].id, {"primary_color": "#FFE600"}).get_data(as_text=True)
    assert "اتغمّق" in body


@pytest.mark.parametrize("data,file,name", [
    ({"primary_color": "red;}"}, None, None),
    ({}, b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', "logo.svg"),
    ({}, b"not an image at all", "logo.png"),
])
def test_bad_input_changes_nothing(capp, two_schools, data, file, name):
    A = two_schools["A"]
    c, _ = _console_client(capp, "owner")
    _post(c, A["school"].id, {"primary_color": "#123456"}, file=_png())
    before = _school(capp, A["school"].id)
    _post(c, A["school"].id, data, file=file, name=name or "logo.png")
    assert _school(capp, A["school"].id) == before


@pytest.mark.parametrize("role", ["support", "finance"])
def test_other_platform_roles_are_refused(capp, two_schools, role):
    A = two_schools["A"]
    c, _ = _console_client(capp, role)
    r = c.post(f"/superadmin/schools/{A['school'].id}/branding", base_url=CONSOLE, data={"primary_color": "#123456"})
    assert r.status_code == 403 and _school(capp, A["school"].id) == (None, None)


def test_school_users_and_visitors_never_reach_it(capp, two_schools, login_as):
    A = two_schools["A"]
    sc = capp.test_client()
    login_as(sc, A["users"]["admin"], base_url=host(A))
    for base in (host(A), CONSOLE):
        r = sc.post(f"/superadmin/schools/{A['school'].id}/branding", base_url=base, data={"primary_color": "#123456"})
        assert r.status_code in (302, 401, 403, 404), (base, r.status_code)
    r = capp.test_client().post(f"/superadmin/schools/{A['school'].id}/branding", base_url=CONSOLE,
                                data={"primary_color": "#123456"})
    assert r.status_code in (302, 401, 403)
    assert _school(capp, A["school"].id) == (None, None)
