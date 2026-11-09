"""Seed 10 bank questions per (grade, subject) pair.

Run with:  python -m seeds.seed_question_bank
"""
import random
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

from app import create_app
from app.extensions import db
from app.models import School, AcademicYear, Grade, Subject
from app.models.lms import BankQuestion, BankChoice

random.seed(21)
DIFFICULTIES = ["easy", "medium", "hard"]


def run():
    app = create_app()
    with app.app_context():
        school = School.query.first()
        year = AcademicYear.query.filter_by(school_id=school.id, status="active").first()

        grades = Grade.query.filter_by(school_id=school.id).order_by(Grade.order_index).all()
        created = 0
        for grade in grades:
            subjects = (
                Subject.query.filter_by(school_id=school.id, is_active=True)
                .join(Subject.grades).filter(Grade.id == grade.id)
                .all()
            )
            for subj in subjects:
                existing = BankQuestion.query.filter_by(
                    school_id=school.id, subject_id=subj.id, grade_id=grade.id,
                ).count()
                if existing >= 10:
                    continue
                for q_idx in range(existing + 1, 11):
                    q = BankQuestion(
                        school_id=school.id, subject_id=subj.id, grade_id=grade.id,
                        academic_year_id=year.id, kind="mcq",
                        prompt=f"سؤال بنك رقم {q_idx} — {subj.name} ({grade.name})؟",
                        points=1, difficulty=random.choice(DIFFICULTIES),
                        tags=f"{subj.name},{grade.name}",
                    )
                    db.session.add(q)
                    db.session.flush()
                    correct_idx = random.randint(0, 3)
                    for c_idx in range(4):
                        db.session.add(BankChoice(
                            question_id=q.id, order_index=c_idx,
                            label=f"اختيار {c_idx + 1}",
                            is_correct=(c_idx == correct_idx),
                        ))
                    created += 1
            db.session.commit()
            print(f"OK {grade.name}")

        print(f"\nDone. Bank questions created: {created}")


if __name__ == "__main__":
    run()
