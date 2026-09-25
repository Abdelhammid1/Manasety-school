"""Global soft-delete filter.

Registers a single `do_orm_execute` listener that appends
`deleted_at IS NULL` to every ORM query over a `SoftDeleteMixin`
subclass. Any query that legitimately needs to see deleted rows
passes `execution_options(include_deleted=True)` — the trash / restore
page is the obvious caller.

The listener is idempotent: safe to call `register(app)` many times
(defensive against Flask's dev-reloader).
"""

from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

_registered = False


def _query_predicate(cls):
    """The filter applied to every mixed-in class."""
    return cls.deleted_at.is_(None)


def register(app):
    global _registered
    if _registered:
        return
    from ..models.mixins import SoftDeleteMixin

    @event.listens_for(Session, "do_orm_execute")
    def _apply_soft_delete_filter(execute_state):
        # Escape hatch: caller opted out.
        if execute_state.execution_options.get("include_deleted"):
            return
        # Only SELECTs.
        if not execute_state.is_select:
            return
        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(
                SoftDeleteMixin,
                _query_predicate,
                include_aliases=True,
            )
        )
    _registered = True
