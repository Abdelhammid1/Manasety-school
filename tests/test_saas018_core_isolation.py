"""SAAS-018 — academic / teachers / results / platform / admin / schedule /
nafis / messaging: the special cases of the ticket, and school A's own
pages still working (the cross-school matrix is in test_saas002)."""

from __future__ import annotations

import pytest

from isolation_harness import build_url, host
from test_saas002_route_isolation import ROUTE_MATRIX

PREFIXES = ("academic.", "admin.", "platform.", "teachers.", "results.", "schedule.",
            "nafis.", "messaging.")
OWN_PAGES = sorted(ep for ep, e in ROUTE_MATRIX.items()
                   if ep.startswith(PREFIXES) and e.methods == ("GET",))


@pytest.fixture
def sapp(app, monkeypatch):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    return app


def _admin(sapp, login_as, A):
    c = sapp.test_client()
    login_as(c, A["users"]["admin"], base_url=host(A))
    return c


@pytest.mark.parametrize("endpoint", OWN_PAGES)
def test_own_page_opens(sapp, world, login_as, endpoint):
    A, B = world["A"], world["B"]
    c = _admin(sapp, login_as, A)
    url = build_url(sapp, endpoint, ROUTE_MATRIX[endpoint].ids(A), host(A))
    r = c.get(url, base_url=host(A))
    assert r.status_code == 200, f"{endpoint}: {url} -> {r.status_code}"
    assert not [m for m in B["markers"] if m in r.get_data(as_text=True)]


def test_trash_restore_kind_is_a_fixed_whitelist(sapp, world, login_as):
    from app.extensions import db
    from app.models import Vendor
    from sqlalchemy import select
    A, B = world["A"], world["B"]
    c = _admin(sapp, login_as, A)
    for kind in ("users", "schools", "Vendor", "../vendors", "audit_logs"):
        r = c.post(f"/admin/trash/{kind}/{A['trash_vendor']}/restore", base_url=host(A))
        assert r.status_code == 404, kind
    assert c.post(f"/admin/trash/vendors/{B['trash_vendor']}/restore",
                  base_url=host(A)).status_code == 404
    assert c.post(f"/admin/trash/vendors/{A['trash_vendor']}/restore",
                  base_url=host(A)).status_code in (200, 302)
    with sapp.app_context():
        def deleted(vid):
            return db.session.execute(select(Vendor.__table__.c.deleted_at)
                                      .where(Vendor.__table__.c.id == vid)).scalar()
        assert deleted(A["trash_vendor"]) is None          # A's row restored
        assert deleted(B["trash_vendor"]) is not None      # B's row untouched
        db.session.remove()


@pytest.mark.parametrize("path", ["/admin/audit", "/platform/audit-log"])
def test_audit_log_shows_neither_other_schools_nor_platform_rows(sapp, world, login_as, path):
    from app.extensions import db
    from app.models import AuditLog
    A, B = world["A"], world["B"]
    with sapp.app_context():
        rows = [AuditLog(school_id=A["school"].id, action="update", entity_type="AuditOwn-alpha"),
                AuditLog(school_id=B["school"].id, action="update", entity_type="AuditOther-beta"),
                AuditLog(school_id=None, action="update", entity_type="AuditPlatform-null")]
        db.session.add_all(rows)
        db.session.commit()
        ids = [r.id for r in rows]
        db.session.remove()
    try:
        c = _admin(sapp, login_as, A)
        body = c.get(path, base_url=host(A)).get_data(as_text=True)
        assert "AuditOwn-alpha" in body
        assert "AuditOther-beta" not in body
        assert "AuditPlatform-null" not in body
    finally:
        with sapp.app_context():
            AuditLog.query.filter(AuditLog.id.in_(ids)).delete(synchronize_session=False)
            db.session.commit()
            db.session.remove()


def test_year_close_foreign_and_missing_are_a_real_404_with_a_way_back(sapp, world, login_as):
    A, B = world["A"], world["B"]
    c = _admin(sapp, login_as, A)
    foreign = c.get(f"/academic/years/{B['year'].id}/close", base_url=host(A))
    missing = c.get("/academic/years/999999/close", base_url=host(A))
    assert foreign.status_code == missing.status_code == 404
    assert "/academic/years" in foreign.get_data(as_text=True)
    assert c.get(f"/academic/years/{A['year'].id}/close", base_url=host(A)).status_code == 200


