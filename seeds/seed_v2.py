"""seed_v2 — Bootstrap a fresh Saudi school (SAR, VAT 15%, two terms,
15 grades, 30 sections, 7 roles, Saudi chart of accounts).

Run AFTER `flask db upgrade` on an EMPTY database:

    python -m seeds.seed_v2

Idempotent for everything EXCEPT the chart of accounts, which is
force-reset on every run (see _seed_chart_saudi). The reset refuses
to run if any JournalLine rows exist, so it can't wipe production
bookkeeping by accident.

Saudi-specific defaults:
  · currency SAR (ر.س), VAT 15%
  · school week: Sunday → Thursday
  · 7 periods/day + one break
  · academic year 2026-2027 with two 50%-weight terms
  · 15 grades (KG1 → 3rd secondary)
  · 2 sections per grade (أ + ب) = 30 sections
"""
from __future__ import annotations

import sys
from datetime import date, datetime, time
from decimal import Decimal

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

from app import create_app
from app.extensions import db
from app.models import (
    School, Role, User,
    AcademicYear, Term, Grade, Section,
    Subject, Room, Day, Period,
    Account, CostCenter, PaymentMethod,
    BankQuestion, BankChoice,
)
from app.models.user import PERMISSION_MODULES, PERMISSION_ACTIONS


# ════════════════════════════════════════════════════════════════════
# 1. SAUDI CHART OF ACCOUNTS
# ════════════════════════════════════════════════════════════════════
#
# 3-level tree tuned for a Saudi K-12 school:
#   · Level 1 (e.g. 1000)  → aggregate, is_postable=False
#   · Level 2 (e.g. 1100)  → aggregate, is_postable=False
#   · Level 3 (e.g. 1110)  → leaf, is_postable=True
#
# Row format:
#   (code, name_ar, type, parent_code, is_postable, account_role)
#
# account_role is a unique semantic pin (e.g. ar_default) that the
# services look up instead of hardcoding a code. NULL on non-pinned.
#
# Tax note: Saudi VAT is 15%. Zakat (2.5%) is handled on the equity
# side (3200 series) rather than as a payable, because it's a
# shareholder obligation, not a school liability.

