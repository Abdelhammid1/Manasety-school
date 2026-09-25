"""Sprint 16 — school-platform additions.

Every model here is additive; existing rows across the app remain
untouched. Grouping them in one module keeps the sprint's surface easy
to review — the natural per-domain homes (student.py, results.py …)
would spread across seven files.
"""
from datetime import datetime, timezone
from ..extensions import db
from .mixins import SoftDeleteMixin


def _utcnow():
    return datetime.now(timezone.utc)


# ─── Ticket 1 — Guardian / StudentGuardian ──────────────────────────

class Guardian(db.Model):
    """ولي أمر — كيان مستقل يمكن ربطه بأكثر من طالب.

    Sits alongside Student (not inside). One Guardian can be shared by
    every sibling in a family; the sibling relationship falls out of
    that shared row rather than being duplicated per-student.
    """
    __tablename__ = "guardians"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"),
                          nullable=False, index=True)

    full_name = db.Column(db.String(160), nullable=False)
    national_id = db.Column(db.String(32), index=True)
    phone = db.Column(db.String(32), index=True)
    phone_alt = db.Column(db.String(32))
    email = db.Column(db.String(128))
    occupation = db.Column(db.String(128))
    address = db.Column(db.String(255))
    # Login-side link so a guardian can sign in via the parent app.
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)

    user = db.relationship("User", backref=db.backref("guardian_profile", uselist=False))

    students = db.relationship(
        "Student", secondary="student_guardians",
        backref="guardians", viewonly=True,
    )


class StudentGuardian(SoftDeleteMixin, db.Model):
    """Join row — permissions live here, not on Guardian, so the same
    guardian can have different rights per child (rare but real)."""
    __tablename__ = "student_guardians"

    id = db.Column(db.Integer, primary_key=True)
    student_id  = db.Column(db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"),
                            nullable=False, index=True)
    guardian_id = db.Column(db.Integer, db.ForeignKey("guardians.id", ondelete="CASCADE"),
                            nullable=False, index=True)

    relationship = db.Column(db.String(32))   # أب | أم | جد | عم | وصي
    is_primary            = db.Column(db.Boolean, default=False, nullable=False)
    is_emergency_contact  = db.Column(db.Boolean, default=False, nullable=False)
    can_pickup_student    = db.Column(db.Boolean, default=True,  nullable=False)
    can_view_academic_data   = db.Column(db.Boolean, default=True,  nullable=False)
    can_view_financial_data  = db.Column(db.Boolean, default=False, nullable=False)
    can_receive_notifications = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)

    student  = db.relationship("Student", backref=db.backref(
        "guardian_links", cascade="all, delete-orphan"))
    guardian = db.relationship("Guardian", backref=db.backref(
        "student_links", cascade="all, delete-orphan"))

    __table_args__ = (
        db.UniqueConstraint("student_id", "guardian_id", name="uq_student_guardian"),
    )


# ─── Ticket 4 — SchoolCalendarDay ────────────────────────────────────

class SchoolCalendarDay(SoftDeleteMixin, db.Model):
    """A single dated entry in the school calendar. day_type drives the
    behaviour hooks (attendance refuses entry on holidays, etc)."""
    __tablename__ = "calendar_days"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"),
                          nullable=False, index=True)
    academic_year_id = db.Column(
        db.Integer, db.ForeignKey("academic_years.id", ondelete="CASCADE"),
        nullable=False,
    )
    date = db.Column(db.Date, nullable=False, index=True)
    day_type = db.Column(db.String(24), nullable=False)
    #   instructional | holiday | weekend | exam | event | teacher_day | break
    title = db.Column(db.String(160))
    description = db.Column(db.Text)
    applies_to_stage = db.Column(db.String(32))    # NULL = whole school
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)

    year = db.relationship("AcademicYear")

    __table_args__ = (
        db.UniqueConstraint("academic_year_id", "date", "applies_to_stage",
                            name="uq_cal_year_date_stage"),
    )

    @property
    def is_teaching(self) -> bool:
        """True when instruction (attendance, schedule) should count
        this date. Everything except `instructional` and `exam` is
        treated as non-teaching for those hooks."""
        return self.day_type in ("instructional", "exam")


