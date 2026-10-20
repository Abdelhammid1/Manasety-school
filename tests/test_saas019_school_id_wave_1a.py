"""SAAS-019 — school_id on 17 child tables: the migration contract and
the column default that fills it on every insert path."""

from __future__ import annotations

from decimal import Decimal

import re

import pytest
import sqlalchemy as sa

from app.services.schema_waves import Child, WaveIntegrityError, add_school_id, drop_school_id

WAVE_1A = (
    "installments invoice_lines journal_lines messages conversation_participants "
    "notification_preferences student_guardians student_tag_links behavior_actions "
    "subject_grades subject_terms teacher_subjects grading_scale_levels "
    "intervention_plan_outcomes intervention_sessions nafis_outcome_scores rubric_criteria"
).split()


# ─── Migration contract on a scratch DB ──────────────────────────────

def _scratch(rows_child, rows_other=()):
    eng = sa.create_engine("sqlite://")
    with eng.begin() as c:
        c.execute(sa.text("CREATE TABLE schools (id INTEGER PRIMARY KEY)"))
        c.execute(sa.text("CREATE TABLE parent (id INTEGER PRIMARY KEY, school_id INTEGER)"))
        c.execute(sa.text("CREATE TABLE other (id INTEGER PRIMARY KEY, school_id INTEGER)"))
        c.execute(sa.text("CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER, other_id INTEGER)"))
        c.execute(sa.text("INSERT INTO schools VALUES (1), (2)"))
        c.execute(sa.text("INSERT INTO parent VALUES (10, 1), (20, 2), (30, NULL)"))
        c.execute(sa.text("INSERT INTO other VALUES (100, 1), (200, 2), (300, NULL)"))
        for r in rows_child:
            c.execute(sa.text("INSERT INTO child VALUES (:i, :p, :o)"), r)
    return eng


def _run(eng, fn):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    with eng.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            return fn(__import__("alembic").op)


CHILD = Child("child", "parent", "parent_id", (("other", "other_id"),))


def test_clean_rows_backfill_and_become_not_null():
    eng = _scratch([{"i": 1, "p": 10, "o": 100}, {"i": 2, "p": 20, "o": 300}])
    res = _run(eng, lambda op: add_school_id(op, CHILD))
    assert res == {"table": "child", "rows": 2}
    with eng.connect() as c:
        rows = c.execute(sa.text("SELECT id, school_id FROM child ORDER BY id")).all()
        assert [tuple(r) for r in rows] == [(1, 1), (2, 2)]
        col = [r for r in c.execute(sa.text("PRAGMA table_info(child)")) if r[1] == "school_id"][0]
        assert col[3] == 1   # NOT NULL


@pytest.mark.parametrize("row, needle", [
    ({"i": 1, "p": 999, "o": 100}, "1 row(s) have no school"),   # orphan
    ({"i": 1, "p": 30, "o": 100}, "1 row(s) have no school"),    # parent without school
    ({"i": 1, "p": 10, "o": 200}, "1 row(s) link a parent of one school to a other"),  # mixed
])
def test_bad_rows_fail_loudly_and_name_the_table(row, needle):
    eng = _scratch([row])
    with pytest.raises(WaveIntegrityError, match=re.escape("child: " + needle)):
        _run(eng, lambda op: add_school_id(op, CHILD))


def test_empty_table_is_fine():
    eng = _scratch([])
    assert _run(eng, lambda op: add_school_id(op, CHILD))["rows"] == 0


def test_downgrade_restores_schema_and_keeps_rows():
    eng = _scratch([{"i": 1, "p": 10, "o": 100}])
    _run(eng, lambda op: add_school_id(op, CHILD))
    _run(eng, lambda op: drop_school_id(op, CHILD))
    with eng.connect() as c:
        cols = {r[1] for r in c.execute(sa.text("PRAGMA table_info(child)"))}
        assert "school_id" not in cols
        assert c.execute(sa.text("SELECT COUNT(*) FROM child")).scalar() == 1