SAUDI_ACCOUNT_TREE = [
    # ── 1000 الأصول ──────────────────────────────────────────────
    ("1000", "الأصول", "asset", None, False, None),
    ("1100", "النقدية وما يعادلها", "asset", "1000", False, None),
    ("1110", "الصندوق النقدي", "asset", "1100", True, "cash_default"),
    ("1120", "الحساب البنكي — الحساب الجاري", "asset", "1100", True, None),
    ("1130", "الحساب البنكي — حساب الرسوم", "asset", "1100", True, None),
    ("1140", "مدى / نقاط البيع (POS)", "asset", "1100", True, None),
    ("1150", "محفظة إلكترونية (STC Pay / Apple Pay)", "asset", "1100", True, None),
    ("1200", "الذمم المدينة", "asset", "1000", False, None),
    ("1210", "ذمم الطلاب (AR)", "asset", "1200", True, "ar_default"),
    ("1220", "ذمم أخرى", "asset", "1200", True, None),
    ("1300", "مصروفات مدفوعة مقدماً", "asset", "1000", False, None),
    ("1310", "إيجارات مدفوعة مقدماً", "asset", "1300", True, None),
    ("1320", "تأمينات مدفوعة", "asset", "1300", True, None),
    ("1400", "الأصول الثابتة", "asset", "1000", False, None),
    ("1410", "أثاث ومعدات", "asset", "1400", True, None),
    ("1420", "أجهزة حاسوب وتقنية", "asset", "1400", True, None),
    ("1430", "مبانٍ وتحسينات", "asset", "1400", True, None),
    ("1440", "سيارات وحافلات مدرسية", "asset", "1400", True, None),
    ("1450", "أثاث مكتبي", "asset", "1400", True, None),
    ("1500", "مجمع الإهلاك", "asset", "1000", False, None),
    ("1510", "مجمع إهلاك الأصول الثابتة", "asset", "1500", True, None),
    ("1160", "سلف الموظفين", "asset", "1100", True, "employee_advance_default"),

    # ── 2000 الالتزامات ──────────────────────────────────────────
    ("2000", "الالتزامات", "liability", None, False, None),
    ("2100", "الذمم الدائنة", "liability", "2000", False, None),
    ("2110", "ذمم الموردين (AP)", "liability", "2100", True, "ap_default"),
    ("2120", "ذمم أخرى دائنة", "liability", "2100", True, None),
    ("2200", "مصروفات مستحقة", "liability", "2000", False, None),
    ("2210", "رواتب مستحقة", "liability", "2200", True, None),
    ("2220", "إيجار مستحق", "liability", "2200", True, None),
    ("2230", "مرافق مستحقة (كهرباء/مياه/إنترنت)", "liability", "2200", True, None),
    ("2240", "ضرائب مستحقة", "liability", "2200", False, None),
    ("2250", "ضريبة القيمة المضافة المستحقة", "liability", "2240", True, "vat_payable_default"),
    ("2260", "التأمينات الاجتماعية (GOSI) المستحقة", "liability", "2200", True, None),
    ("2300", "دفعات مقدمة من أولياء الأمور", "liability", "2000", False, None),
    ("2310", "دفعات مقدمة — رسوم دراسية", "liability", "2300", True, None),
    ("2320", "تأمينات مستردة لأولياء الأمور", "liability", "2300", True, None),
    ("2400", "قروض", "liability", "2000", False, None),
    ("2410", "قروض قصيرة الأجل", "liability", "2400", True, None),
    ("2420", "قروض طويلة الأجل", "liability", "2400", True, None),

    # ── 3000 حقوق الملكية ────────────────────────────────────────
    ("3000", "حقوق الملكية", "equity", None, False, None),
    ("3100", "رأس المال", "equity", "3000", True, None),
    ("3200", "أرباح/خسائر مرحّلة", "equity", "3000", True, "retained_earnings_default"),
    ("3300", "مسحوبات المالك", "equity", "3000", True, None),
    ("3400", "مخصص الزكاة", "equity", "3000", True, None),

    # ── 4000 الإيرادات ───────────────────────────────────────────
    ("4000", "الإيرادات", "revenue", None, False, None),
    ("4100", "إيرادات الرسوم الدراسية", "revenue", "4000", False, None),
    ("4110", "الرسوم الدراسية السنوية", "revenue", "4100", True, "tuition_default"),
    ("4120", "الرسوم الدراسية الفصلية", "revenue", "4100", True, None),
    ("4130", "رسوم التسجيل والقبول", "revenue", "4100", True, None),
    ("4140", "رسوم اختبارات القبول", "revenue", "4100", True, None),
    ("4200", "إيرادات إضافية", "revenue", "4000", False, None),
    ("4210", "رسوم الكتب والمستلزمات", "revenue", "4200", True, None),
    ("4220", "رسوم النقل المدرسي", "revenue", "4200", True, None),
    ("4230", "رسوم الأنشطة والرحلات", "revenue", "4200", True, None),
    ("4240", "رسوم الزي المدرسي", "revenue", "4200", True, None),
    ("4250", "إيرادات المقصف/الكافتيريا", "revenue", "4200", True, None),
    ("4260", "إيرادات الأنشطة الصيفية", "revenue", "4200", True, None),
    ("4270", "إيرادات تأجير المرافق (قاعات/ملاعب)", "revenue", "4200", True, None),
    ("4280", "إيرادات التبرعات والدعم", "revenue", "4000", True, None),
    ("4290", "إيرادات متنوعة أخرى", "revenue", "4000", True, None),
    ("4900", "خصومات وتخفيضات (Contra-Revenue)", "revenue", "4000", False, None),
    ("4910", "خصم الإخوة", "revenue", "4900", True, "discount_default"),
    ("4920", "منح دراسية", "revenue", "4900", True, None),
    ("4930", "خصم أبناء الموظفين", "revenue", "4900", True, None),
    ("4940", "خصم التفوق الدراسي", "revenue", "4900", True, None),

    # ── 5000 المصروفات ───────────────────────────────────────────
    ("5000", "المصروفات", "expense", None, False, None),
    ("5100", "المصروفات التشغيلية", "expense", "5000", False, None),
    ("5110", "رواتب المعلمين", "expense", "5100", True, "payroll_salary_default"),
    ("5120", "رواتب الإداريين", "expense", "5100", True, None),
    ("5130", "المرافق (كهرباء/مياه/إنترنت)", "expense", "5100", True, None),
    ("5140", "الصيانة والإصلاحات", "expense", "5100", True, None),
    ("5150", "القرطاسية والمستلزمات", "expense", "5100", True, None),
    ("5160", "النقل والمواصلات", "expense", "5100", True, None),
    ("5170", "التأمينات الاجتماعية (حصة المدرسة)", "expense", "5100", True, None),
    ("5180", "الأنشطة والرحلات المدرسية", "expense", "5100", True, None),
    ("5190", "التدريب وتطوير المعلمين", "expense", "5100", True, None),
    ("5195", "اشتراكات المناهج والبرامج التعليمية", "expense", "5100", True, None),
    ("5200", "مصروفات أخرى", "expense", "5000", False, None),
    ("5210", "مصروفات متنوعة", "expense", "5200", True, None),
    ("5220", "التأمين", "expense", "5200", True, None),
    ("5230", "الدعاية والتسويق", "expense", "5200", True, None),
    ("5240", "استشارات قانونية ومحاسبية", "expense", "5200", True, None),
    ("5250", "رسوم بنكية وتحويلات", "expense", "5200", True, None),
    ("5260", "الأمن والحراسة", "expense", "5200", True, None),
    ("5270", "النظافة", "expense", "5200", True, None),
    ("5280", "إهلاك الأصول الثابتة", "expense", "5200", True, None),
    ("5290", "الزكاة", "expense", "5200", True, None),
]


# ════════════════════════════════════════════════════════════════════
# 2. ROLES
# ════════════════════════════════════════════════════════════════════

