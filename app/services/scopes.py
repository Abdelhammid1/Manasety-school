"""Ticket #14 — reusable UserScope filter.

Every route that lists sections / students / grades / attendance should
walk its query through `apply_scope()` so the user only sees the rows
their UserScope allows. When the user has no UserScope rows the helper
defaults to full-school access (matches the pre-ticket behaviour).

Usage:
    from ...services.scopes import apply_scope
    q = Section.query.filter_by(school_id=sid)
    q = apply_scope(q, current_user, section_field='id',
                    grade_field='grade_id')
    sections = q.all()

The helper is deliberately non-magical — it takes the column names to
apply the scope against so the calling route stays explicit.
"""
from flask_login import current_user as _current
from sqlalchemy import or_, and_

from ..models import UserScope, Section, Grade, Assignment as TeachingAssignment


def _user_scopes(user):
    return UserScope.query.filter_by(
        user_id=user.id, school_id=user.school_id,
    ).all() if getattr(user, "id", None) else []


def scope_summary(user):
    """Human-readable summary of the user's scope for logs / debug UIs."""
    scopes = _user_scopes(user)
    if not scopes:
        return "all_school (default)"
    types = ", ".join(sorted({s.scope_type for s in scopes}))
    return f"{types} ({len(scopes)} rows)"


def apply_scope(query, user, *, section_field=None, grade_field=None, stage_field=None):
    """Restrict a query to the user's scope.

    section_field, grade_field, stage_field name the column paths to
    filter against — pass None when the model doesn't carry that column
    and the corresponding scope rows should be skipped.

    all_school → returns the query unchanged (open access).
    stage      → grades whose Grade.stage == the scope's stage_value.
    grade      → row where <grade_field> IN (scope_values).
    section    → row where <section_field> IN (scope_values).
    own_assignments → resolved via the caller (we can't join arbitrary
                      models here); returns query unchanged and the
                      route re-filters by TeachingAssignment ids.
    """
    scopes = _user_scopes(user)
    if not scopes:
        return query

    types = {s.scope_type for s in scopes}
    if "all_school" in types:
        return query

    filters = []
    if "stage" in types and stage_field is not None:
        stages = {s.stage_value for s in scopes if s.scope_type == "stage" and s.stage_value}
        if stages:
            # Resolve stages → grade ids
            grade_ids = [g.id for g in Grade.query.filter(Grade.stage.in_(stages)).all()]
            if grade_field is not None and grade_ids:
                filters.append(grade_field.in_(grade_ids))

    if "grade" in types and grade_field is not None:
        gids = [s.scope_value for s in scopes if s.scope_type == "grade" and s.scope_value]
        if gids:
            filters.append(grade_field.in_(gids))

    if "section" in types and section_field is not None:
        sids = [s.scope_value for s in scopes if s.scope_type == "section" and s.scope_value]
        if sids:
            filters.append(section_field.in_(sids))

    if not filters:
        return query
    # Any listed filter matches — union semantics (grade OR section).
    return query.filter(or_(*filters))


def user_can_touch_section(user, section):
    """Non-query check — is this section within the user's scope?
    False on scope violation; True when scope allows or user has none."""
    scopes = _user_scopes(user)
    if not scopes:
        return True
    for s in scopes:
        if s.scope_type == "all_school":
            return True
        if s.scope_type == "section" and s.scope_value == section.id:
            return True
        if s.scope_type == "grade" and s.scope_value == section.grade_id:
            return True
        if s.scope_type == "stage" and s.stage_value and section.grade and section.grade.stage == s.stage_value:
            return True
        if s.scope_type == "own_assignments":
            teacher = getattr(user, "teacher_profile", None)
            if teacher and TeachingAssignment.query.filter_by(
                teacher_id=teacher.id, section_id=section.id, is_active=True,
            ).first():
                return True
    return False