# ─── Ticket 6 — AuditLog ────────────────────────────────────────────

class AuditLog(db.Model):
    """Row-level change trail. Written by services.audit event listeners
    on the sensitive tables listed in that module."""
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"))
    user_id   = db.Column(db.Integer, db.ForeignKey("users.id"))
    action = db.Column(db.String(16), nullable=False)   # create | update | delete
    entity_type = db.Column(db.String(64), nullable=False, index=True)
    entity_id   = db.Column(db.Integer, index=True)
    old_value = db.Column(db.JSON)
    new_value = db.Column(db.JSON)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(255))
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, index=True)

    user = db.relationship("User")


# ─── Ticket 7 — Rooms ────────────────────────────────────────────────

class Room(SoftDeleteMixin, db.Model):
    __tablename__ = "rooms"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"),
                          nullable=False, index=True)
    name = db.Column(db.String(64), nullable=False)   # قاعة 201 | معمل الحاسب
    code = db.Column(db.String(32))
    capacity = db.Column(db.Integer)
    room_type = db.Column(db.String(32))              # classroom | lab | gym | library
    is_active = db.Column(db.Boolean, default=True, nullable=False)


# ─── Ticket 9b — StaffAttendance + Substitutions ─────────────────────

class StaffAttendance(db.Model):
    """Daily record for an Employee. Feeds Payroll deductions."""
    __tablename__ = "staff_attendance"

    id = db.Column(db.Integer, primary_key=True)
    school_id  = db.Column(db.Integer, db.ForeignKey("schools.id"),
                           nullable=False, index=True)
    employee_id = db.Column(
        db.Integer, db.ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    date = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(16), default="present", nullable=False)
    #   present | absent | late | leave | official_mission
    leave_type = db.Column(db.String(32))
    #   annual | sick | emergency | unpaid
    notes = db.Column(db.String(255))

    employee = db.relationship("Employee", backref="attendance_records")

    __table_args__ = (
        db.UniqueConstraint("employee_id", "date", name="uq_staff_att_emp_date"),
    )


class SubstitutionLog(db.Model):
    """When a substitute teacher covers a slot for the absent original."""
    __tablename__ = "substitutions"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"),
                          nullable=False, index=True)
    schedule_slot_id = db.Column(db.Integer, db.ForeignKey("schedule_slots.id"),
                                 nullable=False)
    date = db.Column(db.Date, nullable=False)
    original_teacher_id   = db.Column(db.Integer, db.ForeignKey("teachers.id"),
                                       nullable=False)
    substitute_teacher_id = db.Column(db.Integer, db.ForeignKey("teachers.id"),
                                       nullable=False)
    reason = db.Column(db.String(255))
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)

    original_teacher = db.relationship("Teacher", foreign_keys=[original_teacher_id])
    substitute_teacher = db.relationship("Teacher", foreign_keys=[substitute_teacher_id])


# ─── Ticket 10 — Health ──────────────────────────────────────────────

class StudentHealthProfile(db.Model):
    __tablename__ = "student_health_profiles"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False)
    student_id = db.Column(
        db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False, unique=True,
    )
    blood_type = db.Column(db.String(8))
    chronic_conditions = db.Column(db.Text)
    allergies = db.Column(db.Text)
    regular_medications = db.Column(db.Text)
    special_needs = db.Column(db.Text)
    emergency_instructions = db.Column(db.Text)
    doctor_name = db.Column(db.String(128))
    doctor_phone = db.Column(db.String(32))
    insurance_provider = db.Column(db.String(128))
    insurance_number = db.Column(db.String(64))
    last_updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    updated_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    student = db.relationship("Student", backref=db.backref(
        "health_profile", uselist=False, cascade="all, delete-orphan"))


class HealthIncident(db.Model):
    __tablename__ = "health_incidents"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False)
    student_id = db.Column(
        db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    incident_date = db.Column(db.DateTime(timezone=True), nullable=False)
    incident_type = db.Column(db.String(32))
    #   injury | illness | medication_given | emergency
    description = db.Column(db.Text, nullable=False)
    action_taken = db.Column(db.Text)
    guardian_notified = db.Column(db.Boolean, default=False, nullable=False)
    notified_at = db.Column(db.DateTime(timezone=True))
    referred_to_hospital = db.Column(db.Boolean, default=False, nullable=False)
    recorded_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)

    student = db.relationship("Student", backref="health_incidents")


