"""Seed one Course per (grade, subject) and attach it to that grade's
sections via CourseSection, so /courses/pick/... stops showing 0 shoab.

Run with:  python -m seeds.seed_courses
"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

from app import create_app
from app.extensions import db
from app.models import School, AcademicYear, Term, Grade, Subject, Section
from app.models.lms import Course, CourseSection


def run():
    app = create_app()
    with app.app_context():
        school = School.query.first()
        year = AcademicYear.query.filter_by(school_id=school.id, status="active").first()
        term = Term.query.filter_by(year_id=year.id, order_index=1).first()

        grades = Grade.query.filter_by(school_id=school.id).order_by(Grade.order_index).all()
        created = 0
        linked = 0
        for grade in grades:
            subjects = (
                Subject.query.filter_by(school_id=school.id, is_active=True)
                .join(Subject.grades).filter(Grade.id == grade.id)
                .all()
            )
            sections = Section.query.filter_by(year_id=year.id, grade_id=grade.id).all()
            for subj in subjects:
                course = Course.query.filter_by(
                    school_id=school.id, academic_year_id=year.id,
                    grade_id=grade.id, subject_id=subj.id, term_id=term.id,
                ).first()
                if not course:
                    course = Course(
                        school_id=school.id, academic_year_id=year.id,
                        grade_id=grade.id, subject_id=subj.id, term_id=term.id,
                        title=f"{subj.name} — {grade.name}",
                        description=f"مقرر {subj.name} لصف {grade.name}",
                        is_published=True,
                    )
                    db.session.add(course)
                    db.session.flush()
                    created += 1
                for sec in sections:
                    cs = CourseSection.query.filter_by(
                        course_id=course.id, section_id=sec.id,
                    ).first()
                    if not cs:
                        db.session.add(CourseSection(
                            course_id=course.id, section_id=sec.id,
                            is_published=True,
                        ))
                        linked += 1
            db.session.commit()
            print(f"OK {grade.name}: {len(subjects)} subject(s)")

        print(f"\nDone. Courses created: {created} | CourseSection links: {linked}")


if __name__ == "__main__":
    run()