def test_bulk_operations_from_a_leave_b_untouched(sapp, world, login_as):
    """recompute_ranks / bulk_transfer / year_close run from A with B's
    ids anywhere: B's enrollment, year and results are unchanged."""
    from sqlalchemy import select
    from app.extensions import db
    from app.models import AcademicYear, Enrollment, YearResult
    A, B = world["A"], world["B"]

    def b_state():
        with sapp.app_context():
            e = db.session.execute(select(Enrollment.__table__).where(
                Enrollment.__table__.c.id == B["enrollment"].id)).mappings().one()
            y = db.session.execute(select(AcademicYear.__table__).where(
                AcademicYear.__table__.c.id == B["year"].id)).mappings().one()
            n = YearResult.query.filter_by(enrollment_id=B["enrollment"].id).count()
            db.session.remove()
            return dict(e), dict(y), n

    before = b_state()
    c = _admin(sapp, login_as, A)
    c.post(f"/results/section/{A['section'].id}/recompute-ranks", base_url=host(A))
    c.post(f"/results/section/{B['section'].id}/recompute-ranks", base_url=host(A))
    c.post(f"/academic/sections/{A['section'].id}/bulk-transfer", base_url=host(A),
           data={"target_section_id": B["section"].id, "enrollment_ids": [B["enrollment"].id]})
    c.post(f"/academic/years/{B['year'].id}/close", base_url=host(A), data={"confirm": "1"})
    assert b_state() == before


def test_bulk_transfer_with_one_foreign_id_writes_nothing(sapp, world, login_as):
    from app.extensions import db
    from app.models import Enrollment, Section
    A, B = world["A"], world["B"]
    with sapp.app_context():
        sec = Section(school_id=A["school"].id, year_id=A["year"].id, grade_id=A["grade"].id,
                      name="Sec2-alpha", capacity=30)
        db.session.add(sec)
        db.session.commit()
        target = sec.id
        db.session.remove()
    c = _admin(sapp, login_as, A)
    r = c.post(f"/academic/sections/{A['section'].id}/bulk-transfer", base_url=host(A),
               data={"target_section_id": target,
                     "enrollment_ids": [A["enrollment"].id, B["enrollment"].id]})
    assert r.status_code == 404
    with sapp.app_context():
        assert db.session.get(Enrollment, A["enrollment"].id).section_id == A["section"].id
        db.session.remove()
    r = c.post(f"/academic/sections/{A['section'].id}/bulk-transfer", base_url=host(A),
               data={"target_section_id": target, "enrollment_ids": [A["enrollment"].id]})
    assert r.status_code == 302
    with sapp.app_context():
        e = db.session.get(Enrollment, A["enrollment"].id)
        assert e.section_id == target
        e.section_id = A["section"].id
        db.session.commit()
        db.session.remove()


def test_slot_save_checks_every_reference(sapp, world, login_as):
    """day, period, subject, teacher, room: each one foreign on its own is
    refused, and A's own five still save a slot."""
    from app.extensions import db
    from app.models import ScheduleSlot
    A, B = world["A"], world["B"]
    own = {"day_id": A["day"], "period_id": A["period"], "subject_id": A["subject"].id,
           "teacher_id": A["teacher"], "room_id": A["room"]}
    foreign = {"day_id": B["day"], "period_id": B["period"], "subject_id": B["subject"].id,
               "teacher_id": B["teacher"], "room_id": B["room"]}
    c = _admin(sapp, login_as, A)
    url = f"/schedule/section/{A['section'].id}/slot"
    for key in own:
        r = c.post(url, base_url=host(A), data={**own, key: foreign[key]})
        assert r.status_code == 404, key
        assert not [m for m in B["markers"] if m in r.get_data(as_text=True)], key
    assert c.post(url, base_url=host(A), data=own).status_code == 302
    with sapp.app_context():
        slot = ScheduleSlot.query.filter_by(section_id=A["section"].id, day_id=A["day"],
                                            period_id=A["period"]).one()
        assert (slot.teacher_id, slot.room_id) == (A["teacher"], A["room"])
        db.session.remove()


def test_components_refuse_another_schools_quiz_as_source(sapp, world, login_as):
    from app.extensions import db
    from app.models import AssessmentComponent
    A, B = world["A"], world["B"]
    c = _admin(sapp, login_as, A)
    base = {"term_id": A["term"].id, "subject_id": A["subject"].id, "action": "add",
            "name": "مكون", "max_score": "10", "source_type": "lms_quiz", "auto_sync": "1"}
    assert c.post("/results/components", base_url=host(A),
                  data={**base, "source_id": B["quiz"]}).status_code == 404
    assert c.post("/results/components", base_url=host(A),
                  data={**base, "source_id": A["quiz"]}).status_code == 302
    with sapp.app_context():
        comps = AssessmentComponent.query.filter_by(school_id=A["school"].id, name="مكون").all()
        assert [x.source_id for x in comps] == [A["quiz"]]
        db.session.remove()
