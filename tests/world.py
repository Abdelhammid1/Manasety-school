"""Seed data for the isolation matrix beyond the two_schools basics,
plus a teardown purge that removes every row two test schools own.

Each seeder returns plain ids (never ORM objects) and extra marker
strings unique to the school, so a sweep can grep responses for them.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal


def seed_finance_hr(bundle: dict) -> dict:
    """Finance + HR records for one school. Must run in an app context."""
    from app.extensions import db
    from app.models import (
        Account, BankStatementLine, Budget, CostCenter, DiscountType, Guardian, StudentGuardian,
        Employee, Expense, FeeType, Invoice, InvoiceLine, JournalEntry,
        JournalLine, LeaveRequest, PaymentMethod, Payroll,
        RecurringFeeSchedule, RefundRequest, StudentDiscount, Vendor,
    )

    slug = bundle["school"].slug
    sid = bundle["school"].id
    add = db.session.add

    def acc(code, name, typ, role=None):
        a = Account(school_id=sid, code=code, name=f"{name}-{slug}", type=typ,
                    is_postable=True, account_role=role)
        add(a)
        return a

    cash = acc("1101", "Cash", "asset", "cash_default")
    ar = acc("1201", "AR", "asset", "ar_default")
    bank = acc("1102", "Bank", "asset")
    revenue = acc("4101", "Revenue", "revenue")
    expense_acc = acc("5101", "Expense", "expense")
    acc("1170", "Petty", "asset")
    db.session.flush()

    cc = CostCenter(school_id=sid, name=f"CC-{slug}")
    ft = FeeType(school_id=sid, name=f"Fee-{slug}", revenue_account_id=revenue.id,
                 default_amount=Decimal("100"))
    pm = PaymentMethod(school_id=sid, name=f"PM-{slug}", account_id=cash.id)
    vendor = Vendor(school_id=sid, name=f"Vendor-{slug}")
    dt = DiscountType(school_id=sid, name=f"Disc-{slug}", calc_method="percent",
                      value=Decimal("10"))
    emp = Employee(school_id=sid, full_name=f"Emp-{slug}", job_title="Clerk",
                   base_salary=Decimal("5000"))
    for o in (cc, ft, pm, vendor, dt, emp):
        add(o)
    db.session.flush()

    inv = Invoice(school_id=sid, enrollment_id=bundle["enrollment"].id,
                  number=f"INV-{slug}", issue_date=date(2026, 9, 1),
                  due_date=date(2026, 10, 1), status="unpaid",
                  total_amount=Decimal("100"), paid_amount=Decimal("0"))
    add(inv)
    db.session.flush()
    add(InvoiceLine(invoice_id=inv.id, fee_type_id=ft.id, amount=Decimal("100")))

    je = JournalEntry(school_id=sid, entry_date=date(2026, 9, 1),
                      description=f"JE-{slug}")
    add(je)
    db.session.flush()
    jl = JournalLine(entry_id=je.id, account_id=cash.id, debit=Decimal("100"),
                     credit=Decimal("0"))
    add(jl)
    add(JournalLine(entry_id=je.id, account_id=revenue.id, debit=Decimal("0"),
                    credit=Decimal("100")))

    exp = Expense(school_id=sid, vendor_id=vendor.id, expense_account_id=expense_acc.id,
                  cash_account_id=cash.id, date=date(2026, 9, 2),
                  amount=Decimal("50"), description=f"Exp-{slug}",
                  approval_status="pending")
    bsl = BankStatementLine(school_id=sid, bank_account_id=bank.id,
                            statement_date=date(2026, 9, 3), amount=Decimal("100"),
                            description=f"BSL-{slug}")
    budget = Budget(school_id=sid, year_id=bundle["year"].id, account_id=expense_acc.id,
                    planned_amount=Decimal("1000"), note=f"Budget-{slug}")
    rec = RecurringFeeSchedule(school_id=sid, fee_type_id=ft.id, frequency="monthly")
    sd = StudentDiscount(school_id=sid, enrollment_id=bundle["enrollment"].id,
                         discount_type_id=dt.id, status="pending")
    rr = RefundRequest(school_id=sid, invoice_id=inv.id, amount=Decimal("10"),
                       requested_by_user_id=bundle["users"]["admin"].id,
                       status="pending", reason=f"Refund-{slug}")
    leave = LeaveRequest(school_id=sid, employee_id=emp.id, leave_type="annual",
                         start_date=date(2026, 9, 10), end_date=date(2026, 9, 11),
                         days_count=2, status="pending")
    payroll = Payroll(school_id=sid, employee_id=emp.id, period_year=2026,
                      period_month=9, base_salary=Decimal("5000"),
                      net_pay=Decimal("5000"))
    guardian = Guardian(school_id=sid, full_name=f"Guardian-{slug}", phone=f"0101{sid:07d}")
    for o in (exp, bsl, budget, rec, sd, rr, leave, payroll, guardian):
        add(o)
    db.session.flush()
    add(StudentGuardian(student_id=bundle["student"].id, guardian_id=guardian.id,
                        relationship="father", is_primary=True))
    db.session.commit()

    return {
        "account": cash.id, "bank_account": bank.id, "cost_center": cc.id,
        "fee_type": ft.id, "payment_method": pm.id, "vendor": vendor.id,
        "discount_type": dt.id, "employee": emp.id, "invoice": inv.id,
        "journal_entry": je.id, "journal_line": jl.id, "expense": exp.id,
        "bank_line": bsl.id, "budget": budget.id, "recurring": rec.id,
        "student_discount": sd.id, "refund_request": rr.id,
        "leave_request": leave.id, "payroll": payroll.id,
        "revenue_account": revenue.id, "guardian": guardian.id,
        "markers": (
            f"Vendor-{slug}", f"Emp-{slug}", f"INV-{slug}", f"Fee-{slug}",
            f"PM-{slug}", f"CC-{slug}", f"Disc-{slug}", f"BSL-{slug}",
            f"Exp-{slug}", f"JE-{slug}", f"Budget-{slug}", f"Refund-{slug}",
            f"Cash-{slug}", f"Bank-{slug}", f"Revenue-{slug}", f"Expense-{slug}",
            f"Guardian-{slug}",
        ),
    }


def seed_students(bundle: dict) -> dict:
    """Students / attendance / portal records for one school (SAAS-014).
    Run after seed_finance_hr (reuses its guardian). App context."""
    from app.extensions import db
    from app.models import (
        Attendance, AttendanceRule, AttendanceRuleTriggered, BehaviorCategory,
        BehaviorIncident, Guardian, HealthIncident, PickupCall, PreviousSchool,
        StudentDocument, StudentGuardian, StudentHealthProfile, StudentNote, StudentTag,
    )
    slug, sid = bundle["school"].slug, bundle["school"].id
    stu, enr = bundle["student"], bundle["enrollment"]       # detached: read ids only
    add = db.session.add
    guardian = Guardian.query.filter_by(school_id=sid, full_name=f"Guardian-{slug}").one()
    guardian.user_id = bundle["users"]["parent"].id          # a portal account
    link = StudentGuardian.query.filter_by(student_id=stu.id, guardian_id=guardian.id).one()
    note = StudentNote(school_id=sid, student_id=stu.id, body=f"Note-{slug}")
    tag = StudentTag(school_id=sid, name=f"Tag-{slug}")
    prev = PreviousSchool(school_id=sid, student_id=stu.id, name=f"Prev-{slug}")
    health = StudentHealthProfile(school_id=sid, student_id=stu.id)
    inc = HealthIncident(school_id=sid, student_id=stu.id, incident_date=date(2026, 9, 4),
                         description=f"Health-{slug}")
    doc = StudentDocument(school_id=sid, student_id=stu.id, document_type="birth_certificate",
                          file_path=f"/files/{sid}/student_doc/{stu.id}/doc-{slug}.pdf")
    cat = BehaviorCategory(school_id=sid, name=f"BehCat-{slug}")
    rule = AttendanceRule(school_id=sid, name=f"Rule-{slug}", kind="absence_count", threshold=3)
    for o in (note, tag, prev, health, inc, doc, cat, rule):
        add(o)
    db.session.flush()
    from app.models import Student
    tag.students.append(db.session.get(Student, stu.id))   # never attach the bundle's detached object
    beh = BehaviorIncident(school_id=sid, student_id=stu.id, category_id=cat.id,
                           incident_date=date(2026, 9, 5), description=f"Behavior-{slug}")
    trig = AttendanceRuleTriggered(school_id=sid, rule_id=rule.id, student_id=stu.id, count_at_trigger=3)
    att = Attendance(school_id=sid, enrollment_id=enr.id, date=date(2026, 9, 6), status="absent")
    pick = PickupCall(school_id=sid, parent_user_id=bundle["users"]["parent"].id, student_id=stu.id,
                      section_id=bundle["section"].id)
    for o in (beh, trig, att, pick):
        add(o)
    db.session.commit()
    return {
        "guardian_link": link.id, "student_note": note.id, "student_tag": tag.id,
        "previous_school": prev.id, "health_incident": inc.id, "document": doc.id,
        "behavior_category": cat.id, "behavior": beh.id, "rule_trigger": trig.id,
        "attendance": att.id, "pickup": pick.id, "health_profile": health.id,
        "parent_user": bundle["users"]["parent"].id, "student_user": bundle["users"]["student"].id,
        "teacher_user": bundle["users"]["teacher"].id,
        "markers": (f"Note-{slug}", f"Tag-{slug}", f"Prev-{slug}", f"Health-{slug}",
                    f"doc-{slug}", f"BehCat-{slug}", f"Behavior-{slug}", f"Rule-{slug}"),
    }


def seed_lms(bundle: dict) -> dict:
    """LMS records for one school (SAAS-015 / 016). App context."""
    from datetime import datetime, timedelta
    from app.extensions import db
    from app.models.lms import (
        Announcement, AssessmentTemplate, AssessmentTemplateItem, AssignmentExtension,
        AssignmentQuestion, AssignmentTemplate, BankChoice, BankQuestion, Choice, Course,
        CourseAssignment, CourseSection, FeedbackTemplate, LearningObjective, Lesson, Passage,
        Question, QuestionCollection, Quiz, QuizAttempt, Skill, Submission, Unit,
    )
    slug, sid = bundle["school"].slug, bundle["school"].id
    add = db.session.add
    course = Course(school_id=sid, academic_year_id=bundle["year"].id, grade_id=bundle["grade"].id,
                    subject_id=bundle["subject"].id, title=f"Course-{slug}", is_published=True)
    bank = BankQuestion(school_id=sid, prompt=f"BankQ-{slug}")
    skill = Skill(school_id=sid, title=f"Skill-{slug}")
    obj = LearningObjective(school_id=sid, title=f"Objective-{slug}")
    coll = QuestionCollection(school_id=sid, title=f"Collection-{slug}")
    fb = FeedbackTemplate(school_id=sid, title=f"Feedback-{slug}")
    atpl = AssignmentTemplate(school_id=sid, title=f"AssignTpl-{slug}")
    stpl = AssessmentTemplate(school_id=sid, title=f"AssessTpl-{slug}")
    passage = Passage(school_id=sid, title=f"Passage-{slug}")
    from app.models import Rubric
    rubric = Rubric(school_id=sid, title=f"Rubric-{slug}")
    add(rubric)
    ann = Announcement(school_id=sid, title=f"Announce-{slug}")
    for o in (course, bank, skill, obj, coll, fb, atpl, stpl, passage, ann):
        add(o)
    db.session.flush()
    add(CourseSection(course_id=course.id, section_id=bundle["section"].id, is_published=True))
    add(BankChoice(question_id=bank.id, label=f"BankChoice-{slug}", is_correct=True))
    unit = Unit(course_id=course.id, title=f"Unit-{slug}")
    add(unit)
    db.session.flush()
    lesson = Lesson(course_id=course.id, unit_id=unit.id, title=f"Lesson-{slug}", body="x")
    quiz = Quiz(course_id=course.id, title=f"Quiz-{slug}", is_published=True)
    asg = CourseAssignment(course_id=course.id, title=f"Assign-{slug}", is_published=True)
    item = AssessmentTemplateItem(template_id=stpl.id, bank_question_id=bank.id)
    for o in (lesson, quiz, asg, item):
        add(o)
    db.session.flush()
    q = Question(quiz_id=quiz.id, prompt=f"QuizQ-{slug}", kind="mcq", points=1)
    aq = AssignmentQuestion(assignment_id=asg.id, prompt=f"AssignQ-{slug}")
    attempt = QuizAttempt(quiz_id=quiz.id, student_id=bundle["student"].id)
    sub = Submission(assignment_id=asg.id, student_id=bundle["student"].id)
    ext = AssignmentExtension(assignment_id=asg.id, student_id=bundle["student"].id,
                              new_due_at=datetime(2026, 12, 1) + timedelta(days=1))
    for o in (q, aq, attempt, sub, ext):
        add(o)
    db.session.flush()
    choice = Choice(question_id=q.id, label=f"Choice-{slug}", is_correct=True)
    add(choice)
    db.session.commit()
    return {
        "course": course.id, "unit": unit.id, "lesson": lesson.id, "quiz": quiz.id, "question": q.id,
        "assignment": asg.id, "assignment_question": aq.id, "attempt": attempt.id, "submission": sub.id,
        "bank_question": bank.id, "skill": skill.id, "objective": obj.id, "collection": coll.id,
        "feedback_template": fb.id, "assign_template": atpl.id, "assess_template": stpl.id,
        "template_item": item.id, "passage": passage.id, "announcement": ann.id, "extension": ext.id,
        "rubric": rubric.id, "choice": choice.id,
        "markers": (f"Course-{slug}", f"BankQ-{slug}", f"Skill-{slug}", f"Objective-{slug}",
                    f"Collection-{slug}", f"Feedback-{slug}", f"AssignTpl-{slug}", f"AssessTpl-{slug}",
                    f"Passage-{slug}", f"Announce-{slug}", f"Unit-{slug}", f"Lesson-{slug}",
                    f"Quiz-{slug}", f"Assign-{slug}", f"QuizQ-{slug}", f"AssignQ-{slug}",
                    f"Rubric-{slug}"),
    }


def seed_core(bundle: dict) -> dict:
    """Academic / teachers / results / schedule / platform / admin / nafis /
    messaging records for one school (SAAS-018). App context."""
    from datetime import datetime, time, timezone
    from app.extensions import db
    from app.models import (
        AssessmentComponent, Assignment, Conversation, ConversationParticipant, Day, GradingScale,
        Message, NotificationLog, SchoolBackup, SchoolRestore,
        NafisCycle, Period, Room, ScheduleSlot, SchoolCalendarDay, Teacher, TranscriptSnapshot,
        UserScope, Vendor,
    )
    slug, sid = bundle["school"].slug, bundle["school"].id
    year, section, subject = bundle["year"].id, bundle["section"].id, bundle["subject"].id
    users = bundle["users"]
    add = db.session.add
    teacher = Teacher(school_id=sid, full_name=f"TeacherRec-{slug}", specialization=f"Spec-{slug}",
                      user_id=users["teacher"].id)
    day = Day(school_id=sid, name=f"Day-{slug}", order_index=1, academic_year_id=year)
    period = Period(school_id=sid, name=f"Period-{slug}", order_index=1,
                    start_time=time(8, 0), end_time=time(8, 45), academic_year_id=year)
    room = Room(school_id=sid, name=f"Room-{slug}")
    cal = SchoolCalendarDay(school_id=sid, academic_year_id=year, date=date(2026, 10, 6),
                            day_type="holiday")
    scale = GradingScale(school_id=sid, name=f"Scale-{slug}")
    cycle = NafisCycle(school_id=sid, name_ar=f"Nafis-{slug}", academic_year_id=year)
    conv = Conversation(school_id=sid, created_by_user_id=users["admin"].id)
    # Soft-deleted row for admin.trash_restore.
    trash = Vendor(school_id=sid, name=f"TrashVendor-{slug}", deleted_at=datetime.now(timezone.utc))
    for o in (teacher, day, period, room, cal, scale, cycle, conv, trash):
        add(o)
    db.session.flush()
    tasg = Assignment(school_id=sid, year_id=year, section_id=section, subject_id=subject,
                      teacher_id=teacher.id, term_id=bundle["term"].id)
    slot = ScheduleSlot(school_id=sid, year_id=year, section_id=section, day_id=day.id,
                        period_id=period.id, subject_id=subject, teacher_id=teacher.id, room_id=room.id)
    for u in ("admin", "teacher"):
        add(ConversationParticipant(conversation_id=conv.id, user_id=users[u].id))
    msg = Message(school_id=sid, conversation_id=conv.id, sender_user_id=users["admin"].id,
                  body=f"Msg-{slug}")
    scope = UserScope(school_id=sid, user_id=users["teacher"].id, scope_type="section",
                      scope_value=section)
    snap = TranscriptSnapshot(school_id=sid, student_id=bundle["student"].id,
                              content={"note": f"Transcript-{slug}"}, serial_number=f"TS-{slug}-1")
    comp = AssessmentComponent(school_id=sid, term_id=bundle["term"].id, subject_id=subject,
                               name=f"Comp-{slug}", max_score=10)
    notif = NotificationLog(school_id=sid, student_id=bundle["student"].id, kind="announcement",
                            status="sent", payload="{}")
    backup = SchoolBackup(school_id=sid, status="succeeded", progress=100,
                          file_name=f"Backup-{slug}.tar.gz", size_bytes=1,
                          requested_by_user_id=users["admin"].id)
    for o in (tasg, slot, msg, snap, scope, comp, notif, backup):
        add(o)
    db.session.flush()
    restore = SchoolRestore(school_id=sid, status="succeeded", mode="replace", modules=["academic"],
                            package_file=backup.file_name, source_backup_id=backup.id,
                            restore_point_backup_id=backup.id, requested_by_user_id=users["admin"].id)
    add(restore)
    db.session.commit()
    return {
        "teacher": teacher.id, "day": day.id, "period": period.id, "room": room.id,
        "calendar_day": cal.id, "scale": scale.id, "nafis_cycle": cycle.id,
        "conversation": conv.id, "message": msg.id, "trash_vendor": trash.id,
        "teacher_assignment": tasg.id, "slot": slot.id, "transcript": snap.id, "scope": scope.id,
        "component": comp.id, "notification": notif.id, "backup": backup.id, "restore": restore.id,
        "role": bundle["roles"]["teacher"].id, "admin_user": users["admin"].id,
        "markers": (f"TeacherRec-{slug}", f"Spec-{slug}", f"Day-{slug}", f"Period-{slug}",
                    f"Room-{slug}", f"Scale-{slug}", f"Nafis-{slug}", f"Msg-{slug}",
                    f"TrashVendor-{slug}", f"Transcript-{slug}", f"Comp-{slug}",
                    f"Backup-{slug}"),
    }


def ledger_state(school_ids) -> tuple:
    """Accounting fingerprint of the given schools: journal entries,
    debit/credit totals and money-moving rows. Any cross-tenant write
    that touches the books changes it."""
    from sqlalchemy import func
    from app.extensions import db
    from app.models import (
        EmployeeAdvance, Expense, Invoice, JournalEntry, JournalLine,
        Payment, Payroll, RefundRequest,
    )
    out = []
    for sid in school_ids:
        dr, cr = (db.session.query(func.coalesce(func.sum(JournalLine.debit), 0),
                                   func.coalesce(func.sum(JournalLine.credit), 0))
                  .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
                  .filter(JournalEntry.school_id == sid).one())
        counts = tuple(
            m.query.filter_by(school_id=sid).count()
            for m in (JournalEntry, Payment, RefundRequest, Expense,
                      EmployeeAdvance, Payroll, Invoice)
        )
        out.append((sid, str(dr), str(cr), counts))
    # Journal lines posted to an account of a different school than the
    # entry — invisible to the per-school totals above.
    from app.models import Account
    foreign = (db.session.query(func.count(JournalLine.id))
               .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
               .join(Account, Account.id == JournalLine.account_id)
               .filter(Account.school_id != JournalEntry.school_id).scalar())
    out.append(("foreign_lines", foreign))
    return tuple(out)


def give_subscription(school) -> None:
    """SAAS-027 — an active test school needs a current subscription or
    the resolver blocks it. Open-ended internal plan, like the migration
    gives every existing school."""
    from app.services.subscriptions import ensure_subscription
    ensure_subscription(school, reason="test fixture")


def purge_schools(school_ids) -> None:
    """Delete every row owned by `school_ids`, children first.

    Owned = has school_id in the set, or (transitively) references an
    owned row through any FK. Runs on the raw connection so soft-delete
    filters and ORM listeners don't interfere."""
    from sqlalchemy import select
    from app.extensions import db

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
    from app.services.platform_security import audit_prune
    with db.engine.begin() as conn, audit_prune(conn):      # SAAS-036: audit rows are immutable
        # The schools themselves: rows that point at them under another
        # name (platform_audit_logs.target_school_id) go too.
        doomed["schools"] = set(ids)
        for t in tables:
            if "school_id" in t.c and "id" in t.c:
                doomed[t.name] = {r[0] for r in conn.execute(
                    select(t.c.id).where(t.c.school_id.in_(ids)))}
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
                        found |= {r[0] for r in conn.execute(
                            select(t.c.id).where(fk.parent.in_(part)))}
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
