"""Seed one assignment (with MCQ questions) per Course.

Run with:  python -m seeds.seed_assignments
"""
import random
import sys
from datetime import datetime, timedelta, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

from app import create_app
from app.extensions import db
from app.models.lms import Course, CourseAssignment, AssignmentQuestion, AssignmentChoice

random.seed(11)


def run():
    app = create_app()
    with app.app_context():
        courses = Course.query.all()
        assignments_created = 0
        questions_created = 0

        for course in courses:
            if CourseAssignment.query.filter_by(course_id=course.id).first():
                continue  # already seeded

            due = datetime.now(timezone.utc) + timedelta(days=random.randint(3, 14))
            assignment = CourseAssignment(
                course_id=course.id,
                title=f"واجب — {course.title}",
                instructions=(
                    f"أجب عن الأسئلة التالية بعد مراجعة دروس {course.title}. "
                    "اقرأ كل سؤال جيدًا قبل الإجابة."
                ),
                max_score=20,
                due_at=due,
                allow_late=True,
                is_published=True,
            )
            db.session.add(assignment)
            db.session.flush()
            assignments_created += 1

            for q_idx in range(1, 6):
                question = AssignmentQuestion(
                    assignment_id=assignment.id, order_index=q_idx,
                    kind="mcq",
                    prompt=f"سؤال {q_idx} — {course.title}؟",
                    points=4,
                )
                db.session.add(question)
                db.session.flush()
                questions_created += 1
                correct_idx = random.randint(0, 3)
                for c_idx in range(4):
                    db.session.add(AssignmentChoice(
                        question_id=question.id, order_index=c_idx,
                        label=f"اختيار {c_idx + 1}",
                        is_correct=(c_idx == correct_idx),
                    ))

            db.session.commit()

        print(f"Assignments: {assignments_created} | Questions: {questions_created}")


if __name__ == "__main__":
    run()
