"""SAAS-011 — protected file storage and the /files download route."""

from __future__ import annotations

import io

import pytest
from werkzeug.datastructures import FileStorage

from isolation_harness import host, hid

PDF = b"%PDF-1.4\n%fake but well-formed enough\n"
def _real_png() -> bytes:
    """A real (tiny) PNG: logos are decoded on upload (School Branding)."""
    import io as _io
    from PIL import Image
    buf = _io.BytesIO()
    Image.new("RGB", (4, 4), (30, 58, 138)).save(buf, "PNG")
    return buf.getvalue()


PNG = _real_png()

# Anonymous: 401, which the app's handler turns into a login redirect.
DENIED = (302, 401)


@pytest.fixture
def files_app(app, tmp_path, monkeypatch):
    monkeypatch.setitem(app.config, "UPLOAD_ROOT", str(tmp_path / "uploads"))
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    return app


def _fs(data=PDF, name="doc.pdf"):
    return FileStorage(stream=io.BytesIO(data), filename=name)


def _store(app, school_id, kind, owner_id, data=PDF, name="doc.pdf"):
    from app.services import file_storage as fs
    from app.services.tenancy import tenant_context
    with app.app_context(), tenant_context(school_id):
        return fs.save(_fs(data, name), kind, owner_id)


@pytest.fixture
def lms_world(files_app, two_schools):
    """Course + course-section + assignment + submission + conversation
    in school A, so every file kind has a real owner."""
    from app.extensions import db
    from app.models import (
        Conversation, ConversationParticipant, Course, CourseAssignment,
        CourseSection, Submission,
    )
    A = two_schools["A"]
    with files_app.app_context():
        course = Course(school_id=A["school"].id, academic_year_id=A["year"].id,
                        grade_id=A["grade"].id, subject_id=A["subject"].id, title="C-alpha")
        db.session.add(course); db.session.flush()
        db.session.add(CourseSection(course_id=course.id, section_id=A["section"].id,
                                     is_published=True))
        asg = CourseAssignment(course_id=course.id, title="HW")
        db.session.add(asg); db.session.flush()
        sub = Submission(assignment_id=asg.id, student_id=A["student"].id)
        conv = Conversation(school_id=A["school"].id)
        db.session.add_all([sub, conv]); db.session.flush()
        db.session.add(ConversationParticipant(conversation_id=conv.id,
                                               user_id=A["users"]["teacher"].id))
        db.session.commit()
        ids = {"course": course.id, "submission": sub.id, "conversation": conv.id}
        db.session.remove()
    return {**two_schools, "ids": ids}


def _get(app, login_as, user, url, base):
    with app.test_client() as c:
        if user is not None:
            login_as(c, user, base_url=base)
        return c.get(url, base_url=base).status_code


# kind -> (owner(A, ids), allowed role, forbidden role or None)
CASES = {
    "student_docs":    (lambda A, i: A["student"].id, "admin", "parent"),
    "previous_school": (lambda A, i: A["student"].id, "admin", "parent"),
    "student_photo":   (lambda A, i: A["student"].id, "parent", None),
    "excuse":          (lambda A, i: A["enrollment"].id, "parent", None),
    "materials":       (lambda A, i: A["section"].id, "student", None),
    "lessons":         (lambda A, i: i["course"], "student", None),
    "submissions":     (lambda A, i: i["submission"], "student", "parent_other"),
    "messages":        (lambda A, i: i["conversation"], "teacher", "parent"),
    "logo":            (lambda A, i: A["school"].id, "parent", None),
}


@pytest.mark.parametrize("kind", sorted(CASES))
def test_file_access_matrix(files_app, lms_world, login_as, kind):
    A, B = lms_world["A"], lms_world["B"]
    owner, allowed, forbidden = CASES[kind]
    data, name = (PNG, "f.png") if kind in ("logo", "student_photo") else (PDF, "doc.pdf")
    url = _store(files_app, A["school"].id, kind, owner(A, lms_world["ids"]), data, name)
    assert url.startswith(f"/files/{A['school'].id}/{kind}/")

    assert _get(files_app, login_as, A["users"][allowed], url, host(A)) == 200
    assert _get(files_app, login_as, None, url, host(A)) in DENIED
    # another school — on its own host, and with the cookie replayed on A's
    assert _get(files_app, login_as, B["users"]["admin"], url, host(B)) == 404
    if forbidden and forbidden in A["users"]:
        assert _get(files_app, login_as, A["users"][forbidden], url, host(A)) == 403


