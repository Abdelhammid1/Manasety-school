"""Rich demo data for client-facing platform walkthroughs.

Builds on top of seeds/seed.py (which must run first — it creates the
admin user, the default chart of accounts, and the Sprint-9 e2e fixture).
This script is idempotent-ish per entity (checks before insert on the
unique-constrained rows) but is really meant to run ONCE on a freshly
truncated database.

Run with:  python -m seeds.demo_data
"""
import random
import sys
from datetime import date, timedelta
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
    Subject, Teacher, Assignment,
    Student, Enrollment,
    Attendance,
    PassRule, AssessmentComponent, GradeEntry,
    Account, FeeType, Invoice, InvoiceLine, PaymentMethod,
    CostCenter,
)
from app.models.finance import ensure_default_cost_centers
from app.models.platform import SchoolCalendarDay
from app.services.ledger import post_invoice_to_ledger, record_payment, LedgerError
from app.services.subsidiary import ensure_student_account

random.seed(42)

GRADES = [
    (1, "الأول الابتدائي", "ابتدائي"),
    (2, "الثاني الابتدائي", "ابتدائي"),
    (3, "الثانث الابتدائي", "ابتدائي"),
    (4, "الرابع الابتدائي", "ابتدائي"),
    (5, "الخامس الابتدائي", "ابتدائي"),
    (6, "السادس الابتدائي", "ابتدائي"),
    (7, "الأول الإعدادي", "إعدادي"),
    (8, "الثاني الإعدادي", "إعدادي"),
    (9, "الثالث الإعدادي", "إعدادي"),
    (10, "الأول الثانوي", "ثانوي"),
    (11, "الثاني الثانوي", "ثانوي"),
    (12, "الثالث الثانوي", "ثانوي"),
]
SECTIONS = [("أ", "A"), ("ب", "B")]
SUBJECTS = ["اللغة العربية", "الرياضيات", "العلوم", "اللغة الإنجليزية", "التربية الدينية"]
EXTRA_TEACHERS = [
    ("sara", "سارة أحمد", "لغة عربية"),
    ("mostafa", "مصطفى كامل", "علوم"),
]
FIRST_MALE = ["أحمد", "محمد", "علي", "يوسف", "عمر", "كريم", "حسن", "خالد", "إبراهيم", "سيف", "زياد", "آدم"]
FIRST_FEMALE = ["فاطمة", "مريم", "نور", "سارة", "هبة", "ياسمين", "ملك", "جنى", "رقية", "آية", "ليلى", "دينا"]
LAST_NAMES = ["السيد", "عبدالله", "حسنين", "الشريف", "فتحي", "سليمان", "عبدالرحمن",
              "محمود", "النجار", "حماد", "توفيق", "الشافعي"]

ATTENDANCE_WEIGHTS = [("present", 85), ("absent", 8), ("late", 5), ("excused", 2)]


def weighted_choice(pairs):
    total = sum(w for _, w in pairs)
    r = random.uniform(0, total)
    upto = 0
    for val, w in pairs:
        upto += w
        if upto >= r:
            return val
    return pairs[-1][0]


