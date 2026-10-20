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
