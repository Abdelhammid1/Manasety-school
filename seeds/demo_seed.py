"""Demo seed — wipes the DB and rebuilds a rich Manasety school with
realistic mock data:

  · 1 school (مدرسة منصتي التجريبية)
  · 4 roles (admin / teacher / parent / student) — full permissions matrix
  · 1 admin + 8 teachers + 30 parents + 30 students (all with login accounts)
  · 1 academic year (٢٠٢٥-٢٠٢٦) + 2 terms
  · 8 grades (grades 1–8 primary/middle), 2 sections each = 16 sections
  · 8 subjects mapped to grades
  · 30 enrollments distributed across the sections
  · Teacher-Assignments per (subject × section)
  · Working days + periods + a full weekly schedule
  · 90 days of attendance history
  · Assessment components + grade entries
  · Chart of accounts + fee types
  · Invoices per student + installments + some paid payments
  · Employees + last 2 months of payroll
  · 6 courses (one per subject-with-materials) + lessons + assignments +
    quizzes + question bank
  · 8 school announcements

Run:  PYTHONPATH=. .venv/Scripts/python.exe seeds/demo_seed.py
"""
import random
from datetime import datetime, timedelta, date, time
from decimal import Decimal

from app import create_app
from app.extensions import db, bcrypt
from app.models import (
    School, User, Role,
    AcademicYear, Term, Grade, Section,
    Student, Enrollment,
    Teacher, Subject, Assignment,
    Day, Period, ScheduleSlot,
    Attendance,
    PassRule, AssessmentComponent, GradeEntry,
    Account, JournalEntry, JournalLine, FeeType, Invoice, InvoiceLine,
    Installment, Payment,
    Employee, Payroll,
    Course, CourseSection, Lesson, CourseAssignment, Submission,
    Quiz, Question, Choice, QuizAttempt, Answer,
    Announcement,
)
from app.services.accounting import post_journal


random.seed(42)
FIRST_NAMES_M = ["عبدالله","محمد","أحمد","خالد","عمر","يوسف","فيصل","سلطان","بندر","سعد","ماجد","تركي","سعود","نايف","سلمان"]
FIRST_NAMES_F = ["نور","سارة","ريم","لطيفة","دانة","فاطمة","حنين","لمى","جود","ملاك","شهد","رغد","لينا","مي"]
LAST_NAMES = ["السالم","الشمري","الغامدي","القحطاني","العتيبي","الحربي","المطيري","الدوسري","العمري","الشهري","الزهراني","الرشيد","الحارثي","المالكي","التميمي"]
STAGES = ["ابتدائي"]*6 + ["متوسط"]*2

def name_male():   return f"{random.choice(FIRST_NAMES_M)} {random.choice(FIRST_NAMES_M)} {random.choice(LAST_NAMES)}"
def name_female(): return f"{random.choice(FIRST_NAMES_F)} {random.choice(FIRST_NAMES_M)} {random.choice(LAST_NAMES)}"


def wipe(session):
    """Delete data in FK-safe order. Keep the schema."""
    # LMS
    Answer.query.delete()
    QuizAttempt.query.delete()
    Choice.query.delete()
    Question.query.delete()
    Quiz.query.delete()
    Submission.query.delete()
    CourseAssignment.query.delete()
    Lesson.query.delete()
    Course.query.delete()
    Announcement.query.delete()
    # HR
    Payroll.query.delete()
    Employee.query.delete()
    # Finance
    Payment.query.delete()
    Installment.query.delete()
    InvoiceLine.query.delete()
    Invoice.query.delete()
    FeeType.query.delete()
    JournalLine.query.delete()
    JournalEntry.query.delete()
    Account.query.delete()
    # Results
    GradeEntry.query.delete()
    AssessmentComponent.query.delete()
    PassRule.query.delete()
    # Attendance
    Attendance.query.delete()
    # Schedule
    ScheduleSlot.query.delete()
    Period.query.delete()
    Day.query.delete()
    # Teaching + subjects
    Assignment.query.delete()
    session.execute(db.text("DELETE FROM subject_grades"))
    Subject.query.delete()
    Teacher.query.delete()
    # Students
    Enrollment.query.delete()
    Student.query.delete()
    # Academic
    Section.query.delete()
    Grade.query.delete()
    Term.query.delete()
    AcademicYear.query.delete()
    # Users
    User.query.delete()
    Role.query.delete()
    # School
    School.query.delete()
    session.commit()


