"""SAAS-041 — the two test schools (test-a / test-b) for isolation tests
and UAT, built through the app's own services.

- Only ever touches the schools it created itself: their ids are kept in
  platform_settings["test_seed_school_ids"]. A school that merely has a
  test slug but wasn't made here is refused, never overwritten.
- Every name carries the school's tag ("TA" / "TB") so a leak shows at a
  glance on screen.
- Known accounts: admin / teacher1 / student1 / parent1 per school, with
  passwords generated on each run (never in code), printed once and
  written to one file outside git.
- After building: integrity checks (balanced books, tenant integrity,
  scores within max, invoices not over-paid, nothing shared between A
  and B).
"""
from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from ..extensions import db

TEST_SLUGS = ("test-a", "test-b")
TAGS = {"test-a": "TA", "test-b": "TB"}
NAMES = {"test-a": "مدرسة الاختبار أ", "test-b": "مدرسة الاختبار ب"}
SETTING_KEY = "test_seed_school_ids"

FIRST = ["أحمد", "محمد", "يوسف", "عمر", "مريم", "سارة", "ليلى", "نور", "خالد", "حبيبة",
         "آدم", "فاطمة", "علي", "جنى", "حمزة", "ملك", "زياد", "هنا", "مازن", "رقية"]
LAST = ["حسن", "إبراهيم", "سالم", "عبد الله", "منصور", "السيد", "فؤاد", "رشدي", "نبيل", "شاكر"]
SUBJECTS = ["الرياضيات", "اللغة العربية", "العلوم", "اللغة الإنجليزية", "الدراسات الاجتماعية"]


class SeedRefused(RuntimeError):
    pass


@dataclass(frozen=True)
class Size:
    grades: int
    sections_per_grade: int
    subjects: int
    students: int            # per school
    teachers: int
    attendance_days: int
    bank_questions: int
    employees: int

    @classmethod
    def full(cls, students: int | None = None) -> "Size":
        return cls(grades=3, sections_per_grade=2, subjects=5, students=students or 40, teachers=6,
                   attendance_days=20, bank_questions=20, employees=4)

    @classmethod
    def small(cls, students: int | None = None) -> "Size":
        return cls(grades=1, sections_per_grade=2, subjects=3, students=students or 8, teachers=2,
                   attendance_days=5, bank_questions=4, employees=1)


@dataclass
class Built:
    slug: str
    school_id: int
    url: str
    accounts: dict = field(default_factory=dict)      # role -> (username, password)
    counts: dict = field(default_factory=dict)


# ─── bookkeeping of what this tool owns ─────────────────────────────

def owned_ids() -> list[int]:
    from ..models import PlatformSetting
    row = db.session.get(PlatformSetting, SETTING_KEY)
    try:
        return [int(x) for x in json.loads(row.value or "[]")] if row else []
    except (ValueError, TypeError):
        return []


def _remember(ids: list[int]) -> None:
    from ..models import PlatformSetting
    row = db.session.get(PlatformSetting, SETTING_KEY) or PlatformSetting(key=SETTING_KEY)
    row.value = json.dumps(sorted(set(ids)))
    db.session.add(row)


def existing() -> dict[str, object]:
    """{slug: School} for the test slugs present, with ownership checked."""
    from ..models import School
    out = {}
    mine = set(owned_ids())
    for s in School.query.filter(School.slug.in_(TEST_SLUGS)).all():
        if s.id not in mine:
            raise SeedRefused(f"school {s.slug!r} (#{s.id}) exists but was not created by "
                              "seed-test-schools - refusing to touch it")
        out[s.slug] = s
    return out


# ─── build ──────────────────────────────────────────────────────────

def _pw() -> str:
    return secrets.token_urlsafe(9)          # ~12 chars, random per run