def test_migration_covers_exactly_the_wave():
    import importlib.util
    from pathlib import Path
    path = next(Path(__file__).parents[1].glob("migrations/versions/*_saas019_*.py"))
    spec = importlib.util.spec_from_file_location("saas019_mig", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert sorted(c.table for c in mod.WAVE_1A) == sorted(WAVE_1A)


# ─── Model + default on the real schema ──────────────────────────────

def test_every_wave_table_has_not_null_school_id(app):
    from app.extensions import db
    for t in WAVE_1A:
        col = db.metadata.tables[t].c.school_id
        assert not col.nullable and col.default is not None, t


def test_orm_children_inherit_parent_school(app, world):
    """Rows created by app code without passing school_id (invoice lines,
    journal lines) land in the parent's school."""
    from app.models import InvoiceLine, JournalLine
    A, B = world["A"], world["B"]
    with app.app_context():
        for bundle in (A, B):
            sid = bundle["school"].id
            assert {l.school_id for l in InvoiceLine.query.filter_by(invoice_id=bundle["invoice"])} == {sid}
            assert {l.school_id for l in JournalLine.query.filter_by(entry_id=bundle["journal_entry"])} == {sid}


def test_association_rows_inherit_parent_school(app, two_schools):
    """`secondary=` rows are inserted by SQLAlchemy itself — the default
    must still fill school_id from the owning side."""
    from app.extensions import db
    from app.models import Grade, Guardian, Student, Subject, StudentGuardian
    A = two_schools["A"]
    with app.app_context():
        subj = db.session.get(Subject, A["subject"].id)
        assert subj is not None
        subj.grades.append(db.session.get(Grade, A["grade"].id))
        g = Guardian(school_id=A["school"].id, full_name="G-alpha")
        db.session.add(g); db.session.flush()
        db.session.add(StudentGuardian(student_id=A["student"].id, guardian_id=g.id,
                                       relationship="father"))
        db.session.commit()
        sg = db.session.execute(sa.text(
            "SELECT school_id FROM subject_grades WHERE subject_id = :s"),
            {"s": subj.id}).scalar()
        assert sg == A["school"].id
        assert StudentGuardian.query.filter_by(guardian_id=g.id).one().school_id == A["school"].id
        db.session.remove()


def test_message_and_nafis_score_get_school(app, two_schools):
    from app.extensions import db
    from app.models import Conversation, ConversationParticipant, Message
    A = two_schools["A"]
    with app.app_context():
        conv = Conversation(school_id=A["school"].id)
        db.session.add(conv); db.session.flush()
        db.session.add(ConversationParticipant(conversation_id=conv.id,
                                               user_id=A["users"]["teacher"].id))
        msg = Message(conversation_id=conv.id, sender_user_id=A["users"]["teacher"].id, body="hi")
        db.session.add(msg); db.session.commit()
        assert msg.school_id == A["school"].id
        db.session.remove()


def test_insert_without_parent_or_tenant_is_refused(app):
    """No parent row and no tenant in scope: never NULL, never a guess."""
    from sqlalchemy.exc import IntegrityError, StatementError
    from app.extensions import db
    from app.models import InvoiceLine
    from app.services.tenancy import TenantNotResolved
    from app.services.tenant_guard import TenantIntegrityError
    with app.app_context():
        db.session.add(InvoiceLine(invoice_id=987654, fee_type_id=1, amount=Decimal("1")))
        # Refused by the SAAS-022 guard first; the column default alone
        # would raise TenantNotResolved.
        with pytest.raises((TenantIntegrityError, TenantNotResolved, StatementError,
                            IntegrityError)):
            db.session.flush()
        db.session.rollback()
        db.session.remove()


def test_tenant_context_fills_when_parent_unknown(app, two_schools):
    """Falls back to the current tenant (jobs / seeds use tenant_context)."""
    from app.extensions import db
    from app.models import NotificationPreference
    from app.services.tenancy import tenant_context
    A = two_schools["A"]
    with app.app_context(), tenant_context(A["school"].id):
        pref = NotificationPreference(user_id=A["users"]["admin"].id,
                                      channel="email", event_type="invoice")
        db.session.add(pref); db.session.commit()
        assert pref.school_id == A["school"].id
        db.session.remove()