# ─── Ticket 11 — StudentDocument ─────────────────────────────────────

class StudentDocument(SoftDeleteMixin, db.Model):
    __tablename__ = "student_documents"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False)
    student_id = db.Column(
        db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    document_type = db.Column(db.String(48), nullable=False)
    title = db.Column(db.String(160))
    file_path = db.Column(db.String(255), nullable=False)
    file_size = db.Column(db.Integer)
    mime_type = db.Column(db.String(96))
    document_number = db.Column(db.String(64))
    issue_date = db.Column(db.Date)
    expiry_date = db.Column(db.Date)
    status = db.Column(db.String(16), default="valid", nullable=False)
    notes = db.Column(db.Text)
    uploaded_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)

    student = db.relationship("Student", backref="documents")


# ─── Ticket 12 — Behavior ────────────────────────────────────────────

class BehaviorCategory(db.Model):
    __tablename__ = "behavior_categories"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False)
    name = db.Column(db.String(96), nullable=False)
    kind = db.Column(db.String(16), default="negative", nullable=False)  # positive|negative
    default_points = db.Column(db.Integer, default=0, nullable=False)
    severity = db.Column(db.String(16))         # low|medium|high
    is_active = db.Column(db.Boolean, default=True, nullable=False)


class BehaviorIncident(db.Model):
    __tablename__ = "behavior_incidents"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False)
    student_id = db.Column(
        db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    category_id = db.Column(db.Integer, db.ForeignKey("behavior_categories.id"),
                            nullable=False)
    incident_date = db.Column(db.Date, nullable=False, index=True)
    section_id = db.Column(db.Integer, db.ForeignKey("sections.id"))
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"))
    description = db.Column(db.Text, nullable=False)
    points = db.Column(db.Integer, default=0, nullable=False)
    reported_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)

    student = db.relationship("Student", backref="behavior_incidents")
    category = db.relationship("BehaviorCategory")
    actions = db.relationship(
        "BehaviorAction", backref="incident",
        cascade="all, delete-orphan",
    )


class BehaviorAction(db.Model):
    __tablename__ = "behavior_actions"

    id = db.Column(db.Integer, primary_key=True)
    incident_id = db.Column(
        db.Integer, db.ForeignKey("behavior_incidents.id", ondelete="CASCADE"),
        nullable=False,
    )
    action_type = db.Column(db.String(32), nullable=False)
    #   warning | guardian_contact | guardian_meeting |
    #   detention | suspension | reward | counseling
    description = db.Column(db.Text)
    action_date = db.Column(db.Date)
    guardian_notified = db.Column(db.Boolean, default=False, nullable=False)
    taken_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)


# ─── Ticket 13 — Conversations + Messages ────────────────────────────

class Conversation(db.Model):
    __tablename__ = "conversations"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False)
    subject = db.Column(db.String(200))
    context_type = db.Column(db.String(32))
    #   student | invoice | attendance | behavior | general
    context_id = db.Column(db.Integer)
    status = db.Column(db.String(16), default="open", nullable=False)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)
    last_message_at = db.Column(db.DateTime(timezone=True))

    messages = db.relationship(
        "Message", backref="conversation",
        cascade="all, delete-orphan", order_by="Message.created_at",
    )
    participants = db.relationship(
        "ConversationParticipant", backref="conversation",
        cascade="all, delete-orphan",
    )


