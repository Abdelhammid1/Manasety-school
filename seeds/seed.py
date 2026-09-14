"""Seed default school, roles, admin user, and chart of accounts. Idempotent.

Also seeds the Sprint 9 e2e fixture (teacher `ehab`, year/term/grade/sections/
subject/assignment) so `tests/e2e/permissions.spec.ts` and the docs' claim in
SPRINT_9_ACCEPTANCE.md ("ehab / admin12345 بدور معلم") hold on a fresh DB.
"""
import sys
try:
    # Windows default console codepage (cp1252) can't encode the ✓ char or the
    # Arabic role/account names below, which crashes the seed mid-run and leaves
    # the DB with only a `schools` row (no admin, no login). Force UTF-8.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass  # stdout replaced (pytest capture, redirects) — safe to skip.

from datetime import date, timedelta
from decimal import Decimal

from app import create_app
from app.extensions import db
from app.models import (
    School, Role, User, Account,
    AcademicYear, Term, Grade, Section,
    Subject, Teacher, Assignment,
    Student, Enrollment,
)
from app.models.user import PERMISSION_MODULES, PERMISSION_ACTIONS


DEFAULT_ACCOUNTS = [
    # (code, name, type, parent_code, is_system)
    ("1000", "الأصول", "asset", None, True),
    ("1100", "النقدية", "asset", "1000", True),
    ("1200", "البنك", "asset", "1000", True),
    ("1300", "ذمم الطلاب (مدينة)", "asset", "1000", True),
    ("2000", "الخصوم", "liability", None, True),
    ("2100", "ذمم الموردين (دائنة)", "liability", "2000", True),
    ("3000", "حقوق الملكية", "equity", None, True),
    ("3100", "رأس المال", "equity", "3000", True),
    ("4000", "الإيرادات", "revenue", None, True),
    ("4100", "إيرادات رسوم تعليمية", "revenue", "4000", True),
    ("4200", "إيرادات رسوم مواصلات", "revenue", "4000", True),
    ("4900", "إيرادات أخرى", "revenue", "4000", True),
    ("5000", "المصروفات", "expense", None, True),
    ("5100", "رواتب الموظفين", "expense", "5000", True),
    ("5200", "الإيجار والمرافق", "expense", "5000", True),
    ("5300", "الصيانة والمستلزمات", "expense", "5000", True),
    ("5900", "مصروفات أخرى", "expense", "5000", True),
]


DEFAULT_ROLES = [
    ("admin",            "مدير",          True,  "all"),
    ("student_affairs",  "شؤون طلاب",     False, [
        ("students", PERMISSION_ACTIONS), ("sections", ["view"]),
        ("grades", ["view"]), ("academic_years", ["view"]),
    ]),
    ("teacher",          "معلم",          False, [
        ("attendance", PERMISSION_ACTIONS), ("results", ["view", "add", "edit"]),
        ("schedule", ["view"]), ("portal", PERMISSION_ACTIONS),
    ]),
    ("accountant",       "محاسب",         False, [
        ("finance", PERMISSION_ACTIONS), ("expenses", PERMISSION_ACTIONS),
    ]),
    ("warehouse",        "أمين مخزن",     False, [("expenses", ["view", "add"])]),
    ("parent",           "ولي أمر",       False, [("portal", ["view"])]),
]


def all_permissions() -> dict:
    return {m: list(PERMISSION_ACTIONS) for m in PERMISSION_MODULES}


def role_permissions(spec) -> dict:
    if spec == "all":
        return all_permissions()
    return {module: list(actions) for module, actions in spec}


def run():
    app = create_app()
    with app.app_context():
        school = School.query.filter_by(code=app.config["DEFAULT_SCHOOL_CODE"]).first()
        if not school:
            school = School(
                code=app.config["DEFAULT_SCHOOL_CODE"],
                name=app.config["DEFAULT_SCHOOL_NAME"],
            )
            db.session.add(school)
            db.session.commit()
            print(f"✓ Created school: {school.name}")

        for name, name_ar, is_system, spec in DEFAULT_ROLES:
            role = Role.query.filter_by(school_id=school.id, name=name).first()
            if not role:
                role = Role(
                    school_id=school.id,
                    name=name,
                    name_ar=name_ar,
                    is_system=is_system,
                    permissions=role_permissions(spec),
                )
                db.session.add(role)
                print(f"✓ Created role: {name_ar}")
        db.session.commit()

        for code, name, type_, parent_code, is_system in DEFAULT_ACCOUNTS:
            existing = Account.query.filter_by(school_id=school.id, code=code).first()
            if existing:
                continue
            parent = None
            if parent_code:
                parent = Account.query.filter_by(school_id=school.id, code=parent_code).first()
            a = Account(
                school_id=school.id, code=code, name=name, type=type_,
                parent_id=parent.id if parent else None, is_system=is_system,
            )
            db.session.add(a)
            print(f"✓ Created account: {code} {name}")
        db.session.commit()

        admin_role = Role.query.filter_by(school_id=school.id, name="admin").first()
        admin = User.query.filter_by(school_id=school.id, username="admin").first()
        if not admin:
            admin = User(
                school_id=school.id,
                role_id=admin_role.id,
                username="admin",
                full_name="مدير النظام",
                email="admin@manasety.local",
            )
            admin.set_password("admin12345")
            db.session.add(admin)
            db.session.commit()
            print("✓ Created admin user (username=admin / password=admin12345)")
        else:
            print("• Admin user already exists.")

        seed_sprint9_fixture(school, admin_role)

        print("\nDone. Login at /auth/login")