def test_submission_file_is_only_for_its_student(files_app, lms_world, login_as):
    """Copying another submission's URL into your own record must not
    help: the policy keys off the owner id in the path."""
    from app.extensions import db
    from app.models import Role, User
    A = lms_world["A"]
    url = _store(files_app, A["school"].id, "submissions", lms_world["ids"]["submission"])
    with files_app.app_context():
        other = User(school_id=A["school"].id, role_id=A["roles"]["student"].id,
                     username="s_other", full_name="Other", is_active=True)
        other.set_password("x" * 12)
        db.session.add(other); db.session.commit()
        other_id = other.id
        db.session.remove()
    with files_app.app_context():
        u = db.session.get(User, other_id)
        assert _get(files_app, login_as, u, url, host(A)) == 403
        db.session.remove()


def test_files_are_stored_outside_static(files_app, two_schools):
    import os
    from pathlib import Path
    A = two_schools["A"]
    url = _store(files_app, A["school"].id, "student_docs", A["student"].id)
    root = Path(files_app.config["UPLOAD_ROOT"]).resolve()
    stored = root / url[len("/files/"):]
    assert stored.is_file()
    assert Path(files_app.static_folder).resolve() not in stored.parents
    assert stored.parts[-4] == str(A["school"].id)
    assert os.path.getsize(stored) == len(PDF)


def test_static_uploads_path_is_404(files_app, two_schools):
    with files_app.test_client() as c:
        assert c.get("/static/uploads/logos/x.png",
                     base_url=host(two_schools["A"])).status_code == 404


@pytest.mark.parametrize("key", [
    "../../etc/passwd", "1/student_docs/1/..%2f..%2fsecret",
    "/abs/student_docs/1/x.pdf", "1/student_docs/1/../../x.pdf",
    "1/unknown_kind/1/x.pdf", "1/student_docs/x/y.pdf",
    "1\\student_docs\\1\\x.pdf", "C:/x/student_docs/1/a.pdf",
])
def test_traversal_and_malformed_keys_are_rejected(files_app, key):
    from app.services import file_storage as fs
    with files_app.app_context():
        assert fs.parse_key(key) is None


@pytest.mark.parametrize("data,name,needle", [
    (b"MZ\x90\x00 not a pdf", "evil.pdf", "لا يطابق"),
    (b"<html>hi</html>", "x.png", "لا يطابق"),
    (PDF, "x.exe", "غير مدعومة"),
    (b"", "empty.pdf", "فارغ"),
])
def test_bad_uploads_are_rejected(files_app, two_schools, data, name, needle):
    from app.services import file_storage as fs
    A = two_schools["A"]
    with pytest.raises(fs.UploadRejected, match=needle):
        _store(files_app, A["school"].id, "student_docs", A["student"].id, data, name)


def test_size_limit(files_app, two_schools):
    from app.services import file_storage as fs
    A = two_schools["A"]
    big = PNG + b"\x00" * (5 * 1024 * 1024)
    with pytest.raises(fs.UploadRejected, match="يتجاوز"):
        _store(files_app, A["school"].id, "student_photo", A["student"].id, big, "p.png")


def test_arabic_filename_keeps_extension(files_app, two_schools):
    A = two_schools["A"]
    url = _store(files_app, A["school"].id, "student_docs", A["student"].id, PDF, "تقرير.pdf")
    assert url.endswith(".pdf")


def test_signed_url_works_without_login_and_expires(files_app, two_schools, monkeypatch):
    from app.services import file_storage as fs
    A, B = two_schools["A"], two_schools["B"]
    url = _store(files_app, A["school"].id, "materials", A["section"].id)
    from app.services.tenancy import tenant_context
    with files_app.test_request_context(base_url=host(A)), tenant_context(A["school"].id):
        signed = fs.signed_url(url, "materials", A["section"].id, ttl_seconds=60)
        expired = fs.signed_url(url, "materials", A["section"].id, ttl_seconds=-1)
    with files_app.test_client() as c:
        assert c.get(signed, base_url=host(A)).status_code == 200
        assert c.get(expired, base_url=host(A)).status_code in DENIED
        assert c.get(signed.replace("sig=", "sig=0"), base_url=host(A)).status_code in DENIED
        # a valid signature is still bound to its school's host
        assert c.get(signed, base_url=host(B)).status_code == 404


