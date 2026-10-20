"""SAAS-022 — ORM flush guard, TenantOwnedMixin default, integrity check."""

from __future__ import annotations

import time
from decimal import Decimal

import pytest
import sqlalchemy as sa


# ─── flush guard ─────────────────────────────────────────────────────

def test_new_row_pointing_at_other_schools_parent_is_refused(app, world):
    from app.extensions import db
    from app.models import InvoiceLine
    from app.services.tenant_guard import TenantIntegrityError
    A, B = world["A"], world["B"]
    with app.app_context():
        before = InvoiceLine.query.count()
        db.session.add(InvoiceLine(invoice_id=A["invoice"], fee_type_id=B["fee_type"],
                                   amount=Decimal("5")))
        with pytest.raises(TenantIntegrityError, match="invoice_lines.fee_type_id -> fee_types"):
            db.session.flush()
        db.session.rollback()
        assert InvoiceLine.query.count() == before
        db.session.remove()


def test_same_school_row_is_saved(app, world):
    from app.extensions import db
    from app.models import InvoiceLine
    A = world["A"]
    with app.app_context():
        line = InvoiceLine(invoice_id=A["invoice"], fee_type_id=A["fee_type"], amount=Decimal("5"))
        db.session.add(line)
        db.session.commit()
        assert line.school_id == A["school"].id
        db.session.remove()


def test_updating_an_fk_to_another_school_is_refused(app, world):
    from app.extensions import db
    from app.models import JournalLine
    from app.services.tenant_guard import TenantIntegrityError
    A, B = world["A"], world["B"]
    with app.app_context():
        jl = db.session.get(JournalLine, A["journal_line"])
        assert jl is not None
        jl.account_id = B["account"]
        with pytest.raises(TenantIntegrityError):
            db.session.flush()
        db.session.rollback()
        assert db.session.get(JournalLine, A["journal_line"]).account_id == A["account"]
        db.session.remove()


def test_junction_with_parents_from_two_schools_is_refused(app, two_schools):
    from app.extensions import db
    from app.models import Guardian, StudentGuardian
    from app.services.tenant_guard import TenantIntegrityError
    A, B = two_schools["A"], two_schools["B"]
    with app.app_context():
        g = Guardian(school_id=B["school"].id, full_name="G-beta")
        db.session.add(g); db.session.commit()
        db.session.add(StudentGuardian(student_id=A["student"].id, guardian_id=g.id))
        with pytest.raises(TenantIntegrityError, match="guardian_id -> guardians"):
            db.session.flush()
        db.session.rollback()
        db.session.remove()


def test_explicit_school_id_must_match_parent(app, world):
    from app.extensions import db
    from app.models import Installment
    from app.services.tenant_guard import TenantIntegrityError
    A, B = world["A"], world["B"]
    with app.app_context():
        db.session.add(Installment(invoice_id=A["invoice"], school_id=B["school"].id,
                                   due_date=world["A"]["year"].start_date,
                                   amount=Decimal("1")))
        with pytest.raises(TenantIntegrityError, match="installments.invoice_id -> invoices"):
            db.session.flush()
        db.session.rollback()
        db.session.remove()


def test_guard_edges_cover_multi_parent_tables(app):
    from app.services.tenant_guard import edges
    with app.app_context():
        got = {(e.child, e.column, e.parent) for e in edges()}
    for expected in [
        ("invoice_lines", "fee_type_id", "fee_types"),
        ("journal_lines", "account_id", "accounts"),
        ("student_guardians", "guardian_id", "guardians"),
        ("lms_answers", "choice_id", "lms_choices"),
        ("rubric_scores", "grade_entry_id", "grade_entries"),
    ]:
        assert expected in got, expected


# ─── TenantOwnedMixin default ────────────────────────────────────────

def test_mixin_default_needs_a_tenant(app, two_schools):
    from app.models.mixins import TenantOwnedMixin, _current_tenant_school
    from app.services.tenancy import TenantNotResolved, tenant_context
    assert "school_id" in TenantOwnedMixin.__dict__
    with app.app_context():
        with pytest.raises(TenantNotResolved):
            _current_tenant_school()
        with tenant_context(two_schools["A"]["school"].id):
            assert _current_tenant_school() == two_schools["A"]["school"].id


# ─── integrity check ─────────────────────────────────────────────────

def test_integrity_check_clean_then_catches_bulk_update(app, world):
    """Raw / bulk SQL skips the ORM guard; the check catches it."""
    from app.extensions import db
    A, B = world["A"], world["B"]
    runner = app.test_cli_runner()
    clean = runner.invoke(args=["tenant-integrity-check"])
    assert clean.exit_code == 0, clean.output
    with app.app_context():
        db.session.execute(sa.text("UPDATE journal_lines SET account_id = :b WHERE id = :l"),
                           {"b": B["account"], "l": A["journal_line"]})
        db.session.commit()
        db.session.remove()
    try:
        dirty = runner.invoke(args=["tenant-integrity-check"])
        assert dirty.exit_code == 1
        assert "VIOLATION journal_lines.account_id -> accounts: 1" in dirty.output
    finally:
        with app.app_context():
            db.session.execute(sa.text("UPDATE journal_lines SET account_id = :a WHERE id = :l"),
                               {"a": A["account"], "l": A["journal_line"]})
            db.session.commit()
            db.session.remove()


# ─── schema gate ─────────────────────────────────────────────────────

def test_only_shared_tables_may_skip_school_id():
    from test_saas002_schema_gate import TENANT_INHERIT_MAP
    inheriting = [t for t, (p, _w) in TENANT_INHERIT_MAP.items() if p != "__shared__"]
    assert inheriting == [], (
        "New tables must carry school_id directly (SAAS-022); "
        f"found inheriting entries: {inheriting}")