def seed_sprint9_fixture(school: School, teacher_role_fallback: Role) -> None:
    """Idempotently seed the Sprint 9 e2e fixture: ehab teacher + surrounding scaffolding.

    Required by `tests/e2e/permissions.spec.ts` and documented in
    SPRINT_9_ACCEPTANCE.md:101-107. Field values mirror the equivalent blocks
    in `scripts/create_apple_reviewer.py` so seed & reviewer stay consistent.
    """
    teacher_role = Role.query.filter_by(school_id=school.id, name="teacher").first() \
        or teacher_role_fallback

    year = AcademicYear.query.filter_by(school_id=school.id, name="2025-2026").first()
    if not year:
        year = AcademicYear(
            school_id=school.id, name="2025-2026",
            start_date=date(2025, 9, 1), end_date=date(2026, 6, 30),
            status="active",
        )
        db.session.add(year)
        db.session.flush()
        print(f"✓ Created academic year: {year.name}")

    term = Term.query.filter_by(year_id=year.id, order_index=1).first()
    if not term:
        term = Term(
            school_id=school.id, year_id=year.id,
            name="الفترة الأولى", order_index=1,
            start_date=year.start_date,
            end_date=year.start_date + timedelta(days=90),
            weight=Decimal("50"),
        )
        db.session.add(term)
        print(f"✓ Created term: {term.name} (weight={term.weight})")

    grade = Grade.query.filter_by(school_id=school.id, name="الأول الابتدائي").first()
    if not grade:
        grade = Grade(
            school_id=school.id, name="الأول الابتدائي",
            order_index=1, stage="ابتدائي",
        )
        db.session.add(grade)
        db.session.flush()
        print(f"✓ Created grade: {grade.name}")

    sections = {}
    for sec_name in ("أ-fx", "ب-fx"):
        sec = Section.query.filter_by(
            year_id=year.id, grade_id=grade.id, name=sec_name,
        ).first()
        if not sec:
            sec = Section(
                school_id=school.id, year_id=year.id, grade_id=grade.id,
                name=sec_name, capacity=30,
            )
            db.session.add(sec)
            db.session.flush()
            print(f"✓ Created section: {sec_name}")
        sections[sec_name] = sec

    subject = Subject.query.filter_by(school_id=school.id, name="الرياضيات-fx").first()
    if not subject:
        subject = Subject(school_id=school.id, name="الرياضيات-fx", is_active=True)
        db.session.add(subject)
        db.session.flush()
        print(f"✓ Created subject: {subject.name}")
    if grade not in subject.grades:
        subject.grades.append(grade)

    ehab = User.query.filter_by(school_id=school.id, username="ehab").first()
    if not ehab:
        ehab = User(
            school_id=school.id, role_id=teacher_role.id,
            username="ehab", full_name="إيهاب",
            email="ehab@manasety.local",
        )
        ehab.set_password("admin12345")
        db.session.add(ehab)
        db.session.flush()
        print("✓ Created teacher user (username=ehab / password=admin12345)")

    teacher = Teacher.query.filter_by(user_id=ehab.id).first()
    if not teacher:
        teacher = Teacher(
            school_id=school.id, user_id=ehab.id,
            full_name="إيهاب", specialization="رياضيات",
            is_active=True,
        )
        db.session.add(teacher)
        db.session.flush()
        print(f"✓ Created teacher profile for ehab (id={teacher.id})")

    section_a = sections["أ-fx"]
    assignment = Assignment.query.filter_by(
        year_id=year.id, section_id=section_a.id,
        subject_id=subject.id, teacher_id=teacher.id,
    ).first()
    if not assignment:
        assignment = Assignment(
            school_id=school.id, year_id=year.id,
            section_id=section_a.id, subject_id=subject.id,
            teacher_id=teacher.id, is_active=True, weekly_periods=1,
        )
        db.session.add(assignment)
        print(f"✓ Assigned ehab → {subject.name} in section {section_a.name}")

    # ── Parent (ولي أمر) account + demo student ──────────────────────────────
    # Gives the `parent` role a real login and populates the parent app with
    # one student in section أ-fx so /portal has data to render.
    parent_role = Role.query.filter_by(school_id=school.id, name="parent").first()
    wali = User.query.filter_by(school_id=school.id, username="wali").first()
    if not wali and parent_role:
        wali = User(
            school_id=school.id, role_id=parent_role.id,
            username="wali", full_name="ولي الأمر",
            email="wali@manasety.local",
        )
        wali.set_password("admin12345")
        db.session.add(wali)
        db.session.flush()
        print("✓ Created parent user (username=wali / password=admin12345)")

    student = Student.query.filter_by(
        school_id=school.id, permanent_code="STU-FX-0001",
    ).first()
    if not student:
        student = Student(
            school_id=school.id,
            permanent_code="STU-FX-0001",
            full_name="طالب تجريبي",
            gender="male",
            parent_name="ولي الأمر",
            parent_user_id=wali.id if wali else None,
        )
        db.session.add(student)
        db.session.flush()
        print(f"✓ Created demo student: {student.full_name} ({student.permanent_code})")
    elif wali and student.parent_user_id != wali.id:
        student.parent_user_id = wali.id
        print(f"🔗 Linked demo student to parent {wali.username}")

    enrollment = Enrollment.query.filter_by(
        student_id=student.id, year_id=year.id,
    ).first()
    if not enrollment:
        enrollment = Enrollment(
            school_id=school.id, student_id=student.id, year_id=year.id,
            grade_id=grade.id, section_id=section_a.id, status="active",
        )
        db.session.add(enrollment)
        print(f"✓ Enrolled demo student in section {section_a.name}")

    db.session.commit()


if __name__ == "__main__":
    run()