def build_school(slug: str, size: Size, *, today: date | None = None) -> Built:
    from ..models import School
    from . import provisioning as prov
    from .subscriptions import internal_plan
    from .tenancy import tenant_context
    tag, today = TAGS[slug], today or date.today()
    spec = prov.ProvisionSpec(name=NAMES[slug], slug=slug, admin_full_name=f"{tag} مدير المدرسة",
                              plan_id=internal_plan().id, starts_on=today - timedelta(days=60),
                              months=24, email=f"{slug}@manasety.test", invoice_prefix=f"{tag}-INV")
    res = prov.provision_school(spec, None)          # commits
    _remember(owned_ids() + [res.school_id])         # ours from now on: a failure can be reset
    db.session.commit()
    school = db.session.get(School, res.school_id)
    school.notify_channels = "in_app"               # SAAS-043: test schools never reach anyone
    db.session.commit()
    built = Built(slug=slug, school_id=school.id, url=res.url)
    try:
        with tenant_context(school.id):
            _fill(school, tag, size, today, built)
        db.session.commit()
    except Exception:
        db.session.rollback()
        teardown([res.school_id])                   # never leave a half-built school
        raise
    return built


def _fill(school, tag, size: Size, today: date, built: Built) -> None:
    from ..models import (AcademicYear, Enrollment, Grade, Role, Section, Student, Subject,
                          Teacher, Term, User)
    from ..models.teacher import Assignment
    from .student_codes import next_permanent_code
    sid = school.id
    roles = {r.name: r for r in Role.query.filter_by(school_id=sid)}

    # admin: known password (the provisioning link stays valid too)
    admin = User.query.filter_by(school_id=sid, username="admin").one()
    pw = _pw()
    admin.set_password(pw)
    built.accounts["admin"] = ("admin", pw)

    year_start = date(today.year if today.month >= 9 else today.year - 1, 9, 1)
    year = AcademicYear(school_id=sid, name=f"{tag} {year_start.year}/{year_start.year + 1}",
                        start_date=year_start, end_date=date(year_start.year + 1, 6, 30), status="active")
    db.session.add(year)
    db.session.flush()
    terms = []
    for i, (s, e) in enumerate(((year_start, date(year_start.year + 1, 1, 31)),
                                (date(year_start.year + 1, 2, 1), date(year_start.year + 1, 6, 30))), 1):
        t = Term(school_id=sid, year_id=year.id, name=f"{tag} الفصل {i}", order_index=i,
                 start_date=s, end_date=e, weight=50)
        db.session.add(t)
        terms.append(t)
    db.session.flush()

    grades, sections = [], []
    for g in range(1, size.grades + 1):
        grade = Grade(school_id=sid, name=f"{tag} الصف {g}", order_index=g)
        db.session.add(grade)
        db.session.flush()
        grades.append(grade)
        for k in range(size.sections_per_grade):
            sec = Section(school_id=sid, year_id=year.id, grade_id=grade.id,
                          name=f"{tag}-{g}{'أبجد'[k]}", capacity=30)
            db.session.add(sec)
            sections.append(sec)
    db.session.flush()

    subjects = []
    for name in SUBJECTS[:size.subjects]:
        sub = Subject(school_id=sid, name=f"{tag} {name}")
        for g in grades:
            sub.grades.append(g)
        db.session.add(sub)
        subjects.append(sub)
    db.session.flush()

    # teachers (teacher1 has the known login)
    teachers = []
    for i in range(1, size.teachers + 1):
        uname, upw = f"teacher{i}", _pw()
        u = User(school_id=sid, role_id=roles["teacher"].id, username=uname,
                 full_name=f"{tag} المعلم {i}", email=f"{uname}@{school.slug}.manasety.test", is_active=True)
        u.set_password(upw)
        db.session.add(u)
        db.session.flush()
        sub = subjects[(i - 1) % len(subjects)]
        t = Teacher(school_id=sid, user_id=u.id, full_name=u.full_name, specialization=sub.name)
        t.subjects.append(sub)
        db.session.add(t)
        teachers.append(t)
        if i == 1:
            built.accounts["teacher"] = (uname, upw)
    db.session.flush()
    for sec in sections:
        for j, sub in enumerate(subjects):
            db.session.add(Assignment(school_id=sid, year_id=year.id, section_id=sec.id, subject_id=sub.id,
                                      teacher_id=teachers[j % len(teachers)].id, is_active=True))
    db.session.flush()

    # students + guardians (student1 / parent1 have the known logins)
    students, enrollments = [], []
    for i in range(1, size.students + 1):
        sec = sections[(i - 1) % len(sections)]
        first, last = FIRST[(i - 1) % len(FIRST)], LAST[(i - 1) % len(LAST)]
        full = f"{tag} {first} {last} {i:02d}"
        su = User(school_id=sid, role_id=roles["student"].id, username=f"student{i}", full_name=full,
                  is_active=True)
        spw = _pw()
        su.set_password(spw)
        pu = User(school_id=sid, role_id=roles["parent"].id, username=f"parent{i}",
                  full_name=f"{tag} ولي أمر {first} {last}", phone=f"0100{school.id:02d}{i:05d}"[:11],
                  is_active=True)
        ppw = _pw()
        pu.set_password(ppw)
        db.session.add_all([su, pu])
        db.session.flush()
        st = Student(school_id=sid, permanent_code=next_permanent_code(school_id=sid), full_name=full,
                     user_id=su.id, parent_user_id=pu.id)
        db.session.add(st)
        db.session.flush()
        _guardian(sid, st, pu)
        enr = Enrollment(school_id=sid, student_id=st.id, year_id=year.id, grade_id=sec.grade_id,
                         section_id=sec.id, status="active", enrolled_at=year_start)
        db.session.add(enr)
        students.append(st)
        enrollments.append(enr)
        if i == 1:
            built.accounts["student"] = (su.username, spw)
            built.accounts["parent"] = (pu.username, ppw)
    db.session.flush()

    # Commit per stage: tenant_guard checks parents on its own connection,
    # so later stages need earlier rows committed (a failure is torn down
    # by build_school anyway).
    db.session.commit()
    for stage in (lambda: _lms(sid, tag, year, grades, sections, subjects, size),
                  lambda: _attendance(sid, enrollments, size, today),
                  lambda: _grades(sid, tag, terms[0], subjects, enrollments),
                  lambda: _finance(school, tag, year, enrollments, today),
                  lambda: _hr(sid, tag, size, today)):
        stage()
        db.session.commit()
    built.counts = {"grades": len(grades), "sections": len(sections), "subjects": len(subjects),
                    "teachers": len(teachers), "students": len(students)}