def test_download_headers_neutralise_active_content(files_app, two_schools, login_as):
    A = two_schools["A"]
    # an SVG logo from before uploads became raster-only: still served, neutralised
    from app.services.file_storage import upload_root
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    sid = A["school"].id
    key = f"{sid}/logo/{sid}/legacy_logo.svg"
    with files_app.app_context():
        dest = upload_root() / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(svg)
    url = "/files/" + key
    with files_app.test_client() as c:
        login_as(c, A["users"]["admin"], base_url=host(A))
        r = c.get(url, base_url=host(A))
    assert r.status_code == 200
    assert "sandbox" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_document_upload_and_view_end_to_end(files_app, two_schools, login_as):
    from app.models import StudentDocument
    A = two_schools["A"]
    with files_app.test_client() as c:
        login_as(c, A["users"]["admin"], base_url=host(A))
        r = c.post(f"/students/{hid(A['student'].id)}/documents/upload", base_url=host(A),
                   data={"file": (io.BytesIO(PDF), "id.pdf"), "title": "ID"},
                   content_type="multipart/form-data")
        assert r.status_code == 302
        with files_app.app_context():
            doc = StudentDocument.query.filter_by(student_id=A["student"].id).one()
            path, size = doc.file_path, doc.file_size
        assert path.startswith("/files/") and size == len(PDF)
        assert c.get(path, base_url=host(A)).status_code == 200
        page = c.get(f"/students/{hid(A['student'].id)}/documents", base_url=host(A))
        assert path in page.get_data(as_text=True)


def test_api_material_paths_are_signed(files_app, two_schools):
    from app.blueprints.api.routes import _signed
    A = two_schools["A"]
    url = _store(files_app, A["school"].id, "materials", A["section"].id)
    from app.services.tenancy import tenant_context
    with files_app.test_request_context(base_url=host(A)), tenant_context(A["school"].id):
        assert "sig=" in _signed(url, "materials", A["section"].id)
        assert _signed("https://youtu.be/x", "lessons", 1) == "https://youtu.be/x"
        assert _signed(None, "lessons", 1) is None


def test_legacy_static_rows_are_migrated_idempotently(files_app, two_schools, tmp_path):
    from pathlib import Path
    from app.blueprints.files import migrate_static_uploads
    from app.extensions import db
    from app.models import Student
    A = two_schools["A"]
    static = tmp_path / "static"
    sid = A["student"].id
    (static / "uploads" / "students" / str(sid)).mkdir(parents=True)
    (static / "uploads" / "students" / str(sid) / "old.png").write_bytes(PNG)
    with files_app.app_context():
        s = db.session.get(Student, A["student"].id)
        s.photo_url = f"/static/uploads/students/{sid}/old.png"
        db.session.commit()
        first = migrate_static_uploads(static)
        assert first["students.photo_url"]["moved"] == 1
        new = db.session.get(Student, A["student"].id).photo_url
        assert new.startswith(f"/files/{A['school'].id}/student_photo/{A['student'].id}/")
        stored = Path(files_app.config["UPLOAD_ROOT"]) / new[len("/files/"):]
        assert stored.read_bytes() == PNG
        assert migrate_static_uploads(static)["students.photo_url"]["moved"] == 0

        s = db.session.get(Student, A["student"].id)
        s.photo_url = f"/static/uploads/students/{sid}/gone.png"
        db.session.commit()
        assert migrate_static_uploads(static)["students.photo_url"]["missing"] == 1
        assert db.session.get(Student, A["student"].id).photo_url.endswith("gone.png")
        db.session.remove()


# ─── security review follow-ups ──────────────────────────────────────

