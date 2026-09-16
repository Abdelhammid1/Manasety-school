"""sprint 16: school-platform expansion — guardians, calendar, audit,
health, documents, behavior, grading scales, rubrics, discounts,
transcripts, question versioning, per-period attendance, rooms.

Additive only — every column added is nullable or has a safe server
default, and every widened UniqueConstraint stays back-compatible via
NULLs in the new columns. Tickets 2 and 3 (course refactor + grade
unification) are deliberately deferred to a later migration because
they touch existing row semantics.

Covers tickets: 1, 4, 6, 7 (rooms + duration), 8, 9b (staff attendance +
substitutions), 10, 11, 12, 13, 14 (user_scopes), 15, 16, 17, 18, 19.

Revision ID: c5e6f7a8b9d1
Revises: b3d4e5f6a7c8
Create Date: 2026-09-16 15:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'c5e6f7a8b9d1'
down_revision = 'b3d4e5f6a7c8'
branch_labels = None
depends_on = None


def upgrade():
    # ── Ticket 1: Guardian + StudentGuardian ────────────────────────────
    op.create_table(
        'guardians',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('full_name', sa.String(length=160), nullable=False),
        sa.Column('national_id', sa.String(length=32), nullable=True),
        sa.Column('phone', sa.String(length=32), nullable=True),
        sa.Column('phone_alt', sa.String(length=32), nullable=True),
        sa.Column('email', sa.String(length=128), nullable=True),
        sa.Column('occupation', sa.String(length=128), nullable=True),
        sa.Column('address', sa.String(length=255), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('guardians', schema=None) as b:
        b.create_index(b.f('ix_guardians_school_id'), ['school_id'], unique=False)
        b.create_index(b.f('ix_guardians_national_id'), ['national_id'], unique=False)
        b.create_index(b.f('ix_guardians_phone'), ['phone'], unique=False)

    op.create_table(
        'student_guardians',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('student_id', sa.Integer(), nullable=False),
        sa.Column('guardian_id', sa.Integer(), nullable=False),
        sa.Column('relationship', sa.String(length=32), nullable=True),
        sa.Column('is_primary', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('is_emergency_contact', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('can_pickup_student', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('can_view_academic_data', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('can_view_financial_data', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('can_receive_notifications', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['student_id'], ['students.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['guardian_id'], ['guardians.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('student_id', 'guardian_id', name='uq_student_guardian'),
    )
    with op.batch_alter_table('student_guardians', schema=None) as b:
        b.create_index(b.f('ix_student_guardians_student_id'), ['student_id'], unique=False)
        b.create_index(b.f('ix_student_guardians_guardian_id'), ['guardian_id'], unique=False)

    # ── Ticket 4: SchoolCalendarDay ─────────────────────────────────────
    op.create_table(
        'calendar_days',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('academic_year_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('day_type', sa.String(length=24), nullable=False),
        sa.Column('title', sa.String(length=160), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('applies_to_stage', sa.String(length=32), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id']),
        sa.ForeignKeyConstraint(['academic_year_id'], ['academic_years.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('academic_year_id', 'date', 'applies_to_stage',
                            name='uq_cal_year_date_stage'),
    )
    with op.batch_alter_table('calendar_days', schema=None) as b:
        b.create_index(b.f('ix_calendar_days_school_id'), ['school_id'], unique=False)
        b.create_index(b.f('ix_calendar_days_date'), ['date'], unique=False)

    # ── Ticket 6: AuditLog ──────────────────────────────────────────────
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(length=16), nullable=False),
        sa.Column('entity_type', sa.String(length=64), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=True),
        sa.Column('old_value', sa.JSON(), nullable=True),
        sa.Column('new_value', sa.JSON(), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('audit_logs', schema=None) as b:
        b.create_index(b.f('ix_audit_logs_entity_type'), ['entity_type'], unique=False)
        b.create_index(b.f('ix_audit_logs_entity_id'), ['entity_id'], unique=False)
        b.create_index(b.f('ix_audit_logs_created_at'), ['created_at'], unique=False)

    # ── Ticket 7: rooms + Period.duration_minutes + Day/Period scope ────
    op.create_table(
        'rooms',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('code', sa.String(length=32), nullable=True),
        sa.Column('capacity', sa.Integer(), nullable=True),
        sa.Column('room_type', sa.String(length=32), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('rooms', schema=None) as b:
        b.create_index(b.f('ix_rooms_school_id'), ['school_id'], unique=False)

    with op.batch_alter_table('days', schema=None) as b:
        b.add_column(sa.Column('academic_year_id', sa.Integer(), nullable=True))
        b.add_column(sa.Column('stage', sa.String(length=32), nullable=True))
        b.create_foreign_key('fk_days_year', 'academic_years', ['academic_year_id'], ['id'])
    with op.batch_alter_table('periods', schema=None) as b:
        b.add_column(sa.Column('academic_year_id', sa.Integer(), nullable=True))
        b.add_column(sa.Column('stage', sa.String(length=32), nullable=True))
        b.add_column(sa.Column('duration_minutes', sa.Integer(), nullable=True))
        b.create_foreign_key('fk_periods_year', 'academic_years', ['academic_year_id'], ['id'])
    with op.batch_alter_table('schedule_slots', schema=None) as b:
        b.add_column(sa.Column('room_id', sa.Integer(), nullable=True))
        b.create_index(b.f('ix_schedule_slots_room_id'), ['room_id'], unique=False)
        b.create_foreign_key('fk_slot_room', 'rooms', ['room_id'], ['id'])

    # ── Ticket 8: per-period attendance widening ────────────────────────
    with op.batch_alter_table('attendance', schema=None) as b:
        b.add_column(sa.Column('schedule_slot_id', sa.Integer(), nullable=True))
        b.add_column(sa.Column('subject_id', sa.Integer(), nullable=True))
        b.add_column(sa.Column('period_id', sa.Integer(), nullable=True))
        b.add_column(sa.Column('excuse_reason', sa.String(length=255), nullable=True))
        b.add_column(sa.Column('excuse_document', sa.String(length=255), nullable=True))
        b.create_index(b.f('ix_attendance_schedule_slot_id'), ['schedule_slot_id'], unique=False)
        b.create_index(b.f('ix_attendance_subject_id'), ['subject_id'], unique=False)
        b.create_index(b.f('ix_attendance_period_id'), ['period_id'], unique=False)
        b.create_foreign_key('fk_att_slot', 'schedule_slots', ['schedule_slot_id'], ['id'])
        b.create_foreign_key('fk_att_subject', 'subjects', ['subject_id'], ['id'])
        b.create_foreign_key('fk_att_period', 'periods', ['period_id'], ['id'])
        # Widen the uniqueness to include period_id — NULL keeps the
        # legacy daily-attendance semantics working.
        try:
            b.drop_constraint('uq_attendance_enrollment_date', type_='unique')
        except Exception:
            pass
        b.create_unique_constraint(
            'uq_attendance_enrollment_date_period',
            ['enrollment_id', 'date', 'period_id'],
        )

    with op.batch_alter_table('schools', schema=None) as b:
        b.add_column(sa.Column('attendance_mode', sa.String(length=16),
                               nullable=False, server_default='daily'))

    # ── Ticket 9b: StaffAttendance + Substitutions ─────────────────────
    op.create_table(
        'staff_attendance',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('employee_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='present'),
        sa.Column('leave_type', sa.String(length=32), nullable=True),
        sa.Column('notes', sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id']),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('employee_id', 'date', name='uq_staff_att_emp_date'),
    )
    with op.batch_alter_table('staff_attendance', schema=None) as b:
        b.create_index(b.f('ix_staff_attendance_employee_id'), ['employee_id'], unique=False)
        b.create_index(b.f('ix_staff_attendance_date'), ['date'], unique=False)

    op.create_table(
        'substitutions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('schedule_slot_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('original_teacher_id', sa.Integer(), nullable=False),
        sa.Column('substitute_teacher_id', sa.Integer(), nullable=False),
        sa.Column('reason', sa.String(length=255), nullable=True),
        sa.Column('created_by_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id']),
        sa.ForeignKeyConstraint(['schedule_slot_id'], ['schedule_slots.id']),
        sa.ForeignKeyConstraint(['original_teacher_id'], ['teachers.id']),
        sa.ForeignKeyConstraint(['substitute_teacher_id'], ['teachers.id']),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    # ── Ticket 10: StudentHealthProfile + HealthIncident ───────────────
    op.create_table(
        'student_health_profiles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('student_id', sa.Integer(), nullable=False),
        sa.Column('blood_type', sa.String(length=8), nullable=True),
        sa.Column('chronic_conditions', sa.Text(), nullable=True),
        sa.Column('allergies', sa.Text(), nullable=True),
        sa.Column('regular_medications', sa.Text(), nullable=True),
        sa.Column('special_needs', sa.Text(), nullable=True),
        sa.Column('emergency_instructions', sa.Text(), nullable=True),
        sa.Column('doctor_name', sa.String(length=128), nullable=True),
        sa.Column('doctor_phone', sa.String(length=32), nullable=True),
        sa.Column('insurance_provider', sa.String(length=128), nullable=True),
        sa.Column('insurance_number', sa.String(length=64), nullable=True),
        sa.Column('last_updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_by_user_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id']),
        sa.ForeignKeyConstraint(['student_id'], ['students.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['updated_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('student_id', name='uq_health_profile_student'),
    )
    op.create_table(
        'health_incidents',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('student_id', sa.Integer(), nullable=False),
        sa.Column('incident_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('incident_type', sa.String(length=32), nullable=True),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('action_taken', sa.Text(), nullable=True),
        sa.Column('guardian_notified', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('notified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('referred_to_hospital', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('recorded_by_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id']),
        sa.ForeignKeyConstraint(['student_id'], ['students.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['recorded_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('health_incidents', schema=None) as b:
        b.create_index(b.f('ix_health_incidents_student_id'), ['student_id'], unique=False)

    # ── Ticket 11: StudentDocument ─────────────────────────────────────
    op.create_table(
        'student_documents',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('student_id', sa.Integer(), nullable=False),
        sa.Column('document_type', sa.String(length=48), nullable=False),
        sa.Column('title', sa.String(length=160), nullable=True),
        sa.Column('file_path', sa.String(length=255), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('mime_type', sa.String(length=96), nullable=True),
        sa.Column('document_number', sa.String(length=64), nullable=True),
        sa.Column('issue_date', sa.Date(), nullable=True),
        sa.Column('expiry_date', sa.Date(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='valid'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('uploaded_by_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id']),
        sa.ForeignKeyConstraint(['student_id'], ['students.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['uploaded_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('student_documents', schema=None) as b:
        b.create_index(b.f('ix_student_documents_student_id'), ['student_id'], unique=False)

    # ── Ticket 12: Behavior ────────────────────────────────────────────
    op.create_table(
        'behavior_categories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=96), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False, server_default='negative'),
        sa.Column('default_points', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('severity', sa.String(length=16), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'behavior_incidents',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('student_id', sa.Integer(), nullable=False),
        sa.Column('category_id', sa.Integer(), nullable=False),
        sa.Column('incident_date', sa.Date(), nullable=False),
        sa.Column('section_id', sa.Integer(), nullable=True),
        sa.Column('subject_id', sa.Integer(), nullable=True),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('points', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('reported_by_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id']),
        sa.ForeignKeyConstraint(['student_id'], ['students.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['category_id'], ['behavior_categories.id']),
        sa.ForeignKeyConstraint(['section_id'], ['sections.id']),
        sa.ForeignKeyConstraint(['subject_id'], ['subjects.id']),
        sa.ForeignKeyConstraint(['reported_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('behavior_incidents', schema=None) as b:
        b.create_index(b.f('ix_behavior_incidents_student_id'), ['student_id'], unique=False)
        b.create_index(b.f('ix_behavior_incidents_incident_date'), ['incident_date'], unique=False)

    op.create_table(
        'behavior_actions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('incident_id', sa.Integer(), nullable=False),
        sa.Column('action_type', sa.String(length=32), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('action_date', sa.Date(), nullable=True),
        sa.Column('guardian_notified', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('taken_by_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['incident_id'], ['behavior_incidents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['taken_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    # ── Ticket 13: Conversations + Messages + NotificationPrefs ────────
    op.create_table(
        'conversations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('subject', sa.String(length=200), nullable=True),
        sa.Column('context_type', sa.String(length=32), nullable=True),
        sa.Column('context_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='open'),
        sa.Column('created_by_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id']),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'conversation_participants',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('conversation_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(length=24), nullable=True),
        sa.Column('last_read_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_muted', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('conversation_id', 'user_id', name='uq_conv_participant'),
    )
    op.create_table(
        'messages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('conversation_id', sa.Integer(), nullable=False),
        sa.Column('sender_user_id', sa.Integer(), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('attachment_path', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('edited_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['sender_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('messages', schema=None) as b:
        b.create_index(b.f('ix_messages_conversation_id'), ['conversation_id'], unique=False)

    op.create_table(
        'notification_preferences',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('channel', sa.String(length=16), nullable=False),
        sa.Column('event_type', sa.String(length=32), nullable=False),
        sa.Column('is_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'channel', 'event_type', name='uq_notif_pref'),
    )

    # ── Ticket 14: UserScope ────────────────────────────────────────────
    op.create_table(
        'user_scopes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('scope_type', sa.String(length=24), nullable=False),
        sa.Column('scope_value', sa.Integer(), nullable=True),
        sa.Column('stage_value', sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    # ── Ticket 15: GradingScale + Levels ───────────────────────────────
    op.create_table(
        'grading_scales',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=96), nullable=False),
        sa.Column('scale_type', sa.String(length=16), nullable=False, server_default='numeric'),
        sa.Column('applies_to_stage', sa.String(length=32), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'grading_scale_levels',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('scale_id', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(length=32), nullable=False),
        sa.Column('min_score', sa.Numeric(5, 2), nullable=False),
        sa.Column('max_score', sa.Numeric(5, 2), nullable=False),
        sa.Column('gpa_points', sa.Numeric(4, 2), nullable=True),
        sa.Column('is_passing', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('color', sa.String(length=16), nullable=True),
        sa.Column('order_index', sa.Integer(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['scale_id'], ['grading_scales.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    # ── Ticket 16: Rubric ──────────────────────────────────────────────
    op.create_table(
        'rubrics',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('subject_id', sa.Integer(), nullable=True),
        sa.Column('is_template', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id']),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['subject_id'], ['subjects.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'rubric_criteria',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('rubric_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=160), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('weight', sa.Numeric(5, 2), nullable=False, server_default='0'),
        sa.Column('max_score', sa.Numeric(6, 2), nullable=False, server_default='100'),
        sa.Column('order_index', sa.Integer(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['rubric_id'], ['rubrics.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'rubric_scores',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('criterion_id', sa.Integer(), nullable=False),
        sa.Column('submission_id', sa.Integer(), nullable=True),
        sa.Column('grade_entry_id', sa.Integer(), nullable=True),
        sa.Column('score', sa.Numeric(6, 2), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('graded_by_id', sa.Integer(), nullable=True),
        sa.Column('graded_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['criterion_id'], ['rubric_criteria.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['submission_id'], ['lms_submissions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['grade_entry_id'], ['grade_entries.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['graded_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    # ── Ticket 17: Discounts ───────────────────────────────────────────
    op.create_table(
        'discount_types',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('calc_method', sa.String(length=16), nullable=False, server_default='percentage'),
        sa.Column('value', sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('applies_to_fee_type_id', sa.Integer(), nullable=True),
        sa.Column('auto_rule', sa.String(length=32), nullable=True),
        sa.Column('requires_approval', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id']),
        sa.ForeignKeyConstraint(['applies_to_fee_type_id'], ['fee_types.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'student_discounts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('enrollment_id', sa.Integer(), nullable=False),
        sa.Column('discount_type_id', sa.Integer(), nullable=False),
        sa.Column('override_value', sa.Numeric(12, 2), nullable=True),
        sa.Column('reason', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='pending'),
        sa.Column('approved_by_user_id', sa.Integer(), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id']),
        sa.ForeignKeyConstraint(['enrollment_id'], ['enrollments.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['discount_type_id'], ['discount_types.id']),
        sa.ForeignKeyConstraint(['approved_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    # ── Ticket 18: TranscriptSnapshot ──────────────────────────────────
    op.create_table(
        'transcript_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('student_id', sa.Integer(), nullable=False),
        sa.Column('issued_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('issued_by_user_id', sa.Integer(), nullable=True),
        sa.Column('content', sa.JSON(), nullable=False),
        sa.Column('serial_number', sa.String(length=48), nullable=False),
        sa.Column('purpose', sa.String(length=128), nullable=True),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id']),
        sa.ForeignKeyConstraint(['student_id'], ['students.id']),
        sa.ForeignKeyConstraint(['issued_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('serial_number', name='uq_transcript_serial'),
    )

    # ── Ticket 19: Question versioning ─────────────────────────────────
    for table in ('lms_questions', 'lms_assignment_questions'):
        with op.batch_alter_table(table, schema=None) as b:
            b.add_column(sa.Column('version', sa.Integer(), nullable=False, server_default='1'))
            b.add_column(sa.Column('is_locked', sa.Boolean(), nullable=False, server_default=sa.false()))
            b.add_column(sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True))

    # ── Ticket 3: source_type/source_id on AssessmentComponent ─────────
    with op.batch_alter_table('assessment_components', schema=None) as b:
        b.add_column(sa.Column('source_type', sa.String(length=20),
                               nullable=False, server_default='manual'))
        b.add_column(sa.Column('source_id', sa.Integer(), nullable=True))
        b.add_column(sa.Column('auto_sync', sa.Boolean(), nullable=False, server_default=sa.false()))

    # ── Ticket 5: ImportBatch tracking ─────────────────────────────────
    op.create_table(
        'import_batches',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('entity_type', sa.String(length=32), nullable=False),
        sa.Column('file_name', sa.String(length=255), nullable=True),
        sa.Column('total_rows', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('success_rows', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('failed_rows', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error_log', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    # Reverse order. Kept terse — new tables just drop; column adds
    # walked back via batch.
    op.drop_table('import_batches')
    with op.batch_alter_table('assessment_components', schema=None) as b:
        b.drop_column('auto_sync'); b.drop_column('source_id'); b.drop_column('source_type')
    for table in ('lms_assignment_questions', 'lms_questions'):
        with op.batch_alter_table(table, schema=None) as b:
            b.drop_column('locked_at'); b.drop_column('is_locked'); b.drop_column('version')
    op.drop_table('transcript_snapshots')
    op.drop_table('student_discounts')
    op.drop_table('discount_types')
    op.drop_table('rubric_scores'); op.drop_table('rubric_criteria'); op.drop_table('rubrics')
    op.drop_table('grading_scale_levels'); op.drop_table('grading_scales')
    op.drop_table('user_scopes')
    op.drop_table('notification_preferences')
    op.drop_table('messages'); op.drop_table('conversation_participants'); op.drop_table('conversations')
    op.drop_table('behavior_actions'); op.drop_table('behavior_incidents'); op.drop_table('behavior_categories')
    op.drop_table('student_documents')
    op.drop_table('health_incidents'); op.drop_table('student_health_profiles')
    op.drop_table('substitutions'); op.drop_table('staff_attendance')
    with op.batch_alter_table('schools', schema=None) as b:
        b.drop_column('attendance_mode')
    with op.batch_alter_table('attendance', schema=None) as b:
        b.drop_constraint('uq_attendance_enrollment_date_period', type_='unique')
        b.create_unique_constraint('uq_attendance_enrollment_date', ['enrollment_id', 'date'])
        for c in ('excuse_document', 'excuse_reason', 'period_id', 'subject_id', 'schedule_slot_id'):
            b.drop_column(c)
    with op.batch_alter_table('schedule_slots', schema=None) as b:
        b.drop_column('room_id')
    with op.batch_alter_table('periods', schema=None) as b:
        b.drop_column('duration_minutes'); b.drop_column('stage'); b.drop_column('academic_year_id')
    with op.batch_alter_table('days', schema=None) as b:
        b.drop_column('stage'); b.drop_column('academic_year_id')
    op.drop_table('rooms')
    op.drop_table('audit_logs')
    op.drop_table('calendar_days')
    op.drop_table('student_guardians')
    op.drop_table('guardians')
