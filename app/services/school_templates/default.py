"""SAAS-028 — the default starter data for a new school (data only).

Derived from the discovery crawl (tests/test_saas028_provisioning.py
::test_smoke_crawl_new_school): the rows the core screens need so a
brand-new school opens every sidebar page without a 500, plus the
defaults every school configures anyway. Roles mirror seeds/seed.py.
"""
from app.models.user import PERMISSION_ACTIONS, PERMISSION_MODULES

# (name, name_ar, is_system, permissions — "all" or [(module, actions)])
ROLES = [
    ("admin", "مدير", True, "all"),
    ("student_affairs", "شؤون طلاب", False, [
        ("students", PERMISSION_ACTIONS), ("sections", ["view"]),
        ("grades", ["view"]), ("academic_years", ["view"]),
    ]),
    ("teacher", "معلم", False, [
        ("attendance", PERMISSION_ACTIONS), ("results", ["view", "add", "edit"]),
        ("schedule", ["view"]), ("portal", PERMISSION_ACTIONS),
        ("lms", ["view", "add", "edit"]),
    ]),
    ("accountant", "محاسب", False, [
        ("finance", PERMISSION_ACTIONS),
        ("finance_transactions", PERMISSION_ACTIONS),
        ("expenses", PERMISSION_ACTIONS),
    ]),
    ("warehouse", "أمين مخزن", False, [("expenses", ["view", "add"])]),
    ("parent", "ولي أمر", False, [("portal", ["view"])]),
    ("student", "طالب", True, [("portal", ["view"])]),
]


def role_permissions(spec) -> dict:
    if spec == "all":
        return {m: list(PERMISSION_ACTIONS) for m in PERMISSION_MODULES}
    return {module: list(actions) for module, actions in spec}


# School week (Egypt / Gulf default). Editable later from the schedule screen.
DAYS = ["الأحد", "الاثنين", "الثلاثاء", "الأربعاء", "الخميس"]

# (name, (start h, m), (end h, m), is_break)
PERIODS = [
    ("الحصة 1", (8, 0), (8, 45), False),
    ("الحصة 2", (8, 45), (9, 30), False),
    ("الحصة 3", (9, 30), (10, 15), False),
    ("الفسحة", (10, 15), (10, 45), True),
    ("الحصة 4", (10, 45), (11, 30), False),
    ("الحصة 5", (11, 30), (12, 15), False),
    ("الحصة 6", (12, 15), (13, 0), False),
]

# (name, kind, account_role of the chart account it posts to)
PAYMENT_METHODS = [
    ("نقدي", "immediate_cash", "cash_default"),
]

# (name, kind, default_points, severity)
BEHAVIOR_CATEGORIES = [
    ("سلوك متميز", "positive", 5, None),
    ("مشاركة فعّالة", "positive", 2, None),
    ("تأخر عن الحصة", "negative", -1, "low"),
    ("إزعاج داخل الفصل", "negative", -2, "medium"),
    ("سلوك عدواني", "negative", -5, "high"),
]

# (name, [(label, min, max, is_passing)])
GRADING_SCALE = ("السلم الافتراضي", [
    ("ممتاز", 90, 100, True),
    ("جيد جدًا", 80, 89.99, True),
    ("جيد", 65, 79.99, True),
    ("مقبول", 50, 64.99, True),
    ("ضعيف", 0, 49.99, False),
])