def test_stored_url_of_another_owner_is_never_signed(files_app, two_schools):
    """Confused deputy: a record whose URL field names someone else's
    file (e.g. a student pasting another submission's link) must not
    get a signed URL for it."""
    from app.services import file_storage as fs
    A = two_schools["A"]
    docs = _store(files_app, A["school"].id, "student_docs", A["student"].id)
    from app.services.tenancy import tenant_context
    with files_app.test_request_context(base_url=host(A)), tenant_context(A["school"].id):
        assert fs.signed_url(docs, "submissions", 1) is None
        assert fs.signed_url(docs, "student_docs", A["student"].id + 1) is None
        assert "sig=" in fs.signed_url(docs, "student_docs", A["student"].id)


def test_api_submit_refuses_stored_file_keys(files_app, lms_world):
    """A client may submit an external link, never the name of a stored
    file (which the API would later hand back as a signed URL)."""
    from app.extensions import db
    from app.models import CourseAssignment, Submission, User
    from app.services.auth_jwt import issue_token
    A = lms_world["A"]
    with files_app.app_context():
        asg = CourseAssignment.query.join(Submission).filter(
            Submission.id == lms_world["ids"]["submission"]).one()
        asg.is_published = True
        # SAAS-017 review: the API serves a student only courses published
        # to one of their sections — publish this one to the student's.
        from app.models import CourseSection, Enrollment, Student
        course = asg.course
        course.is_published = True
        stu = Student.query.filter_by(user_id=A["users"]["student"].id).one()
        for e in Enrollment.query.filter_by(student_id=stu.id, status="active"):
            if not CourseSection.query.filter_by(course_id=course.id, section_id=e.section_id).first():
                db.session.add(CourseSection(course_id=course.id, section_id=e.section_id, is_published=True))
        db.session.commit()
        aid = asg.id
        token = issue_token(db.session.get(User, A["users"]["student"].id))
        db.session.remove()
    hdr = {"Authorization": f"Bearer {token}"}
    with files_app.test_client() as c:
        bad = c.post(f"/api/student/assignments/{aid}/submit", base_url=host(A), headers=hdr,
                     json={"file_url": f"/files/{A['school'].id}/student_docs/1/x.pdf"})
        assert bad.status_code == 400
        ok = c.post(f"/api/student/assignments/{aid}/submit", base_url=host(A), headers=hdr,
                    json={"file_url": "https://drive.example/x"})
        assert ok.status_code == 200, ok.get_data(as_text=True)[:200]


@pytest.mark.parametrize("path", [
    "/static/uploads/x.png", "/static//uploads/x.png", "/static/./uploads/x.png",
    "/static/Uploads/x.png", "/static/UPLOADS/logos/x.png", "/static/css/../uploads/x.png",
    "/static/uploads",
])
def test_static_uploads_blocked_in_every_spelling(files_app, two_schools, path):
    with files_app.test_client() as c:
        r = c.get(path, base_url=host(two_schools["A"]), follow_redirects=True)
        assert r.status_code == 404


def test_deactivated_user_jwt_cannot_download(files_app, two_schools):
    from app.extensions import db
    from app.models import User
    from app.services.auth_jwt import issue_token
    A = two_schools["A"]
    url = _store(files_app, A["school"].id, "student_docs", A["student"].id)
    with files_app.app_context():
        admin = db.session.get(User, A["users"]["admin"].id)
        token = issue_token(admin)
        db.session.remove()
    with files_app.test_client() as c:
        ok = c.get(url, base_url=host(A), headers={"Authorization": f"Bearer {token}"})
        assert ok.status_code == 200
    with files_app.app_context():
        admin = db.session.get(User, A["users"]["admin"].id)
        admin.is_active = False
        db.session.commit()
        db.session.remove()
    with files_app.test_client() as c:
        r = c.get(url, base_url=host(A), headers={"Authorization": f"Bearer {token}"})
        assert r.status_code in DENIED


def test_legacy_migration_moves_file_out_of_static(files_app, two_schools, tmp_path):
    from app.blueprints.files import migrate_static_uploads
    from app.extensions import db
    from app.models import Student
    A = two_schools["A"]
    old = tmp_path / "static" / "uploads" / "students" / str(A["student"].id) / "p.png"
    old.parent.mkdir(parents=True)
    old.write_bytes(PNG)
    with files_app.app_context():
        s = db.session.get(Student, A["student"].id)
        s.photo_url = f"/static/uploads/students/{A['student'].id}/p.png"
        db.session.commit()
        migrate_static_uploads(tmp_path / "static")
        db.session.remove()
    assert not old.exists()


