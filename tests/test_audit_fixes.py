"""Regressions for bugs found in the pre-push audit (smoke crawl)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from isolation_harness import host


@pytest.fixture
def lessons(app, two_schools, monkeypatch):
    """A published course + lesson in each school, published to its section."""
    from app.extensions import db
    from app.models import Course, CourseSection, Lesson
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    ids = {}
    with app.app_context():
        for key in ("A", "B"):
            X = two_schools[key]
            c = Course(school_id=X["school"].id, academic_year_id=X["year"].id,
                       grade_id=X["grade"].id, subject_id=X["subject"].id,
                       title=f"Course-{key}", is_published=True)
            db.session.add(c); db.session.flush()
            db.session.add(CourseSection(course_id=c.id, section_id=X["section"].id,
                                         is_published=True))
            lesson = Lesson(course_id=c.id, title=f"Lesson-{key}", kind="text",
                            is_published=True)
            db.session.add(lesson); db.session.flush()
            ids[key] = {"course": c.id, "lesson": lesson.id}
        db.session.commit()
        db.session.remove()
    return {**two_schools, "ids": ids}


def _status(app, login_as, user, path, base, method="GET"):
    with app.test_client() as c:
        login_as(c, user, base_url=base)
        return c.open(path, method=method, base_url=base).status_code


@pytest.mark.parametrize("suffix,method", [("", "GET"), ("/edit", "GET"), ("/delete", "POST")])
def test_other_schools_lesson_is_404(app, lessons, login_as, suffix, method):
    A = lessons["A"]
    b_lesson = lessons["ids"]["B"]["lesson"]
    assert _status(app, login_as, A["users"]["admin"],
                   f"/courses/lessons/{b_lesson}{suffix}", host(A), method) == 404


def test_own_lesson_opens_for_editor_and_enrolled_student(app, lessons, login_as):
    A = lessons["A"]
    path = f"/courses/lessons/{lessons['ids']['A']['lesson']}"
    assert _status(app, login_as, A["users"]["admin"], path, host(A)) == 200
    assert _status(app, login_as, A["users"]["student"], path, host(A)) == 200


def test_student_not_in_the_course_section_gets_404(app, lessons, login_as):
    from app.extensions import db
    from app.models import CourseSection
    A = lessons["A"]
    with app.app_context():
        CourseSection.query.filter_by(course_id=lessons["ids"]["A"]["course"]).delete()
        db.session.commit()
        db.session.remove()
    path = f"/courses/lessons/{lessons['ids']['A']['lesson']}"
    assert _status(app, login_as, A["users"]["student"], path, host(A)) == 404


def test_lesson_of_soft_deleted_course_is_404_not_500(app, lessons, login_as):
    from app.extensions import db
    from app.models import Course
    A = lessons["A"]
    with app.app_context():
        c = db.session.get(Course, lessons["ids"]["A"]["course"])
        assert c is not None
        c.deleted_at = datetime.now(timezone.utc)
        db.session.commit()
        db.session.remove()
    for suffix in ("", "/edit"):
        path = f"/courses/lessons/{lessons['ids']['A']['lesson']}{suffix}"
        assert _status(app, login_as, A["users"]["admin"], path, host(A)) == 404


def test_teacher_schedule_page_renders(app, two_schools, login_as, monkeypatch):
    from app.extensions import db
    from app.models import Teacher
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    A = two_schools["A"]
    with app.app_context():
        t = Teacher(school_id=A["school"].id, full_name="Teacher-alpha", specialization="Math")
        db.session.add(t); db.session.commit()
        tid = t.id
        db.session.remove()
    assert _status(app, login_as, A["users"]["admin"], f"/schedule/teacher/{tid}", host(A)) == 200


# ─── reviewer follow-ups ─────────────────────────────────────────────

@pytest.mark.parametrize("exp", ["²", "١٢٣", "-5", "abc"])
def test_non_ascii_expiry_is_denied_not_500(app, two_schools, exp, tmp_path, monkeypatch):
    import io
    from werkzeug.datastructures import FileStorage
    from app.services import file_storage as fs
    from app.services.tenancy import tenant_context
    monkeypatch.setitem(app.config, "UPLOAD_ROOT", str(tmp_path))
    A = two_schools["A"]
    with app.app_context(), tenant_context(A["school"].id):
        url = fs.save(FileStorage(io.BytesIO(b"%PDF-1.4\n"), "d.pdf"), "materials", A["section"].id)
    with app.test_client() as c:
        r = c.get(f"{url}?exp={exp}&sig=x", base_url=host(A))
    assert r.status_code in (302, 401)


def test_unicode_digit_key_is_rejected(app):
    from app.services import file_storage as fs
    with app.app_context():
        assert fs.parse_key("١/student_docs/١/x.pdf") is None


def test_legacy_source_kept_when_commit_fails(app, two_schools, tmp_path, monkeypatch):
    """The public copy is removed only after the DB commit succeeds."""
    from app.blueprints import files as files_bp
    from app.extensions import db
    from app.models import Student
    monkeypatch.setitem(app.config, "UPLOAD_ROOT", str(tmp_path / "up"))
    A = two_schools["A"]
    src = tmp_path / "static" / "uploads" / "students" / str(A["student"].id) / "p.png"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 8)
    with app.app_context():
        s = db.session.get(Student, A["student"].id)
        s.photo_url = f"/static/uploads/students/{A['student'].id}/p.png"
        db.session.commit()

        def boom():
            raise RuntimeError("commit failed")
        monkeypatch.setattr(db.session, "commit", boom)
        with pytest.raises(RuntimeError):
            files_bp.migrate_static_uploads(tmp_path / "static")
        monkeypatch.undo()
        db.session.rollback()
        db.session.remove()
    assert src.exists()