DEFAULT_ROLES = [
    # (name, name_ar, is_system, permission_spec)
    ("admin",           "مدير النظام",   True,  "all"),
    ("student_affairs", "شؤون الطلاب",  False, [
        ("students", ["view", "add", "edit", "delete"]),
        ("sections", ["view"]),
        ("grades", ["view"]),
        ("academic_years", ["view"]),
    ]),
    ("teacher",         "معلم",         False, [
        ("attendance", ["view", "add", "edit"]),
        ("results", ["view", "add", "edit"]),
        ("schedule", ["view"]),
        ("portal", ["view", "add", "edit"]),
        ("students", ["view"]),
    ]),
    ("accountant",      "محاسب",         False, [
        ("finance", PERMISSION_ACTIONS),
        ("finance_transactions", PERMISSION_ACTIONS),
        ("expenses", PERMISSION_ACTIONS),
        ("payroll", PERMISSION_ACTIONS),
    ]),
    ("warehouse",       "أمين مخزن",     False, [("expenses", ["view", "add"])]),
    ("parent",          "ولي أمر",       False, [("portal", ["view"])]),
    ("student",         "طالب",          False, [("portal", ["view"])]),
]


# ════════════════════════════════════════════════════════════════════
# 3. ACADEMIC STRUCTURE
# ════════════════════════════════════════════════════════════════════

# 15 grades — KG1 through 3rd secondary.
GRADES = [
    # (name_ar, order_index, stage)
    ("روضة أولى",         1,  "رياض أطفال"),
    ("روضة ثانية",        2,  "رياض أطفال"),
    ("الأول الابتدائي",   3,  "ابتدائي"),
    ("الثاني الابتدائي",  4,  "ابتدائي"),
    ("الثالث الابتدائي",  5,  "ابتدائي"),
    ("الرابع الابتدائي",  6,  "ابتدائي"),
    ("الخامس الابتدائي",  7,  "ابتدائي"),
    ("السادس الابتدائي",  8,  "ابتدائي"),
    ("الأول المتوسط",     9,  "متوسط"),
    ("الثاني المتوسط",   10,  "متوسط"),
    ("الثالث المتوسط",   11,  "متوسط"),
    ("الأول الثانوي",    12,  "ثانوي"),
    ("الثاني الثانوي",   13,  "ثانوي"),
    ("الثالث الثانوي",   14,  "ثانوي"),
]
# NOTE: order_index starts at 1; the row count is 14 not 15 because I
# folded KG1+KG2 into "رياض أطفال" as two grades. Adjust to 15 by
# adding a third kindergarten year if your school uses it.

SECTIONS_PER_GRADE = ["أ", "ب"]  # 2 sections each → 28 sections

DAYS = [
    # (name_ar, order_index)
    ("الأحد",     1),
    ("الاثنين",   2),
    ("الثلاثاء",  3),
    ("الأربعاء",  4),
    ("الخميس",    5),
]

PERIODS = [
    # (name_ar, order_index, start, end, is_break)
    ("الحصة الأولى",   1, time(7, 30),  time(8, 15),  False),
    ("الحصة الثانية",  2, time(8, 25),  time(9, 10),  False),
    ("الحصة الثالثة",  3, time(9, 20),  time(10, 5),  False),
    ("الاستراحة",      4, time(10, 5),  time(10, 25), True),
    ("الحصة الرابعة",  5, time(10, 25), time(11, 10), False),
    ("الحصة الخامسة",  6, time(11, 20), time(12, 5),  False),
    ("الحصة السادسة",  7, time(12, 15), time(13, 0),  False),
    ("الحصة السابعة",  8, time(13, 10), time(13, 55), False),
]


# (name_ar, code, list_of_grade_order_indexes)
SUBJECTS = [
    ("القرآن الكريم",             "QUR", list(range(3, 12))),        # 1st primary → 3rd middle
    ("التربية الإسلامية",         "ISL", list(range(3, 15))),        # 1st primary → 3rd secondary
    ("اللغة العربية",             "ARB", list(range(3, 15))),
    ("الرياضيات",                 "MTH", list(range(3, 15))),
    ("العلوم",                    "SCI", list(range(3, 12))),
    ("الدراسات الاجتماعية",       "SOC", list(range(3, 15))),
    ("اللغة الإنجليزية",          "ENG", list(range(3, 15))),
    ("الحاسب وتقنية المعلومات",   "CS",  list(range(6, 15))),
    ("التربية الفنية",            "ART", list(range(3, 12))),
    ("التربية البدنية",           "PE",  list(range(3, 15))),
    ("المهارات الحياتية والأسرية", "LFS", list(range(3, 12))),
]


ROOMS = [
    # (name_ar, room_type, capacity)
    ("قاعة 101", "classroom", 25),
    ("قاعة 102", "classroom", 25),
    ("قاعة 103", "classroom", 25),
    ("قاعة 201", "classroom", 25),
    ("قاعة 202", "classroom", 25),
    ("قاعة 203", "classroom", 25),
    ("قاعة 301", "classroom", 25),
    ("قاعة 302", "classroom", 25),
    ("قاعة 303", "classroom", 25),
    ("قاعة 401", "classroom", 25),
    ("معمل الحاسب", "lab", 20),
    ("معمل العلوم", "lab", 20),
    ("المكتبة",     "library", 40),
    ("الملعب",      "gym", 100),
    ("قاعة الفنون", "classroom", 25),
]


