from datetime import datetime
from ..extensions import db


ATTENDANCE_STATUSES = ["present", "absent", "late"]


class Attendance(db.Model):
    __tablename__ = "attendance"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    enrollment_id = db.Column(db.Integer, db.ForeignKey("enrollments.id"), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(16), nullable=False)
    notes = db.Column(db.String(255))
    recorded_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    enrollment = db.relationship("Enrollment", backref="attendance_records")

    __table_args__ = (
        db.UniqueConstraint("enrollment_id", "date", name="uq_attendance_enrollment_date"),
    )


class NotificationLog(db.Model):
    __tablename__ = "notification_logs"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    # Sprint 11 (parent-scoping fix): notifications now carry a direct FK to
    # the student they concern. The prior read-side filter joined via
    # target_phone matching, which cross-leaked when two families shared a
    # phone number. Nullable so legacy rows without a resolvable student
    # (backfill misses) don't fail the constraint; those rows just stop
    # surfacing to any parent — expected behavior.
    student_id = db.Column(
        db.Integer,
        db.ForeignKey("students.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    kind = db.Column(db.String(32), nullable=False)
    target_phone = db.Column(db.String(32))
    target_email = db.Column(db.String(128))
    payload = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(16), default="queued", nullable=False)
    attempts = db.Column(db.Integer, default=0, nullable=False)
    last_attempt_at = db.Column(db.DateTime)
    sent_at = db.Column(db.DateTime)
    error = db.Column(db.String(255))
    related_kind = db.Column(db.String(32))
    related_id = db.Column(db.Integer)
    read_at = db.Column(db.DateTime, nullable=True)  # Sprint 10: parent tapped/read
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    student = db.relationship("Student", foreign_keys=[student_id])


class DeviceToken(db.Model):
    """Sprint 10 Phase 3 — FCM device token registered by mobile apps."""
    __tablename__ = "device_tokens"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    platform = db.Column(db.String(16), nullable=False)  # "ios" | "android"
    token = db.Column(db.String(255), nullable=False, unique=True)
    app = db.Column(db.String(16), nullable=False)  # "teacher" | "parent"
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User", backref="device_tokens")
