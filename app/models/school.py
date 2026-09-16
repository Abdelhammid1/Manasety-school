from datetime import datetime
from ..extensions import db


class School(db.Model):
    __tablename__ = "schools"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(32), unique=True, nullable=False)
    name = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(32))
    address = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    # Ticket 8 — attendance display mode. Governs which UI the school
    # sees on the attendance screen.
    #   daily        → one status per day (legacy)
    #   per_period   → one status per Period
    #   both         → both modes available side-by-side
    attendance_mode = db.Column(db.String(16), default="daily",
                                nullable=False, server_default="daily")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<School {self.code} {self.name}>"
