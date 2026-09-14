"""
LMS domain models — the "learning" half of Manasety.

Adds on top of the existing SIS/ERP:
- Course (per subject × section × academic year)
- Lesson (ordered content: video/pdf/text/embed)
- CourseAssignment / Submission
- Quiz / Question / Choice / QuizAttempt / Answer
- Announcement (per section)

Note: the existing `teacher.Assignment` model represents a *teaching assignment*
(teacher-subject-section binding). We call the LMS homework model
`CourseAssignment` to avoid the name clash.
"""
from datetime import datetime, timezone

from ..extensions import db


def _utcnow():
    return datetime.now(timezone.utc)


# ---------- Courses & Lessons ----------

class Course(db.Model):
    __tablename__ = "lms_courses"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    academic_year_id = db.Column(db.Integer, db.ForeignKey("academic_years.id"), nullable=False, index=True)
    section_id = db.Column(db.Integer, db.ForeignKey("sections.id"), nullable=False, index=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=False, index=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teachers.id"), nullable=True, index=True)

    title = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, default="")
    cover_url = db.Column(db.String(500), default="")
    is_published = db.Column(db.Boolean, default=False, nullable=False)

    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    lessons = db.relationship("Lesson", backref="course", cascade="all, delete-orphan",
                              order_by="Lesson.order_index")
    assignments = db.relationship("CourseAssignment", backref="course", cascade="all, delete-orphan")
    quizzes = db.relationship("Quiz", backref="course", cascade="all, delete-orphan")

    __table_args__ = (
        db.UniqueConstraint("academic_year_id", "section_id", "subject_id",
                            name="uq_course_year_section_subject"),
    )


class Lesson(db.Model):
    __tablename__ = "lms_lessons"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("lms_courses.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    order_index = db.Column(db.Integer, default=0, nullable=False)

    title = db.Column(db.String(200), nullable=False)
    kind = db.Column(db.String(20), default="text")   # text | video | pdf | embed | link
    body = db.Column(db.Text, default="")              # markdown/html
    media_url = db.Column(db.String(500), default="")  # for video/pdf/embed/link
    duration_minutes = db.Column(db.Integer, default=0)
    is_published = db.Column(db.Boolean, default=True, nullable=False)

    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)


# ---------- Assignments ----------

class CourseAssignment(db.Model):
    __tablename__ = "lms_assignments"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("lms_courses.id", ondelete="CASCADE"),
                          nullable=False, index=True)

    title = db.Column(db.String(200), nullable=False)
    instructions = db.Column(db.Text, default="")
    max_score = db.Column(db.Numeric(6, 2), default=100)
    due_at = db.Column(db.DateTime(timezone=True))
    allow_late = db.Column(db.Boolean, default=True, nullable=False)
    is_published = db.Column(db.Boolean, default=False, nullable=False)

    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)

    submissions = db.relationship("Submission", backref="assignment", cascade="all, delete-orphan")


class Submission(db.Model):
    __tablename__ = "lms_submissions"

    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey("lms_assignments.id", ondelete="CASCADE"),
                              nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False, index=True)

    body = db.Column(db.Text, default="")
    file_url = db.Column(db.String(500), default="")
    submitted_at = db.Column(db.DateTime(timezone=True), default=_utcnow)
    score = db.Column(db.Numeric(6, 2))
    feedback = db.Column(db.Text, default="")
    graded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    graded_at = db.Column(db.DateTime(timezone=True))

    __table_args__ = (
        db.UniqueConstraint("assignment_id", "student_id", name="uq_submission_assignment_student"),
    )


# ---------- Quizzes ----------

class Quiz(db.Model):
    __tablename__ = "lms_quizzes"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("lms_courses.id", ondelete="CASCADE"),
                          nullable=False, index=True)

    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="")
    duration_minutes = db.Column(db.Integer, default=30)
    opens_at = db.Column(db.DateTime(timezone=True))
    closes_at = db.Column(db.DateTime(timezone=True))
    max_attempts = db.Column(db.Integer, default=1)
    shuffle_questions = db.Column(db.Boolean, default=True)
    is_published = db.Column(db.Boolean, default=False, nullable=False)

    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)

    questions = db.relationship("Question", backref="quiz", cascade="all, delete-orphan",
                                order_by="Question.order_index")


class Question(db.Model):
    __tablename__ = "lms_questions"

    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey("lms_quizzes.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    order_index = db.Column(db.Integer, default=0, nullable=False)

    kind = db.Column(db.String(20), default="mcq")  # mcq | multi | tf | short | essay
    prompt = db.Column(db.Text, nullable=False)
    points = db.Column(db.Numeric(6, 2), default=1)
    correct_short = db.Column(db.String(200), default="")  # for short-answer

    choices = db.relationship("Choice", backref="question", cascade="all, delete-orphan",
                              order_by="Choice.order_index")


class Choice(db.Model):
    __tablename__ = "lms_choices"

    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey("lms_questions.id", ondelete="CASCADE"),
                            nullable=False, index=True)
    order_index = db.Column(db.Integer, default=0, nullable=False)
    label = db.Column(db.String(500), nullable=False)
    is_correct = db.Column(db.Boolean, default=False, nullable=False)


class QuizAttempt(db.Model):
    __tablename__ = "lms_quiz_attempts"

    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey("lms_quizzes.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False, index=True)

    started_at = db.Column(db.DateTime(timezone=True), default=_utcnow)
    submitted_at = db.Column(db.DateTime(timezone=True))
    score = db.Column(db.Numeric(6, 2))
    auto_graded = db.Column(db.Boolean, default=False)

    answers = db.relationship("Answer", backref="attempt", cascade="all, delete-orphan")


class Answer(db.Model):
    __tablename__ = "lms_answers"

    id = db.Column(db.Integer, primary_key=True)
    attempt_id = db.Column(db.Integer, db.ForeignKey("lms_quiz_attempts.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey("lms_questions.id"), nullable=False)
    choice_id = db.Column(db.Integer, db.ForeignKey("lms_choices.id"))  # mcq/tf
    text_answer = db.Column(db.Text, default="")                          # short/essay
    is_correct = db.Column(db.Boolean)                                    # null until graded
    awarded_points = db.Column(db.Numeric(6, 2))


# ---------- Announcements ----------

class Announcement(db.Model):
    __tablename__ = "lms_announcements"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    section_id = db.Column(db.Integer, db.ForeignKey("sections.id"), index=True)  # null = school-wide
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, default="")
    is_pinned = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)