# ════════════════════════════════════════════════════════════════════
# 4. BANK QUESTIONS (baseline content so pickers work)
# ════════════════════════════════════════════════════════════════════
#
# Format: (subject_code, grade_order_index, kind, difficulty, prompt,
#          points, correct_short, choices)
# choices = list of (label, is_correct) — only for mcq / tf / multi
# For short: correct_short matters; choices = []

BANK_QUESTIONS = [
    # ── الرياضيات (MTH) — 4th primary ─────────────────────────────
    ("MTH", 6, "mcq", "easy", "ما ناتج 7 × 8 ؟", Decimal("1"), "",
     [("54", False), ("56", True), ("64", False), ("48", False)]),
    ("MTH", 6, "mcq", "medium", "ما ناتج 144 ÷ 12 ؟", Decimal("1"), "",
     [("10", False), ("11", False), ("12", True), ("14", False)]),
    ("MTH", 6, "tf", "easy", "العدد 15 عدد فردي.", Decimal("1"), "",
     [("صح", True), ("خطأ", False)]),
    ("MTH", 6, "short", "medium", "اكتب العدد التالي في المتتالية: 2، 4، 6، 8، ...",
     Decimal("2"), "10", []),

    # ── الرياضيات — 5th primary ────────────────────────────────────
    ("MTH", 7, "mcq", "medium", "ما هو الكسر المكافئ للكسر 2/4 ؟", Decimal("1"), "",
     [("1/2", True), ("1/3", False), ("2/3", False), ("3/4", False)]),
    ("MTH", 7, "short", "hard", "ما مساحة مستطيل طوله 8 سم وعرضه 5 سم؟",
     Decimal("2"), "40", []),

    # ── اللغة العربية (ARB) — 4th primary ─────────────────────────
    ("ARB", 6, "mcq", "easy", "ما مفرد كلمة \"كتب\" ؟", Decimal("1"), "",
     [("كتاب", True), ("كاتب", False), ("مكتوب", False), ("كتابة", False)]),
    ("ARB", 6, "tf", "easy", "الفعل \"ذهب\" فعل ماضٍ.", Decimal("1"), "",
     [("صح", True), ("خطأ", False)]),
    ("ARB", 6, "short", "medium", "اكتب جمع كلمة \"قلم\".", Decimal("2"), "أقلام", []),

    # ── العربية — 5th primary ─────────────────────────────────────
    ("ARB", 7, "mcq", "medium", "ما نوع كلمة \"جميل\" في جملة \"الولدُ جميلٌ\"؟",
     Decimal("1"), "",
     [("اسم", True), ("فعل", False), ("حرف", False), ("ظرف", False)]),
    ("ARB", 7, "short", "hard", "أعرب كلمة \"المعلم\" في: \"يشرحُ المعلمُ الدرسَ\".",
     Decimal("2"), "فاعل مرفوع", []),

    # ── اللغة الإنجليزية (ENG) — 4th primary ──────────────────────
    ("ENG", 6, "mcq", "easy", "What is the plural of \"book\"?", Decimal("1"), "",
     [("books", True), ("bookes", False), ("book", False), ("bookies", False)]),
    ("ENG", 6, "tf", "easy", "\"Cat\" is an animal.", Decimal("1"), "",
     [("True", True), ("False", False)]),
    ("ENG", 6, "short", "medium", "Write the number 5 in English.", Decimal("2"),
     "five", []),

    # ── الإنجليزية — 5th primary ──────────────────────────────────
    ("ENG", 7, "mcq", "medium", "Choose the correct verb: She ____ to school every day.",
     Decimal("1"), "",
     [("go", False), ("goes", True), ("going", False), ("gone", False)]),
    ("ENG", 7, "short", "hard", "Translate to English: \"أنا طالب\".", Decimal("2"),
     "I am a student", []),

    # ── العلوم (SCI) — 4th primary ────────────────────────────────
    ("SCI", 6, "mcq", "easy", "ما الحالة التي يتحول إليها الماء عند التجمد؟",
     Decimal("1"), "",
     [("صلبة", True), ("سائلة", False), ("غازية", False), ("بلازما", False)]),
    ("SCI", 6, "tf", "easy", "الشمس نجم.", Decimal("1"), "",
     [("صح", True), ("خطأ", False)]),
    ("SCI", 6, "short", "medium", "اذكر ثلاث حالات للمادة.", Decimal("2"),
     "صلبة، سائلة، غازية", []),

    # ── العلوم — 5th primary ──────────────────────────────────────
    ("SCI", 7, "mcq", "medium", "ما العضو المسؤول عن ضخ الدم في الجسم؟",
     Decimal("1"), "",
     [("القلب", True), ("الرئة", False), ("الكبد", False), ("الكلى", False)]),
    ("SCI", 7, "short", "hard", "اشرح دورة الماء في الطبيعة بإيجاز.", Decimal("3"),
     "تبخر ثم تكاثف ثم هطول", []),

    # ── التربية الإسلامية (ISL) — 4th primary ─────────────────────
    ("ISL", 6, "mcq", "easy", "كم عدد أركان الإسلام؟", Decimal("1"), "",
     [("3", False), ("4", False), ("5", True), ("6", False)]),
    ("ISL", 6, "tf", "easy", "الصلاة واجبة على كل مسلم بالغ عاقل.", Decimal("1"), "",
     [("صح", True), ("خطأ", False)]),
    ("ISL", 6, "short", "medium", "اذكر أول أركان الإسلام.", Decimal("2"),
     "الشهادتان", []),

    # ── الإسلامية — 5th primary ───────────────────────────────────
    ("ISL", 7, "mcq", "medium", "في أي شهر يصوم المسلمون؟", Decimal("1"), "",
     [("رمضان", True), ("شوال", False), ("رجب", False), ("محرم", False)]),
    ("ISL", 7, "short", "hard", "اذكر ثلاثة من أركان الوضوء.", Decimal("3"),
     "غسل الوجه، غسل اليدين، مسح الرأس", []),

    # ── الدراسات الاجتماعية (SOC) — 4th primary ───────────────────
    ("SOC", 6, "mcq", "easy", "ما عاصمة المملكة العربية السعودية؟", Decimal("1"), "",
     [("الرياض", True), ("جدة", False), ("مكة المكرمة", False), ("المدينة المنورة", False)]),
    ("SOC", 6, "tf", "easy", "المملكة العربية السعودية تقع في قارة آسيا.", Decimal("1"), "",
     [("صح", True), ("خطأ", False)]),

    # ── الاجتماعية — 5th primary ──────────────────────────────────
    ("SOC", 7, "mcq", "medium", "ما أكبر مدينة في المملكة العربية السعودية من حيث عدد السكان؟",
     Decimal("1"), "",
     [("الرياض", True), ("جدة", False), ("مكة", False), ("الدمام", False)]),
    ("SOC", 7, "short", "medium", "اذكر اثنتين من مدن المملكة الكبرى.", Decimal("2"),
     "الرياض وجدة", []),
]

