"""Shared model mixins.

`SoftDeleteMixin` — adds `deleted_at` and `deleted_by_id` on any model
that includes it. Combined with the session-level global filter in
`app/services/soft_delete.py`, every ORM query over a mixed-in model
transparently hides rows where `deleted_at IS NOT NULL`. Callers opt
back into full visibility with
`db.session.execute(select(..).execution_options(include_deleted=True))`
or `Model.query.execution_options(include_deleted=True)`.
"""

from datetime import datetime, timezone

from ..extensions import db


class SoftDeleteMixin:
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    deleted_by_id = db.Column(db.Integer, db.ForeignKey("users.id"),
                              nullable=True)

    def soft_delete(self, user_id=None):
        self.deleted_at = datetime.now(timezone.utc)
        self.deleted_by_id = user_id

    def restore(self):
        self.deleted_at = None
        self.deleted_by_id = None

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None