def _guardian(sid, student, parent_user) -> None:
    from ..models import Guardian, StudentGuardian
    g = Guardian(school_id=sid, full_name=parent_user.full_name, phone=parent_user.phone,
                 user_id=parent_user.id)
    db.session.add(g)
    db.session.flush()
    db.session.add(StudentGuardian(student_id=student.id, guardian_id=g.id, relationship="father",
                                   is_primary=True))


def _lms(sid, tag, year, grades, sections, subjects, size: Size) -> None:
    from ..models.lms import (AssignmentQuestion, BankChoice, BankQuestion, Choice, Course,
                              CourseAssignment, CourseSection, Lesson, Question, Quiz, Unit)
    for grade in grades:
        for sub in subjects:
            c = Course(school_id=sid, academic_year_id=year.id, grade_id=grade.id, subject_id=sub.id,
                       title=f"{sub.name} — {grade.name}", is_published=True)
            db.session.add(c)
            db.session.flush()
            for sec in (s for s in sections if s.grade_id == grade.id):
                db.session.add(CourseSection(course_id=c.id, section_id=sec.id, is_published=True))
            for u in range(1, 3):
                unit = Unit(course_id=c.id, title=f"{tag} الوحدة {u}")
                db.session.add(unit)
                db.session.flush()
                for le in range(1, 3):
                    db.session.add(Lesson(course_id=c.id, unit_id=unit.id, title=f"{tag} درس {u}.{le}",
                                          kind="text", body=f"محتوى {tag} للدرس {u}.{le} في {c.title}."))
            q = Quiz(course_id=c.id, title=f"{tag} اختبار قصير — {sub.name}", is_published=True)
            db.session.add(q)
            db.session.flush()
            for n in range(1, 4):
                qu = Question(quiz_id=q.id, order_index=n, kind="mcq", prompt=f"{tag} سؤال {n}: ٢ + {n} = ؟",
                              points=1)
                db.session.add(qu)
                db.session.flush()
                for k, ans in enumerate((2 + n, 1 + n, 3 + n)):
                    db.session.add(Choice(question_id=qu.id, order_index=k, label=str(ans), is_correct=k == 0))
            a = CourseAssignment(course_id=c.id, title=f"{tag} واجب — {sub.name}", is_published=True,
                                 max_score=10)
            db.session.add(a)
            db.session.flush()
            db.session.add(AssignmentQuestion(assignment_id=a.id, prompt=f"{tag} اكتب فقرة قصيرة عن {sub.name}."))
    for n in range(1, size.bank_questions + 1):
        bq = BankQuestion(school_id=sid, prompt=f"{tag} سؤال بنك رقم {n}")
        db.session.add(bq)
        db.session.flush()
        for k in range(3):
            db.session.add(BankChoice(question_id=bq.id, label=f"{tag} اختيار {k + 1}", is_correct=k == 0))
    db.session.flush()