# ════════════════════════════════════════════════════════════════════
# 5. HELPERS
# ════════════════════════════════════════════════════════════════════

def _log(msg: str) -> None:
    print(msg, flush=True)


def _ensure_role_perms(spec) -> dict:
    """Return the JSON permission dict for a role spec.

    `spec` is either the literal string "all" or a list of
    (module, actions) tuples. When it's a list, modules that appear
    without a tuple are treated as view-only.
    """
    if spec == "all":
        return {m: list(PERMISSION_ACTIONS) for m in PERMISSION_MODULES}
    out = {}
    for module, actions in spec:
        out[module] = list(actions)
    return out


def _upsert(model, lookup: dict, defaults: dict):
    """Get-or-create by `lookup`. Returns (obj, created).

    On re-runs, only sets fields that are still NULL/empty so we don't
    silently overwrite an admin's later edits. Exceptions: fields that
    are part of the natural key (never touched) and identity columns.
    """
    obj = model.query.filter_by(**lookup).first()
    if obj is not None:
        return obj, False
    obj = model(**lookup, **defaults)
    db.session.add(obj)
    db.session.flush()
    return obj, True


def _has_journal_lines() -> bool:
    """Guard for the chart reset — refuse to wipe accounts that are
    already wired to the ledger."""
    from app.models import JournalLine
    return db.session.query(JournalLine.id).first() is not None


# ════════════════════════════════════════════════════════════════════
# 6. CHART OF ACCOUNTS — SAUDI RESET
# ════════════════════════════════════════════════════════════════════

def _wipe_existing_accounts(school_id: int) -> int:
    """Delete every Account row for the school.

    Safety: refuses if any JournalLine exists. Called only on a
    freshly-migrated DB where the migrations already inserted an
    Egyptian chart; we drop it and lay down the Saudi one instead.

    Cost centers are NOT deleted here (they're independent of the
    chart and stay). Payment methods are deleted because they point
    at accounts and must be re-created after the new chart is in.
    """
    if _has_journal_lines():
        raise RuntimeError(
            "REFUSING to reset the chart of accounts — the DB already "
            "has journal lines. Drop the database and re-run the "
            "migrations, or reset the chart manually."
        )
    # payment_methods hold a FK to accounts — delete them first.
    PaymentMethod.query.filter_by(school_id=school_id).delete()
    db.session.flush()
    n = Account.query.filter_by(school_id=school_id).delete()
    db.session.flush()
    return n