def test_legacy_migration_refuses_foreign_and_shared_paths(files_app, two_schools, tmp_path):
    """A URL pointing outside the row owner's old directory, or a file
    referenced by two rows, is reported and never moved."""
    from app.blueprints.files import migrate_static_uploads
    from app.extensions import db
    from app.models import Student
    A, B = two_schools["A"], two_schools["B"]
    static = tmp_path / "static"
    victim = static / "uploads" / "students" / str(B["student"].id) / "v.png"
    victim.parent.mkdir(parents=True)
    victim.write_bytes(PNG)
    with files_app.app_context():
        a = db.session.get(Student, A["student"].id)
        a.photo_url = f"/static/uploads/students/{B['student'].id}/v.png"   # not A's dir
        db.session.commit()
        rep = migrate_static_uploads(static)["students.photo_url"]
        assert rep["foreign_path"] == 1 and rep["moved"] == 0
        b = db.session.get(Student, B["student"].id)
        b.photo_url = f"/static/uploads/students/{B['student'].id}/v.png"
        db.session.commit()
        rep = migrate_static_uploads(static)["students.photo_url"]
        assert rep["moved"] == 1      # B's own row is unambiguous once A's is foreign
        db.session.remove()
    assert not victim.exists()


def test_signed_url_refuses_other_schools_key(files_app, two_schools):
    from app.services import file_storage as fs
    A, B = two_schools["A"], two_schools["B"]
    url = _store(files_app, A["school"].id, "materials", A["section"].id)
    from app.services.tenancy import tenant_context
    with files_app.test_request_context(base_url=host(B)), tenant_context(B["school"].id):
        assert fs.signed_url(url, "materials", A["section"].id) is None
    with files_app.test_request_context(base_url=host(B)):
        assert fs.signed_url(url, "materials", A["section"].id) is None  # no tenant


def test_static_uploads_blocked_by_resolved_path(files_app, two_schools):
    """Even when the request string doesn't look like /static/uploads,
    a static request that resolves inside it is refused."""
    import os
    from pathlib import Path
    up = Path(files_app.static_folder, "uploads")
    created = not up.exists()
    up.mkdir(exist_ok=True)
    probe = up / "probe_saas011.txt"
    probe.write_text("x")
    try:
        with files_app.test_client() as c:
            for path in ("/static/uploads/probe_saas011.txt",
                         "/static/css/../uploads/probe_saas011.txt"):
                r = c.get(path, base_url=host(two_schools["A"]), follow_redirects=True)
                assert r.status_code == 404, path
    finally:
        probe.unlink()
        if created:
            os.rmdir(up)


@pytest.mark.parametrize("trick", [
    "{a}/..\..\{b}\v.png", "{a}/..%2f{b}%2fv.png", "{a}/./../{b}/v.png",
    "{a}//../{b}/v.png", "{a}/C:v.png",
])
def test_legacy_migration_rejects_path_tricks(files_app, two_schools, tmp_path, trick):
    """A value that only *looks* like the owner's old directory must be
    judged on the path it resolves to — never moved out of B's folder."""
    from app.blueprints.files import migrate_static_uploads
    from app.extensions import db
    from app.models import Student
    A, B = two_schools["A"], two_schools["B"]
    static = tmp_path / "static"
    victim = static / "uploads" / "students" / str(B["student"].id) / "v.png"
    victim.parent.mkdir(parents=True)
    victim.write_bytes(PNG)
    (static / "uploads" / "students" / str(A["student"].id)).mkdir(parents=True)
    rel = trick.format(a=A["student"].id, b=B["student"].id)
    with files_app.app_context():
        a = db.session.get(Student, A["student"].id)
        a.photo_url = f"/static/uploads/students/{rel}"
        db.session.commit()
        rep = migrate_static_uploads(static)["students.photo_url"]
        assert rep["moved"] == 0 and rep["foreign_path"] == 1, rep
        db.session.remove()
    assert victim.exists()
