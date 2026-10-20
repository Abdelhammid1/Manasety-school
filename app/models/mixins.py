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

from sqlalchemy.orm import declared_attr

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


# ─── SAAS-019..021 — school_id on child tables ──────────────────────

def _school_of_parent(parents):
    """Column default: the school_id of the parent row this row points
    at. Works for ORM rows AND association rows SQLAlchemy inserts on
    its own (`secondary=` relationships), which no app code can set a
    value on. Falls back to the current tenant; with neither, it raises
    TenantNotResolved rather than writing NULL or a guess."""
    from sqlalchemy import text

    def default(ctx):
        params = ctx.get_current_parameters()
        for parent_table, fk_column in parents:
            parent_id = params.get(fk_column)
            if parent_id is None:
                continue
            sid = ctx.connection.execute(
                text(f"SELECT school_id FROM {parent_table} WHERE id = :pid"),
                {"pid": parent_id},
            ).scalar()
            if sid is not None:
                return sid
        from ..services.tenancy import current_school_id
        return current_school_id()
    return default


def inherited_school_id(parent_table: str, fk_column: str, *more: tuple[str, str]):
    """`school_id` column for a child table whose tenant is its parent's.
    `more` lists further (table, fk) parents tried in order when the
    first FK is NULL (e.g. rubric_scores: submission OR grade entry)."""
    return db.Column(
        "school_id", db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True,
        default=_school_of_parent(((parent_table, fk_column),) + tuple(more)),
        # read by services.tenant_guard to predict the default's value
        info={"tenant_parents": ((parent_table, fk_column),) + tuple(more)},
    )


# ─── SAAS-022 — root tables ──────────────────────────────────────────

def _current_tenant_school():
    from ..services.tenancy import current_school_id
    return current_school_id()


class TenantOwnedMixin:
    """`school_id NOT NULL` filled from the current tenant (request host,
    user, or tenant_context()). Outside any tenant it raises
    TenantNotResolved instead of writing NULL or a default school.
    For new school-owned root tables; child tables use
    inherited_school_id() so they always match their parent."""

    @declared_attr
    def school_id(cls):
        return db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False,
                         index=True, default=_current_tenant_school)