class ConversationParticipant(db.Model):
    __tablename__ = "conversation_participants"

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(
        db.Integer, db.ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    role = db.Column(db.String(24))    # initiator | recipient | observer
    last_read_at = db.Column(db.DateTime(timezone=True))
    is_muted = db.Column(db.Boolean, default=False, nullable=False)

    user = db.relationship("User")

    __table_args__ = (
        db.UniqueConstraint("conversation_id", "user_id", name="uq_conv_participant"),
    )


class Message(db.Model):
    __tablename__ = "messages"

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(
        db.Integer, db.ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    sender_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    attachment_path = db.Column(db.String(255))
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)
    edited_at = db.Column(db.DateTime(timezone=True))
    deleted_at = db.Column(db.DateTime(timezone=True))

    sender = db.relationship("User")


class NotificationPreference(db.Model):
    __tablename__ = "notification_preferences"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    channel = db.Column(db.String(16), nullable=False)  # in_app|email|sms|whatsapp|push
    event_type = db.Column(db.String(32), nullable=False)
    #   attendance | grades | homework | invoice | behavior | announcement
    is_enabled = db.Column(db.Boolean, default=True, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("user_id", "channel", "event_type", name="uq_notif_pref"),
    )


# ─── Ticket 14 — UserScope ──────────────────────────────────────────

class UserScope(db.Model):
    __tablename__ = "user_scopes"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    scope_type = db.Column(db.String(24), nullable=False)
    #   all_school | stage | grade | section | own_assignments
    scope_value = db.Column(db.Integer)     # grade_id / section_id
    stage_value = db.Column(db.String(32))


# ─── Ticket 15 — Grading scales ──────────────────────────────────────

class GradingScale(db.Model):
    __tablename__ = "grading_scales"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False)
    name = db.Column(db.String(96), nullable=False)
    scale_type = db.Column(db.String(16), default="numeric", nullable=False)
    #   numeric | letter | descriptive
    applies_to_stage = db.Column(db.String(32))
    is_default = db.Column(db.Boolean, default=False, nullable=False)

    levels = db.relationship(
        "GradingScaleLevel", backref="scale",
        cascade="all, delete-orphan",
        order_by="GradingScaleLevel.order_index",
    )


class GradingScaleLevel(db.Model):
    __tablename__ = "grading_scale_levels"

    id = db.Column(db.Integer, primary_key=True)
    scale_id = db.Column(
        db.Integer, db.ForeignKey("grading_scales.id", ondelete="CASCADE"),
        nullable=False,
    )
    label = db.Column(db.String(32), nullable=False)     # A+ | ممتاز
    min_score = db.Column(db.Numeric(5, 2), nullable=False)
    max_score = db.Column(db.Numeric(5, 2), nullable=False)
    gpa_points = db.Column(db.Numeric(4, 2))
    is_passing = db.Column(db.Boolean, default=True, nullable=False)
    color = db.Column(db.String(16))
    order_index = db.Column(db.Integer, default=0, nullable=False)


# ─── Ticket 16 — Rubrics ─────────────────────────────────────────────

class Rubric(SoftDeleteMixin, db.Model):
    __soft_delete_cascades__ = ("criteria",)
    __tablename__ = "rubrics"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"))
    is_template = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)

    criteria = db.relationship(
        "RubricCriterion", backref="rubric",
        cascade="all, delete-orphan",
        order_by="RubricCriterion.order_index",
    )


class RubricCriterion(SoftDeleteMixin, db.Model):
    __tablename__ = "rubric_criteria"

    id = db.Column(db.Integer, primary_key=True)
    rubric_id = db.Column(
        db.Integer, db.ForeignKey("rubrics.id", ondelete="CASCADE"), nullable=False,
    )
    title = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text)
    weight = db.Column(db.Numeric(5, 2), default=0, nullable=False)
    max_score = db.Column(db.Numeric(6, 2), default=100, nullable=False)
    order_index = db.Column(db.Integer, default=0, nullable=False)


class RubricScore(db.Model):
    __tablename__ = "rubric_scores"

    id = db.Column(db.Integer, primary_key=True)
    criterion_id = db.Column(
        db.Integer, db.ForeignKey("rubric_criteria.id", ondelete="CASCADE"),
        nullable=False,
    )
    submission_id = db.Column(db.Integer, db.ForeignKey("lms_submissions.id", ondelete="CASCADE"))
    grade_entry_id = db.Column(db.Integer, db.ForeignKey("grade_entries.id", ondelete="CASCADE"))
    score = db.Column(db.Numeric(6, 2))
    comment = db.Column(db.Text)
    graded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    graded_at = db.Column(db.DateTime(timezone=True), default=_utcnow)


# ─── Ticket 17 — Discounts ──────────────────────────────────────────

