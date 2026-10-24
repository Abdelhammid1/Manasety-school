"""Apply a ready-made grading template (school_templates/grading_library)
as the current school's own copy. Every row is written with the school
from the session (current_school_id); ids that come from a form go
through owned_id first. Nothing existing is changed or removed.
Pass rules are not here: their template only fills the settings form,
which saves through its usual POST.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..extensions import db
from ..models import AssessmentComponent, GradingScale, GradingScaleLevel, Rubric, RubricCriterion
from .school_templates.grading_library import ComponentSet, get as get_template
from .tenancy import current_school_id


class TemplateError(Exception):
    """A refusal with its Arabic message; nothing was written."""


def apply_scale(key: str, make_default: bool) -> GradingScale:
    t = get_template("scale", key)
    if t is None:
        raise TemplateError("النموذج غير موجود.")
    sid = current_school_id()
    if GradingScale.query.filter_by(school_id=sid, name=t.name).first():
        raise TemplateError(f"يوجد سلم بنفس الاسم «{t.name}» في المدرسة — غيّر اسمه أولًا أو استخدمه كما هو.")
    if make_default:
        GradingScale.query.filter_by(school_id=sid, is_default=True).update({"is_default": False})
    scale = GradingScale(school_id=sid, name=t.name, scale_type=t.scale_type,
                         applies_to_stage=t.applies_to_stage, is_default=make_default)
    db.session.add(scale)
    db.session.flush()
    for i, lvl in enumerate(sorted(t.levels, key=lambda lv: lv.min_score, reverse=True)):
        db.session.add(GradingScaleLevel(
            scale_id=scale.id, label=lvl.label, min_score=lvl.min_score, max_score=lvl.max_score,
            gpa_points=lvl.gpa_points, is_passing=lvl.is_passing, color=lvl.color, order_index=i))
    db.session.commit()
    return scale


def apply_rubric(key: str, user_id) -> Rubric:
    t = get_template("rubric", key)
    if t is None:
        raise TemplateError("النموذج غير موجود.")
    sid = current_school_id()
    if Rubric.query.filter_by(school_id=sid, title=t.title).first():
        raise TemplateError(f"يوجد روبريك بنفس العنوان «{t.title}» في المدرسة.")
    r = Rubric(school_id=sid, created_by_id=user_id, title=t.title, description=t.description,
               subject_id=None, is_template=True)
    db.session.add(r)
    db.session.flush()
    for i, c in enumerate(t.criteria):
        db.session.add(RubricCriterion(rubric_id=r.id, title=c.title, description=c.description,
                                       weight=c.weight, max_score=c.max_score, order_index=i))
    db.session.commit()
    return r


@dataclass
class ComponentPlan:
    template: ComponentSet
    grade_id: int | None
    create: list[tuple] = field(default_factory=list)     # (term, subject)
    skip: list[tuple] = field(default_factory=list)       # (term, subject, reason)

    @property
    def count(self) -> int:
        return len(self.create) * len(self.template.components)


def plan_components(key: str, terms: list, subjects: list, grade_id: int | None) -> ComponentPlan:
    """What applying would do. `terms` / `subjects` are this school's rows
    already (the route resolves them). A (term, subject, grade scope)
    that has ANY component is skipped whole — otherwise its total could
    stop being 100. Checked with an explicit query: the unique
    constraint lets NULL grade_id rows repeat."""
    t = get_template("components", key)
    if t is None:
        raise TemplateError("النموذج غير موجود.")
    if not terms or not subjects:
        raise TemplateError("اختار فصلًا ومادة واحدة على الأقل.")
    sid = current_school_id()
    plan = ComponentPlan(template=t, grade_id=grade_id)
    for term in terms:
        for subject in subjects:
            q = AssessmentComponent.query.filter_by(school_id=sid, term_id=term.id, subject_id=subject.id)
            q = q.filter(AssessmentComponent.grade_id.is_(None) if grade_id is None
                         else AssessmentComponent.grade_id == grade_id)
            n = q.count()
            if n:
                plan.skip.append((term, subject, f"فيها {n} مكوّن بالفعل"))
            else:
                plan.create.append((term, subject))
    return plan


def apply_components(plan: ComponentPlan) -> int:
    """Write the plan in one transaction: any failure rolls it all back."""
    sid = current_school_id()
    try:
        for term, subject in plan.create:
            for name, max_score in plan.template.components:
                db.session.add(AssessmentComponent(
                    school_id=sid, term_id=term.id, subject_id=subject.id, grade_id=plan.grade_id,
                    name=name, max_score=max_score, source_type="manual", source_id=None,
                    auto_sync=False, rubric_id=None))
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return plan.count