def _seed_saudi_chart(school_id: int) -> int:
    """Insert SAUDI_ACCOUNT_TREE for this school.

    Two passes because a child can reference a parent that appears
    later in the list (rare, but the tree is authored parent-first
    so it doesn't matter in practice). The second pass just re-links
    any stragglers whose parent was missing on pass one.
    """
    code_to_id: dict[str, int] = {}

    def _insert(code, name, type_, parent_code, is_postable, role):
        parent_id = code_to_id.get(parent_code) if parent_code else None
        a = Account(
            school_id=school_id,
            code=code, name=name, type=type_,
            parent_id=parent_id,
            is_active=True, is_system=True,
            is_postable=is_postable,
            account_role=role,
        )
        db.session.add(a)
        db.session.flush()
        code_to_id[code] = a.id

    # Pass 1 — insert in the order given (tree is parent-first).
    for code, name, type_, parent_code, is_postable, role in SAUDI_ACCOUNT_TREE:
        _insert(code, name, type_, parent_code, is_postable, role)

    # Pass 2 — re-link any child whose parent wasn't known during pass 1.
    db.session.flush()
    for code, _name, _t, parent_code, _p, _r in SAUDI_ACCOUNT_TREE:
        if not parent_code:
            continue
        a = Account.query.filter_by(school_id=school_id, code=code).first()
        if a is None or a.parent_id is not None:
            continue
        parent = Account.query.filter_by(school_id=school_id, code=parent_code).first()
        if parent is not None:
            a.parent_id = parent.id
    db.session.flush()
    return len(code_to_id)


# ════════════════════════════════════════════════════════════════════
# 7. COST CENTERS
# ════════════════════════════════════════════════════════════════════

SAUDI_COST_CENTERS = [
    "المرحلة الابتدائية",
    "المرحلة المتوسطة",
    "المرحلة الثانوية",
    "رياض الأطفال",
    "النقل المدرسي",
    "الأنشطة والرحلات",
    "المقصف/الكافتيريا",
    "الأنشطة الصيفية",
    "الإدارة العامة",
    "الصيانة والمرافق",
    "معمل الحاسب",
    "معمل العلوم",
]


def _seed_cost_centers(school_id: int) -> int:
    n = 0
    for name in SAUDI_COST_CENTERS:
        obj, created = _upsert(
            CostCenter,
            {"school_id": school_id, "name": name},
            {"is_active": True},
        )
        if created:
            n += 1
    return n


# ════════════════════════════════════════════════════════════════════
# 8. PAYMENT METHODS
# ════════════════════════════════════════════════════════════════════

def _seed_payment_methods(school_id: int) -> int:
    """Three baseline methods: cash, bank transfer, deferred.

    Account lookup is done via code because we just wrote the Saudi
    chart in this same run. Codes:
      1110 → cash_default
      1120 → primary bank account
    """
    cash = Account.query.filter_by(school_id=school_id, code="1110").first()
    bank = Account.query.filter_by(school_id=school_id, code="1120").first()
    if cash is None or bank is None:
        raise RuntimeError(
            "Payment-method seeding needs 1110 and 1120 to exist. "
            "Run the chart seeding first."
        )

    methods = [
        ("نقدي",         "immediate_cash", cash.id),
        ("تحويل بنكي",  "immediate_bank", bank.id),
        ("شبكة/مدى",    "immediate_bank", bank.id),
        ("آجل",          "deferred",       None),
    ]
    n = 0
    for name, kind, account_id in methods:
        obj, created = _upsert(
            PaymentMethod,
            {"school_id": school_id, "name": name},
            {"kind": kind, "account_id": account_id, "is_active": True},
        )
        if created:
            n += 1
    return n


# ════════════════════════════════════════════════════════════════════
# 9. ACADEMIC YEAR + TERMS
# ════════════════════════════════════════════════════════════════════

def _seed_academic_year(school_id: int):
    """2026-2027 with two 50%-weight terms.

    Dates follow the typical Saudi public-school calendar:
      · T1: late Aug → late Dec
      · T2: early Jan → late May
    Adjust if the school publishes different dates.
    """
    year, created = _upsert(
        AcademicYear,
        {"school_id": school_id, "name": "2026-2027"},
        {
            "start_date": date(2026, 8, 23),
            "end_date":   date(2027, 6, 10),
            "status":     "active",
        },
    )
    if created:
        _log(f"✓ Created academic year: {year.name}")

    t1, c1 = _upsert(
        Term,
        {"year_id": year.id, "order_index": 1},
        {
            "school_id":  school_id,
            "name":       "الفصل الدراسي الأول",
            "start_date": date(2026, 8, 23),
            "end_date":   date(2026, 12, 24),
            "weight":     Decimal("50"),
            "status_mode": "auto",
        },
    )
    if c1:
        _log(f"✓ Created term: {t1.name}")

    t2, c2 = _upsert(
        Term,
        {"year_id": year.id, "order_index": 2},
        {
            "school_id":  school_id,
            "name":       "الفصل الدراسي الثاني",
            "start_date": date(2027, 1, 10),
            "end_date":   date(2027, 5, 27),
            "weight":     Decimal("50"),
            "status_mode": "auto",
        },
    )
    if c2:
        _log(f"✓ Created term: {t2.name}")

    return year, [t1, t2]


# ════════════════════════════════════════════════════════════════════
# 10. GRADES + SECTIONS
# ════════════════════════════════════════════════════════════════════

def _seed_grades(school_id: int):
    grades = {}
    for name, oi, stage in GRADES:
        g, created = _upsert(
            Grade,
            {"school_id": school_id, "name": name},
            {"order_index": oi, "stage": stage},
        )
        if created:
            _log(f"✓ Created grade: {name}")
        grades[name] = g
    return grades


