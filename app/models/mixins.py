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
    #: List of relationship attribute names whose target rows should
    #: get soft-deleted (or restored) alongside the parent. Only
    #: relationships whose target class ALSO uses SoftDeleteMixin are
    #: honoured. Override on any subclass, e.g.:
    #:     class Course(SoftDeleteMixin, db.Model):
    #:         __soft_delete_cascades__ = ("lessons", "units", "quizzes")
    __soft_delete_cascades__: tuple[str, ...] = ()

    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    deleted_by_id = db.Column(db.Integer, db.ForeignKey("users.id"),
                              nullable=True)

    def soft_delete(self, user_id=None, *, _batch_ts=None):
        """Soft-delete this row + walk any declared cascades.

        All rows in a single cascade share the *same* `deleted_at`
        timestamp — that's how `restore()` figures out which children
        came down with the parent (equality on the batch) vs children
        that were deleted separately earlier."""
        ts = _batch_ts or datetime.now(timezone.utc)
        self.deleted_at = ts
        self.deleted_by_id = user_id
        for attr in self.__soft_delete_cascades__:
            children = getattr(self, attr, None)
            if children is None:
                continue
            it = children if isinstance(children, (list, tuple, set)) \
                          else [children]
            for child in it:
                if isinstance(child, SoftDeleteMixin) and not child.is_deleted:
                    child.soft_delete(user_id, _batch_ts=ts)

    def restore(self):
        """Un-delete this row + walk cascades. Only restores children
        whose `deleted_at` equals ours (i.e. brought down in the same
        cascade). Children deleted independently stay deleted.

        Uses the `include_deleted` escape hatch when fetching children
        — the relationships would otherwise be filtered by the global
        soft-delete filter and return an empty list."""
        from sqlalchemy import inspect as sa_inspect, select
        target = self.deleted_at
        self.deleted_at = None
        self.deleted_by_id = None
        if target is None:
            return
        insp = sa_inspect(self.__class__)
        # Normalise target once.
        t_ts = target
        if t_ts.tzinfo is not None:
            t_ts = t_ts.astimezone(timezone.utc).replace(tzinfo=None)

        for attr in self.__soft_delete_cascades__:
            rel = insp.relationships.get(attr)
            if rel is None:
                continue
            child_cls = rel.mapper.class_
            if not issubclass(child_cls, SoftDeleteMixin):
                continue
            # Resolve the FK column pointing back at us.
            local_col, remote_col = next(iter(rel.local_remote_pairs))
            local_val = getattr(self, local_col.name)
            stmt = (
                select(child_cls)
                .execution_options(include_deleted=True)
                .filter(remote_col == local_val)
                .filter(child_cls.deleted_at.isnot(None))
            )
            for child in db.session.execute(stmt).scalars().all():
                c_ts = child.deleted_at
                if c_ts is None:
                    continue
                if c_ts.tzinfo is not None:
                    c_ts = c_ts.astimezone(timezone.utc).replace(tzinfo=None)
                if abs((c_ts - t_ts).total_seconds()) < 1:
                    child.restore()

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None