def _attendance(sid, enrollments, size: Size, today: date) -> None:
    from ..models import Attendance
    days, d = [], today
    while len(days) < size.attendance_days:
        d -= timedelta(days=1)
        if d.weekday() not in (4, 5):          # Friday / Saturday off
            days.append(d)
    statuses = ["present"] * 8 + ["absent", "late"]
    for i, enr in enumerate(enrollments):
        for j, day in enumerate(days):
            db.session.add(Attendance(school_id=sid, enrollment_id=enr.id, date=day,
                                      status=statuses[(i + j) % len(statuses)]))
    db.session.flush()


def _grades(sid, tag, term, subjects, enrollments) -> None:
    from ..models import AssessmentComponent, GradeEntry
    for sub in subjects:
        comps = [AssessmentComponent(school_id=sid, term_id=term.id, subject_id=sub.id,
                                     name=f"{tag} {n}", max_score=m)
                 for n, m in (("أعمال السنة", 20), ("اختبار الفصل", 80))]
        db.session.add_all(comps)
        db.session.flush()
        for i, enr in enumerate(enrollments):
            for c in comps:
                score = (Decimal(c.max_score) * Decimal(55 + (i * 7) % 45) / 100).quantize(Decimal("0.5"))
                db.session.add(GradeEntry(school_id=sid, enrollment_id=enr.id, component_id=c.id,
                                          score=min(score, Decimal(c.max_score))))
    db.session.flush()