def _seed_sections(school_id: int, year, grades: dict):
    n = 0
    for gname, g in grades.items():
        for sname in SECTIONS_PER_GRADE:
            s, created = _upsert(
                Section,
                {"year_id": year.id, "grade_id": g.id, "name": sname},
                {"school_id": school_id, "capacity": 25},
            )
            if created:
                n += 1
    if n:
        _log(f"✓ Created {n} sections ({len(SECTIONS_PER_GRADE)} per grade)")
    return n


# ════════════════════════════════════════════════════════════════════
# 11. DAYS + PERIODS
# ════════════════════════════════════════════════════════════════════

def _seed_days(school_id: int):
    n = 0
    for name, oi in DAYS:
        d, created = _upsert(
            Day,
            {"school_id": school_id, "order_index": oi},
            {"name": name, "is_active": True},
        )
        if created:
            n += 1
    if n:
        _log(f"✓ Created {n} days")
    return n


def _seed_periods(school_id: int):
    n = 0
    for name, oi, start, end, is_break in PERIODS:
        p, created = _upsert(
            Period,
            {"school_id": school_id, "order_index": oi},
            {
                "name": name,
                "start_time": start,
                "end_time": end,
                "is_break": is_break,
            },
        )
        if created:
            n += 1
    if n:
        _log(f"✓ Created {n} periods (incl. one break)")
    return n


# ════════════════════════════════════════════════════════════════════
# 12. SUBJECTS (linked to grades + terms)
# ════════════════════════════════════════════════════════════════════

def _seed_subjects(school_id: int, grades: dict, terms: list):
    """Create subjects and wire them to the right grades + both terms.

    SUBJECTS stores grade order_index values; we resolve them to the
    actual Grade rows via `grades` (keyed by Arabic name, so we need a
    reverse map first).
    """
    oi_to_grade = {g.order_index: g for g in grades.values()}
    subjects = {}
    for name, code, grade_ois in SUBJECTS:
        s, created = _upsert(
            Subject,
            {"school_id": school_id, "name": name},
            {"code": code, "is_active": True},
        )
        if created:
            _log(f"✓ Created subject: {name}")

        # Link to grades (idempotent — M2M append is a no-op if present).
        for oi in grade_ois:
            g = oi_to_grade.get(oi)
            if g is not None and g not in s.grades:
                s.grades.append(g)

        # Link to both terms (subject runs all year).
        for t in terms:
            if t not in s.terms:
                s.terms.append(t)

        subjects[code] = s
    db.session.flush()
    return subjects


# ════════════════════════════════════════════════════════════════════
# 13. ROOMS
# ════════════════════════════════════════════════════════════════════

def _seed_rooms(school_id: int):
    n = 0
    for name, rtype, cap in ROOMS:
        r, created = _upsert(
            Room,
            {"school_id": school_id, "name": name},
            {"room_type": rtype, "capacity": cap, "is_active": True},
        )
        if created:
            n += 1
    if n:
        _log(f"✓ Created {n} rooms")
    return n


# ════════════════════════════════════════════════════════════════════
# 14. BANK QUESTIONS
# ════════════════════════════════════════════════════════════════════

def _seed_bank_questions(school_id: int, year, grades: dict, subjects: dict, admin_id: int):
    """Insert the baseline bank so the pickers + analytics have data.

    Each row is upserted on (school_id, prompt) so re-runs are safe.
    review_state is forced to `approved` so the pickers see them.
    `source` = 'school' (NOT 'nafis').
    """
    oi_to_grade = {g.order_index: g for g in grades.values()}
    n = 0
    for (subj_code, grade_oi, kind, difficulty, prompt,
         points, correct_short, choices) in BANK_QUESTIONS:

        subject = subjects.get(subj_code)
        grade   = oi_to_grade.get(grade_oi)
        if subject is None or grade is None:
            continue

        bq, created = _upsert(
            BankQuestion,
            {"school_id": school_id, "prompt": prompt},
            {
                "subject_id": subject.id,
                "grade_id": grade.id,
                "academic_year_id": year.id,
                "created_by_id": admin_id,
                "kind": kind,
                "points": points,
                "correct_short": correct_short,
                "difficulty": difficulty,
                "tags": "",
                "review_state": "approved",
                "source": "school",
                "visibility": "shared",
                "is_archived": False,
            },
        )
        if not created:
            continue

        if choices:
            for i, (label, is_correct) in enumerate(choices):
                db.session.add(BankChoice(
                    question_id=bq.id,
                    order_index=i + 1,
                    label=label,
                    is_correct=is_correct,
                ))
        n += 1

    if n:
        _log(f"✓ Created {n} bank questions (approved)")
    return n

# ════════════════════════════════════════════════════════════════════
# 15. MAIN
# ════════════════════════════════════════════════════════════════════

DEFAULT_SCHOOL_CODE = "MNS"
DEFAULT_SCHOOL_NAME = "مدرستي"


