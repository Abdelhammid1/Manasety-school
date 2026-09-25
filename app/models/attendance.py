from datetime import datetime
from ..extensions import db


ATTENDANCE_STATUSES = ["present", "absent", "late", "excused", "left_early"]


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

    # Ticket 8 — per-period attendance. NULL period_id preserves the
    # legacy daily-attendance semantics; when set, the row records one
    # slot only, letting a student be present at some periods and
    # absent at others.
    schedule_slot_id = db.Column(db.Integer, db.ForeignKey("schedule_slots.id"), index=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), index=True)
    period_id  = db.Column(db.Integer, db.ForeignKey("periods.id"),  index=True)
    excuse_reason = db.Column(db.String(255))
    excuse_document = db.Column(db.String(255))

    enrollment = db.relationship("Enrollment", backref="attendance_records")

    __table_args__ = (
        db.UniqueConstraint("enrollment_id", "date", "period_id",
                            name="uq_attendance_enrollment_date_period"),
    )


# ─── Ticket T3 — Attendance rules engine ───────────────────────────
class AttendanceRule(db.Model):
    """Configurable escalation rule. Evaluated after every absence
    write; matching students get one AttendanceRuleTriggered row per
    match so the same threshold doesn't re-fire on refresh.

    kind:
      - `consecutive` — X absences in a row
      - `cumulative`  — X absences in the window
    window:
      - `term`   — from the enrollment's term start
      - `year`   — from the enrollment's academic year start
      - `days:N` — the last N calendar days
    action:
      - `warning`      — internal flag
      - `notify_guardian` — enqueue an SMS/notification
      - `escalate_admin`  — flag for admin review
    """
    __tablename__ = "attendance_rules"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"),
                          nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    kind = db.Column(db.String(20), nullable=False)       # consecutive|cumulative
    threshold = db.Column(db.Integer, nullable=False)
    window = db.Column(db.String(20), nullable=False,
                       default="term", server_default="term")
    action = db.Column(db.String(24), nullable=False,
                       default="warning", server_default="warning")
    is_active = db.Column(db.Boolean, default=True, nullable=False,
                          server_default="true")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class AttendanceRuleTriggered(db.Model):
    """One row per (rule, student, week) so re-runs stay idempotent."""
    __tablename__ = "attendance_rule_triggers"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"),
                          nullable=False, index=True)
    rule_id = db.Column(db.Integer, db.ForeignKey("attendance_rules.id",
                                                   ondelete="CASCADE"),
                        nullable=False, index=True)
    student_id = db.Column(db.Integer,
                           db.ForeignKey("students.id",
                                          ondelete="CASCADE"),
                           nullable=False, index=True)
    triggered_on = db.Column(db.Date, nullable=False,
                             default=lambda: datetime.utcnow().date())
    count_at_trigger = db.Column(db.Integer, nullable=False)
    resolved = db.Column(db.Boolean, default=False, nullable=False,
                         server_default="false")

    rule    = db.relationship("AttendanceRule")
    student = db.relationship("Student")


# ─── Ticket T4 — Student risk score ────────────────────────────────
class StudentRiskScore(db.Model):
    """Per-student risk score (0..100). Higher = higher risk.

    Signal sources (v1):
      - attendance_rate over 30d      (weight 40)
      - chronic absent days last 30d  (weight 25)
      - unresolved rule triggers      (weight 20)
      - behavior points (last term)   (weight 15)
    """
    __tablename__ = "student_risk_scores"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"),
                          nullable=False, index=True)
    student_id = db.Column(db.Integer,
                           db.ForeignKey("students.id",
                                          ondelete="CASCADE"),
                           nullable=False, unique=True, index=True)
    score = db.Column(db.Integer, nullable=False, default=0)
    tier  = db.Column(db.String(16), nullable=False,
                      default="low")   # low | medium | high | critical
    inputs = db.Column(db.JSON, nullable=True)
    computed_at = db.Column(db.DateTime, default=datetime.utcnow,
                            nullable=False)

    student = db.relationship("Student")


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