def _finance(school, tag, year, enrollments, today: date) -> None:
    from ..models import FeeType, PaymentMethod
    from . import ledger, vouchers
    from .system_codes import get_account_by_code
    sid = school.id
    revenue = get_account_by_code(sid, "4110")
    fee = FeeType(school_id=sid, name=f"{tag} رسوم دراسية", revenue_account_id=revenue.id,
                  default_amount=Decimal("12000"))
    bus = FeeType(school_id=sid, name=f"{tag} رسوم أتوبيس", revenue_account_id=revenue.id,
                  default_amount=Decimal("3000"))
    db.session.add_all([fee, bus])
    # committed: create_invoice rolls the session back on a number clash
    # and retries — uncommitted rows of ours would vanish with it
    db.session.commit()
    method = PaymentMethod.query.filter_by(school_id=sid, is_active=True).first()
    issue = today - timedelta(days=45)
    for i, enr in enumerate(enrollments):
        lines = [(fee.id, Decimal("12000"))] + ([(bus.id, Decimal("3000"))] if i % 3 == 0 else [])
        inv = ledger.create_invoice(school_id=sid, enrollment_id=enr.id, year_name=year.name,
                                    fee_lines=lines, issue_date=issue, due_date=issue + timedelta(days=30),
                                    installments_count=2)   # the year name carries the tag
        ledger.post_invoice_to_ledger(inv, entry_date=issue)
        # a mix: fully paid, half paid, unpaid
        part = (Decimal(inv.total_amount) if i % 3 == 0 else (Decimal(inv.total_amount) / 2).quantize(Decimal("0.01"))
                if i % 3 == 1 else None)
        if part:
            p = ledger.record_payment(inv, part, method.id if method else None,
                                      payment_date=issue + timedelta(days=10), reference=f"{tag}-PAY-{i + 1:03d}")
            vouchers.auto_create_for_payment(p)
        db.session.commit()


def _hr(sid, tag, size: Size, today: date) -> None:
    from ..models import Employee, Payroll
    from . import ledger
    from .system_codes import get_account_by_code
    salary = get_account_by_code(sid, "5110")
    month = (today.replace(day=1) - timedelta(days=1))
    for i in range(1, size.employees + 1):
        e = Employee(school_id=sid, full_name=f"{tag} الموظف {i}", job_title="إداري",
                     base_salary=Decimal(6000 + 500 * i), hire_date=today - timedelta(days=400))
        db.session.add(e)
        db.session.flush()
        p = Payroll(school_id=sid, employee_id=e.id, period_year=month.year, period_month=month.month,
                    base_salary=e.base_salary, allowances=0, deductions=0, net_pay=e.base_salary)
        db.session.add(p)
        db.session.flush()
        je = ledger.post_payroll_accrual(p, salary, entry_date=month)
        if hasattr(p, "journal_entry_id") and je is not None:
            p.journal_entry_id = je.id
    db.session.flush()


# ─── checks ─────────────────────────────────────────────────────────

def integrity(school_ids: list[int]) -> list[str]:
    """[] = clean. Books balanced, tenant integrity, sane values, and
    nothing shared between the test schools."""
    from sqlalchemy import func
    from ..models import AssessmentComponent, GradeEntry, Invoice, JournalEntry, JournalLine, Student, User
    from .tenant_guard import integrity_report
    problems = []
    for sid in school_ids:
        dr, cr = (db.session.query(func.coalesce(func.sum(JournalLine.debit), 0),
                                   func.coalesce(func.sum(JournalLine.credit), 0))
                  .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
                  .filter(JournalEntry.school_id == sid).one())
        if Decimal(dr) != Decimal(cr):
            problems.append(f"school {sid}: books not balanced (DR {dr} / CR {cr})")
        unbalanced = (db.session.query(JournalLine.entry_id)
                      .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
                      .filter(JournalEntry.school_id == sid).group_by(JournalLine.entry_id)
                      .having(func.sum(JournalLine.debit) != func.sum(JournalLine.credit)).count())
        if unbalanced:
            problems.append(f"school {sid}: {unbalanced} unbalanced journal entries")
        over = (db.session.query(GradeEntry.id)
                .join(AssessmentComponent, AssessmentComponent.id == GradeEntry.component_id)
                .filter(GradeEntry.school_id == sid,
                        (GradeEntry.score > AssessmentComponent.max_score) | (GradeEntry.score < 0)).count())
        if over:
            problems.append(f"school {sid}: {over} scores outside 0..max")
        overpaid = Invoice.query.filter(Invoice.school_id == sid, Invoice.paid_amount > Invoice.total_amount).count()
        if overpaid:
            problems.append(f"school {sid}: {overpaid} invoices paid above their total")
    bad = {edge: n for edge, n in integrity_report().items() if n}
    if bad:
        problems.append(f"tenant integrity: {bad}")
    if len(school_ids) == 2:
        a, b = school_ids
        shared = (db.session.query(Student.id).filter(Student.school_id == a)
                  .filter(Student.user_id.in_(db.session.query(User.id).filter(User.school_id == b))).count())
        if shared:
            problems.append(f"{shared} students of school {a} point at users of school {b}")
    return problems