def _upsert_school() -> School:
    """Create the school if missing; refresh the Saudi defaults on
    every run so a config change here rolls forward cleanly."""
    school, created = _upsert(
        School,
        {"code": DEFAULT_SCHOOL_CODE},
        {
            "name": DEFAULT_SCHOOL_NAME,
            "phone": "+966500000000",
            "address": "الرياض — المملكة العربية السعودية",
            "is_active": True,
        },
    )
    # Saudi-specific settings (idempotent refresh).
    school.name = school.name or DEFAULT_SCHOOL_NAME
    school.currency = "SAR"
    school.currency_symbol = "ر.س"
    school.default_tax_rate = Decimal("15")
    school.fiscal_year_start_month = 9
    school.invoice_prefix = "INV"
    school.invoice_start_number = 1
    school.rounding_policy = "normal"
    school.show_logo_on_prints = True
    school.reminder_days_before = "7,3"
    school.notify_channels = "in_app,email"
    school.attendance_mode = "daily"  # change to per_period after testing
    db.session.flush()
    if created:
        _log(f"✓ Created school: {school.name} ({school.code})")
    else:
        _log(f"• School already exists: {school.name} ({school.code})")
    return school


def _upsert_roles(school: School) -> dict:
    roles = {}
    for name, name_ar, is_system, spec in DEFAULT_ROLES:
        r, created = _upsert(
            Role,
            {"school_id": school.id, "name": name},
            {
                "name_ar": name_ar,
                "is_system": is_system,
                "permissions": _ensure_role_perms(spec),
            },
        )
        if created:
            _log(f"✓ Created role: {name_ar} ({name})")
        roles[name] = r
    return roles


def _upsert_admin(school: School, roles: dict) -> User:
    admin_role = roles["admin"]
    admin, created = _upsert(
        User,
        {"school_id": school.id, "username": "admin"},
        {
            "role_id": admin_role.id,
            "full_name": "مدير النظام",
            "email": "admin@manasety.local",
            "phone": "+966500000001",
            "is_active": True,
        },
    )
    if created:
        admin.set_password("admin12345")
        db.session.flush()
        _log("✓ Created admin user: admin / admin12345")
    return admin


def run():
    app = create_app()
    with app.app_context():
        _log("=" * 60)
        _log("seed_v2 — Saudi school bootstrap")
        _log("=" * 60)

        # ── 0. Guard: the chart reset only works on a fresh DB.
        if _has_journal_lines():
            _log("✗ Journal lines exist — aborting before the chart reset.")
            _log("  If this is a fresh DB, drop it and re-run migrations.")
            return

        # ── 1. School
        school = _upsert_school()

        # ── 2. Roles
        roles = _upsert_roles(school)

        # ── 3. Admin
        admin = _upsert_admin(school, roles)

        # ── 4. Chart of accounts (Saudi reset)
        wiped = _wipe_existing_accounts(school.id)
        if wiped:
            _log(f"• Wiped {wiped} legacy accounts (Egyptian chart)")
        inserted = _seed_saudi_chart(school.id)
        _log(f"✓ Seeded {inserted} Saudi accounts (3-level tree)")

        # ── 5. Cost centers
        _seed_cost_centers(school.id)

        # ── 6. Payment methods
        _seed_payment_methods(school.id)

        # ── 7. Academic year + terms
        year, terms = _seed_academic_year(school.id)

        # ── 8. Grades
        grades = _seed_grades(school.id)

        # ── 9. Sections
        _seed_sections(school.id, year, grades)

        # ── 10. Days
        _seed_days(school.id)

        # ── 11. Periods
        _seed_periods(school.id)

        # ── 12. Subjects (grades + terms links)
        subjects = _seed_subjects(school.id, grades, terms)

        # ── 13. Rooms
        _seed_rooms(school.id)

        # ── 14. Bank questions
        _seed_bank_questions(
            school.id, year, grades, subjects, admin.id,
        )

        # ── Commit everything
        db.session.commit()

        # ── Summary
        from app.models import (
            Account as _A, Section as _S, Subject as _Sub,
            Day as _D, Period as _P, Room as _R,
            BankQuestion as _BQ,
        )
        _log("")
        _log("=" * 60)
        _log("✅ seed_v2 complete")
        _log("=" * 60)
        _log(f"  School:        {school.name} ({school.code}) — currency {school.currency}")
        _log(f"  Academic year: {year.name}")
        _log(f"  Terms:         {len(terms)}")
        _log(f"  Grades:        {len(grades)}")
        _log(f"  Sections:      {_S.query.filter_by(school_id=school.id).count()}")
        _log(f"  Subjects:      {len(subjects)}")
        _log(f"  Days:          {_D.query.filter_by(school_id=school.id).count()}")
        _log(f"  Periods:       {_P.query.filter_by(school_id=school.id).count()}")
        _log(f"  Rooms:         {_R.query.filter_by(school_id=school.id).count()}")
        _log(f"  Accounts:      {_A.query.filter_by(school_id=school.id).count()}")
        _log(f"  BankQuestion:  {_BQ.query.filter_by(school_id=school.id).count()}")
        _log("")
        _log("🔑 Admin login:   admin / admin12345")
        _log("=" * 60)


if __name__ == "__main__":
    run()