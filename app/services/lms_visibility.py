"""Which courses a student sees: the one rule, for the web, the mobile API
and file downloads. A course reaches a student when it is published AND
published (CourseSection.is_published) to a section they are enrolled in.
A draft course linked to a section stays hidden (BUG-007)."""

from __future__ import annotations

from ..extensions import db
from ..models import Course, CourseSection


def visible_course_ids(section_ids) -> set[int]:
    """The published courses published to any of `section_ids`."""
    section_ids = {s for s in (section_ids or ()) if s is not None}
    if not section_ids:
        return set()
    rows = (db.session.query(CourseSection.course_id)
            .join(Course, Course.id == CourseSection.course_id)
            .filter(CourseSection.section_id.in_(section_ids),
                    CourseSection.is_published.is_(True),
                    Course.is_published.is_(True)))
    return {cid for (cid,) in rows}


def course_visible(course_id: int, section_ids) -> bool:
    """The same rule for one course (one EXISTS, not the whole set)."""
    section_ids = {s for s in (section_ids or ()) if s is not None}
    if not section_ids:
        return False
    return db.session.query(
        db.session.query(CourseSection.id)
        .join(Course, Course.id == CourseSection.course_id)
        .filter(CourseSection.course_id == course_id,
                CourseSection.section_id.in_(section_ids),
                CourseSection.is_published.is_(True),
                Course.is_published.is_(True))
        .exists()).scalar()
