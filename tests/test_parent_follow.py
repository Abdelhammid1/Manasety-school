"""Parent portal follow-up pages: read-only invoices / attendance / grades.
A parent sees only their own children; everything else is 403/404."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from isolation_harness import hid, host

NOKIDS = "\u0644\u0627 \u064a\u0648\u062c\u062f \u0623\u0628\u0646\u0627\u0621"
INV_LIST = "/portal/follow/invoices"
ATT = "/portal/follow/attendance"
GR = "/portal/follow/grades"
PAGES = (INV_LIST, ATT, GR)


@pytest.fixture
def papp(app, monkeypatch):
    monkeypatch.setitem(app.config, "TENANT_RESOLUTION_MODE", "enforce")
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
    return app


@pytest.fixture
def fam(papp, world):
    from app.extensions import db
    from app.models import (Account, Attendance, Enrollment, Invoice, Payment,
                            Role, Student, Subject, Term)
    from app.models.results import AssessmentComponent, GradeEntry

    A, B = world["A"], world["B"]
    sid, pid = A["school"].id, A["users"]["parent"].id
    slug = A["school"].slug
    with papp.app_context():
        # production state: a parent holds portal.view only
        for b in (A, B):
            r = Role.query.filter_by(school_id=b["school"].id, name="parent").one()
            r.permissions = {"portal": ["view"]}
        enr1 = Enrollment.query.filter_by(school_id=sid, student_id=A["student"].id).first()
        kid1 = db.session.get(Student, enr1.student_id)

        def mk_kid(code, name, parent_id):
            s = Student(school_id=sid, permanent_code=code, full_name=name, parent_user_id=parent_id)
            db.session.add(s); db.session.flush()
            e = Enrollment(school_id=sid, student_id=s.id, year_id=enr1.year_id, grade_id=enr1.grade_id,
                           section_id=enr1.section_id, status="active", enrolled_at=date(2026, 9, 1))
            db.session.add(e); db.session.flush()
            return s, e

        kid2, enr2 = mk_kid("PC-A-02", "KidTwo-A", pid)
        stranger, enr3 = mk_kid("PC-A-03", "Stranger-A", None)

        def mk_inv(enr, number, status):
            i = Invoice(school_id=sid, enrollment_id=enr.id, number=number, issue_date=date(2026, 9, 2),
                        due_date=date(2026, 10, 2), status=status, total_amount=Decimal("200"),
                        paid_amount=Decimal("0"))
            db.session.add(i); db.session.flush()
            return i

        inv1 = Invoice.query.filter_by(school_id=sid, number=f"INV-{slug}").one()
        inv1.paid_amount = Decimal("40")
        inv2 = mk_inv(enr2, "INV-A-KID2", "sent")
        inv_x = mk_inv(enr3, "INV-A-STRANGER", "sent")
        inv_d = mk_inv(enr1, "INV-A-DRAFT", "draft")
        cash = Account.query.filter_by(school_id=sid, code="1101").one()
        db.session.add(Payment(school_id=sid, invoice_id=inv1.id, payment_date=date(2026, 9, 10),
                               amount=Decimal("40"), method="cash", cash_account_id=cash.id,
                               reference="REF-PAY-1"))
        db.session.add(Attendance(school_id=sid, enrollment_id=enr1.id, date=date.today(), status="late"))
        db.session.add(Attendance(school_id=sid, enrollment_id=enr1.id,
                                  date=date.today() - timedelta(days=1), status="excused",
                                  excuse_reason="SICK-REASON"))
        db.session.add(Attendance(school_id=sid, enrollment_id=enr3.id, date=date.today(), status="absent",
                                  notes="x"))
        term = Term.query.filter_by(school_id=sid).first()
        subj = Subject.query.filter_by(school_id=sid).first()
        c1 = AssessmentComponent(school_id=sid, term_id=term.id, subject_id=subj.id,
                                 name="COMP-QUIZ", max_score=Decimal("20"))
        c2 = AssessmentComponent(school_id=sid, term_id=term.id, subject_id=subj.id,
                                 name="COMP-STRANGER", max_score=Decimal("20"))
        db.session.add_all([c1, c2]); db.session.flush()
        db.session.add(GradeEntry(school_id=sid, enrollment_id=enr1.id, component_id=c1.id, score=Decimal("18")))
        db.session.add(GradeEntry(school_id=sid, enrollment_id=enr3.id, component_id=c2.id, score=Decimal("7.77")))
        inv_b = Invoice.query.filter_by(school_id=B["school"].id, number=f"INV-{B['school'].slug}").one()
        db.session.commit()
        out = {"A": A, "B": B, "kid1": kid1.id, "kid2": kid2.id, "stranger": stranger.id,
               "inv1": inv1.id, "inv2": inv2.id, "inv_x": inv_x.id, "inv_d": inv_d.id, "inv_b": inv_b.id,
               "kid1_name": kid1.full_name, "b_invnum": inv_b.number, "b_kid": B["student"].id}
        db.session.remove()
    return out


def _client(app, login_as, bundle, role="parent"):
    c = app.test_client()
    login_as(c, bundle["users"][role], base_url=host(bundle))
    return c


def _get(c, bundle, path):
    return c.get(path, base_url=host(bundle))


def test_parent_sees_own_children_only(papp, fam, login_as):
    A = fam["A"]
    c = _client(papp, login_as, A)
    body = _get(c, A, INV_LIST).data.decode()
    assert _get(c, A, INV_LIST).status_code == 200
    assert "INV-alpha" in body and "INV-A-KID2" in body
    assert "INV-A-STRANGER" not in body and "INV-A-DRAFT" not in body and fam["b_invnum"] not in body
    assert "/portal/follow/invoices/" in body
    r = _get(c, A, ATT + "?child_id=%d&days=7" % fam["kid1"])
    page = r.data.decode()
    assert r.status_code == 200 and "SICK-REASON" in page
    r = _get(c, A, GR + "?child_id=%d" % fam["kid1"])
    page = r.data.decode()
    assert r.status_code == 200 and "COMP-QUIZ" in page and "18 / 20" in page and "COMP-STRANGER" not in page


def test_default_pages_render_for_a_parent_with_two_children(papp, fam, login_as):
    A = fam["A"]
    c = _client(papp, login_as, A)
    for p in PAGES:
        r = _get(c, A, p)
        assert r.status_code == 200, p
        assert "Stranger-A" not in r.data.decode(), p


def test_invoice_detail_shows_lines_installments_and_payments_read_only(papp, fam, login_as):
    A = fam["A"]
    c = _client(papp, login_as, A)
    r = _get(c, A, "/portal/follow/invoices/" + hid(fam["inv1"]))
    body = r.data.decode()
    assert r.status_code == 200 and "INV-alpha" in body and "REF-PAY-1" in body
    assert "<form" not in body.split("</header>")[-1] or "method=\"post\"" not in body.lower().split("<main")[-1]


@pytest.mark.parametrize("key", ["inv_x", "inv_d", "inv_b"])
def test_invoice_idor_is_404(papp, fam, login_as, key):
    A = fam["A"]
    c = _client(papp, login_as, A)
    r = _get(c, A, "/portal/follow/invoices/" + hid(fam[key]))
    assert r.status_code == 404
    assert "INV-A-STRANGER" not in r.data.decode()


@pytest.mark.parametrize("path", [INV_LIST, ATT, GR])
@pytest.mark.parametrize("which", ["stranger", "b_kid", "999999", "abc"])
def test_foreign_or_bad_child_id_is_404(papp, fam, login_as, path, which):
    A = fam["A"]
    cid = fam[which] if which in fam else which
    c = _client(papp, login_as, A)
    assert _get(c, A, f"{path}?child_id={cid}").status_code == 404


@pytest.mark.parametrize("role", ["teacher", "student"])
@pytest.mark.parametrize("path", [INV_LIST, ATT, GR])
def test_non_parents_get_403(papp, fam, login_as, role, path):
    A = fam["A"]
    c = _client(papp, login_as, A, role)
    assert _get(c, A, path).status_code == 403
    assert _get(c, A, "/portal/follow/invoices/" + hid(fam["inv1"])).status_code == 403


@pytest.mark.parametrize("path", PAGES)
def test_pages_are_read_only(papp, fam, login_as, path):
    A = fam["A"]
    c = _client(papp, login_as, A)
    assert c.post(path, base_url=host(A), data={}).status_code == 405


def test_other_school_parent_cannot_open_a_invoice(papp, fam, login_as):
    B = fam["B"]
    c = _client(papp, login_as, B)
    r = _get(c, B, "/portal/follow/invoices/" + hid(fam["inv1"]))
    assert r.status_code == 404


def test_parent_without_children_sees_a_message_not_an_error(papp, fam, login_as):
    from app.extensions import db
    from app.models import Student
    A = fam["A"]
    with papp.app_context():
        for s in Student.query.filter_by(school_id=A["school"].id, parent_user_id=A["users"]["parent"].id):
            s.parent_user_id = None
        db.session.commit()
        db.session.remove()
    c = _client(papp, login_as, A)
    for p in PAGES:
        r = _get(c, A, p)
        assert r.status_code == 200, p
        assert NOKIDS in r.data.decode(), p


def test_dashboard_links_and_invoice_number(papp, fam, login_as):
    A = fam["A"]
    c = _client(papp, login_as, A)
    r = _get(c, A, "/dashboard")
    body = r.data.decode()
    assert r.status_code == 200
    assert "INV-alpha" in body
    assert "\u0641\u0627\u062a\u0648\u0631\u0629 #" not in body
    for p in (INV_LIST, ATT, GR, "/portal/follow/invoices/"):
        assert p in body, p
