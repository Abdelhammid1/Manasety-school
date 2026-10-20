"""SAAS-021 — school_id on the deep LMS chains (waves 2, 3, 4)."""

from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest

WAVES = {
    "wave2": {"lms_lessons", "lms_questions", "lms_quiz_attempts", "lms_submissions",
              "lms_assignment_questions", "lms_assignment_extensions",
              "lms_assignment_template_choices"},
    "wave3": {"lms_choices", "lms_attempt_flagged_questions", "lms_assignment_choices",
              "rubric_scores"},
    "wave4": {"lms_answers", "lms_assignment_answers"},
}


def _wave(label):
    path = next(Path(__file__).parents[1].glob(f"migrations/versions/*_saas021_school_id_{label}.py"))
    spec = importlib.util.spec_from_file_location(f"saas021_{label}", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("label", sorted(WAVES))
def test_each_migration_covers_exactly_its_wave(label):
    mod = _wave(label)
    wave = next(v for k, v in vars(mod).items() if k.startswith("WAVE"))
    assert {c.table for c in wave} == WAVES[label]


def test_waves_chain_in_depth_order():
    w2, w3, w4 = _wave("wave2"), _wave("wave3"), _wave("wave4")
    assert w2.down_revision == "k1t5v7x9z1b3"          # SAAS-020
    assert w3.down_revision == w2.revision
    assert w4.down_revision == w3.revision


def test_every_child_table_now_has_school_id(app):
    """With waves 1A..4 in, every table either carries school_id or is
    one of the two shared ones — nothing inherits any more."""
    from sqlalchemy import inspect
    from app.extensions import db
    from test_saas002_schema_gate import TENANT_INHERIT_MAP
    from app.services.tenant_guard import PLATFORM_TABLES
    with app.app_context():
        insp = inspect(db.engine)
        missing = [t for t in insp.get_table_names()
                   if "school_id" not in {c["name"] for c in insp.get_columns(t)}
                   and t not in TENANT_INHERIT_MAP and t not in PLATFORM_TABLES
                   and not t.startswith("sqlite_")]
    assert missing == []
    assert set(TENANT_INHERIT_MAP) == {"alembic_version", "schools"}


def test_quiz_attempt_answer_chain_carries_the_course_school(app, two_schools):
    from app.extensions import db
    from app.models import Answer, Choice, Course, Question, Quiz, QuizAttempt
    for key in ("A", "B"):
        X = two_schools[key]
        sid = X["school"].id
        with app.app_context():
            course = Course(school_id=sid, academic_year_id=X["year"].id,
                            grade_id=X["grade"].id, subject_id=X["subject"].id, title="C")
            db.session.add(course); db.session.flush()
            quiz = Quiz(course_id=course.id, title="Q")
            db.session.add(quiz); db.session.flush()
            q = Question(quiz_id=quiz.id, prompt="1+1?")
            db.session.add(q); db.session.flush()
            ch = Choice(question_id=q.id, label="2")
            att = QuizAttempt(quiz_id=quiz.id, student_id=X["student"].id)
            db.session.add_all([ch, att]); db.session.flush()
            ans = Answer(attempt_id=att.id, question_id=q.id, choice_id=ch.id)
            db.session.add(ans); db.session.commit()
            assert {q.school_id, ch.school_id, att.school_id, ans.school_id} == {sid}
            db.session.remove()


def test_rubric_score_on_a_grade_entry_uses_the_alternate_parent(app, two_schools):
    """rubric_scores belongs to a submission OR a grade entry; with only
    a grade entry the default must come from it, not the tenant."""
    from app.extensions import db
    from app.models import (
        AssessmentComponent, GradeEntry, Rubric, RubricCriterion, RubricScore,
    )
    B = two_schools["B"]
    sid = B["school"].id
    with app.app_context():
        comp = AssessmentComponent(school_id=sid, term_id=B["term"].id,
                                   subject_id=B["subject"].id, name="HW", max_score=10)
        rub = Rubric(school_id=sid, title="R")
        db.session.add_all([comp, rub]); db.session.flush()
        ge = GradeEntry(school_id=sid, enrollment_id=B["enrollment"].id,
                        component_id=comp.id, score=Decimal("7"))
        crit = RubricCriterion(rubric_id=rub.id, title="clarity")
        db.session.add_all([ge, crit]); db.session.flush()
        rs = RubricScore(criterion_id=crit.id, grade_entry_id=ge.id)
        db.session.add(rs); db.session.commit()
        assert rs.school_id == sid
        db.session.remove()
