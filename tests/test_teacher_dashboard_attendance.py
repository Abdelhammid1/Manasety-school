"""The teacher dashboard's 30-day attendance rate for the teacher's
sections. It used to filter on a column attendance rows don't have
(the section is on the enrollment): the error was swallowed and the
card always showed "—"."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from isolation_harness import host


@pytest.fixture
def tapp(app, monkeypatch):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    return app


def test_rate_counts_the_teachers_sections(tapp, world, login_as):
    from app.extensions import db
    from app.models import Attendance
    A = world["A"]
    today = date.today()
    with tapp.app_context():
        rows = [Attendance(school_id=A["school"].id, enrollment_id=A["enrollment"].id,
                           date=today - timedelta(days=d), status=s)
                for d, s in ((1, "present"), (2, "present"), (3, "present"), (4, "absent"))]
        db.session.add_all(rows); db.session.commit()
        ids = [r.id for r in rows]
        db.session.remove()
    try:
        c = tapp.test_client()
        login_as(c, A["users"]["teacher"], base_url=host(A))
        r = c.get("/dashboard", base_url=host(A), follow_redirects=True)
        assert r.status_code == 200
        assert "75.0٪" in r.get_data(as_text=True)
    finally:
        with tapp.app_context():
            Attendance.query.filter(Attendance.id.in_(ids)).delete(synchronize_session=False)
            db.session.commit()
            db.session.remove()