def run():
    app = create_app()
    with app.app_context():
        school = School.query.first()
        year = AcademicYear.query.filter_by(school_id=school.id, name="2025-2026").first()
        term = Term.query.filter_by(year_id=year.id, order_index=1).first()
        admin = User.query.filter_by(school_id=school.id, username="admin").first()

        ensure_default_cost_centers(school.id)
        db.session.commit()
        print("✓ Cost centers ensured")

        # ── Fee types ──────────────────────────────────────────────
        def get_acct(code):
            return Account.query.filter_by(school_id=school.id, code=code).first()

        fee_defs = [
            ("رسوم دراسية سنوية", 6000, "4110", True, False),
            ("رسوم كتب ومستلزمات", 800, "4210", False, False),
            ("رسوم نقل", 1200, "4220", False, False),
        ]
        fee_types = {}
        for name, amt, code, installable, taxable in fee_defs:
            ft = FeeType.query.filter_by(school_id=school.id, name=name).first()
            if not ft:
                ft = FeeType(
                    school_id=school.id, name=name, default_amount=amt,
                    installable=installable, revenue_account_id=get_acct(code).id,
                    is_taxable=taxable,
                )
                db.session.add(ft)
                db.session.flush()
                print(f"✓ Fee type: {name}")
            fee_types[name] = ft
        db.session.commit()

        # ── Payment methods ───────────────────────────────────────
        pm_defs = [
            ("نقدي", "immediate_cash", "1110"),
            ("تحويل بنكي", "immediate_bank", "1120"),
        ]
        payment_methods = {}
        for name, kind, code in pm_defs:
            pm = PaymentMethod.query.filter_by(school_id=school.id, name=name).first()
            if not pm:
                pm = PaymentMethod(
                    school_id=school.id, name=name, kind=kind,
                    account_id=get_acct(code).id,
                )
                db.session.add(pm)
                db.session.flush()
                print(f"✓ Payment method: {name}")
            payment_methods[name] = pm
        db.session.commit()

        # ── Subjects (shared across all grades) ──────────────────
        subjects = {}
        for name in SUBJECTS:
            subj = Subject.query.filter_by(school_id=school.id, name=name).first()
            if not subj:
                subj = Subject(school_id=school.id, name=name, is_active=True)
                db.session.add(subj)
                db.session.flush()
                print(f"✓ Subject: {name}")
            subjects[name] = subj
        db.session.commit()

        # ── Teachers ───────────────────────────────────────────────
        teachers = []
        ehab_user = User.query.filter_by(school_id=school.id, username="ehab").first()
        ehab_teacher = Teacher.query.filter_by(user_id=ehab_user.id).first()
        teachers.append(ehab_teacher)
        teacher_role = Role.query.filter_by(school_id=school.id, name="teacher").first()
        for uname, full_name, spec in EXTRA_TEACHERS:
            u = User.query.filter_by(school_id=school.id, username=uname).first()
            if not u:
                u = User(school_id=school.id, role_id=teacher_role.id, username=uname,
                         full_name=full_name, email=f"{uname}@manasety.local")
                u.set_password("admin12345")
                db.session.add(u)
                db.session.flush()
            t = Teacher.query.filter_by(user_id=u.id).first()
            if not t:
                t = Teacher(school_id=school.id, user_id=u.id, full_name=full_name,
                            specialization=spec, is_active=True)
                db.session.add(t)
                db.session.flush()
                print(f"✓ Teacher: {full_name}")
            teachers.append(t)
        db.session.commit()

        # ── Grades + sections (rename fixture's -fx sections for grade 1) ──
        grade1 = Grade.query.filter_by(school_id=school.id, name="الأول الابتدائي").first()
        for old_name, new_name in [("أ-fx", "أ"), ("ب-fx", "ب")]:
            sec = Section.query.filter_by(year_id=year.id, grade_id=grade1.id, name=old_name).first()
            if sec:
                sec.name = new_name
        db.session.commit()
        print("✓ Renamed fixture sections to أ / ب")

        all_sections = []  # (grade, section)
        for order_idx, name, stage in GRADES:
            grade = Grade.query.filter_by(school_id=school.id, order_index=order_idx).first()
            if not grade:
                grade = Grade(school_id=school.id, name=name, order_index=order_idx, stage=stage)
                db.session.add(grade)
                db.session.flush()
                print(f"✓ Grade: {name}")
            for sec_name, _ in SECTIONS:
                sec = Section.query.filter_by(year_id=year.id, grade_id=grade.id, name=sec_name).first()
                if not sec:
                    sec = Section(school_id=school.id, year_id=year.id, grade_id=grade.id,
                                  name=sec_name, capacity=30)
                    db.session.add(sec)
                    db.session.flush()
                # link every subject to every grade
                for subj in subjects.values():
                    if grade not in subj.grades:
                        subj.grades.append(grade)
                all_sections.append((grade, sec))
            db.session.commit()
        print(f"✓ {len(GRADES)} grades / {len(all_sections)} sections ready")

        # ── Assignments (teacher ↔ subject ↔ section), round-robin ─
        t_idx = 0
        for grade, sec in all_sections:
            for subj in subjects.values():
                teacher = teachers[t_idx % len(teachers)]
                t_idx += 1
                exists = Assignment.query.filter_by(
                    year_id=year.id, section_id=sec.id, subject_id=subj.id, teacher_id=teacher.id,
                ).first()
                if not exists:
                    db.session.add(Assignment(
                        school_id=school.id, year_id=year.id, term_id=term.id,
                        section_id=sec.id, subject_id=subj.id, teacher_id=teacher.id,
                        is_active=True, weekly_periods=3,
                    ))
        db.session.commit()
        print("✓ Assignments created")

        # ── Assessment components per subject/term (shared across sections) ─
        components = {}
        for subj in subjects.values():
            for comp_name, max_score in [("اختبار الشهر الأول", 20), ("المشاركة الصفية", 10)]:
                comp = AssessmentComponent.query.filter_by(
                    term_id=term.id, subject_id=subj.id, name=comp_name,
                ).first()
                if not comp:
                    comp = AssessmentComponent(
                        school_id=school.id, term_id=term.id, subject_id=subj.id,
                        name=comp_name, max_score=max_score,
                    )
                    db.session.add(comp)
                    db.session.flush()
                components.setdefault(subj.id, []).append(comp)
        db.session.commit()
        print("✓ Assessment components created")

        # ── Students, invoices, payments, attendance, grades ───────
        invoice_seq = 1
        today = date.today()
        weekdays_back = []
        d = today
        while len(weekdays_back) < 10:
            d -= timedelta(days=1)
            if d.weekday() not in (4, 5):  # skip Fri/Sat (Egypt weekend)
                weekdays_back.append(d)

        total_students = 0
        for grade, sec in all_sections:
            n_students = random.randint(10, 15)
            for i in range(1, n_students + 1):
                code = f"STU-G{grade.order_index:02d}{sec.name}-{i:03d}"
                existing = Student.query.filter_by(school_id=school.id, permanent_code=code).first()
                if existing:
                    continue
                is_male = random.random() < 0.5
                first = random.choice(FIRST_MALE if is_male else FIRST_FEMALE)
                full_name = f"{first} {random.choice(LAST_NAMES)}"
                student = Student(
                    school_id=school.id, permanent_code=code, full_name=full_name,
                    gender="male" if is_male else "female",
                    parent_name=f"ولي أمر {full_name}",
                    parent_phone=f"01{random.randint(0,2)}{random.randint(10000000,99999999)}",
                )
                db.session.add(student)
                db.session.flush()

                enrollment = Enrollment(
                    school_id=school.id, student_id=student.id, year_id=year.id,
                    grade_id=grade.id, section_id=sec.id, status="active",
                    enrolled_at=date(2025, 9, 1),
                )
                db.session.add(enrollment)
                db.session.flush()
                total_students += 1

                # ── Invoice (tuition + maybe books/transport) ──
                lines_spec = [("رسوم دراسية سنوية", 6000)]
                if random.random() < 0.7:
                    lines_spec.append(("رسوم كتب ومستلزمات", 800))
                if random.random() < 0.4:
                    lines_spec.append(("رسوم نقل", 1200))
                total = sum(a for _, a in lines_spec)

                invoice = Invoice(
                    school_id=school.id, enrollment_id=enrollment.id,
                    number=f"INV-2026-{invoice_seq:05d}",
                    issue_date=date(2025, 9, 5), due_date=date(2025, 10, 5),
                    status="draft", total_amount=total,
                )
                invoice_seq += 1
                db.session.add(invoice)
                db.session.flush()
                for fname, amt in lines_spec:
                    db.session.add(InvoiceLine(
                        invoice_id=invoice.id, fee_type_id=fee_types[fname].id,
                        description=fname, amount=amt,
                    ))
                db.session.flush()

                try:
                    post_invoice_to_ledger(invoice, entry_date=invoice.issue_date)
                    db.session.commit()
                except LedgerError as e:
                    db.session.rollback()
                    print(f"  ! تخطي ترحيل فاتورة {code}: {e}")
                    continue

                # payment behaviour: 60% fully paid, 25% partial, 15% unpaid
                roll = random.random()
                if roll < 0.60:
                    pay_amount = invoice.remaining
                elif roll < 0.85:
                    pay_amount = round(total * random.uniform(0.4, 0.7), 2)
                else:
                    pay_amount = 0

                if pay_amount > 0:
                    pm_name = random.choice(["نقدي", "تحويل بنكي"])
                    pay_date = date(2025, 9, random.randint(6, 28))
                    try:
                        record_payment(
                            invoice, pay_amount, payment_methods[pm_name].id,
                            payment_date=pay_date, created_by=admin.id,
                        )
                        db.session.commit()
                    except LedgerError as e:
                        db.session.rollback()
                        print(f"  ! تخطي سداد فاتورة {code}: {e}")

                # ── Attendance (last 10 school days) ──
                for wd in weekdays_back:
                    status = weighted_choice(ATTENDANCE_WEIGHTS)
                    db.session.add(Attendance(
                        school_id=school.id, enrollment_id=enrollment.id,
                        date=wd, status=status, recorded_by_user_id=admin.id,
                    ))
                db.session.commit()

                # ── Grades (per subject linked to this grade) ──
                for subj in subjects.values():
                    if grade not in subj.grades:
                        continue
                    for comp in components.get(subj.id, []):
                        pct = random.uniform(0.55, 1.0)
                        score = round(float(comp.max_score) * pct, 2)
                        db.session.add(GradeEntry(
                            school_id=school.id, enrollment_id=enrollment.id,
                            component_id=comp.id, score=score,
                            recorded_by_user_id=admin.id,
                        ))
                db.session.commit()

            print(f"✓ {grade.name} - {sec.name}: {n_students} طالب")

        print(f"\n✓ إجمالي الطلاب: {total_students}")

        # ── Calendar events ────────────────────────────────────────
        cal_events = [
            (date(2025, 10, 6), "holiday", "عيد القوات المسلحة"),
            (date(2025, 11, 15), "exam", "بداية اختبارات منتصف الفصل"),
            (date(2025, 11, 16), "exam", "اختبارات منتصف الفصل"),
            (date(2025, 11, 17), "exam", "اختبارات منتصف الفصل"),
            (date(2025, 12, 1), "event", "معرض المشروعات العلمية"),
            (date(2025, 12, 25), "holiday", "إجازة نصف العام - بداية"),
            (date(2026, 1, 10), "teacher_day", "يوم تدريبي للمعلمين"),
            (date(2026, 2, 5), "event", "يوم الرياضة المدرسي"),
            (date(2026, 4, 20), "holiday", "إجازة شم النسيم"),
            (date(2026, 5, 10), "exam", "بداية اختبارات آخر العام"),
        ]
        for d, kind, title in cal_events:
            exists = SchoolCalendarDay.query.filter_by(
                school_id=school.id, academic_year_id=year.id, date=d, applies_to_stage=None,
            ).first()
            if not exists:
                db.session.add(SchoolCalendarDay(
                    school_id=school.id, academic_year_id=year.id,
                    date=d, day_type=kind, title=title,
                ))
        db.session.commit()
        print(f"✓ {len(cal_events)} حدث كالندر مُضاف")

        print("\nDone. افتح /calendar/month → توليد عطلات نهاية الأسبوع للسنة كاملة يدويًا من الواجهة.")


if __name__ == "__main__":
    run()
