"""SAAS-025 — platform (Super Admin) identity. Not tenant-owned: these
tables have no school_id and sit outside every school.

(`app/models/platform.py` is unrelated: it holds per-school features
such as rooms and staff attendance.)
"""
from datetime import datetime, timezone

from flask_login import UserMixin

from ..extensions import bcrypt, db

PLATFORM_ROLES = ("owner", "support", "finance")


def _utcnow():
    return datetime.now(timezone.utc)


class PlatformUser(UserMixin, db.Model):
    __tablename__ = "platform_users"
    __table_args__ = (
        db.CheckConstraint("role IN ('owner', 'support', 'finance')",
                           name="ck_platform_users_role"),
    )

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, unique=True)
    full_name = db.Column(db.String(160), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(16), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    failed_attempts = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime(timezone=True))
    last_login_at = db.Column(db.DateTime(timezone=True))
    # NULL until the user sets their own password (CLI-created accounts
    # are forced through a change on first login).
    password_changed_at = db.Column(db.DateTime(timezone=True))
    totp_secret_encrypted = db.Column(db.Text)
    totp_enabled = db.Column(db.Boolean, nullable=False, default=False)
    # Last accepted TOTP time-step: a code can never be accepted twice.
    totp_last_counter = db.Column(db.BigInteger)
    # Bumped on logout / password change / TOTP enrolment; a session
    # carrying an older value is dead (server-side revocation).
    session_version = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)

    is_platform_user = True

    def get_id(self):
        # Prefixed so a platform id can never be read as a school user id.
        return f"p:{self.id}"

    def set_password(self, password: str) -> None:
        self.password_hash = bcrypt.generate_password_hash(password).decode("utf-8")

    def check_password(self, password: str) -> bool:
        return bcrypt.check_password_hash(self.password_hash, password)

    def is_locked(self) -> bool:
        if self.locked_until is None:
            return False
        lu = self.locked_until
        if lu.tzinfo is None:
            lu = lu.replace(tzinfo=timezone.utc)
        return lu > _utcnow()

    # School-side templates/helpers call these on current_user.
    school_id = None

    def can(self, module, action="view"):
        return False


class PlatformRecoveryCode(db.Model):
    __tablename__ = "platform_recovery_codes"

    id = db.Column(db.Integer, primary_key=True)
    platform_user_id = db.Column(db.Integer, db.ForeignKey("platform_users.id", ondelete="CASCADE"),
                                 nullable=False, index=True)
    code_hash = db.Column(db.String(128), nullable=False)
    used_at = db.Column(db.DateTime(timezone=True))


class PlatformAuditLog(db.Model):
    __tablename__ = "platform_audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    platform_user_id = db.Column(db.Integer, db.ForeignKey("platform_users.id"), index=True)
    action = db.Column(db.String(64), nullable=False, index=True)
    target_school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), index=True)
    ip = db.Column(db.String(45))
    user_agent = db.Column(db.String(255))
    meta = db.Column(db.JSON)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow, index=True)


# ─── SAAS-026 — plans and subscriptions ──────────────────────────────
# Platform tables: school_subscriptions / school_subscription_events
# carry a school_id that POINTS at a school; they don't belong to it.

BILLING_CYCLES = ("monthly", "yearly", "custom")
SUBSCRIPTION_EVENT_KINDS = ("created", "renewed", "extended", "plan_changed",
                            "trial_started", "state_changed", "reminder_sent")


class Plan(db.Model):
    __tablename__ = "plans"
    __table_args__ = (
        db.CheckConstraint("billing_cycle IN ('monthly', 'yearly', 'custom')",
                           name="ck_plans_billing_cycle"),
    )

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(64), nullable=False, unique=True)
    name_ar = db.Column(db.String(128), nullable=False)
    name_en = db.Column(db.String(128))
    max_students = db.Column(db.Integer)       # NULL = unlimited
    max_users = db.Column(db.Integer)
    max_storage_mb = db.Column(db.Integer)
    # AI tokens per calendar month (ticket E); NULL = unlimited
    max_ai_tokens_month = db.Column(db.Integer)
    modules = db.Column(db.JSON, nullable=False, default=list)
    price_amount = db.Column(db.Numeric(12, 2))
    currency = db.Column(db.String(8))
    billing_cycle = db.Column(db.String(16), nullable=False, default="monthly")
    trial_days = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)