def make_user(school_id, role_id, username, full_name, password, email=None, phone=None):
    u = User(
        school_id=school_id, role_id=role_id, username=username,
        full_name=full_name, email=email, phone=phone, is_active=True,
    )
    u.password_hash = bcrypt.generate_password_hash(password).decode("utf-8")
    db.session.add(u); db.session.flush()
    return u


def seed():
    app = create_app()
    with app.app_context():
        print("Wiping existing data...")
        wipe(db.session)

        print("Seeding school...")
        school = School(code="MNS", name="مدرسة منصتي التجريبية النموذجية",
                        phone="+966501234567", address="حي النرجس، الرياض")
        db.session.add(school); db.session.flush()

        # ── Roles ────────────────────────────────────────────────────────
        print("Seeding roles + permissions...")
        FULL_PERMS = {m: ["view","add","edit","delete"] for m in [
            "users","roles","academic_years","terms","grades","sections",
            "students","teachers","schedule","attendance","results",
            "finance","expenses","payroll","portal",
        ]}
        TEACHER_PERMS = {
            "students":["view"], "teachers":["view"],
            "schedule":["view"], "attendance":["view","add","edit"],
            "results":["view","add","edit"], "portal":["view","add","edit"],
        }
        PARENT_PERMS = {"students":["view"], "finance":["view"]}
        STUDENT_PERMS = {"students":["view"]}

        admin_role   = Role(school_id=school.id, name="admin",   name_ar="مدير النظام", is_system=True, permissions=FULL_PERMS)
        teacher_role = Role(school_id=school.id, name="teacher", name_ar="معلم",        is_system=True, permissions=TEACHER_PERMS)
        parent_role  = Role(school_id=school.id, name="parent",  name_ar="ولي أمر",     is_system=True, permissions=PARENT_PERMS)
        student_role = Role(school_id=school.id, name="student", name_ar="طالب",         is_system=True, permissions=STUDENT_PERMS)
        db.session.add_all([admin_role, teacher_role, parent_role, student_role])
        db.session.flush()

        # ── Users (the 4 demo accounts) ──────────────────────────────────
        print("Seeding demo users...")
        u_admin   = make_user(school.id, admin_role.id,   "admin",   "أ. عبدالرحمن التميمي",     "admin12345", "admin@manasety.demo", "+966501000001")
        u_teacher = make_user(school.id, teacher_role.id, "teacher", "أ. فيصل الغامدي",           "teacher12345","teacher@manasety.demo","+966501000002")
        u_parent  = make_user(school.id, parent_role.id,  "parent",  "أ. سعد الشهري",             "parent12345", "parent@manasety.demo","+966501000003")
        u_student = make_user(school.id, student_role.id, "student", "عمر سعد الشهري",            "student12345","student@manasety.demo","+966501000004")

        # extra teachers as users
        extra_teacher_users = []
        for i, tname in enumerate(["أ. سلطان القحطاني","أ. ماجد العتيبي","أ. تركي المطيري","أ. بندر الشمري","أ. سعود العمري","أ. نايف الرشيد","أ. سلمان الحربي"]):
            u = make_user(school.id, teacher_role.id, f"teacher{i+2}", tname, "teacher12345")
            extra_teacher_users.append(u)

        # extra parents (linked to the batch of students below)
        extra_parent_users = []
        for i in range(29):
            u = make_user(school.id, parent_role.id, f"parent{i+2}", f"وليّ أمر رقم {i+2}", "parent12345")
            extra_parent_users.append(u)

        # ── Academic year + terms + grades + sections ───────────────────
        print("Seeding academic structure...")
        year = AcademicYear(school_id=school.id, name="2025-2026",
                            start_date=date(2025,9,1), end_date=date(2026,6,15), status="active")
        db.session.add(year); db.session.flush()
        t1 = Term(school_id=school.id, year_id=year.id, name="الفترة الأولى", order_index=1,
                  start_date=date(2025,9,1), end_date=date(2026,1,20), weight=Decimal("50"))
        t2 = Term(school_id=school.id, year_id=year.id, name="الفترة الثانية", order_index=2,
                  start_date=date(2026,1,25), end_date=date(2026,6,15), weight=Decimal("50"))
        db.session.add_all([t1, t2]); db.session.flush()

        grades = []
        grade_names = [
            ("الأول الابتدائي","ابتدائي",1),("الثاني الابتدائي","ابتدائي",2),
            ("الثالث الابتدائي","ابتدائي",3),("الرابع الابتدائي","ابتدائي",4),
            ("الخامس الابتدائي","ابتدائي",5),("السادس الابتدائي","ابتدائي",6),
            ("الأول المتوسط","متوسط",7),("الثاني المتوسط","متوسط",8),
        ]
        for name, stage, oi in grade_names:
            g = Grade(school_id=school.id, name=name, stage=stage, order_index=oi)
            db.session.add(g); grades.append(g)
        db.session.flush()

        sections = []
        for g in grades:
            for sname in ("أ","ب"):
                s = Section(school_id=school.id, year_id=year.id, grade_id=g.id, name=sname, capacity=25)
                db.session.add(s); sections.append(s)
        db.session.flush()

        # ── Subjects ────────────────────────────────────────────────────
        print("Seeding subjects...")
        subjects = []
        for sname, code, gcodes in [
            ("الرياضيات","MATH", list(range(1,9))),
            ("اللغة العربية","ARB", list(range(1,9))),
            ("اللغة الإنجليزية","ENG", list(range(1,9))),
            ("العلوم","SCI", list(range(1,9))),
            ("الدراسات الاجتماعية","SOC", list(range(4,9))),
            ("التربية الإسلامية","ISL", list(range(1,9))),
            ("الحاسب","CS",  list(range(4,9))),
            ("الفنون","ART", list(range(1,7))),
        ]:
            sub = Subject(school_id=school.id, name=sname, code=code, is_active=True)
            sub.grades = [g for g in grades if g.order_index in gcodes]
            db.session.add(sub); subjects.append(sub)
        db.session.flush()

        # ── Teachers ────────────────────────────────────────────────────
        print("Seeding teachers...")
        teachers = []
        # Linked teacher (u_teacher above)
        t_linked = Teacher(school_id=school.id, user_id=u_teacher.id,
                           full_name=u_teacher.full_name,
                           specialization="الرياضيات — الابتدائي والمتوسط",
                           phone=u_teacher.phone, email=u_teacher.email,
                           hire_date=date(2020,9,1), is_active=True)
        db.session.add(t_linked); teachers.append(t_linked)
        specs = [
            "اللغة العربية","اللغة الإنجليزية","العلوم",
            "الدراسات الاجتماعية","التربية الإسلامية","الحاسب","الفنون",
        ]
        for u, spec in zip(extra_teacher_users, specs):
            t = Teacher(school_id=school.id, user_id=u.id, full_name=u.full_name,
                        specialization=spec, phone=f"+96650{random.randint(1000000,9999999)}",
                        email=u.email, hire_date=date(random.randint(2015,2023), random.randint(1,12), 1),
                        is_active=True)
            db.session.add(t); teachers.append(t)
        db.session.flush()

        # ── Teaching Assignments ────────────────────────────────────────
        print("Seeding teaching assignments...")
        # Map subject index → teacher index (round-robin fallback)
        subj_teacher = {i: teachers[i % len(teachers)] for i in range(len(subjects))}
        for i, sub in enumerate(subjects):
            for sec in sections:
                if sec.grade in sub.grades:
                    a = Assignment(school_id=school.id, year_id=year.id,
                                   section_id=sec.id, subject_id=sub.id,
                                   teacher_id=subj_teacher[i].id, weekly_periods=random.choice([3,4,5]),
                                   is_active=True)
                    db.session.add(a)
        db.session.flush()

        # ── Days + periods ──────────────────────────────────────────────
        print("Seeding schedule shell...")
        days = []
        for oi, n in enumerate(["الأحد","الاثنين","الثلاثاء","الأربعاء","الخميس"], start=1):
            d = Day(school_id=school.id, name=n, order_index=oi, is_active=True)
            db.session.add(d); days.append(d)
        periods = []
        clock = time(8,0)
        for oi in range(1,7):
            end_hh = 8 + oi
            p = Period(school_id=school.id, name=f"الحصة {oi}", order_index=oi,
                       start_time=time(7+oi, 15 if oi%2 else 0),
                       end_time=time(8+oi, 15 if oi%2 else 0))
            db.session.add(p); periods.append(p)
        db.session.flush()

        # ── Sample schedule slots (fill first section of each grade fully) ─
        for sec in sections[::2]:  # every other = section أ
            assigns = Assignment.query.filter_by(school_id=school.id, year_id=year.id, section_id=sec.id, is_active=True).all()
            if not assigns:
                continue
            slot_ptr = 0
            for d in days:
                for p in periods:
                    a = assigns[slot_ptr % len(assigns)]
                    ss = ScheduleSlot(school_id=school.id, year_id=year.id,
                                      section_id=sec.id, day_id=d.id, period_id=p.id,
                                      subject_id=a.subject_id, teacher_id=a.teacher_id)
                    db.session.add(ss)
                    slot_ptr += 1
        db.session.flush()

        # ── Students + parent linkage + enrollments ─────────────────────
        print("Seeding students + enrollments...")
        parents_pool = [u_parent] + extra_parent_users
        students = []
        for i in range(30):
            male = random.random() < 0.55
            fn = name_male() if male else name_female()
            parent_u = parents_pool[i] if i < len(parents_pool) else None
            s = Student(school_id=school.id,
                        permanent_code=f"STU-{2025000+i+1:07d}",
                        full_name=fn,
                        national_id=f"10{random.randint(10000000,99999999)}",
                        dob=date(2025-random.randint(7,15), random.randint(1,12), random.randint(1,28)),
                        gender="male" if male else "female",
                        parent_name=parent_u.full_name if parent_u else "وليّ أمر",
                        parent_phone=f"+96650{random.randint(1000000,9999999)}",
                        parent_email=(parent_u.email if parent_u and parent_u.email else None),
                        parent_user_id=parent_u.id if parent_u else None,
                        mother_name=f"أم {fn.split()[0]}",
                        address=f"حي رقم {random.randint(1,20)}، الرياض")
            db.session.add(s); students.append(s)
        db.session.flush()

        # First student is linked to demo parent/student users
        demo_student = students[0]
        demo_student.parent_user_id = u_parent.id
        demo_student.full_name = u_student.full_name  # sync so student login shows their profile
        # Distribute students across sections
        for i, stu in enumerate(students):
            sec = sections[i % len(sections)]
            enr = Enrollment(school_id=school.id, student_id=stu.id, year_id=year.id,
                             grade_id=sec.grade_id, section_id=sec.id, status="active",
                             enrolled_at=date(2025,9,1))
            db.session.add(enr)
        db.session.flush()

        # ── Pass rule + assessment components ───────────────────────────
        print("Seeding pass rule + assessment components...")
        rule = PassRule(school_id=school.id, year_id=year.id, method="overall_only",
                        subject_pass_threshold=Decimal("50"),
                        overall_pass_threshold=Decimal("60"),
                        allowed_failed_subjects=0)
        db.session.add(rule)

        components = []
        for t in (t1, t2):
            for sub in subjects:
                for cname, mx in [("مشاركة",10),("اختبار قصير",15),("اختبار نصفي",25),("اختبار نهائي",50)]:
                    c = AssessmentComponent(school_id=school.id, term_id=t.id, subject_id=sub.id,
                                            name=cname, max_score=Decimal(mx))
                    db.session.add(c); components.append(c)
        db.session.flush()

        # ── Grade entries for the first section per grade ───────────────
        print("Seeding grade entries...")
        for sec in sections:
            enrolls = Enrollment.query.filter_by(section_id=sec.id, status="active").all()
            for e in enrolls:
                for c in components:
                    if c.term_id == t1.id and c.subject.grades and sec.grade in c.subject.grades:
                        score = Decimal(str(round(float(c.max_score) * (0.6 + random.random() * 0.4), 2)))
                        db.session.add(GradeEntry(school_id=school.id, enrollment_id=e.id,
                                                  component_id=c.id, score=score,
                                                  recorded_by_user_id=u_admin.id))
        db.session.flush()

        # ── Attendance history (30 days) ────────────────────────────────
        print("Seeding attendance history (30 days)...")
        for enrollment in Enrollment.query.filter_by(school_id=school.id, status="active").all():
            for delta in range(30):
                d = date.today() - timedelta(days=delta)
                if d.weekday() in (4,5):  # skip Fri/Sat
                    continue
                r = random.random()
                status = "present" if r < 0.85 else "absent" if r < 0.93 else "late"
                db.session.add(Attendance(school_id=school.id, enrollment_id=enrollment.id,
                                          date=d, status=status,
                                          recorded_by_user_id=u_admin.id))
        db.session.flush()

        # ── Chart of accounts + fee types ───────────────────────────────
        print("Seeding chart of accounts + fee types...")
        def add_acc(code, name, atype):
            a = Account(school_id=school.id, code=code, name=name, type=atype, is_active=True, is_system=(atype in ("asset","revenue")))
            db.session.add(a); db.session.flush()
            return a
        cash    = add_acc("1010","الصندوق النقدي","asset")
        bank    = add_acc("1020","الحساب البنكي","asset")
        ar      = add_acc("1100","ذمم الطلاب (AR)","asset")
        rev_tut = add_acc("4100","إيرادات رسوم التعليم","revenue")
        rev_bk  = add_acc("4200","إيرادات الكتب","revenue")
        rev_bus = add_acc("4300","إيرادات النقل","revenue")
        exp_sal = add_acc("5100","مصروف الرواتب","expense")
        exp_ut  = add_acc("5200","مصروف المرافق","expense")
        exp_mnt = add_acc("5300","مصروف الصيانة","expense")

        ft_tut = FeeType(school_id=school.id, name="رسوم دراسية سنوية", default_amount=Decimal("12000"), installable=True, revenue_account_id=rev_tut.id)
        ft_bk  = FeeType(school_id=school.id, name="رسوم الكتب",         default_amount=Decimal("650"),  installable=False, revenue_account_id=rev_bk.id)
        ft_bus = FeeType(school_id=school.id, name="رسوم النقل",         default_amount=Decimal("2000"), installable=True, revenue_account_id=rev_bus.id)
        db.session.add_all([ft_tut, ft_bk, ft_bus]); db.session.flush()

        # ── Invoices per student ────────────────────────────────────────
        print("Seeding invoices + installments + payments...")
        inv_counter = 0
        for enrollment in Enrollment.query.filter_by(school_id=school.id, status="active").all():
            inv_counter += 1
            number = f"INV-{year.name}-{inv_counter:05d}"
            total = ft_tut.default_amount + ft_bk.default_amount
            inv = Invoice(school_id=school.id, enrollment_id=enrollment.id, number=number,
                          issue_date=date(2025,9,1), due_date=date(2025,10,1),
                          total_amount=total, paid_amount=Decimal(0), status="sent")
            db.session.add(inv); db.session.flush()
            db.session.add(InvoiceLine(invoice_id=inv.id, fee_type_id=ft_tut.id, description=ft_tut.name, amount=ft_tut.default_amount))
            db.session.add(InvoiceLine(invoice_id=inv.id, fee_type_id=ft_bk.id,  description=ft_bk.name,  amount=ft_bk.default_amount))

            # 4 installments
            per = (total / 4).quantize(Decimal("0.01"))
            accum = Decimal(0)
            insts = []
            for i in range(4):
                amt = per if i < 3 else total - accum
                inst = Installment(invoice_id=inv.id, due_date=date(2025,10,1) + timedelta(days=90*i),
                                   amount=amt, paid_amount=Decimal(0), status="pending")
                db.session.add(inst); insts.append(inst)
                accum += amt

            # Auto journal
            post_journal(school_id=school.id, entry_date=inv.issue_date,
                         description=f"فاتورة {number}", reference=number,
                         lines=[(ar.id, total, Decimal(0), "ذمم"),
                                (rev_tut.id, Decimal(0), ft_tut.default_amount, "رسوم دراسية"),
                                (rev_bk.id,  Decimal(0), ft_bk.default_amount, "رسوم كتب")],
                         related_kind="invoice", related_id=inv.id)

            # ~60% of families paid the first 1-3 installments
            paid_count = random.choices([0,1,2,3,4], weights=[10,25,35,20,10])[0]
            paid_amt = Decimal(0)
            for i, inst in enumerate(insts[:paid_count]):
                inst.paid_amount = inst.amount
                inst.status = "paid"
                paid_amt += inst.amount
                pay_date = inst.due_date - timedelta(days=random.randint(0,20))
                je = post_journal(school_id=school.id, entry_date=pay_date,
                                  description=f"دفعة {number}", reference=number,
                                  lines=[(cash.id, inst.amount, Decimal(0), "تحصيل"),
                                         (ar.id, Decimal(0), inst.amount, "خفض ذمم")],
                                  related_kind="payment", related_id=inv.id)
                pmt = Payment(school_id=school.id, invoice_id=inv.id,
                              payment_date=pay_date, amount=inst.amount, method="cash",
                              cash_account_id=cash.id, is_refund=False,
                              journal_entry_id=je.id)
                db.session.add(pmt)
            inv.paid_amount = paid_amt
            inv.status = "paid" if paid_amt >= total else "partial" if paid_amt > 0 else "sent"
        db.session.flush()

        # ── Employees + payroll ─────────────────────────────────────────
        print("Seeding employees + payroll...")
        for t in teachers:
            emp = Employee(school_id=school.id, user_id=t.user_id,
                           full_name=t.full_name, job_title=t.specialization,
                           base_salary=Decimal(random.randint(6000,15000)),
                           phone=t.phone, email=t.email, hire_date=t.hire_date, is_active=True)
            db.session.add(emp); db.session.flush()

            # Last 2 months of payroll
            for m in ((date.today().year, date.today().month - 1), (date.today().year, date.today().month)):
                if m[1] < 1:
                    continue
                base = emp.base_salary
                allow = Decimal(random.randint(0,2000))
                deduct = Decimal(random.randint(0,500))
                net = base + allow - deduct
                pay_date = date(m[0], m[1], 25)
                je = post_journal(school_id=school.id, entry_date=pay_date,
                                  description=f"راتب {emp.full_name} - {m[0]}/{m[1]:02d}",
                                  reference=f"PR-{m[0]}{m[1]:02d}-{emp.id}",
                                  lines=[(exp_sal.id, net, Decimal(0), "راتب"),
                                         (bank.id, Decimal(0), net, "صرف")],
                                  related_kind="payroll", related_id=None)
                db.session.add(Payroll(school_id=school.id, employee_id=emp.id,
                                       period_year=m[0], period_month=m[1],
                                       base_salary=base, allowances=allow, deductions=deduct,
                                       net_pay=net, paid_at=pay_date, journal_entry_id=je.id))
        db.session.flush()

        # ── LMS: 6 courses (one per top subject) ─────────────────────────
        # Ticket #2 — Course now belongs to (year, grade, subject, term);
        # publish it to sections via CourseSection instead of section_id.
        print("Seeding LMS content...")
        first_sec = sections[0]  # الأول الابتدائي — أ
        for i, sub in enumerate(subjects[:6]):
            teacher = subj_teacher[i]
            c = Course(school_id=school.id, academic_year_id=year.id,
                       grade_id=first_sec.grade_id, subject_id=sub.id,
                       title=f"مادة {sub.name}",
                       description=f"مقرر {sub.name} الكامل مع دروس تفاعلية، واجبات، واختبارات.",
                       is_published=True)
            db.session.add(c); db.session.flush()
            db.session.add(CourseSection(
                course_id=c.id, section_id=first_sec.id,
                is_published=True, published_at=datetime.utcnow(),
            ))
            db.session.flush()

            # Lessons
            for lo in range(1, 6):
                lesson = Lesson(course_id=c.id, order_index=lo,
                                title=f"الدرس {lo}: {sub.name} — الوحدة {lo}",
                                kind=random.choice(["text","video","pdf","link"]),
                                body="محتوى تعليمي غني بالنقاط الأساسية والتمارين التطبيقية.",
                                media_url="https://www.youtube.com/embed/dQw4w9WgXcQ" if lo % 2 else "",
                                duration_minutes=random.choice([10,15,20,25]),
                                is_published=True)
                db.session.add(lesson)

            # Assignments
            for lo in range(1, 3):
                a = CourseAssignment(course_id=c.id,
                                     title=f"واجب الوحدة {lo} — {sub.name}",
                                     instructions=f"حل التمارين المرفقة وسلّم قبل الموعد.",
                                     max_score=Decimal(100),
                                     due_at=datetime.utcnow() + timedelta(days=lo*3),
                                     allow_late=True, is_published=True)
                db.session.add(a)

            # Quiz with mixed question types
            q = Quiz(course_id=c.id, title=f"اختبار نهائي — {sub.name}",
                     description="اختبار متنوّع الأنواع", duration_minutes=20,
                     opens_at=datetime.utcnow() - timedelta(days=1),
                     closes_at=datetime.utcnow() + timedelta(days=14),
                     max_attempts=2, is_published=True)
            db.session.add(q); db.session.flush()

            for qi, (kind, prompt, points) in enumerate([
                ("mcq", "ما هي العاصمة الرسمية للمملكة العربية السعودية؟", Decimal("2")),
                ("tf",  "الأرض كوكب من كواكب المجموعة الشمسية.", Decimal("2")),
                ("short","اذكر عدد أيام الأسبوع.", Decimal("2")),
                ("essay","اكتب فقرة قصيرة عن أهمية العلم.", Decimal("4")),
            ]):
                qq = Question(quiz_id=q.id, order_index=qi+1, kind=kind,
                              prompt=prompt, points=points,
                              correct_short="سبعة" if kind == "short" else "")
                db.session.add(qq); db.session.flush()
                if kind == "mcq":
                    for co, (label, ok) in enumerate([("الرياض", True), ("جدة", False), ("مكة المكرمة", False)]):
                        db.session.add(Choice(question_id=qq.id, order_index=co+1, label=label, is_correct=ok))
                elif kind == "tf":
                    for co, (label, ok) in enumerate([("صح", True), ("خطأ", False)]):
                        db.session.add(Choice(question_id=qq.id, order_index=co+1, label=label, is_correct=ok))
        db.session.flush()

        # ── Announcements ───────────────────────────────────────────────
        print("Seeding announcements...")
        anns = [
            ("أهلاً بكم في العام الدراسي 2025-2026","نرحّب بكم في مدرسة منصتي — لنجعل هذا العام مميزاً.", True),
            ("موعد اجتماع أولياء الأمور","سيُعقد اجتماع أولياء الأمور يوم الخميس القادم بعد صلاة العصر.", True),
            ("رحلة مدرسية تعليمية","رحلة قادمة إلى معرض الرياضيات المتقدمة، رسوم اختيارية 150 ر.س.", False),
            ("جدول الاختبارات الشهرية","اطلعوا على جدول الاختبارات المرفق في بوابة ولي الأمر.", False),
            ("نتائج مسابقة القراءة","تهنئة للفائزين في مسابقة القراءة السنوية — سلطان وسارة.", False),
            ("تحديث بيانات الطلاب","الرجاء تحديث بيانات الاتصال في ملف الطالب قبل نهاية الأسبوع.", False),
            ("ورشة الذكاء الاصطناعي","ورشة تعليمية تفاعلية عن أساسيات الذكاء الاصطناعي، اختيارية للصف السادس فأعلى.", False),
            ("إعلان تشغيل بوابة منصتي الإلكترونية","تم تفعيل بوابة أولياء الأمور — للاطلاع اليومي على الحضور والدرجات.", False),
        ]
        for i, (title, body, pinned) in enumerate(anns):
            db.session.add(Announcement(school_id=school.id,
                                        section_id=None,
                                        author_id=u_admin.id,
                                        title=title, body=body, is_pinned=pinned,
                                        created_at=datetime.utcnow() - timedelta(days=i)))
        db.session.commit()

        # ── Summary ─────────────────────────────────────────────────────
        print("\n" + "="*60)
        print("✅ Demo data seeded successfully")
        print("="*60)
        print(f"  School:      {school.name}")
        print(f"  Year:        {year.name}")
        print(f"  Terms:       2")
        print(f"  Grades:      {len(grades)}")
        print(f"  Sections:    {len(sections)}")
        print(f"  Subjects:    {len(subjects)}")
        print(f"  Teachers:    {len(teachers)}")
        print(f"  Students:    {len(students)}")
        print(f"  Enrollments: {Enrollment.query.count()}")
        print(f"  Attendance:  {Attendance.query.count()} records")
        print(f"  GradeEntry:  {GradeEntry.query.count()} rows")
        print(f"  Invoices:    {Invoice.query.count()}")
        print(f"  Payments:    {Payment.query.count()}")
        print(f"  Payrolls:    {Payroll.query.count()}")
        print(f"  Courses:     {Course.query.count()}")
        print(f"  Lessons:     {Lesson.query.count()}")
        print(f"  Assignments: {CourseAssignment.query.count()}")
        print(f"  Quizzes:     {Quiz.query.count()}")
        print(f"  Questions:   {Question.query.count()}")
        print(f"  Announcements: {Announcement.query.count()}")
        print("\n🔑 Demo accounts (all at http://127.0.0.1:5050):")
        print(f"   admin   / admin12345    (مدير النظام)")
        print(f"   teacher / teacher12345  (معلم — {u_teacher.full_name})")
        print(f"   parent  / parent12345   (ولي أمر — ابنه: {demo_student.full_name})")
        print(f"   student / student12345  (طالب — {demo_student.full_name})")
        print("="*60)


if __name__ == "__main__":
    seed()
