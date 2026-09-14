from datetime import datetime
from ..extensions import db


ENROLLMENT_STATUSES = ["active", "withdrawn", "transferred", "promoted_out"]
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
    mother_name = db.Column(db.String(160))
    mother_phone = db.Column(db.String(32))
    address = db.Column(db.String(255))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    parent_user = db.relationship("User", foreign_keys=[parent_user_id], backref="children")
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

    enrolled_at = db.Column(db.Date, default=datetime.utcnow().date, nullable=False)
    status_changed_at = db.Column(db.Date)
    status_reason = db.Column(db.String(255))
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
    transfer_date = db.Column(db.Date, default=datetime.utcnow().date, nullable=False)
    performed_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    notes = db.Column(db.String(255))

    enrollment = db.relationship("Enrollment", backref="transfer_logs")
    from_section = db.relationship("Section", foreign_keys=[from_section_id])
    to_section = db.relationship("Section", foreign_keys=[to_section_id])