class DiscountType(db.Model):
    __tablename__ = "discount_types"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False)
    name = db.Column(db.String(128), nullable=False)   # خصم إخوة | منحة تفوق | خصم موظفين
    calc_method = db.Column(db.String(16), default="percentage", nullable=False)
    #   percentage | fixed
    value = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    applies_to_fee_type_id = db.Column(db.Integer, db.ForeignKey("fee_types.id"))
    #   NULL → applies to every fee type
    auto_rule = db.Column(db.String(32))
    #   sibling_count_2 | sibling_count_3 | staff_child | NULL = manual
    requires_approval = db.Column(db.Boolean, default=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)


class StudentDiscount(db.Model):
    __tablename__ = "student_discounts"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False)
    enrollment_id = db.Column(
        db.Integer, db.ForeignKey("enrollments.id", ondelete="CASCADE"),
        nullable=False,
    )
    discount_type_id = db.Column(db.Integer, db.ForeignKey("discount_types.id"),
                                 nullable=False)
    override_value = db.Column(db.Numeric(12, 2))
    reason = db.Column(db.String(255))
    status = db.Column(db.String(16), default="pending", nullable=False)
    approved_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    approved_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)

    discount_type = db.relationship("DiscountType")


# ─── Ticket 18 — Transcript snapshot ─────────────────────────────────

class TranscriptSnapshot(db.Model):
    __tablename__ = "transcript_snapshots"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    issued_at = db.Column(db.DateTime(timezone=True), default=_utcnow)
    issued_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    content = db.Column(db.JSON, nullable=False)
    serial_number = db.Column(db.String(48), unique=True, nullable=False)
    purpose = db.Column(db.String(128))    # نقل مدرسة | جهة رسمية | أرشيف

    student = db.relationship("Student")


# ─── Ticket 5 — ImportBatch ─────────────────────────────────────────

class ImportBatch(db.Model):
    __tablename__ = "import_batches"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    entity_type = db.Column(db.String(32), nullable=False)
    #   students | teachers | guardians | questions
    file_name = db.Column(db.String(255))
    total_rows = db.Column(db.Integer, default=0, nullable=False)
    success_rows = db.Column(db.Integer, default=0, nullable=False)
    failed_rows = db.Column(db.Integer, default=0, nullable=False)
    error_log = db.Column(db.JSON)
    status = db.Column(db.String(16), default="pending", nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)


# ── نداء — parent pickup call ────────────────────────────────────────
class PickupCall(db.Model):
    """A live "pick me up" signal from a parent standing outside the
    school. Broadcasts to the student + the responsible teacher via
    the notifications pipeline; parent can close it when the student
    is in the car."""
    __tablename__ = "pickup_calls"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"),
                          nullable=False, index=True)
    parent_user_id  = db.Column(db.Integer, db.ForeignKey("users.id"),
                                nullable=False, index=True)
    student_id      = db.Column(db.Integer, db.ForeignKey("students.id"),
                                nullable=False, index=True)
    teacher_user_id = db.Column(db.Integer, db.ForeignKey("users.id"),
                                nullable=True, index=True)
    section_id      = db.Column(db.Integer, db.ForeignKey("sections.id"),
                                nullable=True, index=True)
    note = db.Column(db.String(255), nullable=True)
    gate = db.Column(db.String(64), nullable=True)

    called_at          = db.Column(db.DateTime(timezone=True),
                                   default=_utcnow, nullable=False, index=True)
    seen_by_student_at = db.Column(db.DateTime(timezone=True))
    seen_by_teacher_at = db.Column(db.DateTime(timezone=True))
    released_at        = db.Column(db.DateTime(timezone=True), index=True)
    released_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    student = db.relationship("Student", foreign_keys=[student_id])
    section = db.relationship("Section", foreign_keys=[section_id])
    parent  = db.relationship("User",   foreign_keys=[parent_user_id])
    teacher = db.relationship("User",   foreign_keys=[teacher_user_id])

    @property
    def is_active(self):
        return self.released_at is None

    @property
    def waited_minutes(self):
        from datetime import datetime, timezone as _tz
        end = self.released_at or datetime.now(_tz.utc)
        started = self.called_at
        if started and started.tzinfo is None:
            started = started.replace(tzinfo=_tz.utc)
        return int((end - started).total_seconds() // 60)
