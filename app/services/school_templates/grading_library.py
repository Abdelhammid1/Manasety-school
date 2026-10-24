"""Ready-made grading templates a school applies from its own screens
(/results/scales, /components, /settings, /rubrics) as its OWN copy,
then edits freely. Data only — no database here; applying them is
services/grading_templates.py. New schools are still seeded by
default.py through provisioning, unchanged.

Each template has a stable `key` (a slug, used in URLs), an Arabic name
and a short description. `validate()` is the rulebook the tests run:
scale levels cover 0–100 with no gap or overlap (at 0.01 precision, as
default.py writes 89.99), every component set sums to 100, pass
thresholds sit in 1–100, every key is unique.

The content is a proposal awaiting the academic owner's sign-off.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .default import GRADING_SCALE


@dataclass(frozen=True)
class Level:
    label: str
    min_score: Decimal
    max_score: Decimal
    is_passing: bool = True
    gpa_points: Decimal | None = None
    color: str | None = None


@dataclass(frozen=True)
class ScaleTemplate:
    key: str
    name: str
    description: str
    scale_type: str                       # numeric | letter | descriptive (GradingScale.scale_type)
    levels: tuple[Level, ...]
    applies_to_stage: str | None = None


@dataclass(frozen=True)
class ComponentSet:
    key: str
    name: str
    description: str
    components: tuple[tuple[str, Decimal], ...]     # (name, max_score)


@dataclass(frozen=True)
class PassRuleTemplate:
    key: str
    name: str
    description: str
    method: str                           # overall_only | per_subject | mixed (PassRule.method)
    subject_pass_threshold: Decimal
    overall_pass_threshold: Decimal
    allowed_failed_subjects: int = 0


@dataclass(frozen=True)
class Criterion:
    title: str
    description: str
    weight: Decimal                       # relative; the grader normalises by the weights' sum
    max_score: Decimal = Decimal(4)


@dataclass(frozen=True)
class RubricTemplate:
    key: str
    title: str
    description: str
    criteria: tuple[Criterion, ...] = field(default_factory=tuple)


def _d(v) -> Decimal:
    return Decimal(str(v))


SCALES: tuple[ScaleTemplate, ...] = (
    ScaleTemplate(
        key="percent-default", name="السلم المئوي الافتراضي", scale_type="numeric",
        description="نفس السلم اللي بتبدأ بيه أي مدرسة جديدة: ممتاز / جيد جدًا / جيد / مقبول / ضعيف.",
        levels=tuple(Level(label, _d(lo), _d(hi), passing) for label, lo, hi, passing in GRADING_SCALE[1]),
    ),
    ScaleTemplate(
        key="letter-gpa", name="سلم الحروف مع المعدل التراكمي", scale_type="letter",
        description="تقديرات بالحروف (A+ … F) ولكل تقدير نقاط معدل تراكمي من 4.",
        levels=(
            Level("A+", _d(95), _d(100), True, _d("4.00")),
            Level("A", _d(90), _d("94.99"), True, _d("3.75")),
            Level("B+", _d(85), _d("89.99"), True, _d("3.50")),
            Level("B", _d(80), _d("84.99"), True, _d("3.00")),
            Level("C+", _d(75), _d("79.99"), True, _d("2.50")),
            Level("C", _d(70), _d("74.99"), True, _d("2.00")),
            Level("D+", _d(65), _d("69.99"), True, _d("1.50")),
            Level("D", _d(60), _d("64.99"), True, _d("1.00")),
            Level("F", _d(0), _d("59.99"), False, _d("0.00")),
        ),
    ),
    ScaleTemplate(
        key="descriptive-primary", name="السلم الوصفي للمراحل الأولى", scale_type="descriptive",
        description="تقديرات وصفية بدل الأرقام للصفوف الأولية: متقدم / متمكن / مكتسب / غير مكتسب.",
        applies_to_stage="primary",
        levels=(
            Level("متقدم", _d(90), _d(100)),
            Level("متمكن", _d(75), _d("89.99")),
            Level("مكتسب", _d(50), _d("74.99")),
            Level("غير مكتسب", _d(0), _d("49.99"), False),
        ),
    ),
)

COMPONENT_SETS: tuple[ComponentSet, ...] = (
    ComponentSet(
        key="year-20-final-80", name="أعمال السنة 20 / اختبار الفصل 80",
        description="التوزيع الأكثر شيوعًا: 20 درجة لأعمال السنة و80 لاختبار نهاية الفصل.",
        components=(("أعمال السنة", _d(20)), ("اختبار نهاية الفصل", _d(80))),
    ),
    ComponentSet(
        key="activity-10-quiz-20-final-70", name="نشاط 10 / اختبار قصير 20 / امتحان نهائي 70",
        description="ثلاثة مكوّنات: الأنشطة والواجبات، الاختبارات القصيرة، والامتحان النهائي.",
        components=(("نشاط وواجبات", _d(10)), ("اختبارات قصيرة", _d(20)), ("امتحان نهائي", _d(70))),
    ),
    ComponentSet(
        key="continuous-no-final", name="تقويم مستمر بدون امتحان نهائي",
        description="أعمال السنة موزعة على مشاركة وواجبات ومشروع واختبارات قصيرة، بدون امتحان نهائي.",
        components=(("مشاركة", _d(20)), ("واجبات", _d(20)), ("مشروع", _d(20)), ("اختبارات قصيرة", _d(40))),
    ),
)

PASS_RULES: tuple[PassRuleTemplate, ...] = (
    PassRuleTemplate(
        key="overall-50", name="المعدل الكلي فقط (50٪)", method="overall_only",
        description="الطالب ينجح لو معدله الكلي 50٪ أو أكثر، بغض النظر عن كل مادة.",
        subject_pass_threshold=_d(50), overall_pass_threshold=_d(50),
    ),
    PassRuleTemplate(
        key="per-subject-50", name="كل مادة على حدة (50٪)", method="per_subject",
        description="الطالب لازم يجيب 50٪ في كل مادة عشان ينجح.",
        subject_pass_threshold=_d(50), overall_pass_threshold=_d(50),
    ),
    PassRuleTemplate(
        key="mixed-50-one-fail", name="مختلطة 50/50 مع السماح برسوب مادة واحدة", method="mixed",
        description="معدل كلي 50٪ و50٪ في كل مادة، مع السماح برسوب مادة واحدة.",
        subject_pass_threshold=_d(50), overall_pass_threshold=_d(50), allowed_failed_subjects=1,
    ),
)

RUBRICS: tuple[RubricTemplate, ...] = (
    RubricTemplate(
        key="essay", title="تقييم مقال",
        description="لتقييم الكتابة: الأفكار، التنظيم، اللغة، والإملاء — كل معيار من 4.",
        criteria=(
            Criterion("المحتوى والأفكار", "وضوح الفكرة الرئيسية وقوة الأدلة والأمثلة.", _d(40)),
            Criterion("التنظيم", "مقدمة وعرض وخاتمة، وتسلسل منطقي بين الفقرات.", _d(20)),
            Criterion("اللغة والأسلوب", "سلامة التراكيب وثراء المفردات.", _d(25)),
            Criterion("الإملاء وعلامات الترقيم", "خلو النص من الأخطاء الإملائية واستخدام الترقيم.", _d(15)),
        ),
    ),
    RubricTemplate(
        key="presentation", title="تقييم عرض تقديمي",
        description="لتقييم العروض الشفهية: المحتوى، التنظيم، الإلقاء، والوسائل — كل معيار من 4.",
        criteria=(
            Criterion("المحتوى", "دقة المعلومات وصلتها بالموضوع.", _d(35)),
            Criterion("التنظيم", "تسلسل واضح وانتقال سلس بين الأجزاء.", _d(20)),
            Criterion("الإلقاء والتواصل", "وضوح الصوت والتواصل البصري والثقة.", _d(25)),
            Criterion("الوسائل والالتزام بالوقت", "جودة الشرائح والوسائل والالتزام بالزمن.", _d(20)),
        ),
    ),
    RubricTemplate(
        key="project", title="تقييم مشروع",
        description="لتقييم المشاريع: الفكرة، التنفيذ، العرض، والالتزام — كل معيار من 4.",
        criteria=(
            Criterion("الفكرة والتخطيط", "أصالة الفكرة ووضوح الخطة والأهداف.", _d(25)),
            Criterion("التنفيذ والجودة", "جودة المنتج النهائي وإتقانه.", _d(35)),
            Criterion("التوثيق والعرض", "توثيق الخطوات وعرض النتائج.", _d(20)),
            Criterion("العمل الجماعي والالتزام", "التعاون وتوزيع المهام والالتزام بالمواعيد.", _d(20)),
        ),
    ),
)

_STEP = Decimal("0.01")


def get(kind: str, key: str):
    """The template of `kind` (scale | components | pass_rule | rubric) with `key`, or None."""
    pool = {"scale": SCALES, "components": COMPONENT_SETS, "pass_rule": PASS_RULES, "rubric": RUBRICS}[kind]
    return next((t for t in pool if t.key == key), None)


def validate() -> list[str]:
    """Every rule the library must keep; [] when it does."""
    problems: list[str] = []
    keys = [t.key for t in (*SCALES, *COMPONENT_SETS, *PASS_RULES, *RUBRICS)]
    for k in {k for k in keys if keys.count(k) > 1}:
        problems.append(f"duplicate key {k}")
    for s in SCALES:
        lv = sorted(s.levels, key=lambda lvl: lvl.min_score)
        if not lv or lv[0].min_score != 0 or lv[-1].max_score != 100:
            problems.append(f"{s.key}: levels must start at 0 and end at 100")
        for a, b in zip(lv, lv[1:]):
            if b.min_score - a.max_score != _STEP:
                problems.append(f"{s.key}: gap or overlap between {a.label} and {b.label}")
        for lvl in lv:
            if lvl.min_score > lvl.max_score:
                problems.append(f"{s.key}: {lvl.label} min above max")
    for c in COMPONENT_SETS:
        if sum(m for _, m in c.components) != 100:
            problems.append(f"{c.key}: max scores sum to {sum(m for _, m in c.components)}, not 100")
        names = [n for n, _ in c.components]
        if len(set(names)) != len(names):
            problems.append(f"{c.key}: duplicate component name")
    for p in PASS_RULES:
        for th in (p.subject_pass_threshold, p.overall_pass_threshold):
            if not 1 <= th <= 100:
                problems.append(f"{p.key}: threshold {th} outside 1–100")
        if p.method not in ("overall_only", "per_subject", "mixed") or p.allowed_failed_subjects < 0:
            problems.append(f"{p.key}: bad method or allowed_failed_subjects")
    for r in RUBRICS:
        if not r.criteria or any(c.weight <= 0 or c.max_score <= 0 for c in r.criteria):
            problems.append(f"{r.key}: needs criteria with positive weight and max")
        if sum(c.weight for c in r.criteria) != 100:
            problems.append(f"{r.key}: weights sum to {sum(c.weight for c in r.criteria)}, not 100")
    return problems
