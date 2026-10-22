"""SAAS-047 — a school's own backups. One row per requested backup; the
row is also the queue entry the server CLI picks up
(`flask school-backup --from-queue`): the web process never builds a
package itself. The package lives in instance/school_backups/<school_id>/.
"""
from datetime import datetime, timezone

from ..extensions import db

BACKUP_STATUSES = ("pending", "running", "succeeded", "failed")
BACKUP_KINDS = ("manual", "restore_point")
RESTORE_STATUSES = ("pending_preview", "previewing", "previewed", "confirmed", "running",
                    "succeeded", "failed")
RESTORE_MODES = ("replace", "add_missing")


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
    # SAAS-048 — "restore_point": the automatic copy taken before a restore
    # (never pruned by retention; the restore's undo uses it).
    kind = db.Column(db.String(16), nullable=False, default="manual")
    progress = db.Column(db.Integer, nullable=False, default=0)
    file_name = db.Column(db.String(255))
    size_bytes = db.Column(db.BigInteger)
    error = db.Column(db.String(255))
    requested_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)
    started_at = db.Column(db.DateTime(timezone=True))
    finished_at = db.Column(db.DateTime(timezone=True))

    requested_by = db.relationship("User", foreign_keys=[requested_by_user_id])


class SchoolRestore(db.Model):
    """SAAS-048 — one restore of a school from a package: preview first
    (the server CLI computes it), then an explicit confirmation, then the
    run (restore point -> one transaction -> checks -> commit or rollback).
    `package_file` is the decrypted package in the school's private
    restore folder (the passphrase is used once and never stored)."""
    __tablename__ = "school_restores"
    __table_args__ = (
        db.CheckConstraint(
            "status IN ('pending_preview','previewing','previewed','confirmed','running',"
            "'succeeded','failed')", name="ck_school_restores_status"),
        db.CheckConstraint("mode IN ('replace','add_missing')", name="ck_school_restores_mode"),
    )

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    status = db.Column(db.String(16), nullable=False, default="pending_preview", index=True)
    mode = db.Column(db.String(16), nullable=False, default="replace")
    modules = db.Column(db.JSON)
    source_backup_id = db.Column(db.Integer, db.ForeignKey("school_backups.id", ondelete="SET NULL"))
    package_file = db.Column(db.String(255))
    preview = db.Column(db.JSON)
    result = db.Column(db.JSON)
    error = db.Column(db.String(255))
    restore_point_backup_id = db.Column(db.Integer, db.ForeignKey("school_backups.id", ondelete="SET NULL"))
    undo_of_id = db.Column(db.Integer, db.ForeignKey("school_restores.id", ondelete="SET NULL"))
    requested_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    platform_user_id = db.Column(db.Integer, db.ForeignKey("platform_users.id", ondelete="SET NULL"))
    reason = db.Column(db.String(255))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)
    started_at = db.Column(db.DateTime(timezone=True))
    finished_at = db.Column(db.DateTime(timezone=True))

    requested_by = db.relationship("User", foreign_keys=[requested_by_user_id])
