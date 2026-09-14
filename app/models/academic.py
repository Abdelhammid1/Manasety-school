from datetime import datetime
from ..extensions import db


class AcademicYear(db.Model):
    __tablename__ = "academic_years"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    name = db.Column(db.String(32), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(16), default="active", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    terms = db.relationship("Term", backref="year", cascade="all, delete-orphan", order_by="Term.order_index")
    sections = db.relationship("Section", backref="year", cascade="all, delete-orphan")

    __table_args__ = (db.UniqueConstraint("school_id", "name", name="uq_year_school_name"),)


class Term(db.Model):
    __tablename__ = "terms"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    year_id = db.Column(db.Integer, db.ForeignKey("academic_years.id"), nullable=False, index=True)
    name = db.Column(db.String(64), nullable=False)
    order_index = db.Column(db.Integer, nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    weight = db.Column(db.Numeric(5, 2), nullable=False, default=0)

    __table_args__ = (db.UniqueConstraint("year_id", "order_index", name="uq_term_year_order"),)


class Grade(db.Model):
    __tablename__ = "grades"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    name = db.Column(db.String(64), nullable=False)
    order_index = db.Column(db.Integer, nullable=False)
    stage = db.Column(db.String(32))

    sections = db.relationship("Section", backref="grade")

    __table_args__ = (
        db.UniqueConstraint("school_id", "name", name="uq_grade_school_name"),
        db.UniqueConstraint("school_id", "order_index", name="uq_grade_school_order"),
    )


class Section(db.Model):
    __tablename__ = "sections"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    year_id = db.Column(db.Integer, db.ForeignKey("academic_years.id"), nullable=False, index=True)
    grade_id = db.Column(db.Integer, db.ForeignKey("grades.id"), nullable=False, index=True)
    name = db.Column(db.String(16), nullable=False)
    capacity = db.Column(db.Integer, default=30, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("year_id", "grade_id", "name", name="uq_section_year_grade_name"),
    )

    @property
    def current_count(self) -> int:
        from .student import Enrollment
        return Enrollment.query.filter_by(section_id=self.id, status="active").count()

    @property
    def is_full(self) -> bool:
        return self.current_count >= self.capacity
