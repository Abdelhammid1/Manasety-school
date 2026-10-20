"""SAAS-020 — school_id on the LMS roots and the question bank."""

from __future__ import annotations

import importlib.util
from pathlib import Path

WAVE_1B = (
    "lms_quizzes lms_assignments lms_units lms_bank_choices "
    "lms_assignment_template_questions lms_assessment_template_questions "
    "lms_bank_question_tags lms_bank_question_skills lms_bank_question_objectives "
    "lms_question_stats lms_course_sections lms_bank_question_collection_items"
).split()


def test_migration_covers_exactly_the_wave():
    path = next(Path(__file__).parents[1].glob("migrations/versions/*_saas020_*.py"))
    spec = importlib.util.spec_from_file_location("saas020_mig", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert sorted(c.table for c in mod.WAVE_1B) == sorted(WAVE_1B)


def test_every_wave_table_has_not_null_school_id(app):
    from app.extensions import db
    for t in WAVE_1B:
        col = db.metadata.tables[t].c.school_id
        assert not col.nullable and col.default is not None, t


def test_quiz_bank_and_template_rows_get_their_school(app, two_schools):
    """Quiz / unit / course-section rows and bank choices + tag links
    created through the ORM carry the parent's school."""
    import sqlalchemy as sa
    from app.extensions import db
    from app.models import (
        BankChoice, BankQuestion, BankTag, Course, CourseSection, Quiz, Unit,
    )
    for key in ("A", "B"):
        X = two_schools[key]
        sid = X["school"].id
        with app.app_context():
            course = Course(school_id=sid, academic_year_id=X["year"].id,
                            grade_id=X["grade"].id, subject_id=X["subject"].id, title="C")
            db.session.add(course); db.session.flush()
            quiz = Quiz(course_id=course.id, title="Q")
            unit = Unit(course_id=course.id, title="U")
            cs = CourseSection(course_id=course.id, section_id=X["section"].id)
            bq = BankQuestion(school_id=sid, prompt="2+2?")
            tag = BankTag(school_id=sid, name=f"tag-{key}")
            db.session.add_all([quiz, unit, cs, bq, tag]); db.session.flush()
            bq.choices.append(BankChoice(label="4"))
            bq.tag_rows.append(tag)
            db.session.commit()
            assert {quiz.school_id, unit.school_id, cs.school_id,
                    bq.choices[0].school_id} == {sid}
            link = db.session.execute(sa.text(
                "SELECT school_id FROM lms_bank_question_tags WHERE question_id = :q"),
                {"q": bq.id}).scalar()
            assert link == sid
            db.session.remove()
