from datetime import datetime
from ..extensions import db


MATERIAL_KINDS = ["file", "video", "link"]


class Material(db.Model):
    __tablename__ = "materials"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teachers.id"), nullable=False, index=True)
    year_id = db.Column(db.Integer, db.ForeignKey("academic_years.id"), nullable=False, index=True)
    section_id = db.Column(db.Integer, db.ForeignKey("sections.id"), nullable=False, index=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    kind = db.Column(db.String(16), nullable=False)
    file_path = db.Column(db.String(255))
    external_url = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    teacher = db.relationship("Teacher")
    section = db.relationship("Section")
    subject = db.relationship("Subject")
    year = db.relationship("AcademicYear")
