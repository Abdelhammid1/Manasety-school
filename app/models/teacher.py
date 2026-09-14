from datetime import datetime
from ..extensions import db


subject_grades = db.Table(
    "subject_grades",
    db.Column("subject_id", db.Integer, db.ForeignKey("subjects.id"), primary_key=True),
    db.Column("grade_id", db.Integer, db.ForeignKey("grades.id"), primary_key=True),
)


class Teacher(db.Model):
    __tablename__ = "teachers"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, index=True)
    full_name = db.Column(db.String(160), nullable=False)
    national_id = db.Column(db.String(32))
    phone = db.Column(db.String(32))
    email = db.Column(db.String(128))
    specialization = db.Column(db.String(128), nullable=False)
    hire_date = db.Column(db.Date)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User", foreign_keys=[user_id], backref=db.backref("teacher_profile", uselist=False))


class Subject(db.Model):
    __tablename__ = "subjects"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    name = db.Column(db.String(128), nullable=False)
    code = db.Column(db.String(32))
    is_active = db.Column(
        db.Boolean, default=True, nullable=False, server_default="true"
    )

    grades = db.relationship("Grade", secondary=subject_grades, backref="subjects")
    assignments = db.relationship("Assignment", backref="subject")

    __table_args__ = (db.UniqueConstraint("school_id", "name", name="uq_subject_school_name"),)


class Assignment(db.Model):
    __tablename__ = "assignments"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    year_id = db.Column(db.Integer, db.ForeignKey("academic_years.id"), nullable=False, index=True)
    section_id = db.Column(db.Integer, db.ForeignKey("sections.id"), nullable=False, index=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=False, index=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teachers.id"), nullable=False, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    weekly_periods = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    section = db.relationship("Section", backref="assignments")
    teacher = db.relationship("Teacher", backref="assignments")
    year = db.relationship("AcademicYear")

    __table_args__ = (
        db.UniqueConstraint(
            "year_id", "section_id", "subject_id", "teacher_id",
            name="uq_assignment_unique_quad",
        ),
    )


class Day(db.Model):
    __tablename__ = "days"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    name = db.Column(db.String(32), nullable=False)
    order_index = db.Column(db.Integer, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("school_id", "order_index", name="uq_day_school_order"),
    )


class Period(db.Model):
    __tablename__ = "periods"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    name = db.Column(db.String(64), nullable=False)
    order_index = db.Column(db.Integer, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    is_break = db.Column(db.Boolean, default=False, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("school_id", "order_index", name="uq_period_school_order"),
    )


class ScheduleSlot(db.Model):
    __tablename__ = "schedule_slots"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    year_id = db.Column(db.Integer, db.ForeignKey("academic_years.id"), nullable=False, index=True)
    section_id = db.Column(db.Integer, db.ForeignKey("sections.id"), nullable=False, index=True)
    day_id = db.Column(db.Integer, db.ForeignKey("days.id"), nullable=False, index=True)
    period_id = db.Column(db.Integer, db.ForeignKey("periods.id"), nullable=False, index=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teachers.id"), nullable=False)

    section = db.relationship("Section")
    day = db.relationship("Day")
    period = db.relationship("Period")
    subject = db.relationship("Subject")
    teacher = db.relationship("Teacher")

    __table_args__ = (
        db.UniqueConstraint(
            "year_id", "section_id", "day_id", "period_id",
            name="uq_slot_cell",
        ),
    )
