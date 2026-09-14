from datetime import datetime
from ..extensions import db


PASS_METHODS = ["overall_only", "per_subject", "mixed"]
RESULT_STATUSES = ["pending", "pass", "fail", "incomplete"]


class PassRule(db.Model):
    __tablename__ = "pass_rules"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    year_id = db.Column(db.Integer, db.ForeignKey("academic_years.id"), nullable=False, index=True)
    subject_pass_threshold = db.Column(db.Numeric(5, 2), default=50, nullable=False)
    overall_pass_threshold = db.Column(db.Numeric(5, 2), default=50, nullable=False)
    method = db.Column(db.String(16), default="overall_only", nullable=False)
    allowed_failed_subjects = db.Column(db.Integer, default=0, nullable=False)
    is_frozen = db.Column(db.Boolean, default=False, nullable=False)

    __table_args__ = (db.UniqueConstraint("year_id", name="uq_pass_rule_year"),)


class AssessmentComponent(db.Model):
    __tablename__ = "assessment_components"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    term_id = db.Column(db.Integer, db.ForeignKey("terms.id"), nullable=False, index=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=False, index=True)
    name = db.Column(db.String(64), nullable=False)
    max_score = db.Column(db.Numeric(6, 2), nullable=False)

    term = db.relationship("Term")
    subject = db.relationship("Subject")

    __table_args__ = (
        db.UniqueConstraint("term_id", "subject_id", "name", name="uq_component_term_subject_name"),
    )


class GradeEntry(db.Model):
    __tablename__ = "grade_entries"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    enrollment_id = db.Column(db.Integer, db.ForeignKey("enrollments.id"), nullable=False, index=True)
    component_id = db.Column(db.Integer, db.ForeignKey("assessment_components.id"), nullable=False, index=True)
    score = db.Column(db.Numeric(6, 2), nullable=False)
    recorded_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    enrollment = db.relationship("Enrollment")
    component = db.relationship("AssessmentComponent")

    __table_args__ = (
        db.UniqueConstraint("enrollment_id", "component_id", name="uq_grade_enrollment_component"),
    )


class YearResult(db.Model):
    __tablename__ = "year_results"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    enrollment_id = db.Column(db.Integer, db.ForeignKey("enrollments.id"), nullable=False, index=True)
    average = db.Column(db.Numeric(6, 2), nullable=False)
    status = db.Column(db.String(16), nullable=False)
    failed_subjects = db.Column(db.Integer, default=0, nullable=False)
    rule_snapshot = db.Column(db.JSON, nullable=False)
    subject_scores = db.Column(db.JSON, nullable=False)
    approved_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    approved_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    enrollment = db.relationship("Enrollment", backref="year_result")

    __table_args__ = (
        db.UniqueConstraint("enrollment_id", name="uq_year_result_enrollment"),
    )
