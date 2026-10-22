"""SAAS-041 — `flask seed-test-schools`: two test schools on their own
hosts, known accounts printed, integrity checked, idempotent, reset /
teardown, and refusals (production, a school it didn't create)."""

from __future__ import annotations

import re
import time

import pytest



@pytest.fixture
def sapp(app, monkeypatch, tmp_path):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    yield app
    from app.extensions import db
    from app.services import test_seed as ts
    with app.app_context():
        ts.teardown()
        db.session.remove()


def _backup(tmp_path):
    f = tmp_path / "dump.sql"
    f.write_text("-- fresh dump")
    return str(f)


def _run(app, tmp_path, *args):
    res = app.test_cli_runner().invoke(args=["seed-test-schools", "--small", "--backup-file",
                                             _backup(tmp_path), "--accounts-file",
                                             str(tmp_path / "acc.txt"), *args])
    return res


def _accounts(output):
    """{slug: {role: (user, password)}} from the printed block."""
    out, cur = {}, None
    for line in output.splitlines():
        m = re.match(r"\s+(test-[ab]): https://\S+/auth/login", line)
        if m:
            cur = out.setdefault(m.group(1), {})
            continue
        m = re.match(r"\s+(admin|teacher|student|parent)\s+(\S+)\s+(\S+)$", line)
        if m and cur is not None:
            cur[m.group(1)] = (m.group(2), m.group(3))
    return out


def test_builds_both_schools_on_their_hosts_and_prints_logins(sapp, tmp_path):
    started = time.monotonic()
    res = _run(sapp, tmp_path)
    assert res.exit_code == 0, res.output
    assert time.monotonic() - started < 300
    assert "integrity: OK - 0 problems" in res.output
    for slug in ("test-a", "test-b"):
        assert f"https://{slug}.manasety.ai/auth/login" in res.output
    acc = _accounts(res.output)
    assert set(acc) == {"test-a", "test-b"}
    for slug in acc:
        assert set(acc[slug]) == {"admin", "teacher", "student", "parent"}
    # the same block is in the accounts file (outside git)
    text = (tmp_path / "acc.txt").read_text(encoding="utf-8")
    assert acc["test-a"]["admin"][1] in text and "keep out of git" in text
    # passwords are random per run, never the same in both schools
    assert acc["test-a"]["admin"][1] != acc["test-b"]["admin"][1]
    # each school is reachable on its own host and resolves to itself
    from app.extensions import db
    from app.models import PlatformJob, School
    from app.services.tenancy import resolve_host
    with sapp.app_context():
        for slug in ("test-a", "test-b"):
            r = resolve_host(f"{slug}.manasety.ai")
            assert r.kind == "tenant" and r.school.slug == slug
        ids = [s.id for s in School.query.filter(School.slug.in_(("test-a", "test-b")))]
        assert PlatformJob.query.filter(PlatformJob.kind == "nginx_sync",
                                        PlatformJob.status == "pending").count() >= 1
        db.session.remove()
    assert len(ids) == 2


def test_each_admin_sees_only_their_school(sapp, tmp_path):
    res = _run(sapp, tmp_path)
    assert res.exit_code == 0, res.output
    acc = _accounts(res.output)
    for slug, mine, other in (("test-a", "TA ", "TB "), ("test-b", "TB ", "TA ")):
        c = sapp.test_client()
        user, pw = acc[slug]["admin"]
        r = c.post("/auth/login", base_url=f"http://{slug}.manasety.ai",
                   data={"username": user, "password": pw})
        assert r.status_code == 302, r.data[:300]
        page = c.get("/students", base_url=f"http://{slug}.manasety.ai", follow_redirects=True)
        html = page.get_data(as_text=True)
        assert page.status_code == 200 and mine in html and other not in html
        # the other school's password doesn't work here
        other_slug = "test-b" if slug == "test-a" else "test-a"
        r = sapp.test_client().post("/auth/login", base_url=f"http://{slug}.manasety.ai",
                                    data={"username": "admin", "password": acc[other_slug]["admin"][1]})
        assert r.status_code != 302


def test_the_schools_share_nothing(sapp, tmp_path):
    from app.extensions import db
    from app.models import School
    from app.services import test_seed as ts
    from app.services.tenant_guard import integrity_report
    assert _run(sapp, tmp_path).exit_code == 0
    with sapp.app_context():
        ids = [s.id for s in School.query.filter(School.slug.in_(ts.TEST_SLUGS))]
        assert ts.integrity(ids) == []
        assert not {k: v for k, v in integrity_report().items() if v}
        # every tenant row belongs to exactly one of them, tagged with it
        from app.models import Course, Invoice, Student
        for sid, tag in zip(sorted(ids), ("TA", "TB")):
            assert all(s.full_name.startswith(tag) for s in Student.query.filter_by(school_id=sid))
            assert all(tag in c.title for c in Course.query.filter_by(school_id=sid))
            assert Invoice.query.filter_by(school_id=sid).count() > 0
        db.session.remove()