# ─── performance ─────────────────────────────────────────────────────

def test_guard_overhead_on_a_quiz_attempt(app, two_schools, capsys):
    """Write a 20-answer attempt with and without the guard; recorded for
    the PR, and bounded loosely so a pathological regression fails."""
    from sqlalchemy import event
    from app.extensions import db
    from app.models import Answer, Choice, Course, Question, Quiz, QuizAttempt
    from app.services.tenant_guard import _before_flush
    A = two_schools["A"]
    with app.app_context():
        course = Course(school_id=A["school"].id, academic_year_id=A["year"].id,
                        grade_id=A["grade"].id, subject_id=A["subject"].id, title="P")
        db.session.add(course); db.session.flush()
        quiz = Quiz(course_id=course.id, title="P")
        db.session.add(quiz); db.session.flush()
        qs = [Question(quiz_id=quiz.id, prompt=f"q{i}") for i in range(20)]
        db.session.add_all(qs); db.session.flush()
        cs = [Choice(question_id=q.id, label="a") for q in qs]
        db.session.add_all(cs); db.session.commit()
        q_ids, c_ids = [q.id for q in qs], [c.id for c in cs]

        def write():
            att = QuizAttempt(quiz_id=quiz.id, student_id=A["student"].id)
            db.session.add(att); db.session.flush()
            db.session.add_all([Answer(attempt_id=att.id, question_id=q, choice_id=c)
                                for q, c in zip(q_ids, c_ids)])
            t0 = time.perf_counter()
            db.session.commit()
            return time.perf_counter() - t0

        guarded = min(write() for _ in range(3))
        event.remove(db.session, "before_flush", _before_flush)
        try:
            bare = min(write() for _ in range(3))
        finally:
            event.listen(db.session, "before_flush", _before_flush)
        db.session.remove()
    with capsys.disabled():
        print(f"\n[SAAS-022] 20-answer attempt commit: guard {guarded*1000:.1f} ms, "
              f"no guard {bare*1000:.1f} ms")
    assert guarded < 2.0


# ─── security review follow-ups (fail-closed paths) ─────────────────

def test_parent_set_through_relationship_is_checked(app, world):
    """`line.fee_type = obj` leaves fee_type_id empty until flush; the
    guard must read the relationship, not just the column."""
    from app.extensions import db
    from app.models import FeeType, InvoiceLine
    from app.services.tenant_guard import TenantIntegrityError
    A, B = world["A"], world["B"]
    with app.app_context():
        line = InvoiceLine(invoice_id=A["invoice"], amount=Decimal("5"))
        line.fee_type = db.session.get(FeeType, B["fee_type"])
        db.session.add(line)
        with pytest.raises(TenantIntegrityError, match="fee_type_id -> fee_types"):
            db.session.flush()
        db.session.rollback()
        db.session.remove()


def test_relationship_reassigned_on_saved_row_is_checked(app, world):
    from app.extensions import db
    from app.models import FeeType, InvoiceLine
    from app.services.tenant_guard import TenantIntegrityError
    A, B = world["A"], world["B"]
    with app.app_context():
        line = InvoiceLine.query.filter_by(invoice_id=A["invoice"]).first()
        assert line is not None
        _ = line.fee_type                     # loaded: A's fee type
        line.fee_type = db.session.get(FeeType, B["fee_type"])   # column still A's
        with pytest.raises(TenantIntegrityError):
            db.session.flush()
        db.session.rollback()
        db.session.remove()


def test_soft_deleted_parent_of_other_school_is_still_refused(app, world):
    from datetime import date, datetime, timezone
    from app.extensions import db
    from app.models import Expense, Vendor
    from app.services.tenant_guard import TenantIntegrityError
    A, B = world["A"], world["B"]
    with app.app_context():
        v = db.session.get(Vendor, B["vendor"])
        assert v is not None
        v.deleted_at = datetime.now(timezone.utc)
        db.session.commit()
        db.session.add(Expense(school_id=A["school"].id, vendor_id=B["vendor"],
                               expense_account_id=A["account"], cash_account_id=A["account"],
                               date=date(2026, 9, 9), amount=Decimal("1"), description="x"))
        with pytest.raises(TenantIntegrityError, match="vendor_id -> vendors"):
            db.session.flush()
        db.session.rollback()
        db.session.remove()


def test_nonexistent_parent_is_refused(app, world):
    from app.extensions import db
    from app.models import InvoiceLine
    from app.services.tenant_guard import TenantIntegrityError
    A = world["A"]
    with app.app_context():
        db.session.add(InvoiceLine(invoice_id=A["invoice"], fee_type_id=987654,
                                   amount=Decimal("1")))
        with pytest.raises(TenantIntegrityError, match="does not exist"):
            db.session.flush()
        db.session.rollback()
        db.session.remove()


def test_self_reference_across_schools_is_refused(app, world):
    """accounts.parent_id -> accounts: a child account under another
    school's parent."""
    from app.extensions import db
    from app.models import Account
    from app.services.tenant_guard import TenantIntegrityError, edges
    A, B = world["A"], world["B"]
    with app.app_context():
        assert ("accounts", "parent_id", "accounts") in {(e.child, e.column, e.parent) for e in edges()}
        db.session.add(Account(school_id=A["school"].id, code="9999", name="x", type="asset",
                               parent_id=B["account"]))
        with pytest.raises(TenantIntegrityError, match="accounts.parent_id -> accounts"):
            db.session.flush()
        db.session.rollback()
        db.session.remove()
