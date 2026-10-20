"""SAAS-011 — protected file storage and the /files download route."""

from __future__ import annotations

import io
import time

import pytest
from werkzeug.datastructures import FileStorage

from isolation_harness import host

PDF = b"%PDF-1.4\n%fake but well-formed enough\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32

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
    with files_app.test_request_context(base_url=host(A)):
        signed = fs.signed_url(url, ttl_seconds=60)
        expired = fs.signed_url(url, ttl_seconds=-1)
    with files_app.test_client() as c:
        assert c.get(signed, base_url=host(A)).status_code == 200
        assert c.get(expired, base_url=host(A)).status_code in DENIED
        assert c.get(signed.replace("sig=", "sig=0"), base_url=host(A)).status_code in DENIED
        # a valid signature is still bound to its school's host
        assert c.get(signed, base_url=host(B)).status_code == 404


def test_download_headers_neutralise_active_content(files_app, two_schools, login_as):
    A = two_schools["A"]
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    url = _store(files_app, A["school"].id, "logo", A["school"].id, svg, "logo.svg")
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
        r = c.post(f"/students/{A['student'].id}/documents/upload", base_url=host(A),
                   data={"file": (io.BytesIO(PDF), "id.pdf"), "title": "ID"},
                   content_type="multipart/form-data")
        assert r.status_code == 302
        with files_app.app_context():
            doc = StudentDocument.query.filter_by(student_id=A["student"].id).one()
            path, size = doc.file_path, doc.file_size
        assert path.startswith("/files/") and size == len(PDF)
        assert c.get(path, base_url=host(A)).status_code == 200
        page = c.get(f"/students/{A['student'].id}/documents", base_url=host(A))
        assert path in page.get_data(as_text=True)


def test_api_material_paths_are_signed(files_app, two_schools):
    from app.blueprints.api.routes import _signed
    A = two_schools["A"]
    url = _store(files_app, A["school"].id, "materials", A["section"].id)
    with files_app.test_request_context(base_url=host(A)):
        assert "sig=" in _signed(url)
        assert _signed("https://youtu.be/x") == "https://youtu.be/x"
        assert _signed(None) is None
    time.sleep(0)


def test_legacy_static_rows_are_migrated_idempotently(files_app, two_schools, tmp_path):
    from pathlib import Path
    from app.blueprints.files import migrate_static_uploads
    from app.extensions import db
    from app.models import Student
    A = two_schools["A"]
    static = tmp_path / "static"
    (static / "uploads" / "students" / "1").mkdir(parents=True)
    (static / "uploads" / "students" / "1" / "old.png").write_bytes(PNG)
    with files_app.app_context():
        s = db.session.get(Student, A["student"].id)
        s.photo_url = "/static/uploads/students/1/old.png"
        db.session.commit()
        first = migrate_static_uploads(static)
        assert first["students.photo_url"] == {"moved": 1, "missing": 0}
        new = db.session.get(Student, A["student"].id).photo_url
        assert new.startswith(f"/files/{A['school'].id}/student_photo/{A['student'].id}/")
        stored = Path(files_app.config["UPLOAD_ROOT"]) / new[len("/files/"):]
        assert stored.read_bytes() == PNG
        assert migrate_static_uploads(static)["students.photo_url"] == {"moved": 0, "missing": 0}

        s = db.session.get(Student, A["student"].id)
        s.photo_url = "/static/uploads/students/1/gone.png"
        db.session.commit()
        assert migrate_static_uploads(static)["students.photo_url"] == {"moved": 0, "missing": 1}
        assert db.session.get(Student, A["student"].id).photo_url.endswith("gone.png")
        db.session.remove()
