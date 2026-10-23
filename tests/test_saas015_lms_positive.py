"""SAAS-015 — the LMS / courses pages still open on school A's own records
after the switch to owned_or_404 (the cross-school attacks are in
test_saas002)."""

from __future__ import annotations

import pytest

from isolation_harness import build_url, host, hid
from test_saas002_route_isolation import ROUTE_MATRIX

OWN_PAGES = sorted(
    ep for ep, e in ROUTE_MATRIX.items()
    if ep.startswith(("lms.", "courses.")) and e.methods == ("GET",)
)


@pytest.fixture
def sapp(app, monkeypatch):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    return app


def test_there_are_own_pages_to_check():
    assert len(OWN_PAGES) >= 10


@pytest.mark.parametrize("endpoint", OWN_PAGES)
def test_own_page_opens(sapp, world, login_as, endpoint):
    A, B = world["A"], world["B"]
    entry = ROUTE_MATRIX[endpoint]
    role = entry.roles[-1]
    c = sapp.test_client()
    login_as(c, A["users"][role], base_url=host(A))
    url = build_url(sapp, endpoint, entry.ids(A), host(A))
    r = c.get(url, base_url=host(A))
    # course_pick_section jumps straight to the course when there is one.
    ok = (200, 302) if endpoint == "courses.course_pick_section" else (200,)
    assert r.status_code in ok, f"{endpoint} as {role}: {url} -> {r.status_code}"
    if r.status_code == 302:
        assert r.headers["Location"].startswith(("/", host(A)))
    assert not [m for m in B["markers"] if m in r.get_data(as_text=True)]


def test_own_references_in_forms_still_save(sapp, world, login_as):
    """The form ids now checked by owned_id still accept A's own rows."""
    from app.extensions import db
    from app.models import BankQuestion, CourseAssignment, Skill
    A = world["A"]
    c = sapp.test_client()
    login_as(c, A["users"]["admin"], base_url=host(A))
    r = c.post("/lms/bank/new", base_url=host(A), data={
        "prompt": "سؤال A", "kind": "short", "correct_short": "x",
        "subject_id": A["subject"].id, "grade_id": A["grade"].id, "term_id": A["term"].id,
        "unit_id": A["unit"], "lesson_id": A["lesson"], "passage_id": A["passage"]})
    assert r.status_code in (200, 302)
    r = c.post(f"/lms/assignments/{hid(A['assignment'])}/edit", base_url=host(A),
               data={"title": "تكليف A", "rubric_id": A["rubric"]})
    assert r.status_code in (200, 302)
    r = c.post("/lms/skills/new", base_url=host(A), data={"title": "فرعية", "parent_id": A["skill"]})
    assert r.status_code == 200
    with sapp.app_context():
        q = BankQuestion.query.filter_by(prompt="سؤال A").one()
        assert (q.passage_id, q.lesson_id, q.unit_id) == (A["passage"], A["lesson"], A["unit"])
        assert db.session.get(CourseAssignment, A["assignment"]).rubric_id == A["rubric"]
        assert Skill.query.filter_by(title="فرعية").one().parent_id == A["skill"]
        db.session.remove()