# ─── teardown ───────────────────────────────────────────────────────

def teardown(ids: list[int] | None = None) -> list[int]:
    """Delete the schools this tool created (and only those), every row
    they own, and their platform audit rows (test data — through the
    sanctioned audit_prune path, recorded in a new audit row)."""
    from ..models import PlatformAuditLog, PlatformJob, School
    from .platform_auth import audit
    from .platform_security import audit_prune
    mine = set(owned_ids())
    ids = [i for i in (ids if ids is not None else sorted(mine)) if i in mine]
    if not ids:
        return []
    for s in School.query.filter(School.id.in_(ids)).all():
        if s.slug not in TEST_SLUGS:
            raise SeedRefused(f"#{s.id} {s.slug!r} is not a test slug - refusing")
    db.session.commit()
    with audit_prune(db.session.connection()):
        PlatformAuditLog.query.filter(PlatformAuditLog.target_school_id.in_(ids)).delete(
            synchronize_session=False)
    PlatformJob.query.filter(PlatformJob.school_id.in_(ids)).delete(synchronize_session=False)
    db.session.commit()
    purge_rows(ids)
    _remember([i for i in mine if i not in ids])
    audit("test_schools_teardown", None, school_ids=ids)
    db.session.commit()
    return ids


def purge_rows(school_ids) -> None:
    """Delete every row owned by `school_ids`, children first (owned = a
    school_id in the set, or — transitively — an FK to an owned row), then
    the schools. Raw connection: soft-delete filters and ORM listeners
    don't interfere. Same walk as tests/world.purge_schools."""
    from sqlalchemy import select
    from .platform_security import audit_prune
    ids = list(school_ids)
    if not ids:
        return

    def chunks(values, n=500):
        values = list(values)
        for i in range(0, len(values), n):
            yield values[i:i + n]

    md = db.metadata
    tables = [t for t in md.sorted_tables if t.name != "schools"]
    doomed: dict[str, set] = {}
    with db.engine.begin() as conn, audit_prune(conn):
        for t in tables:
            if "school_id" in t.c and "id" in t.c:
                doomed[t.name] = {r[0] for r in conn.execute(select(t.c.id).where(t.c.school_id.in_(ids)))}
        changed = True
        while changed:
            changed = False
            for t in tables:
                if "id" not in t.c:
                    continue
                for fk in t.foreign_keys:
                    parent_ids = doomed.get(fk.column.table.name)
                    if not parent_ids:
                        continue
                    found = set()
                    for part in chunks(parent_ids):
                        found |= {r[0] for r in conn.execute(select(t.c.id).where(fk.parent.in_(part)))}
                    new = found - doomed.get(t.name, set())
                    if new:
                        doomed.setdefault(t.name, set()).update(new)
                        changed = True
        for t in reversed(tables):
            if "id" in t.c and doomed.get(t.name):
                for part in chunks(doomed[t.name]):
                    conn.execute(t.delete().where(t.c.id.in_(part)))
            elif "id" not in t.c:
                for fk in t.foreign_keys:
                    for part in chunks(doomed.get(fk.column.table.name, ())):
                        conn.execute(t.delete().where(fk.parent.in_(part)))
            if "school_id" in t.c:
                conn.execute(t.delete().where(t.c.school_id.in_(ids)))
        schools = md.tables["schools"]
        conn.execute(schools.delete().where(schools.c.id.in_(ids)))
