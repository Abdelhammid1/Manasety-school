from datetime import datetime
from ..extensions import db
from .mixins import SoftDeleteMixin


ENROLLMENT_STATUSES = [
    "active", "withdrawn", "transferred", "promoted_out",
    # Ticket S4 — final-year students land here after graduation instead
    # of being deleted / promoted-out again.
    "graduated",
]
RESULT_VALUES = ["pending", "pass", "fail"]


class Student(db.Model):
    __tablename__ = "students"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    permanent_code = db.Column(db.String(32), nullable=False)
    full_name = db.Column(db.String(160), nullable=False)
    national_id = db.Column(db.String(32))
    dob = db.Column(db.Date)
    gender = db.Column(db.String(8))
    parent_name = db.Column(db.String(160))
    parent_phone = db.Column(db.String(32))
    parent_email = db.Column(db.String(128))
    parent_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    # Student's own login (used by the student mobile app). Nullable
    # only for historical rows created before Ticket #1 (2026-09-25);
    # every new student now gets a User in the same transaction and
    # the `unique=True` here rejects any attempt to bind two Students
    # to the same User.
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"),
                        unique=True, index=True)
    mother_name = db.Column(db.String(160))
    mother_phone = db.Column(db.String(32))
    address = db.Column(db.String(255))
    notes = db.Column(db.Text)
    # Ticket S6 — profile photo URL. Uploaded via student_tabs.
    photo_url = db.Column(db.String(500), nullable=True)
    # Financial-automation ticket — subsidiary AR sub-account under 1210.
    # Lazy-created by services.subsidiary.ensure_student_account on the
    # first invoice; stays NULL until the student actually needs one.
    ar_account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"),
                              nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    parent_user = db.relationship("User", foreign_keys=[parent_user_id], backref="children")
    user = db.relationship("User", foreign_keys=[user_id], backref=db.backref(
        "student_profile", uselist=False,
    ))
    ar_account = db.relationship("Account", foreign_keys=[ar_account_id])
    enrollments = db.relationship(
        "Enrollment", backref="student", order_by="Enrollment.id.desc()"
    )

    __table_args__ = (
        db.UniqueConstraint("school_id", "permanent_code", name="uq_student_school_code"),
    )


class Enrollment(db.Model):
    __tablename__ = "enrollments"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False, index=True)
    year_id = db.Column(db.Integer, db.ForeignKey("academic_years.id"), nullable=False, index=True)
    grade_id = db.Column(db.Integer, db.ForeignKey("grades.id"), nullable=False)
    section_id = db.Column(db.Integer, db.ForeignKey("sections.id"), nullable=False, index=True)

    status = db.Column(db.String(16), default="active", nullable=False)
    final_result = db.Column(db.String(16), default="pending", nullable=False)

    # Ticket T7a — `datetime.utcnow().date` (no lambda) evaluates once
    # at class-load time and freezes the date at server start. Wrap in
    # a lambda so each fresh insert gets today's real date.
    enrolled_at = db.Column(db.Date, default=lambda: datetime.utcnow().date(), nullable=False)
    status_changed_at = db.Column(db.Date)
    status_reason = db.Column(db.String(255))
    # Ticket S4 — set when status transitions to 'graduated'.
    graduation_date = db.Column(db.Date, nullable=True)
    # Ticket S5 — checklist snapshot for the exit interview at
    # withdrawal time. Stored as a JSON string so it survives without
    # a dedicated table for the v1.
    exit_checklist = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    year = db.relationship("AcademicYear")
    grade = db.relationship("Grade")
    section = db.relationship("Section")

    __table_args__ = (
        db.UniqueConstraint("student_id", "year_id", name="uq_enrollment_student_year"),
    )


class TransferLog(db.Model):
    __tablename__ = "transfer_logs"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    enrollment_id = db.Column(db.Integer, db.ForeignKey("enrollments.id"), nullable=False, index=True)
    from_section_id = db.Column(db.Integer, db.ForeignKey("sections.id"), nullable=False)
    to_section_id = db.Column(db.Integer, db.ForeignKey("sections.id"), nullable=False)
    # T7a — see Enrollment.enrolled_at for the same reasoning.
    transfer_date = db.Column(db.Date, default=lambda: datetime.utcnow().date(), nullable=False)
    performed_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    notes = db.Column(db.String(255))

    enrollment = db.relationship("Enrollment", backref="transfer_logs")
    from_section = db.relationship("Section", foreign_keys=[from_section_id])
    to_section = db.relationship("Section", foreign_keys=[to_section_id])


# ─── Ticket S10 — StudentNote (timeline log, not the flat Student.notes) ──
class StudentNote(db.Model):
    __tablename__ = "student_notes"

    id = db.Column(db.Integer, primary_key=True)
    school_id  = db.Column(db.Integer, db.ForeignKey("schools.id"),
                           nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id",
                                                     ondelete="CASCADE"),
                           nullable=False, index=True)
    author_id  = db.Column(db.Integer, db.ForeignKey("users.id"),
                           nullable=True)
    body       = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    student = db.relationship("Student", backref=db.backref(
        "diary_notes", order_by="StudentNote.created_at.desc()",
        cascade="all, delete-orphan",
    ))
    author = db.relationship("User")


# ─── Ticket S11 — StudentTag (M:N) ────────────────────────────────────
student_tag_links = db.Table(
    "student_tag_links",
    db.Column("student_id", db.Integer,
              db.ForeignKey("students.id", ondelete="CASCADE"),
              primary_key=True),
    db.Column("tag_id", db.Integer,
              db.ForeignKey("student_tags.id", ondelete="CASCADE"),
              primary_key=True),
)


class StudentTag(db.Model):
    __tablename__ = "student_tags"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"),
                          nullable=False, index=True)
    name  = db.Column(db.String(60), nullable=False)
    color = db.Column(db.String(16), nullable=True)   # HEX or tailwind key
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    students = db.relationship("Student", secondary="student_tag_links",
                               backref="tags", lazy="selectin")

    __table_args__ = (
        db.UniqueConstraint("school_id", "name", name="uq_student_tag_school_name"),
    )


# ─── Ticket S3 — PreviousSchool (student's academic history pre-enrolment) ─
class PreviousSchool(db.Model):
    __tablename__ = "student_previous_schools"

    id = db.Column(db.Integer, primary_key=True)
    school_id  = db.Column(db.Integer, db.ForeignKey("schools.id"),
                           nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id",
                                                     ondelete="CASCADE"),
                           nullable=False, index=True)
    name        = db.Column(db.String(200), nullable=False)
    city        = db.Column(db.String(100), nullable=True)
    from_year   = db.Column(db.String(20), nullable=True)
    to_year     = db.Column(db.String(20), nullable=True)
    reason      = db.Column(db.Text, nullable=True)
    document_url = db.Column(db.String(500), nullable=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    student = db.relationship("Student", backref=db.backref(
        "previous_schools",
        order_by="PreviousSchool.created_at.desc()",
        cascade="all, delete-orphan",
    ))
