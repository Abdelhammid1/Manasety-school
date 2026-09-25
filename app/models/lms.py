"""LMS domain models — the "learning" half of Manasety.

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
from sqlalchemy.sql import false as sa_false, true as sa_true

from ..extensions import db
from .mixins import SoftDeleteMixin


def _utcnow():
    return datetime.now(timezone.utc)


# ---------- Courses & Lessons ----------

class Course(SoftDeleteMixin, db.Model):
    # When a course is soft-deleted the whole content tree disappears
    # with it (ticket "cascade على الأبناء"). Restore walks back only
    # the children we brought down (< 60s apart).
    __soft_delete_cascades__ = ("lessons", "assignments", "quizzes",
                                "course_sections")
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


class Unit(SoftDeleteMixin, db.Model):
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


class Lesson(SoftDeleteMixin, db.Model):
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

class CourseAssignment(SoftDeleteMixin, db.Model):
    __tablename__ = "lms_assignments"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("lms_courses.id", ondelete="CASCADE"),
                          nullable=False, index=True)

    title = db.Column(db.String(200), nullable=False)
    instructions = db.Column(db.Text, default="")
    max_score = db.Column(db.Numeric(6, 2), default=100)
    due_at = db.Column(db.DateTime(timezone=True))
    allow_late = db.Column(db.Boolean, default=True, nullable=False)
    # Phase-2 ticket #21 — graduated late penalty. When set, a late
    # submission's `score` is reduced by `late_penalty_per_day` percent
    # per day past `due_at`, capped at `max_penalty_percent`. If
    # `late_penalty_percent` is set instead (flat), it applies once
    # regardless of days late.
    late_penalty_percent  = db.Column(db.Numeric(5, 2), nullable=True)
    late_penalty_per_day  = db.Column(db.Numeric(5, 2), nullable=True)
    max_penalty_percent   = db.Column(db.Numeric(5, 2), nullable=True)
    # Phase-2 ticket #22 — multiple submissions per assignment.
    max_attempts   = db.Column(db.Integer, nullable=False,
                               default=1, server_default="1")
    allow_resubmit = db.Column(db.Boolean, nullable=False,
                               default=False, server_default=sa_false())
    # Ticket #30 — same allow_review toggle as Quiz.
    allow_review = db.Column(db.Boolean, nullable=False,
                             default=True, server_default=sa_true())
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
    rubric = db.relationship("Rubric", foreign_keys=[rubric_id])

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
    # Phase-2 ticket #20 — record the kind of submission the student
    # made so the teacher UI can render the right preview (link vs
    # image vs audio vs video vs file vs text). NULL for legacy rows.
    submission_kind = db.Column(db.String(20), nullable=True)
    external_url    = db.Column(db.String(500), nullable=True)
    # Phase-2 ticket #22 — attempt counter for max_attempts on the
    # parent assignment. First submission = 1; subsequent resubmits
    # (when `allow_resubmit`) increment.
    attempt_number = db.Column(db.Integer, nullable=False,
                               default=1, server_default="1")

    # Smart-assignment answers (ticket #16 part 3). Empty for legacy
    # free-form submissions; populated when the assignment has questions.
    answers = db.relationship(
        "AssignmentAnswer", backref="submission",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        db.UniqueConstraint(
            "assignment_id", "student_id", "attempt_number",
            name="uq_submission_assignment_student_attempt",
        ),
    )


class AssignmentQuestion(SoftDeleteMixin, db.Model):
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

class Quiz(SoftDeleteMixin, db.Model):
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
    # Ticket P0-7 — separate toggle for choice-order shuffle. Independent
    # from `shuffle_questions` because a teacher may want fixed question
    # order (so review is easier) but per-student choice permutation.
    shuffle_choices = db.Column(db.Boolean, default=False, nullable=False,
                                server_default=sa_false())
    # Ticket P1-10 — enable partial credit on `multi` questions. When
    # off (default) the classic all-or-nothing rule applies; when on,
    # each `multi` awards a proportional slice of the question's points.
    allow_partial_credit = db.Column(db.Boolean, default=False,
                                     nullable=False, server_default=sa_false())
    # Phase-2 ticket #8 — negative-marking penalty per wrong answer.
    # NULL disables it; > 0 subtracts that many points per wrong pick.
    negative_marking_value = db.Column(db.Numeric(6, 2), nullable=True)
    # Phase-2 ticket #9 — navigation constraints inside the take page.
    navigation_mode = db.Column(db.String(24), nullable=False,
                                default="free", server_default="free")
    # Phase-2 ticket #15 — retake policy + cooldown.
    retake_policy = db.Column(db.String(20), nullable=False,
                              default="on_request", server_default="on_request")
    retake_cooldown_minutes = db.Column(db.Integer, nullable=True)
    # Phase-2 ticket #16 — control when the result page unlocks for
    # students. `immediate` (default) matches current behaviour;
    # `manual` waits for the teacher; `scheduled` waits until publish_at.
    result_publish_mode = db.Column(db.String(20), nullable=False,
                                    default="immediate",
                                    server_default="immediate")
    result_publish_at = db.Column(db.DateTime(timezone=True), nullable=True)
    # `show_answers_after` = 'immediate' / 'after_publish' / 'never'
    show_answers_after = db.Column(db.String(20), nullable=False,
                                   default="immediate",
                                   server_default="immediate")
    # Ticket #30 — teacher choice for post-submission review.
    allow_review = db.Column(db.Boolean, nullable=False,
                             default=True, server_default=sa_true())
    is_published = db.Column(db.Boolean, default=False, nullable=False)

    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)

    questions = db.relationship("Question", backref="quiz", cascade="all, delete-orphan",
                                order_by="Question.order_index")


class Question(SoftDeleteMixin, db.Model):
    __tablename__ = "lms_questions"

    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey("lms_quizzes.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    order_index = db.Column(db.Integer, default=0, nullable=False)

    kind = db.Column(db.String(20), default="mcq")  # mcq | multi | tf | short | essay
    prompt = db.Column(db.Text, nullable=False)
    points = db.Column(db.Numeric(6, 2), default=1)
    correct_short = db.Column(db.String(200), default="")  # for short-answer
    # Ticket #31/#32 — carry the bank's explanation video + hint through
    # to the cloned question so the student sees them in-context.
    explanation_video_url = db.Column(db.String(500), nullable=True)
    hint_text             = db.Column(db.Text, nullable=True)

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
    # Ticket P0-7 — deterministic shuffle seed. Set once when the attempt
    # is created; used by both the take page and quiz_submit so the
    # answer key stays in sync between what the student saw and what the
    # server scored.
    shuffle_seed = db.Column(db.Integer, nullable=True)
    # Phase-2 ticket #10 — soft anti-cheat: count how many times the
    # student left the tab during the attempt. Bumped by an AJAX beacon
    # from the take page's `visibilitychange` listener.
    tab_switch_count = db.Column(db.Integer, nullable=False,
                                 default=0, server_default="0")
    # Phase-2 ticket #14 — Blueprint-generated A/B/C variants pin the
    # student to a specific variant so re-opening keeps the same order.
    # NULL for regular quizzes.
    variant_label = db.Column(db.String(4), nullable=True)

    quiz = db.relationship("Quiz")
    answers = db.relationship("Answer", backref="attempt", cascade="all, delete-orphan")
    flagged_questions = db.relationship(
        "Question",
        secondary="lms_attempt_flagged_questions",
        lazy="selectin",
    )


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

class BankQuestion(SoftDeleteMixin, db.Model):
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
    difficulty    = db.Column(db.String(10),  default="medium")   # easy | medium | hard | very_hard
    tags          = db.Column(db.String(500), default="")         # comma-separated
    # Phase-2 ticket #1 — Bloom cognitive level, separate from
    # `difficulty` (which is teacher's perceived hardness). Values:
    # remember / understand / apply / analyze / evaluate / create.
    cognitive_level = db.Column(db.String(20), nullable=True, index=True)
    # Phase-2 tickets #31-#34 — content authoring extras.
    explanation_video_url = db.Column(db.String(500), nullable=True)
    hint_text             = db.Column(db.Text, nullable=True)
    notes                 = db.Column(db.Text, nullable=True)
    internal_label        = db.Column(db.String(120), nullable=True, index=True)
    # Phase-2 ticket #26 — visibility across teachers within a school
    # (or between schools when 'public'). `private` = only the author.
    visibility = db.Column(db.String(16), nullable=False,
                           default="private", server_default="private",
                           index=True)

    # Qdrat-parity review workflow. A brand-new question lands in
    # `draft`; once the author fills every field it goes to `pending`
    # for the admin to promote to `approved`. `no_answer` flags rows
    # that carry a prompt but no correct choice (Qdrat calls these
    # "بدون إجابات"). `duplicate` is set by the semantic-similarity
    # detector, and `rejected` by an admin sending a question back.
    review_state  = db.Column(db.String(16), nullable=False,
                              default="approved", server_default="approved",
                              index=True)
    review_notes  = db.Column(db.Text, default="")

    # NAFIS separation — a question belongs to either the school's own
    # curriculum bank ('school', the default) or the ETEC نافس bank
    # ('nafis'). Same table, two clean partitions, one page with a tab
    # picker. NAFIS questions carry `outcome_id` back to a specific
    # LearningOutcome and `nafis_level` (g3 / g6 / g9) so drills can be
    # scoped to the exam that grade sits.
    source        = db.Column(db.String(16), nullable=False,
                              default="school", server_default="school",
                              index=True)
    outcome_id    = db.Column(db.Integer,
                              db.ForeignKey("learning_outcomes.id"),
                              nullable=True, index=True)
    nafis_level   = db.Column(db.String(4), nullable=True, index=True)

    # Qdrat-parity pt2 — 2-level skill taxonomy (axis → indicator) plus
    # printable public code + anti-piracy UUID + archive soft-hide.
    axis_id       = db.Column(db.Integer,
                              db.ForeignKey("axes.id", ondelete="SET NULL"),
                              nullable=True, index=True)
    indicator_id  = db.Column(db.Integer,
                              db.ForeignKey("indicators.id", ondelete="SET NULL"),
                              nullable=True, index=True)
    code          = db.Column(db.String(32), nullable=True, index=True)
    uuid          = db.Column(db.String(36), nullable=True)
    is_archived   = db.Column(db.Boolean, nullable=False,
                              default=False, server_default=sa_false())
    # Qdrat-parity #6 — a bank question can attach to a reading passage
    # (قطعة لفظية). Multiple questions typically hang off the same passage.
    passage_id    = db.Column(db.Integer, nullable=True, index=True)
    passage       = db.relationship("Passage", foreign_keys=[passage_id],
                                    primaryjoin="BankQuestion.passage_id == Passage.id")

    created_at    = db.Column(db.DateTime(timezone=True), default=_utcnow)
    updated_at    = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    choices = db.relationship(
        "BankChoice", backref="question",
        cascade="all, delete-orphan",
        order_by="BankChoice.order_index",
    )
    unit      = db.relationship("Unit",   foreign_keys=[unit_id])
    lesson    = db.relationship("Lesson", foreign_keys=[lesson_id])
    outcome   = db.relationship("LearningOutcome", foreign_keys=[outcome_id])
    axis      = db.relationship("Axis",      foreign_keys=[axis_id])
    indicator = db.relationship("Indicator", foreign_keys=[indicator_id])
    tag_rows  = db.relationship("BankTag", secondary="lms_bank_question_tags",
                                lazy="selectin")
    # Phase-2 M:N relations.
    skills     = db.relationship("Skill",
                                 secondary="lms_bank_question_skills",
                                 lazy="selectin")
    objectives = db.relationship("LearningObjective",
                                 secondary="lms_bank_question_objectives",
                                 lazy="selectin")
    stats      = db.relationship("QuestionStats", uselist=False,
                                 cascade="all, delete-orphan")

    @property
    def tag_list(self):
        return [t.strip() for t in (self.tags or "").split(",") if t.strip()]


# ── Ticket P1-8 — unified tag taxonomy ──────────────────────────────
# Legacy: `BankQuestion.tags` was a comma-separated string, which meant
# "جبر", "Algebra" and "معادلات جبرية" all lived as distinct free-text
# blobs and couldn't be searched or reported on cleanly. New model:
# every tag is a row on `BankTag`, and BankQuestion ⇄ BankTag is a
# many-to-many via `lms_bank_question_tags`. The legacy string column
# stays as a mirror for one release so existing pages/exports keep
# working; both sides are written on save.

lms_bank_question_tags = db.Table(
    "lms_bank_question_tags",
    db.Column("question_id",
              db.Integer,
              db.ForeignKey("lms_bank_questions.id", ondelete="CASCADE"),
              primary_key=True),
    db.Column("tag_id",
              db.Integer,
              db.ForeignKey("lms_bank_tags.id", ondelete="CASCADE"),
              primary_key=True),
)


class BankTag(db.Model):
    __tablename__ = "lms_bank_tags"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"),
                          nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        db.UniqueConstraint("school_id", "name", name="uq_bank_tags_school_name"),
    )


# ─── Phase-2 ticket #2 — Skills taxonomy (hierarchical) + M:N ──────
# Skills are a tree — top-level skills are root nodes (parent_id NULL),
# children hang off them. Every question can link to zero or more
# skills. Scoped per-school so two schools can maintain distinct trees.

lms_bank_question_skills = db.Table(
    "lms_bank_question_skills",
    db.Column("question_id", db.Integer,
              db.ForeignKey("lms_bank_questions.id", ondelete="CASCADE"),
              primary_key=True),
    db.Column("skill_id", db.Integer,
              db.ForeignKey("lms_skills.id", ondelete="CASCADE"),
              primary_key=True),
)


class Skill(db.Model):
    __tablename__ = "lms_skills"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"),
                          nullable=False, index=True)
    parent_id = db.Column(db.Integer,
                          db.ForeignKey("lms_skills.id", ondelete="SET NULL"),
                          nullable=True, index=True)
    title = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, default="")
    order_index = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)

    children = db.relationship(
        "Skill",
        backref=db.backref("parent", remote_side=[id]),
        cascade="all",
    )


# ─── Phase-2 ticket #3 — Learning Objectives (per Lesson) + M:N ────
lms_bank_question_objectives = db.Table(
    "lms_bank_question_objectives",
    db.Column("question_id", db.Integer,
              db.ForeignKey("lms_bank_questions.id", ondelete="CASCADE"),
              primary_key=True),
    db.Column("objective_id", db.Integer,
              db.ForeignKey("lms_learning_objectives.id", ondelete="CASCADE"),
              primary_key=True),
)


class LearningObjective(db.Model):
    __tablename__ = "lms_learning_objectives"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"),
                          nullable=False, index=True)
    lesson_id = db.Column(db.Integer,
                          db.ForeignKey("lms_lessons.id", ondelete="CASCADE"),
                          nullable=True, index=True)
    code  = db.Column(db.String(40), nullable=True, index=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="")
    order_index = db.Column(db.Integer, default=0, nullable=False)
    created_at  = db.Column(db.DateTime(timezone=True), default=_utcnow)

    lesson = db.relationship("Lesson", foreign_keys=[lesson_id])


# ─── Phase-2 ticket #5 — Question performance stats ────────────────
# Snapshot updated after every fully-graded attempt. Averages hold the
# rolling mean; discrimination_index is computed after n >= 30 by the
# item-analysis cron (ticket #6). All fields are computed downstream,
# never edited by the teacher.
class QuestionStats(db.Model):
    __tablename__ = "lms_question_stats"

    id = db.Column(db.Integer, primary_key=True)
    bank_question_id = db.Column(
        db.Integer,
        db.ForeignKey("lms_bank_questions.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    usage_count           = db.Column(db.Integer, default=0, nullable=False)
    avg_score             = db.Column(db.Numeric(6, 3), nullable=True)
    avg_time_seconds      = db.Column(db.Numeric(8, 2), nullable=True)
    difficulty_index      = db.Column(db.Numeric(6, 4), nullable=True)
    discrimination_index  = db.Column(db.Numeric(6, 4), nullable=True)
    last_computed_at      = db.Column(db.DateTime(timezone=True),
                                      default=_utcnow, onupdate=_utcnow)


# ─── Phase-2 ticket #11 — flagged-questions on an attempt ──────────
lms_attempt_flagged_questions = db.Table(
    "lms_attempt_flagged_questions",
    db.Column("attempt_id", db.Integer,
              db.ForeignKey("lms_quiz_attempts.id", ondelete="CASCADE"),
              primary_key=True),
    db.Column("question_id", db.Integer,
              db.ForeignKey("lms_questions.id", ondelete="CASCADE"),
              primary_key=True),
    db.Column("flagged_at", db.DateTime(timezone=True), default=_utcnow),
)


# ─── Phase-2 ticket #24 — Assignment extensions (per-student due) ──
class AssignmentExtension(db.Model):
    __tablename__ = "lms_assignment_extensions"

    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(
        db.Integer, db.ForeignKey("lms_assignments.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    student_id = db.Column(
        db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    new_due_at = db.Column(db.DateTime(timezone=True), nullable=False)
    reason      = db.Column(db.Text, default="")
    granted_by_id = db.Column(db.Integer, db.ForeignKey("users.id"),
                              nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        db.UniqueConstraint("assignment_id", "student_id",
                            name="uq_extension_assignment_student"),
    )


# ─── Phase-2 ticket #28 — Question collections (folders) + M:N ─────
lms_bank_question_collection_items = db.Table(
    "lms_bank_question_collection_items",
    db.Column("collection_id", db.Integer,
              db.ForeignKey("lms_question_collections.id", ondelete="CASCADE"),
              primary_key=True),
    db.Column("question_id", db.Integer,
              db.ForeignKey("lms_bank_questions.id", ondelete="CASCADE"),
              primary_key=True),
)


class QuestionCollection(db.Model):
    __tablename__ = "lms_question_collections"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"),
                          nullable=False, index=True)
    owner_user_id = db.Column(db.Integer, db.ForeignKey("users.id"),
                              nullable=True)
    title = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)

    questions = db.relationship(
        "BankQuestion",
        secondary="lms_bank_question_collection_items",
        lazy="dynamic",
    )


# ─── Phase-2 ticket #29 — Feedback templates ───────────────────────
class FeedbackTemplate(db.Model):
    __tablename__ = "lms_feedback_templates"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"),
                          nullable=False, index=True)
    owner_user_id = db.Column(db.Integer, db.ForeignKey("users.id"),
                              nullable=True)
    title = db.Column(db.String(160), nullable=False)
    body  = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)


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

class AssignmentTemplate(SoftDeleteMixin, db.Model):
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


# ---------- Assessment templates (Qdrat parity) -----------------------
#
# Different from `AssignmentTemplate` above: the assessment template is
# a lightweight *pointer* container — the questions live in the shared
# `BankQuestion` table, and the template just holds an ordered list of
# ids plus per-item point overrides. That's what Qdrat calls a "نموذج
# احترافي" and it's what powers the blueprint exam generator: pick
# templates that match a subject, and every enrolled student gets a
# randomised exam drawn from those exact templates.

class AssessmentTemplate(db.Model):
    __tablename__ = "lms_assessment_templates"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"),
                          nullable=False, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    title       = db.Column(db.String(200), nullable=False)
    code        = db.Column(db.String(40),  index=True)     # "M75" — for ImportFromCode flow
    description = db.Column(db.Text, default="")

    subject_id  = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=True, index=True)
    grade_id    = db.Column(db.Integer, db.ForeignKey("grades.id"),   nullable=True, index=True)

    # 'assignment' | 'exam' — one template can seed either flow.
    kind        = db.Column(db.String(16), default="assignment", nullable=False)
    # Optional shorthand for a difficulty blueprint like "easy:5,medium:10,hard:5".
    difficulty_mix = db.Column(db.String(64), nullable=True)
    # 'draft' | 'published' | 'archived'
    state       = db.Column(db.String(16), default="published", nullable=False)

    created_at  = db.Column(db.DateTime(timezone=True), default=_utcnow)
    updated_at  = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    items = db.relationship(
        "AssessmentTemplateItem", backref="template",
        cascade="all, delete-orphan",
        order_by="AssessmentTemplateItem.order_index",
    )


class AssessmentTemplateItem(SoftDeleteMixin, db.Model):
    __tablename__ = "lms_assessment_template_questions"

    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(
        db.Integer, db.ForeignKey("lms_assessment_templates.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    bank_question_id = db.Column(
        db.Integer, db.ForeignKey("lms_bank_questions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    order_index = db.Column(db.Integer, default=0, nullable=False)
    points_override = db.Column(db.Numeric(6, 2), nullable=True)
    # Qdrat-parity #8 — soft-hide an item from a specific template without
    # deleting the row. The template still exposes it in "archive" views for
    # audit purposes.
    is_hidden = db.Column(db.Boolean, nullable=False,
                          default=False, server_default=sa_false())

    bank_question = db.relationship("BankQuestion")

    __table_args__ = (
        db.UniqueConstraint("template_id", "bank_question_id",
                            name="uq_asstmpl_q"),
    )


# ── Reading passages (قطع لفظية) ─────────────────────────────────────
# One shared block of prose that N BankQuestion rows can attach to.
# The passage stays independent — questions carry `passage_id` and can
# be re-parented; deleting the passage nulls the FK on each question.

class Passage(SoftDeleteMixin, db.Model):
    __tablename__ = "passages"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"),
                          nullable=False, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"),
                              nullable=True, index=True)

    title = db.Column(db.String(200), nullable=False)
    body  = db.Column(db.Text, nullable=False, default="")
    source = db.Column(db.String(200), nullable=True)
    language = db.Column(db.String(8), nullable=False,
                         default="ar", server_default="ar")

    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"),
                           nullable=True, index=True)
    grade_id   = db.Column(db.Integer, db.ForeignKey("grades.id"),
                           nullable=True, index=True)

    word_count = db.Column(db.Integer, nullable=False, default=0)
    image_url  = db.Column(db.String(500), nullable=True)
    audio_url  = db.Column(db.String(500), nullable=True)
    state      = db.Column(db.String(16), nullable=False,
                           default="draft", server_default="draft")

    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)
    updated_at = db.Column(db.DateTime(timezone=True),
                           default=_utcnow, onupdate=_utcnow)

    subject = db.relationship("Subject")
    grade   = db.relationship("Grade")


# ── Qdrat-parity 2-level taxonomy (Axis + Indicator) ─────────────────
# Every school owns its own taxonomy tree, so a rename in school A can
# never leak into school B's item bank. The bank stores axis_id +
# indicator_id as plain FKs; the models mirror qdrat's المحور / المؤشر
# fields on the smart-question form.

class Axis(db.Model):
    __tablename__ = "axes"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"),
                          nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    order_index = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)

    indicators = db.relationship("Indicator", backref="axis",
                                 cascade="all, delete-orphan",
                                 order_by="Indicator.order_index")

    __table_args__ = (
        db.UniqueConstraint("school_id", "name", name="uq_axes_school_name"),
    )


class Indicator(db.Model):
    __tablename__ = "indicators"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"),
                          nullable=False, index=True)
    axis_id = db.Column(db.Integer, db.ForeignKey("axes.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    name = db.Column(db.String(160), nullable=False)
    order_index = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        db.UniqueConstraint("axis_id", "name", name="uq_indicators_axis_name"),
    )


# ---------- Announcements ----------

class Announcement(SoftDeleteMixin, db.Model):
    __tablename__ = "lms_announcements"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    section_id = db.Column(db.Integer, db.ForeignKey("sections.id"), index=True)  # null = school-wide
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, default="")
    is_pinned = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)