def test_second_run_skips_reset_rebuilds_teardown_removes(sapp, tmp_path):
    from app.extensions import db
    from app.models import School, Student
    assert _run(sapp, tmp_path).exit_code == 0
    with sapp.app_context():
        first = sorted(s.id for s in School.query.filter(School.slug.in_(("test-a", "test-b"))))
        n_students = Student.query.filter(Student.school_id.in_(first)).count()
        db.session.remove()
    res = _run(sapp, tmp_path)
    assert res.exit_code == 0 and res.output.count("already present") == 2
    with sapp.app_context():
        assert Student.query.filter(Student.school_id.in_(first)).count() == n_students   # untouched
        db.session.remove()
    res = _run(sapp, tmp_path, "--reset")
    assert res.exit_code == 0, res.output
    with sapp.app_context():
        second = sorted(s.id for s in School.query.filter(School.slug.in_(("test-a", "test-b"))))
        assert len(second) == 2
        db.session.remove()
    res = _run(sapp, tmp_path, "--teardown")
    assert res.exit_code == 0, res.output
    with sapp.app_context():
        assert School.query.filter(School.slug.in_(("test-a", "test-b"))).count() == 0
        assert Student.query.filter(Student.school_id.in_(second)).count() == 0
        db.session.remove()


def test_refuses_a_test_slug_it_did_not_create(sapp, tmp_path):
    from app.extensions import db
    from app.models import School
    with sapp.app_context():
        s = School(code="FOREIGN-TA", name="ليست مدرسة اختبار", slug="test-a", status="active", is_active=True)
        db.session.add(s)
        db.session.commit()
        sid = s.id
    try:
        for args in ((), ("--reset",), ("--teardown",)):
            res = _run(sapp, tmp_path, *args)
            assert res.exit_code != 0 and "not created by seed-test-schools" in res.output
        with sapp.app_context():
            assert db.session.get(School, sid) is not None
    finally:
        with sapp.app_context():
            db.session.delete(db.session.get(School, sid))
            db.session.commit()
            db.session.remove()


def test_production_needs_i_know_and_writes_need_a_backup(sapp, tmp_path, monkeypatch):
    monkeypatch.setitem(sapp.config, "APP_ENV", "production")
    res = sapp.test_cli_runner().invoke(args=["seed-test-schools", "--small"])
    assert res.exit_code != 0 and "--i-know" in res.output
    monkeypatch.setitem(sapp.config, "APP_ENV", "development")
    stale = tmp_path / "old.sql"
    stale.write_text("x")
    import os
    os.utime(stale, (time.time() - 7200,) * 2)
    res = sapp.test_cli_runner().invoke(args=["seed-test-schools", "--small", "--backup-file", str(stale)])
    assert res.exit_code != 0 and "older than 1 hour" in res.output


def test_full_size_is_the_default(sapp):
    res = sapp.test_cli_runner().invoke(args=["seed-test-schools", "--dry-run"])
    assert res.exit_code == 0, res.output
    assert "students=40" in res.output and "grades=3" in res.output
    assert "https://test-a.manasety.ai/auth/login" in res.output


def test_mode_note_reads_the_same_setting_as_the_service(app, monkeypatch, tmp_path):
    """The service gets TENANT_RESOLUTION_MODE from the environment (.env);
    the seed's closing note must not say "off" then (Abdelhamid's report)."""
    monkeypatch.delitem(app.config, "TENANT_RESOLUTION_MODE", raising=False)
    monkeypatch.setenv("TENANT_RESOLUTION_MODE", "enforce")
    acc = tmp_path / "acc.txt"
    res = app.test_cli_runner().invoke(args=["seed-test-schools", "--small", "--backup-file", _backup(tmp_path),
                                             "--accounts-file", str(acc)])
    try:
        assert res.exit_code == 0, res.output
        assert "TENANT_RESOLUTION_MODE=off" not in res.output
        assert "(now: enforce)" in acc.read_text(encoding="utf-8")
    finally:
        from app.extensions import db
        from app.services import test_seed as ts
        with app.app_context():
            ts.teardown()
            db.session.remove()
