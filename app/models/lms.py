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
    # Ticket #2 — Course is now scoped by (year, grade, subject, term).
    # section_id + teacher_id are gone; sections live in lms_course_sections,
    # and the teacher is resolved per-section via teacher.Assignment.
    grade_id = db.Column(db.Integer, db.ForeignKey("grades.id"), nullable=False, index=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=False, index=True)
    term_id = db.Column(db.Integer, db.ForeignKey("terms.id", ondelete="SET NULL"),
                        nullable=True, index=True)

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
    # Ticket #2 — sections this course is published to.
    course_sections = db.relationship("CourseSection", backref="course",
                                      cascade="all, delete-orphan")
    grade = db.relationship("Grade")
    term = db.relationship("Term")

    __table_args__ = (
        db.UniqueConstraint("academic_year_id", "grade_id", "subject_id", "term_id",
                            name="uq_course_year_grade_subject_term"),
    )


class CourseSection(db.Model):
    """Ticket #2 — join table: one Course × many Sections. Every row
    represents a "publish" of the course to a specific section, with
    is_published gating student visibility per-section."""
    __tablename__ = "lms_course_sections"

    id = db.Column(db.Integer, primary_key=True)
    course_id  = db.Column(db.Integer, db.ForeignKey("lms_courses.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    section_id = db.Column(db.Integer, db.ForeignKey("sections.id",    ondelete="CASCADE"),
                           nullable=False, index=True)
    is_published = db.Column(db.Boolean, nullable=False, default=True)
    published_at = db.Column(db.DateTime(timezone=True))
    created_at   = db.Column(db.DateTime(timezone=True), default=_utcnow)

    section = db.relationship("Section")

    __table_args__ = (
        db.UniqueConstraint("course_id", "section_id", name="uq_course_section"),
    )


class Unit(db.Model):
    """A Unit groups Lessons under a Course (ticket #16 part 1).
    Lesson.unit_id is nullable, so pre-existing lessons show up under a
    virtual "no unit" bucket until a teacher tags them."""
    __tablename__ = "lms_units"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("lms_courses.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="")
    order_index = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)

    course = db.relationship("Course", backref=db.backref(
        "units", order_by="Unit.order_index", cascade="all, delete-orphan"))
    lessons = db.relationship("Lesson", backref="unit", order_by="Lesson.order_index")


class Lesson(db.Model):
    __tablename__ = "lms_lessons"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("lms_courses.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    unit_id = db.Column(db.Integer, db.ForeignKey("lms_units.id", ondelete="SET NULL"),
                        nullable=True, index=True)
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

    # Ticket #16 part 5 — audit trail back to the AssignmentTemplate this
    # was cloned from. ON DELETE SET NULL keeps live assignments valid if
    # the template is later removed from the library.
    source_template_id = db.Column(
        db.Integer, db.ForeignKey("lms_assignment_templates.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    # Ticket #16 wiring — optional Rubric. When set, grading uses
    # RubricScore rows against the criteria instead of a single score.
    rubric_id = db.Column(
        db.Integer, db.ForeignKey("rubrics.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)

    submissions = db.relationship("Submission", backref="assignment", cascade="all, delete-orphan")
    # Assignment-side quiz-style questions (ticket #16 part 3). When a
    # CourseAssignment has zero AssignmentQuestion rows, it behaves as the
    # legacy free-form "upload / text" homework — nothing regresses.
    questions = db.relationship(
        "AssignmentQuestion", backref="assignment",
        cascade="all, delete-orphan",
        order_by="AssignmentQuestion.order_index",
    )

    @property
    def has_questions(self) -> bool:
        return bool(self.questions)


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

    # Smart-assignment answers (ticket #16 part 3). Empty for legacy
    # free-form submissions; populated when the assignment has questions.
    answers = db.relationship(
        "AssignmentAnswer", backref="submission",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        db.UniqueConstraint("assignment_id", "student_id", name="uq_submission_assignment_student"),
    )


class AssignmentQuestion(db.Model):
    """Quiz-style question attached to a CourseAssignment. Mirrors the
    `Question` model exactly so the bank picker can clone rows either
    into a Quiz or into an Assignment with the same code path."""
    __tablename__ = "lms_assignment_questions"

    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(
        db.Integer, db.ForeignKey("lms_assignments.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    order_index = db.Column(db.Integer, default=0, nullable=False)
    kind = db.Column(db.String(20), default="mcq")   # mcq | multi | tf | short | essay
    prompt = db.Column(db.Text, nullable=False)
    points = db.Column(db.Numeric(6, 2), default=1)
    correct_short = db.Column(db.String(200), default="")

    source_bank_id = db.Column(
        db.Integer, db.ForeignKey("lms_bank_questions.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    version   = db.Column(db.Integer, default=1, nullable=False)   # ticket 19
    is_locked = db.Column(db.Boolean, default=False, nullable=False)
    locked_at = db.Column(db.DateTime(timezone=True))

    choices = db.relationship(
        "AssignmentChoice", backref="question",
        cascade="all, delete-orphan",
        order_by="AssignmentChoice.order_index",
    )


class AssignmentChoice(db.Model):
    __tablename__ = "lms_assignment_choices"

    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(
        db.Integer, db.ForeignKey("lms_assignment_questions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    order_index = db.Column(db.Integer, default=0, nullable=False)
    label = db.Column(db.String(500), nullable=False)
    is_correct = db.Column(db.Boolean, default=False, nullable=False)


class AssignmentAnswer(db.Model):
    __tablename__ = "lms_assignment_answers"

    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(
        db.Integer, db.ForeignKey("lms_submissions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    question_id = db.Column(
        db.Integer, db.ForeignKey("lms_assignment_questions.id"),
        nullable=False,
    )
    choice_id = db.Column(db.Integer, db.ForeignKey("lms_assignment_choices.id"))
    text_answer = db.Column(db.Text, default="")
    is_correct = db.Column(db.Boolean)
    awarded_points = db.Column(db.Numeric(6, 2))


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

    # Provenance: if this question was pulled from the school's question bank,
    # keep a pointer back to the source BankQuestion (nullable, SET NULL on
    # delete so a bank cleanup doesn't wipe live quiz history).
    source_bank_id = db.Column(
        db.Integer, db.ForeignKey("lms_bank_questions.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    # Ticket 19 — versioning. is_locked flips to True on the first
    # student answer so the teacher can't silently rewrite the prompt
    # while attempts already exist.
    version   = db.Column(db.Integer, default=1, nullable=False)
    is_locked = db.Column(db.Boolean, default=False, nullable=False)
    locked_at = db.Column(db.DateTime(timezone=True))

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


# ---------- Question Bank ------------------------------------------------
#
# The bank is the school's *pool* of reusable questions, tagged with
# subject / grade / academic year / difficulty. Teachers write questions
# into the bank once; when they compose a quiz they pick from it, and the
# picked rows are COPIED into `lms_questions` + `lms_choices` (each with a
# `source_bank_id` back-pointer so the quiz stays valid even if the bank
# item is later edited or deleted).
#
# Design choices:
# - subject_id / grade_id / academic_year_id are all NULLABLE so a teacher
#   can bank a generic question first and tag it later.
# - `tags` is a comma-separated string kept on the row for lightweight
#   filtering (chapter, skill, unit …). Full-text later if we need it.
# - choices live in a separate table (BankChoice) mirroring the Choice
#   table's shape 1-to-1, so the picker copy is a straight field-map.

class BankQuestion(db.Model):
    __tablename__ = "lms_bank_questions"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"),
                          nullable=False, index=True)

    subject_id       = db.Column(db.Integer, db.ForeignKey("subjects.id"),        nullable=True, index=True)
    grade_id         = db.Column(db.Integer, db.ForeignKey("grades.id"),          nullable=True, index=True)
    academic_year_id = db.Column(db.Integer, db.ForeignKey("academic_years.id"),  nullable=True, index=True)
    # Extended taxonomy (ticket #16 part 2). All nullable so a teacher
    # can bank a generic prompt first and tag it later.
    term_id   = db.Column(db.Integer, db.ForeignKey("terms.id"),       nullable=True, index=True)
    unit_id   = db.Column(db.Integer, db.ForeignKey("lms_units.id"),   nullable=True, index=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey("lms_lessons.id"), nullable=True, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"),   nullable=True)

    kind          = db.Column(db.String(20), default="mcq")   # mcq | multi | tf | short | essay
    prompt        = db.Column(db.Text, nullable=False)
    points        = db.Column(db.Numeric(6, 2), default=1)
    correct_short = db.Column(db.String(200), default="")
    difficulty    = db.Column(db.String(10),  default="medium")   # easy | medium | hard
    tags          = db.Column(db.String(500), default="")         # comma-separated

    created_at    = db.Column(db.DateTime(timezone=True), default=_utcnow)
    updated_at    = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    choices = db.relationship(
        "BankChoice", backref="question",
        cascade="all, delete-orphan",
        order_by="BankChoice.order_index",
    )
    unit   = db.relationship("Unit",   foreign_keys=[unit_id])
    lesson = db.relationship("Lesson", foreign_keys=[lesson_id])

    @property
    def tag_list(self):
        return [t.strip() for t in (self.tags or "").split(",") if t.strip()]


class BankChoice(db.Model):
    __tablename__ = "lms_bank_choices"

    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(
        db.Integer, db.ForeignKey("lms_bank_questions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    order_index = db.Column(db.Integer, default=0, nullable=False)
    label       = db.Column(db.String(500), nullable=False)
    is_correct  = db.Column(db.Boolean, default=False, nullable=False)


# ---------- Assignment templates (ticket #16 part 5) ------------------
#
# The "assignment bank" — a reusable full-homework template with its own
# questions. Templates are copied (not linked) into CourseAssignment when
# a teacher clones one for a specific course, mirroring the
# BankQuestion → Question copy semantics so an edit to the template
# after the fact does not silently rewrite an already-distributed
# assignment.

class AssignmentTemplate(db.Model):
    __tablename__ = "lms_assignment_templates"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"),
                          nullable=False, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=True, index=True)
    grade_id   = db.Column(db.Integer, db.ForeignKey("grades.id"),   nullable=True, index=True)

    title        = db.Column(db.String(200), nullable=False)
    instructions = db.Column(db.Text, default="")
    max_score    = db.Column(db.Numeric(6, 2), default=100)
    allow_late   = db.Column(db.Boolean, default=True, nullable=False)
    usage_count  = db.Column(db.Integer, default=0, nullable=False)

    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    questions = db.relationship(
        "AssignmentTemplateQuestion", backref="template",
        cascade="all, delete-orphan",
        order_by="AssignmentTemplateQuestion.order_index",
    )


class AssignmentTemplateQuestion(db.Model):
    __tablename__ = "lms_assignment_template_questions"

    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(
        db.Integer, db.ForeignKey("lms_assignment_templates.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    order_index = db.Column(db.Integer, default=0, nullable=False)
    kind = db.Column(db.String(20), default="mcq")
    prompt = db.Column(db.Text, nullable=False)
    points = db.Column(db.Numeric(6, 2), default=1)
    correct_short = db.Column(db.String(200), default="")
    source_bank_id = db.Column(
        db.Integer, db.ForeignKey("lms_bank_questions.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    choices = db.relationship(
        "AssignmentTemplateChoice", backref="question",
        cascade="all, delete-orphan",
        order_by="AssignmentTemplateChoice.order_index",
    )


class AssignmentTemplateChoice(db.Model):
    __tablename__ = "lms_assignment_template_choices"

    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(
        db.Integer, db.ForeignKey("lms_assignment_template_questions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    order_index = db.Column(db.Integer, default=0, nullable=False)
    label = db.Column(db.String(500), nullable=False)
    is_correct = db.Column(db.Boolean, default=False, nullable=False)


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
