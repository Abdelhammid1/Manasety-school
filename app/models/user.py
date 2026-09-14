from datetime import datetime
from flask_login import UserMixin

from ..extensions import db, bcrypt


PERMISSION_MODULES = [
    "users", "roles", "academic_years", "terms", "grades", "sections",
    "students", "teachers", "schedule", "attendance", "results",
    "finance", "expenses", "payroll", "portal",
]
PERMISSION_ACTIONS = ["view", "add", "edit", "delete"]


class Role(db.Model):
    __tablename__ = "roles"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    name = db.Column(db.String(64), nullable=False)
    name_ar = db.Column(db.String(64), nullable=False)
    is_system = db.Column(db.Boolean, default=False, nullable=False)
    permissions = db.Column(db.JSON, default=dict, nullable=False)

    __table_args__ = (db.UniqueConstraint("school_id", "name", name="uq_role_school_name"),)

    def has(self, module: str, action: str = "view") -> bool:
        perms = self.permissions or {}
        return action in (perms.get(module) or [])


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)
    username = db.Column(db.String(64), nullable=False)
    full_name = db.Column(db.String(128), nullable=False)
    email = db.Column(db.String(128))
    phone = db.Column(db.String(32))
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    failed_attempts = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime)
    last_login_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    role = db.relationship("Role", backref="users")
    school = db.relationship("School", backref="users")

    __table_args__ = (db.UniqueConstraint("school_id", "username", name="uq_user_school_username"),)

    def set_password(self, password: str) -> None:
        self.password_hash = bcrypt.generate_password_hash(password).decode("utf-8")

    def check_password(self, password: str) -> bool:
        return bcrypt.check_password_hash(self.password_hash, password)

    def is_locked(self) -> bool:
        return bool(self.locked_until and self.locked_until > datetime.utcnow())

    def can(self, module: str, action: str = "view") -> bool:
        return bool(self.role and self.role.has(module, action))
