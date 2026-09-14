"""Add rich demo data to a freshly seeded DB so every screen has content.

Idempotent — safe to re-run. Assumes seeds.seed has already created the base
fixtures (school + roles + ehab teacher + wali parent + student STU-FX-0001 +
year 2025-2026 + term 1 + grade + sections أ-fx & ب-fx + subject الرياضيات-fx).

What this adds:
  • 3 extra subjects (الفقه-fx, القرآن-fx, العلوم-fx), all assigned to ehab in أ-fx
  • 2 extra children for wali (so parent home shows a list, not auto-nav)
  • 5 extra classmates in أ-fx (teacher's students tab feels populated)
  • Weekly timetable: 5 days × 4 periods × the 4 subjects
  • 15 school days of attendance for wali's first child (mix of present/absent/late)
  • Assessment components (نشاط + امتحان) + grade entries for wali's child
  • 3 invoices (paid / partial / overdue) with installments for wali's child
  • 2 materials per subject (PDF-like + link)
  • 8 notifications for wali (attendance, grades, invoice, material events)

Run:
    PYTHONIOENCODING=utf-8 DATABASE_URL=sqlite:///test.db python -m seeds.demo
"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

import json
import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from app import create_app
from app.extensions import db
from app.models import (
    School, User, AcademicYear, Term, Grade, Section, Subject, Teacher, Assignment,
    Student, Enrollment, Attendance, Day, Period, ScheduleSlot,
    AssessmentComponent, GradeEntry, PassRule, YearResult,
    FeeType, Invoice, InvoiceLine, Installment, Account, NotificationLog,
    Material,
)


EXTRA_SUBJECTS = [
    ("الفقه-fx", "الفقه"),
    ("القرآن-fx", "القرآن"),
    ("العلوم-fx", "العلوم"),
]

EXTRA_STUDENTS = [
    # (permanent_code, full_name, gender, parent_name, parent_phone)
    ("STU-FX-0002", "أحمد محمد الأمين", "male", "محمد الأمين", "+249900000002"),
    ("STU-FX-0003", "فاطمة عبدالله", "female", "عبدالله السنوسي", "+249900000003"),
    ("STU-FX-0004", "يوسف عبدالرحمن", "male", "عبدالرحمن حاج", "+249900000004"),
    ("STU-FX-0005", "مريم حسن", "female", "حسن الأمين", "+249900000005"),
    ("STU-FX-0006", "عمر إبراهيم", "male", "إبراهيم يحيى", "+249900000006"),
]

WALI_EXTRA_CHILDREN = [
    ("STU-FX-WALI-2", "خديجة تجريبية", "female"),
    ("STU-FX-WALI-3", "محمد تجريبي", "male"),
]

DAYS = [
    ("الأحد", 1),
    ("الاثنين", 2),
    ("الثلاثاء", 3),
    ("الأربعاء", 4),
    ("الخميس", 5),
]

PERIODS = [
    ("الفترة الأولى", 1, time(8, 0), time(8, 45)),
    ("الفترة الثانية", 2, time(8, 55), time(9, 40)),
    ("الفترة الثالثة", 3, time(10, 0), time(10, 45)),
    ("الفترة الرابعة", 4, time(10, 55), time(11, 40)),
]

COMPONENTS = [
    ("نشاط", Decimal("20")),
    ("اختبار الفصل", Decimal("30")),
]

FEE_TYPES = [
    # (name, default_amount, is_installable)
    ("رسوم دراسية", Decimal("50000"), True),
    ("رسوم مواصلات", Decimal("15000"), False),
    ("رسوم كتب", Decimal("8000"), False),
]

MATERIALS = [
    # (subject_key, title, description, kind, external_url)
    ("الرياضيات-fx", "ملخص الوحدة الأولى — الأعداد الطبيعية",
     "PDF فيه شرح وأمثلة وتمارين محلولة.", "file", None),
    ("الرياضيات-fx", "درس فيديو — الجمع والطرح",
     "فيديو تعليمي على يوتيوب مدته 10 دقائق.", "video",
     "https://youtube.com/watch?v=demo1"),
    ("الفقه-fx", "الطهارة والوضوء — دليل مبسّط",
     "شرح مصوّر لفروض الوضوء وسننه.", "file", None),
    ("الفقه-fx", "أذكار الوضوء — رابط خارجي",
     "روابط مفيدة لصحيح البخاري.", "link", "https://sunnah.com/bukhari"),
    ("القرآن-fx", "تسميع سورة الفاتحة — تدريب",
     "PDF فيه نص السورة مع مواضع الوقف.", "file", None),
    ("القرآن-fx", "تلاوة مثال — الشيخ عبد الباسط",
     "تلاوة مباركة للاستماع والتدرّب.", "video",
     "https://youtube.com/watch?v=demo2"),
    ("العلوم-fx", "نبذة عن دورة الماء",
     "شرح مصوّر ورسوم توضيحية.", "file", None),
    ("العلوم-fx", "تجربة تبخّر الماء — بالخطوات",
     "خطوات تجربة بسيطة تنفذها مع أهلك.", "link",
     "https://example.org/water-cycle"),
]


def _get_or_die(query_result, description):
    if not query_result:
        sys.exit(f"❌ Required fixture missing: {description}. Run `python -m seeds.seed` first.")
    return query_result


def _upsert(model, filter_kwargs, defaults, label=None):
    """Get-or-create helper. Returns (instance, created_bool)."""
    obj = model.query.filter_by(**filter_kwargs).first()
    if obj:
        return obj, False
    obj = model(**filter_kwargs, **defaults)
    db.session.add(obj)
    db.session.flush()
    if label:
        print(f"✓ {label}")
    return obj, True


def run():
    app = create_app()
    with app.app_context():
        # Look up the base fixtures.
        school = _get_or_die(School.query.first(), "school row")
        year = _get_or_die(
            AcademicYear.query.filter_by(school_id=school.id, status="active").first(),
            "active academic year",
        )
        term = _get_or_die(
            Term.query.filter_by(year_id=year.id, order_index=1).first(),
            "term 1 of active year",
        )
        grade = _get_or_die(
            Grade.query.filter_by(school_id=school.id, name="الأول الابتدائي").first(),
            "grade الأول الابتدائي",
        )
        section_a = _get_or_die(
            Section.query.filter_by(year_id=year.id, grade_id=grade.id, name="أ-fx").first(),
            "section أ-fx",
        )
        ehab = _get_or_die(
            User.query.filter_by(school_id=school.id, username="ehab").first(),
            "user ehab",
        )
        wali = _get_or_die(
            User.query.filter_by(school_id=school.id, username="wali").first(),
            "user wali",
        )
        teacher = _get_or_die(
            Teacher.query.filter_by(user_id=ehab.id).first(),
            "teacher profile for ehab",
        )
        subject_math = _get_or_die(
            Subject.query.filter_by(school_id=school.id, name="الرياضيات-fx").first(),
            "subject الرياضيات-fx",
        )
        wali_first_student = _get_or_die(
            Student.query.filter_by(school_id=school.id, permanent_code="STU-FX-0001").first(),
            "student STU-FX-0001",
        )
        wali_first_enrollment = _get_or_die(
            Enrollment.query.filter_by(student_id=wali_first_student.id, year_id=year.id).first(),
            "enrollment for STU-FX-0001",
        )

        # Ensure the demo student has a parent_phone so notifications can target them.
        if not wali_first_student.parent_phone:
            wali_first_student.parent_phone = "+249900000001"
            print("✓ Set parent_phone on STU-FX-0001")

        # ── extra subjects + assignments ─────────────────────────────────────
        subjects_by_key = {"الرياضيات-fx": subject_math}
        for key, _display in EXTRA_SUBJECTS:
            subj, created = _upsert(
                Subject,
                {"school_id": school.id, "name": key},
                {"is_active": True},
                label=f"Created subject: {key}" if False else None,
            )
            if created:
                print(f"✓ Created subject: {key}")
            if grade not in subj.grades:
                subj.grades.append(grade)
            subjects_by_key[key] = subj

        # ehab teaches every subject in section أ-fx
        for subj in subjects_by_key.values():
            _upsert(
                Assignment,
                {
                    "year_id": year.id,
                    "section_id": section_a.id,
                    "subject_id": subj.id,
                    "teacher_id": teacher.id,
                },
                {"school_id": school.id, "is_active": True, "weekly_periods": 2},
                label=f"Assigned ehab → {subj.name} in أ-fx",
            )

        # ── extra children for wali (so parent home has a list) ─────────────
        for code, name, gender in WALI_EXTRA_CHILDREN:
            child, created = _upsert(
                Student,
                {"school_id": school.id, "permanent_code": code},
                {
                    "full_name": name,
                    "gender": gender,
                    "parent_name": "ولي الأمر",
                    "parent_phone": "+249900000001",  # same phone → wali gets notifs for all
                    "parent_user_id": wali.id,
                },
                label=f"Created wali child: {name} ({code})",
            )
            # Enroll each extra wali child in أ-fx too.
            _upsert(
                Enrollment,
                {"student_id": child.id, "year_id": year.id},
                {
                    "school_id": school.id,
                    "grade_id": grade.id,
                    "section_id": section_a.id,
                    "status": "active",
                },
                label=f"Enrolled {name} in أ-fx",
            )

        # ── 5 extra classmates in أ-fx ──────────────────────────────────────
        for code, name, gender, pname, pphone in EXTRA_STUDENTS:
            stu, created = _upsert(
                Student,
                {"school_id": school.id, "permanent_code": code},
                {
                    "full_name": name,
                    "gender": gender,
                    "parent_name": pname,
                    "parent_phone": pphone,
                },
                label=f"Created classmate: {name} ({code})",
            )
            _upsert(
                Enrollment,
                {"student_id": stu.id, "year_id": year.id},
                {
                    "school_id": school.id,
                    "grade_id": grade.id,
                    "section_id": section_a.id,
                    "status": "active",
                },
                label=f"Enrolled {name} in أ-fx",
            )

        # ── days + periods ──────────────────────────────────────────────────
        days_by_order = {}
        for name, order in DAYS:
            d, _ = _upsert(
                Day,
                {"school_id": school.id, "order_index": order},
                {"name": name, "is_active": True},
                label=f"Created day: {name}",
            )
            days_by_order[order] = d

        periods_by_order = {}
        for name, order, start, end in PERIODS:
            p, _ = _upsert(
                Period,
                {"school_id": school.id, "order_index": order},
                {"name": name, "start_time": start, "end_time": end, "is_break": False},
                label=f"Created period: {name}",
            )
            periods_by_order[order] = p

        # ── weekly timetable: rotate the 4 subjects across days × periods ──
        subject_list = list(subjects_by_key.values())
        for day_order, day_obj in sorted(days_by_order.items()):
            for period_order, period_obj in sorted(periods_by_order.items()):
                subj = subject_list[(day_order + period_order) % len(subject_list)]
                _upsert(
                    ScheduleSlot,
                    {
                        "year_id": year.id,
                        "section_id": section_a.id,
                        "day_id": day_obj.id,
                        "period_id": period_obj.id,
                    },
                    {
                        "school_id": school.id,
                        "subject_id": subj.id,
                        "teacher_id": teacher.id,
                    },
                )
        print("✓ Filled weekly timetable (5 days × 4 periods)")

        # ── pass rule for the year ──────────────────────────────────────────
        _upsert(
            PassRule,
            {"year_id": year.id},
            {
                "school_id": school.id,
                "subject_pass_threshold": Decimal("50"),
                "overall_pass_threshold": Decimal("50"),
                "method": "overall_only",
                "allowed_failed_subjects": 0,
                "is_frozen": False,
            },
            label="Created pass rule (50% threshold)",
        )

        # ── assessment components per subject per term ─────────────────────
        components_by_subject = {}
        for subj in subject_list:
            comps = []
            for name, max_score in COMPONENTS:
                c, _ = _upsert(
                    AssessmentComponent,
                    {"term_id": term.id, "subject_id": subj.id, "name": name},
                    {"school_id": school.id, "max_score": max_score},
                )
                comps.append(c)
            components_by_subject[subj.id] = comps
        print("✓ Created assessment components (نشاط + اختبار الفصل per subject)")

        # ── attendance for wali's first child — last 15 school days ────────
        rng = random.Random(42)  # deterministic for idempotency
        added = 0
        today = date.today()
        for i in range(21):
            d = today - timedelta(days=i)
            if d.weekday() in (4, 5):  # Fri, Sat — skip weekend
                continue
            status = rng.choices(
                ["present", "present", "present", "present", "late", "absent"],
                k=1,
            )[0]
            existing = Attendance.query.filter_by(
                enrollment_id=wali_first_enrollment.id, date=d,
            ).first()
            if existing:
                continue
            db.session.add(Attendance(
                school_id=school.id,
                enrollment_id=wali_first_enrollment.id,
                date=d,
                status=status,
                notes=None,
                recorded_by_user_id=ehab.id,
            ))
            added += 1
        if added:
            print(f"✓ Added {added} attendance records for wali's first child")

        # ── grades for wali's first child ──────────────────────────────────
        # For each subject, give a realistic score out of the component's max.
        grade_added = 0
        for subj in subject_list:
            for comp in components_by_subject[subj.id]:
                existing = GradeEntry.query.filter_by(
                    enrollment_id=wali_first_enrollment.id, component_id=comp.id,
                ).first()
                if existing:
                    continue
                # Score = 60-95% of max_score, deterministic per component.
                pct = 0.60 + (comp.id * 7 % 35) / 100  # 0.60..0.95
                score = (float(comp.max_score) * pct)
                db.session.add(GradeEntry(
                    school_id=school.id,
                    enrollment_id=wali_first_enrollment.id,
                    component_id=comp.id,
                    score=Decimal(f"{score:.2f}"),
                    recorded_by_user_id=ehab.id,
                ))
                grade_added += 1
        if grade_added:
            print(f"✓ Added {grade_added} grade entries for wali's first child")

        # ── year result for wali's first child (so results tab has data) ────
        # Day 5: subject_scores drives SubjectProgressBar rendering.
        year_result_existing = YearResult.query.filter_by(
            enrollment_id=wali_first_enrollment.id,
        ).first()
        if not year_result_existing:
            subject_scores = {
                "الرياضيات-fx": 85,
                "الفقه-fx": 78,
                "القرآن-fx": 92,
                "العلوم-fx": 71,
            }
            db.session.add(YearResult(
                school_id=school.id,
                enrollment_id=wali_first_enrollment.id,
                average=Decimal(f"{sum(subject_scores.values()) / len(subject_scores):.2f}"),
                status="pass",
                failed_subjects=0,
                rule_snapshot={
                    "subject_pass_threshold": 50,
                    "overall_pass_threshold": 50,
                    "method": "overall_only",
                    "allowed_failed_subjects": 0,
                },
                subject_scores=subject_scores,
                approved_by_user_id=ehab.id,
                approved_at=datetime.utcnow(),
            ))
            print("✓ Added year result for wali's first child")

        # ── fee types + 3 invoices ──────────────────────────────────────────
        rev_account = Account.query.filter_by(school_id=school.id, code="4100").first()
        fee_by_key = {}
        for name, amount, installable in FEE_TYPES:
            ft, _ = _upsert(
                FeeType,
                {"school_id": school.id, "name": name},
                {
                    "default_amount": amount,
                    "installable": installable,
                    "revenue_account_id": rev_account.id,
                    "is_active": True,
                },
            )
            fee_by_key[name] = ft
        print("✓ Created fee types (رسوم دراسية، مواصلات، كتب)")

        # 3 invoices for wali's first child with different statuses.
        invoice_specs = [
            # (number, days_offset_from_today_issue, days_to_due, status, paid_pct, fee_key)
            ("INV-FX-2025-001", -60, -30, "paid", 1.0, "رسوم كتب"),
            ("INV-FX-2025-002", -20, 10, "partial", 0.4, "رسوم دراسية"),
            ("INV-FX-2025-003", -50, -5, "overdue", 0.0, "رسوم مواصلات"),
        ]
        for number, issue_off, due_off, status, paid_pct, fee_key in invoice_specs:
            fee = fee_by_key[fee_key]
            existing = Invoice.query.filter_by(
                school_id=school.id, number=number,
            ).first()
            if existing:
                continue
            total = fee.default_amount
            paid = Decimal(f"{float(total) * paid_pct:.2f}")
            inv = Invoice(
                school_id=school.id,
                enrollment_id=wali_first_enrollment.id,
                number=number,
                issue_date=today + timedelta(days=issue_off),
                due_date=today + timedelta(days=due_off),
                status=status,
                total_amount=total,
                paid_amount=paid,
                notes=None,
            )
            db.session.add(inv)
            db.session.flush()
            db.session.add(InvoiceLine(
                invoice_id=inv.id,
                fee_type_id=fee.id,
                description=fee.name,
                amount=total,
            ))
            # One-shot installment mirroring the invoice.
            db.session.add(Installment(
                invoice_id=inv.id,
                due_date=inv.due_date,
                amount=total,
                paid_amount=paid,
                status=("paid" if paid_pct >= 1.0 else
                        "overdue" if due_off < 0 and paid_pct < 1.0 else "pending"),
            ))
            print(f"✓ Created invoice {number} ({status})")

        # ── materials ──────────────────────────────────────────────────────
        for subj_key, title, desc, kind, url in MATERIALS:
            subj = subjects_by_key.get(subj_key)
            if not subj:
                continue
            existing = Material.query.filter_by(
                school_id=school.id,
                teacher_id=teacher.id,
                subject_id=subj.id,
                section_id=section_a.id,
                title=title,
            ).first()
            if existing:
                continue
            db.session.add(Material(
                school_id=school.id,
                teacher_id=teacher.id,
                year_id=year.id,
                section_id=section_a.id,
                subject_id=subj.id,
                title=title,
                description=desc,
                kind=kind,
                external_url=url,
                file_path=None if url else f"/uploads/demo/{kind}/{subj_key}.pdf",
            ))
            print(f"✓ Created material: {title}")

        # ── notifications for wali ──────────────────────────────────────────
        # Target all children under wali by their parent_phone.
        wali_phones = {"+249900000001"}
        notif_specs = [
            ("attendance", "تم تسجيل حضور طالب تجريبي اليوم.", -0),
            ("attendance", "غياب طالب تجريبي أمس. يرجى المتابعة.", -1),
            ("grade", "درجات جديدة: الرياضيات - نشاط (16/20).", -2),
            ("grade", "درجات جديدة: الفقه - اختبار الفصل (24/30).", -3),
            ("invoice", "فاتورة INV-FX-2025-003 تجاوزت تاريخ الاستحقاق.", -5),
            ("invoice", "تم إصدار فاتورة جديدة: INV-FX-2025-002.", -20),
            ("material", "مادة جديدة: ملخص الوحدة الأولى — الأعداد الطبيعية.", -4),
            ("material", "مادة جديدة: أذكار الوضوء — رابط خارجي.", -7),
        ]
        for phone in wali_phones:
            for kind, msg, days_ago in notif_specs:
                # Idempotency probe: (phone, kind, payload substring)
                payload = json.dumps({"message": msg}, ensure_ascii=False)
                existing = NotificationLog.query.filter_by(
                    school_id=school.id,
                    target_phone=phone,
                    kind=kind,
                    payload=payload,
                ).first()
                if existing:
                    continue
                created = datetime.utcnow() + timedelta(days=days_ago)
                db.session.add(NotificationLog(
                    school_id=school.id,
                    kind=kind,
                    target_phone=phone,
                    target_email=None,
                    payload=payload,
                    status="sent",
                    attempts=1,
                    last_attempt_at=created,
                    sent_at=created,
                    created_at=created,
                ))
        print("✓ Added 8 notifications for wali")

        db.session.commit()
        print("\n✅ Demo data seeded. Restart Flask and open the apps.")


if __name__ == "__main__":
    run()
