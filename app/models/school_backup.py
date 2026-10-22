"""SAAS-047 — a school's own backups. One row per requested backup; the
row is also the queue entry the server CLI picks up
(`flask school-backup --from-queue`): the web process never builds a
package itself. The package lives in instance/school_backups/<school_id>/.
"""
from datetime import datetime, timezone

from ..extensions import db

BACKUP_STATUSES = ("pending", "running", "succeeded", "failed")


def _utcnow():
    return datetime.now(timezone.utc)


class SchoolBackup(db.Model):
    __tablename__ = "school_backups"
    __table_args__ = (
        db.CheckConstraint("status IN ('pending','running','succeeded','failed')",
                           name="ck_school_backups_status"),
    )

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    status = db.Column(db.String(16), nullable=False, default="pending", index=True)
    progress = db.Column(db.Integer, nullable=False, default=0)
    file_name = db.Column(db.String(255))
    size_bytes = db.Column(db.BigInteger)
    error = db.Column(db.String(255))
    requested_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)
    started_at = db.Column(db.DateTime(timezone=True))
    finished_at = db.Column(db.DateTime(timezone=True))

    requested_by = db.relationship("User", foreign_keys=[requested_by_user_id])