class SchoolSubscription(db.Model):
    __tablename__ = "school_subscriptions"
    __table_args__ = (
        db.CheckConstraint("ends_on IS NULL OR ends_on >= starts_on",
                           name="ck_school_subscriptions_dates"),
        db.Index("uq_school_subscriptions_current", "school_id", unique=True,
                 postgresql_where=db.text("is_current"), sqlite_where=db.text("is_current = 1")),
    )

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    plan_id = db.Column(db.Integer, db.ForeignKey("plans.id"), nullable=False)
    starts_on = db.Column(db.Date, nullable=False)
    ends_on = db.Column(db.Date)                    # NULL = open-ended
    trial_ends_on = db.Column(db.Date)
    grace_days = db.Column(db.Integer, nullable=False, default=14)
    auto_renew = db.Column(db.Boolean, nullable=False, default=False)   # informational
    is_current = db.Column(db.Boolean, nullable=False, default=True)
    notes = db.Column(db.Text)
    created_by_platform_user_id = db.Column(db.Integer, db.ForeignKey("platform_users.id"))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)

    plan = db.relationship("Plan")


class SchoolSubscriptionEvent(db.Model):
    __tablename__ = "school_subscription_events"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    kind = db.Column(db.String(32), nullable=False, index=True)
    from_value = db.Column(db.String(255))
    to_value = db.Column(db.String(255))
    reason = db.Column(db.Text)
    platform_user_id = db.Column(db.Integer, db.ForeignKey("platform_users.id"))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow, index=True)


JOB_KINDS = ("nginx_sync", "school_export")
JOB_STATUSES = ("pending", "running", "succeeded", "failed")


class PlatformJob(db.Model):
    """SAAS-029 — work the web process queues and a server-side CLI runs
    (the web process never touches docker / nginx). `log` is truncated
    and redacted; `result` holds the structured outcome."""
    __tablename__ = "platform_jobs"

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(32), nullable=False, index=True)
    status = db.Column(db.String(16), nullable=False, default="pending", index=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"))
    reason = db.Column(db.String(255))
    requested_by_platform_user_id = db.Column(db.Integer, db.ForeignKey("platform_users.id"))
    requested_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)
    started_at = db.Column(db.DateTime(timezone=True))
    finished_at = db.Column(db.DateTime(timezone=True))
    log = db.Column(db.Text)
    result = db.Column(db.JSON)

    __table_args__ = (
        db.CheckConstraint("status IN ('pending','running','succeeded','failed')",
                           name="ck_platform_jobs_status"),
    )


class SchoolModuleOverride(db.Model):
    """SAAS-030 — a per-school exception to the plan's modules. Managed
    from the console only; the school never sees it."""
    __tablename__ = "school_module_overrides"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    module_key = db.Column(db.String(32), nullable=False)
    enabled = db.Column(db.Boolean, nullable=False)
    reason = db.Column(db.Text, nullable=False, default="")
    updated_by_platform_user_id = db.Column(db.Integer, db.ForeignKey("platform_users.id"))
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    __table_args__ = (db.UniqueConstraint("school_id", "module_key", name="uq_school_module_override"),)


class SchoolFeatureOverride(db.Model):
    """A per-school exception for one page / ability inside a module
    (services/modules.py FEATURES), e.g. "finance.budgets" off. Same shape
    as SchoolModuleOverride; console only. A row that would repeat the
    feature's default is never stored. Plan changes leave these alone."""
    __tablename__ = "school_feature_overrides"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    feature_key = db.Column(db.String(64), nullable=False)
    enabled = db.Column(db.Boolean, nullable=False)
    reason = db.Column(db.Text, nullable=False)
    updated_by_platform_user_id = db.Column(db.Integer, db.ForeignKey("platform_users.id"))
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    __table_args__ = (db.UniqueConstraint("school_id", "feature_key", name="uq_school_feature_override"),)


