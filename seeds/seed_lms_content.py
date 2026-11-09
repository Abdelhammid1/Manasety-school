"""Seed units, lessons, and a quiz for every Course.

Run with:  python -m seeds.seed_lms_content
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
from app.models.lms import Course, Unit, Lesson, Quiz, Question, Choice

random.seed(7)

UNIT_TITLES = ["الوحدة الأولى", "الوحدة الثانية"]
LESSON_TITLES = ["مقدمة الدرس", "الشرح التفصيلي", "تمارين وتطبيقات"]


def run():
    app = create_app()
    with app.app_context():
        courses = Course.query.all()
        units_created = 0
        lessons_created = 0
        quizzes_created = 0
        questions_created = 0

        for course in courses:
            if Unit.query.filter_by(course_id=course.id).first():
                continue  # already seeded

            for u_idx, u_title in enumerate(UNIT_TITLES, start=1):
                unit = Unit(
                    course_id=course.id, title=f"{u_title} — {course.title}",
                    description=f"محتوى {u_title} في مقرر {course.title}",
                    order_index=u_idx,
                )
                db.session.add(unit)
                db.session.flush()
                units_created += 1

                n_lessons = random.randint(2, 3)
                for l_idx in range(1, n_lessons + 1):
                    l_title = LESSON_TITLES[(l_idx - 1) % len(LESSON_TITLES)]
                    lesson = Lesson(
                        course_id=course.id, unit_id=unit.id,
                        order_index=l_idx,
                        title=f"{l_title} {l_idx}",
                        kind="text",
                        body=f"محتوى الدرس: {l_title} الخاص بـ {course.title}.",
                        duration_minutes=random.choice([15, 20, 25, 30]),
                        is_published=True,
                    )
                    db.session.add(lesson)
                    lessons_created += 1

            quiz = Quiz(
                course_id=course.id,
                title=f"اختبار قصير — {course.title}",
                description="اختبار قصير لمراجعة محتوى المقرر.",
                duration_minutes=20, max_attempts=1,
                shuffle_questions=True, is_published=True,
            )
            db.session.add(quiz)
            db.session.flush()
            quizzes_created += 1

            for q_idx in range(1, 6):
                question = Question(
                    quiz_id=quiz.id, order_index=q_idx, kind="mcq",
                    prompt=f"سؤال {q_idx} في مادة {course.title}؟",
                    points=1,
                )
                db.session.add(question)
                db.session.flush()
                questions_created += 1
                correct_idx = random.randint(0, 3)
                for c_idx in range(4):
                    db.session.add(Choice(
                        question_id=question.id, order_index=c_idx,
                        label=f"اختيار {c_idx + 1}",
                        is_correct=(c_idx == correct_idx),
                    ))

            db.session.commit()

        print(f"Units: {units_created} | Lessons: {lessons_created} | "
              f"Quizzes: {quizzes_created} | Questions: {questions_created}")


if __name__ == "__main__":
    run()