class SchoolLimitOverride(db.Model):
    """SAAS-030 — per-school limits that win over the plan's. NULL = use the plan."""
    __tablename__ = "school_limit_overrides"

    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), primary_key=True)
    max_students = db.Column(db.Integer)
    max_users = db.Column(db.Integer)
    max_storage_mb = db.Column(db.Integer)
    max_ai_tokens_month = db.Column(db.Integer)      # ticket E; NULL = the plan's
    reason = db.Column(db.Text, nullable=False, default="")
    updated_by_platform_user_id = db.Column(db.Integer, db.ForeignKey("platform_users.id"))
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


SUPPORT_MODES = ("read_only", "write")


class SupportSession(db.Model):
    """SAAS-031 — one time-boxed visit of platform support to a school."""
    __tablename__ = "support_sessions"

    id = db.Column(db.Integer, primary_key=True)
    platform_user_id = db.Column(db.Integer, db.ForeignKey("platform_users.id"), nullable=False, index=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    mode = db.Column(db.String(16), nullable=False, default="read_only")
    reason = db.Column(db.Text, nullable=False)
    started_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    last_seen_at = db.Column(db.DateTime(timezone=True))
    ended_at = db.Column(db.DateTime(timezone=True))
    end_reason = db.Column(db.String(32))
    ip = db.Column(db.String(45))
    user_agent = db.Column(db.String(255))
    nonce_hash = db.Column(db.String(64))
    nonce_used_at = db.Column(db.DateTime(timezone=True))

    platform_user = db.relationship("PlatformUser")

    __table_args__ = (
        db.CheckConstraint("mode IN ('read_only','write')", name="ck_support_sessions_mode"),
    )


class SupportSessionEvent(db.Model):
    """SAAS-031 — every request inside a support session. Never the body
    or field values: method, endpoint, path (no query string), status,
    ip, and for writes the submitted field names only."""
    __tablename__ = "support_session_events"

    id = db.Column(db.Integer, primary_key=True)
    support_session_id = db.Column(db.Integer, db.ForeignKey("support_sessions.id"), nullable=False)
    ts = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)
    method = db.Column(db.String(8), nullable=False)
    endpoint = db.Column(db.String(128))
    path = db.Column(db.String(512), nullable=False)
    status = db.Column(db.Integer)
    ip = db.Column(db.String(45))
    field_names = db.Column(db.JSON)

    __table_args__ = (db.Index("ix_support_session_events_session_ts", "support_session_id", "ts"),)


class SchoolSlugHistory(db.Model):
    """SAAS-032 — every slug a school ever had. An old slug is never given
    to anyone again; inside redirect_until it 301s to the new host."""
    __tablename__ = "school_slug_history"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    old_slug = db.Column(db.String(63), nullable=False, unique=True)
    changed_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)
    changed_by_platform_user_id = db.Column(db.Integer, db.ForeignKey("platform_users.id"))
    redirect_until = db.Column(db.DateTime(timezone=True), nullable=False)


class PlatformSchoolNote(db.Model):
    """SAAS-032 — the platform's own notes about a school (never shown to it)."""
    __tablename__ = "platform_school_notes"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    author_platform_user_id = db.Column(db.Integer, db.ForeignKey("platform_users.id"))
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)

    author = db.relationship("PlatformUser")


class SchoolContact(db.Model):
    """SAAS-032 — people at the school the platform talks to. The billing
    contact receives SAAS-033 notices."""
    __tablename__ = "school_contacts"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    name = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(64))
    phone = db.Column(db.String(32))
    email = db.Column(db.String(128))
    is_billing_contact = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)


class SchoolTag(db.Model):
    """SAAS-032 — free platform-side labels ("تجريبي", "VIP", …)."""
    __tablename__ = "school_tags"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    tag = db.Column(db.String(40), nullable=False)

    __table_args__ = (db.UniqueConstraint("school_id", "tag", name="uq_school_tag"),)


class PlatformAnnouncement(db.Model):
    """SAAS-032 — a banner for school admins (all schools, or a list)."""
    __tablename__ = "platform_announcements"

    id = db.Column(db.Integer, primary_key=True)
    message_ar = db.Column(db.Text, nullable=False)
    severity = db.Column(db.String(16), nullable=False, default="info")
    target_school_ids = db.Column(db.JSON)          # NULL = every school
    starts_at = db.Column(db.DateTime(timezone=True), nullable=False)
    ends_at = db.Column(db.DateTime(timezone=True), nullable=False)
    created_by_platform_user_id = db.Column(db.Integer, db.ForeignKey("platform_users.id"))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        db.CheckConstraint("severity IN ('info','warning')", name="ck_platform_announcements_severity"),
    )


class PlatformUsageSnapshot(db.Model):
    """SAAS-034 — one row per (school, day). Numbers only."""
    __tablename__ = "platform_usage_snapshots"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    day = db.Column(db.Date, nullable=False, index=True)
    students_active = db.Column(db.Integer, nullable=False, default=0)
    staff_users = db.Column(db.Integer, nullable=False, default=0)
    storage_bytes = db.Column(db.BigInteger, nullable=False, default=0)
    last_activity_at = db.Column(db.DateTime)
    active_users_7d = db.Column(db.Integer, nullable=False, default=0)
    subscription_state = db.Column(db.String(24))

    __table_args__ = (db.UniqueConstraint("school_id", "day", name="uq_usage_snapshot_school_day"),)


class PlatformAlert(db.Model):
    """SAAS-034 — an open condition (one row while it lasts)."""
    __tablename__ = "platform_alerts"

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(48), nullable=False, index=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"))
    severity = db.Column(db.String(8), nullable=False, default="warn")
    message_ar = db.Column(db.Text, nullable=False)
    first_seen_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)
    last_seen_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)
    resolved_at = db.Column(db.DateTime(timezone=True))
    acknowledged_by = db.Column(db.Integer, db.ForeignKey("platform_users.id"))


class SchoolOffboarding(db.Model):
    """SAAS-035 — a school leaving the platform, step by step."""
    __tablename__ = "school_offboarding"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, unique=True)
    requested_by = db.Column(db.Integer, db.ForeignKey("platform_users.id"))
    requested_at = db.Column(db.DateTime(timezone=True))
    reason = db.Column(db.Text, nullable=False)
    export_job_id = db.Column(db.Integer, db.ForeignKey("platform_jobs.id"))
    export_file = db.Column(db.String(255))
    export_verified_at = db.Column(db.DateTime(timezone=True))
    archived_at = db.Column(db.DateTime(timezone=True))
    retention_until = db.Column(db.DateTime(timezone=True))
    purge_requested_by = db.Column(db.Integer, db.ForeignKey("platform_users.id"))
    purge_requested_at = db.Column(db.DateTime(timezone=True))
    purge_approved_by = db.Column(db.Integer, db.ForeignKey("platform_users.id"))
    purge_approved_at = db.Column(db.DateTime(timezone=True))
    approvals_required = db.Column(db.Integer)      # fixed when the purge is requested
    purged_at = db.Column(db.DateTime(timezone=True))


class PlatformSession(db.Model):
    """SAAS-036 — one console login. The cookie only carries this id."""
    __tablename__ = "platform_sessions"

    id = db.Column(db.String(32), primary_key=True)
    platform_user_id = db.Column(db.Integer, db.ForeignKey("platform_users.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)
    last_seen_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)
    ip = db.Column(db.String(45))
    user_agent = db.Column(db.String(255))
    revoked_at = db.Column(db.DateTime(timezone=True))


class PlatformSetupToken(db.Model):
    """SAAS-036 — one-time console set-password link (invite / reset)."""
    __tablename__ = "platform_setup_tokens"

    id = db.Column(db.Integer, primary_key=True)
    platform_user_id = db.Column(db.Integer, db.ForeignKey("platform_users.id"), nullable=False, index=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    purpose = db.Column(db.String(16), nullable=False, default="invite")
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    used_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)

    user = db.relationship("PlatformUser")


# SAAS-036 — SQLite only: a row here lets the audit retention delete get
# past the immutability trigger (Postgres uses a SET LOCAL setting).
audit_prune_guard = db.Table("audit_prune_guard", db.Column("id", db.Integer, primary_key=True))


class PlatformSetting(db.Model):
    __tablename__ = "platform_settings"

    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.Text)
    updated_by = db.Column(db.Integer, db.ForeignKey("platform_users.id"))
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
