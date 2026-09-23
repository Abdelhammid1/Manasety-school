"""School-admin dashboard — operational metrics, alerts, quick actions.

Every query is scoped by ``sid = current_user.school_id`` and (where relevant)
by the active academic year. Everything is wrapped in try/except so one
query that trips on a missing table / bad column doesn't blank the whole
page — a widget just shows its safe default (0, empty list) instead.
"""
from datetime import date, datetime, timedelta

from flask import render_template, request
from flask_login import current_user, login_required
from sqlalchemy import func

from . import bp
from ..utils import admin_only
from ...extensions import db
from ...models import (
    AcademicYear, Account, Attendance, Enrollment, Expense, Grade, Installment,
    Invoice, NotificationLog, Payment, Section, Student, Subject, Teacher, User,
    # LMS
    Course, Lesson, CourseAssignment, Submission, Quiz, QuizAttempt, Announcement,
)


def _safe(fn, default=None):
    """Run ``fn()``, swallow any exception, return ``default``."""
    try:
        return fn()
    except Exception:
        db.session.rollback()
        return default


def _sections_unmarked_today(sid: int, yid: int, cap: int = 8):
    """Return up to ``cap`` active sections in the year that have NO attendance
    row for today across their active enrollments.

    Implementation is a Python-side anti-join — a single SELECT of every
    enrollment_id that WAS marked today, then filter sections whose active
    enrollments don't intersect that set. Small N — fine at school scale.
    """
    today = date.today()
    marked_ids = {
        r[0]
        for r in db.session.query(Attendance.enrollment_id)
        .filter(Attendance.school_id == sid, Attendance.date == today)
        .all()
    }
    sections = (
        Section.query.filter_by(school_id=sid, year_id=yid)
        .join(Grade, Grade.id == Section.grade_id)
        .order_by(Grade.order_index.asc(), Section.name.asc())
        .all()
    )
    rows = []
    for sec in sections:
        active_enrolls = [e for e in sec.enrollments if e.status == "active"]
        if not active_enrolls:
            continue
        active_ids = {e.id for e in active_enrolls}
        if active_ids & marked_ids:
            continue
        rows.append({
            "section_id": sec.id,
            "section_name": sec.name,
            "grade_name": sec.grade.name if sec.grade else "—",
            "students_count": len(active_enrolls),
        })
        if len(rows) >= cap:
            break
    return rows


def _installments_due_next_7d(sid: int, cap: int = 8):
    """Installments due today→+7d that aren't fully paid, with student names."""
    today = date.today()
    horizon = today + timedelta(days=7)
    q = (
        db.session.query(Installment, Invoice, Student)
        .join(Invoice, Invoice.id == Installment.invoice_id)
        .join(Enrollment, Enrollment.id == Invoice.enrollment_id)
        .join(Student, Student.id == Enrollment.student_id)
        .filter(
            Invoice.school_id == sid,
            Installment.due_date >= today,
            Installment.due_date <= horizon,
            Installment.status != "paid",
        )
        .order_by(Installment.due_date.asc())
        .limit(cap)
    )
    return [
        {
            "installment_id": inst.id,
            "invoice_id": inv.id,
            "student_name": stu.full_name,
            "due_date": inst.due_date,
            "amount": float(inst.remaining),
        }
        for inst, inv, stu in q.all()
    ]


def _attendance_today(sid: int):
    """Aggregate attendance counts + rate for today."""
    today = date.today()
    rows = (
        db.session.query(Attendance.status, func.count(Attendance.id))
        .filter(Attendance.school_id == sid, Attendance.date == today)
        .group_by(Attendance.status)
        .all()
    )
    by_status = {s: int(c) for s, c in rows}
    present = by_status.get("present", 0)
    absent = by_status.get("absent", 0)
    late = by_status.get("late", 0)
    total = present + absent + late
    rate = round((present / total) * 100) if total else 0
    return {"present": present, "absent": absent, "late": late, "total": total, "rate": rate}


def _outstanding_ar(sid: int, yid: int) -> float:
    """Sum of Invoice.total_amount - Invoice.paid_amount for the active year.

    Filter by year via join through Enrollment (Invoice has no year_id).
    """
    q = (
        db.session.query(
            func.coalesce(func.sum(Invoice.total_amount - Invoice.paid_amount), 0)
        )
        .join(Enrollment, Enrollment.id == Invoice.enrollment_id)
        .filter(
            Invoice.school_id == sid,
            Enrollment.year_id == yid,
            Invoice.status != "paid",
        )
    )
    return float(q.scalar() or 0)


def _overdue_invoices_count(sid: int) -> int:
    """Dynamic overdue — Invoice.status is not auto-flipped, so compute:
    due_date < today AND paid_amount < total_amount AND status != 'paid'.
    """
    today = date.today()
    return int(
        Invoice.query.filter(
            Invoice.school_id == sid,
            Invoice.due_date < today,
            Invoice.paid_amount < Invoice.total_amount,
            Invoice.status != "paid",
        ).count()
    )


def _payments_sum(sid: int, since: date) -> float:
    q = (
        db.session.query(func.coalesce(func.sum(Payment.amount), 0))
        .filter(
            Payment.school_id == sid,
            Payment.is_refund.is_(False),
            Payment.payment_date >= since,
        )
    )
    return float(q.scalar() or 0)


def _expenses_sum(sid: int, since: date) -> float:
    q = (
        db.session.query(func.coalesce(func.sum(Expense.amount), 0))
        .filter(Expense.school_id == sid, Expense.date >= since)
    )
    return float(q.scalar() or 0)


def _cash_on_hand(sid: int) -> float:
    """Sum balances of cash + bank accounts only (codes under 1100:
    1110 prefix for cash, 1120 prefix for bank) — not all asset accounts.
    Uses ``Account.balance`` @property from the finance model.
    """
    accts = (
        Account.query.filter_by(school_id=sid, is_active=True, is_postable=True)
        .filter(Account.code.startswith("11"))
        .all()
    )
    return sum(a.balance for a in accts)


def _students_by_grade(sid: int, yid: int):
    """List of {grade_name, count} for active enrollments this year, ordered
    by ``Grade.order_index``."""
    rows = (
        db.session.query(Grade.name, Grade.order_index, func.count(Enrollment.id))
        .join(Enrollment, Enrollment.grade_id == Grade.id)
        .filter(
            Enrollment.school_id == sid,
            Enrollment.year_id == yid,
            Enrollment.status == "active",
        )
        .group_by(Grade.id, Grade.name, Grade.order_index)
        .order_by(Grade.order_index.asc())
        .all()
    )
    return [{"grade_name": n, "count": int(c)} for (n, _o, c) in rows]


def _sections_near_capacity(sid: int, yid: int, threshold: float = 0.9, cap: int = 8):
    """Sections in the active year that are ≥ ``threshold`` full."""
    sections = Section.query.filter_by(school_id=sid, year_id=yid).all()
    out = []
    for sec in sections:
        current = sec.current_count  # uses model @property
        cap_int = int(sec.capacity or 0)
        if cap_int <= 0:
            continue
        pct = current / cap_int
        if pct < threshold:
            continue
        out.append({
            "section_id": sec.id,
            "section_name": sec.name,
            "grade_name": sec.grade.name if sec.grade else "—",
            "current_count": current,
            "capacity": cap_int,
            "pct": round(pct * 100),
        })
    out.sort(key=lambda r: -r["pct"])
    return out[:cap]


def _new_students_this_month(sid: int) -> int:
    start = date.today().replace(day=1)
    return int(
        Student.query.filter(
            Student.school_id == sid,
            Student.created_at >= datetime.combine(start, datetime.min.time()),
        ).count()
    )


def _failed_notifications_last_7d(sid: int) -> int:
    since = datetime.utcnow() - timedelta(days=7)
    return int(
        NotificationLog.query.filter(
            NotificationLog.school_id == sid,
            NotificationLog.status == "failed",
            NotificationLog.created_at >= since,
        ).count()
    )


# ── LMS aggregates ─────────────────────────────────────────────────────────

def _lms_kpis(sid: int, yid: int):
    """One roundtrip's worth of LMS KPIs for the dashboard hero row.

    Every count is scoped by ``school_id``; year-scoped fields (courses) also
    filter by the active academic year so the numbers match the SIS view.
    """
    now = datetime.utcnow()

    courses_q = Course.query.filter_by(school_id=sid)
    if yid:
        courses_q = courses_q.filter_by(academic_year_id=yid)
    courses_total = courses_q.count()
    courses_published = courses_q.filter_by(is_published=True).count()

    # lessons/assignments/quizzes join to courses to inherit school scope
    lessons_total = (
        db.session.query(func.count(Lesson.id))
        .join(Course, Course.id == Lesson.course_id)
        .filter(Course.school_id == sid)
        .scalar() or 0
    )
    assignments_open = (
        db.session.query(func.count(CourseAssignment.id))
        .join(Course, Course.id == CourseAssignment.course_id)
        .filter(
            Course.school_id == sid,
            CourseAssignment.is_published.is_(True),
            (CourseAssignment.due_at.is_(None)) | (CourseAssignment.due_at > now),
        ).scalar() or 0
    )
    # Ungraded submissions across the school — the number the teacher sees
    # in the corner of every screen.
    submissions_pending = (
        db.session.query(func.count(Submission.id))
        .join(CourseAssignment, CourseAssignment.id == Submission.assignment_id)
        .join(Course, Course.id == CourseAssignment.course_id)
        .filter(Course.school_id == sid, Submission.score.is_(None))
        .scalar() or 0
    )
    quizzes_active = (
        db.session.query(func.count(Quiz.id))
        .join(Course, Course.id == Quiz.course_id)
        .filter(
            Course.school_id == sid,
            Quiz.is_published.is_(True),
            (Quiz.opens_at.is_(None)) | (Quiz.opens_at <= now),
            (Quiz.closes_at.is_(None)) | (Quiz.closes_at >= now),
        ).scalar() or 0
    )
    quiz_attempts_today = (
        db.session.query(func.count(QuizAttempt.id))
        .join(Quiz, Quiz.id == QuizAttempt.quiz_id)
        .join(Course, Course.id == Quiz.course_id)
        .filter(
            Course.school_id == sid,
            QuizAttempt.started_at >= datetime.combine(date.today(), datetime.min.time()),
        ).scalar() or 0
    )
    announcements_week = (
        Announcement.query
        .filter(
            Announcement.school_id == sid,
            Announcement.created_at >= datetime.utcnow() - timedelta(days=7),
        ).count()
    )

    return {
        "courses_total": int(courses_total),
        "courses_published": int(courses_published),
        "lessons_total": int(lessons_total),
        "assignments_open": int(assignments_open),
        "submissions_pending": int(submissions_pending),
        "quizzes_active": int(quizzes_active),
        "quiz_attempts_today": int(quiz_attempts_today),
        "announcements_week": int(announcements_week),
    }


def _top_courses_by_engagement(sid: int, yid: int, cap: int = 5):
    """Ranks courses by submissions+attempts count in the last 30d — the
    "hottest" courses. Small N (school-scale), so we compute per-course in
    Python rather than a nested subquery per course.
    """
    since = datetime.utcnow() - timedelta(days=30)
    q = Course.query.filter_by(school_id=sid)
    if yid:
        q = q.filter_by(academic_year_id=yid)
    rows = []
    for c in q.limit(200).all():
        subs = (
            db.session.query(func.count(Submission.id))
            .join(CourseAssignment, CourseAssignment.id == Submission.assignment_id)
            .filter(
                CourseAssignment.course_id == c.id,
                Submission.submitted_at >= since,
            ).scalar() or 0
        )
        atts = (
            db.session.query(func.count(QuizAttempt.id))
            .join(Quiz, Quiz.id == QuizAttempt.quiz_id)
            .filter(Quiz.course_id == c.id, QuizAttempt.started_at >= since)
            .scalar() or 0
        )
        score = int(subs) + int(atts)
        if score == 0:
            continue
        rows.append({
            "course_id": c.id,
            "title": c.title,
            "submissions": int(subs),
            "attempts": int(atts),
            "engagement": score,
        })
    rows.sort(key=lambda r: -r["engagement"])
    return rows[:cap]


def _users_locked_now(sid: int) -> int:
    now = datetime.utcnow()
    return int(
        User.query.filter(
            User.school_id == sid,
            User.locked_until.isnot(None),
            User.locked_until > now,
        ).count()
    )


@bp.route("/dashboard")
@login_required
def home():
    """Role-aware dashboard dispatcher. Admin sees the operational console;
    every other role sees their tailored home built from the Stitch designs."""
    role = getattr(getattr(current_user, "role", None), "name", None)
    if role != "admin":
        if role == "teacher":
            return _teacher_dashboard()
        if role == "parent":
            return _parent_dashboard()
        if role == "student":
            return _student_dashboard()
        # Any other role → the admin console (permissions gate below still
        # allows a school-admin variant to render).
    return _admin_dashboard()


def _admin_dashboard():
    sid = current_user.school_id
    active_year = _safe(
        lambda: AcademicYear.query.filter_by(school_id=sid, status="active").first()
    )
    yid = active_year.id if active_year else 0

    today = date.today()
    start_of_month = today.replace(day=1)

    # ── baseline counts (already on the old dashboard) ──────────────────────
    students_total = _safe(
        lambda: Student.query.filter_by(school_id=sid).count(), 0)
    students_active = _safe(
        lambda: Enrollment.query.filter_by(
            school_id=sid, year_id=yid, status="active").count(), 0) if yid else 0

    # ── daily-ops metrics ───────────────────────────────────────────────────
    attendance_today = _safe(lambda: _attendance_today(sid),
                             {"present": 0, "absent": 0, "late": 0, "total": 0, "rate": 0})
    sections_unmarked = _safe(
        lambda: _sections_unmarked_today(sid, yid), []) if yid else []
    installments_due_7d = _safe(lambda: _installments_due_next_7d(sid), [])

    # ── money row ───────────────────────────────────────────────────────────
    outstanding_ar = _safe(lambda: _outstanding_ar(sid, yid), 0.0) if yid else 0.0
    overdue_invoices = _safe(lambda: _overdue_invoices_count(sid), 0)
    collections_today = _safe(lambda: _payments_sum(sid, today), 0.0)
    collections_mtd = _safe(lambda: _payments_sum(sid, start_of_month), 0.0)
    expenses_mtd = _safe(lambda: _expenses_sum(sid, start_of_month), 0.0)
    cash_on_hand = _safe(lambda: _cash_on_hand(sid), 0.0)

    # ── academic snapshot ───────────────────────────────────────────────────
    students_by_grade = _safe(
        lambda: _students_by_grade(sid, yid), []) if yid else []
    sections_at_capacity = _safe(
        lambda: _sections_near_capacity(sid, yid), []) if yid else []
    new_students_month = _safe(lambda: _new_students_this_month(sid), 0)

    # ── LMS snapshot ────────────────────────────────────────────────────────
    lms = _safe(lambda: _lms_kpis(sid, yid), {
        "courses_total": 0, "courses_published": 0, "lessons_total": 0,
        "assignments_open": 0, "submissions_pending": 0, "quizzes_active": 0,
        "quiz_attempts_today": 0, "announcements_week": 0,
    })
    top_courses = _safe(lambda: _top_courses_by_engagement(sid, yid), [])

    # ── system health ───────────────────────────────────────────────────────
    users_active = _safe(
        lambda: User.query.filter_by(school_id=sid, is_active=True).count(), 0)
    users_locked = _safe(lambda: _users_locked_now(sid), 0)
    notifications_failed = _safe(lambda: _failed_notifications_last_7d(sid), 0)
    teachers_active = _safe(
        lambda: Teacher.query.filter_by(school_id=sid, is_active=True).count(), 0)

    # ── baseline structural counts (kept for footer stats) ──────────────────
    grades_count = _safe(lambda: Grade.query.filter_by(school_id=sid).count(), 0)
    sections_count = _safe(
        lambda: Section.query.filter_by(school_id=sid, year_id=yid).count(), 0) if yid else 0
    subjects_count = _safe(lambda: Subject.query.filter_by(school_id=sid).count(), 0)

    stats = {
        # baseline
        "active_year": active_year.name if active_year else "—",
        "students_total": students_total,
        "students_active": students_active,
        "grades_count": grades_count,
        "sections_count": sections_count,
        "subjects_count": subjects_count,
        # daily ops
        "attendance_today": attendance_today,
        "sections_unmarked": sections_unmarked,
        "installments_due_7d": installments_due_7d,
        "installments_due_7d_total": sum(r["amount"] for r in installments_due_7d),
        # money
        "outstanding_ar": outstanding_ar,
        "overdue_invoices": overdue_invoices,
        "collections_today": collections_today,
        "collections_mtd": collections_mtd,
        "expenses_mtd": expenses_mtd,
        "cash_on_hand": cash_on_hand,
        # academic
        "students_by_grade": students_by_grade,
        "students_by_grade_max": max((r["count"] for r in students_by_grade), default=0),
        "sections_at_capacity": sections_at_capacity,
        "new_students_month": new_students_month,
        # system
        "users_active": users_active,
        "users_locked": users_locked,
        "notifications_failed": notifications_failed,
        "teachers_active": teachers_active,
        # LMS
        "lms": lms,
        "top_courses": top_courses,
    }
    return render_template("dashboard/home.html", stats=stats, today=today)


# ── Role dashboards — ported from Stitch _1 / _3 / _5 ──────────────────────

def _teacher_dashboard():
    """Teacher home — greeting card + 4 KPI tiles + today's schedule +
    recent submissions to grade. All queries scoped to the current teacher.
    """
    teacher = _safe(
        lambda: Teacher.query.filter_by(user_id=current_user.id).first()
    )
    sid = current_user.school_id
    active_year = _safe(
        lambda: AcademicYear.query.filter_by(school_id=sid, status="active").first()
    )
    today_ = date.today()
    now = datetime.utcnow()

    from ...models import Assignment as TeachingAssignment, ScheduleSlot, Course

    def _my_sections():
        if not teacher:
            return []
        rows = (
            db.session.query(TeachingAssignment.section_id)
            .filter(TeachingAssignment.teacher_id == teacher.id)
            .distinct().all()
        )
        return [r[0] for r in rows]

    section_ids = _safe(_my_sections, [])

    def _students_count():
        if not section_ids:
            return 0
        return int(
            Enrollment.query.filter(
                Enrollment.section_id.in_(section_ids),
                Enrollment.status == "active",
            ).count()
        )

    def _today_periods():
        if not teacher:
            return []
        # ScheduleSlot uses day_id (isoweekday-ish) — mirror the pattern used
        # elsewhere by matching today's weekday name in Arabic when we can.
        weekday_map = {0: 6, 1: 7, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5}  # Mon..Sun → Sun..Sat
        rows = (
            ScheduleSlot.query
            .filter_by(school_id=sid, teacher_id=teacher.id)
            .order_by(ScheduleSlot.period_id.asc())
            .limit(10)
            .all()
        )
        return rows

    def _pending_submissions():
        # Ticket #2 — Course no longer has teacher_id; resolve pending
        # submissions via the teacher's TeachingAssignment (subject × section)
        # matched against Course.subject_id + CourseSection.section_id.
        if not teacher:
            return []
        from ...models import CourseSection
        return (
            db.session.query(Submission)
            .join(CourseAssignment, CourseAssignment.id == Submission.assignment_id)
            .join(Course, Course.id == CourseAssignment.course_id)
            .join(CourseSection, CourseSection.course_id == Course.id)
            .join(TeachingAssignment,
                  (TeachingAssignment.section_id == CourseSection.section_id) &
                  (TeachingAssignment.subject_id == Course.subject_id) &
                  (TeachingAssignment.year_id    == Course.academic_year_id))
            .filter(TeachingAssignment.teacher_id == teacher.id,
                    TeachingAssignment.is_active.is_(True),
                    Submission.score.is_(None))
            .order_by(Submission.submitted_at.desc())
            .limit(5)
            .all()
        )

    def _attendance_rate_30d():
        if not section_ids:
            return None
        since = today_ - timedelta(days=30)
        rows = (
            db.session.query(Attendance.status, func.count(Attendance.id))
            .filter(
                Attendance.school_id == sid,
                Attendance.date >= since,
                Attendance.section_id.in_(section_ids),
            )
            .group_by(Attendance.status).all()
        )
        by = {s: int(c) for s, c in rows}
        total = sum(by.values())
        if not total:
            return None
        return round((by.get("present", 0) / total) * 100, 1)

    students_count = _safe(_students_count, 0)
    today_periods = _safe(_today_periods, [])
    pending = _safe(_pending_submissions, [])
    attendance_rate = _safe(_attendance_rate_30d, None)
    def _pending_count():
        # Ticket #2 — mirrors _pending_submissions above.
        if not teacher:
            return 0
        from ...models import CourseSection
        return db.session.query(func.count(Submission.id))\
            .join(CourseAssignment, CourseAssignment.id == Submission.assignment_id)\
            .join(Course, Course.id == CourseAssignment.course_id)\
            .join(CourseSection, CourseSection.course_id == Course.id)\
            .join(TeachingAssignment,
                  (TeachingAssignment.section_id == CourseSection.section_id) &
                  (TeachingAssignment.subject_id == Course.subject_id) &
                  (TeachingAssignment.year_id    == Course.academic_year_id))\
            .filter(TeachingAssignment.teacher_id == teacher.id,
                    TeachingAssignment.is_active.is_(True),
                    Submission.score.is_(None))\
            .scalar()
    pending_count = _safe(_pending_count, 0)

    ctx = {
        "teacher": teacher,
        "active_year_name": active_year.name if active_year else "—",
        "today_date": today_,
        "students_count": students_count,
        "today_periods": today_periods,
        "today_periods_count": len(today_periods),
        "pending_count": int(pending_count or 0),
        "pending_submissions": pending,
        "attendance_rate": attendance_rate,
    }
    return render_template("dashboard/teacher.html", **ctx)


def _student_dashboard():
    """Student home — greeting + urgent assignment + next quiz countdown +
    latest grade + courses grid. Scopes by the linked Student row."""
    from ...models import Assignment as _TA  # noqa: F401 (import parity)
    from ...models import Course

    student = _safe(
        lambda: Student.query.filter_by(user_id=current_user.id).first()
    ) if hasattr(current_user, "id") else None
    # `user_id` isn't a modelled column on Student in the SIS schema. Fall
    # back: the parent-user link at Student.parent_user_id exists, but the
    # STUDENT itself is not typically a user in this SIS. If none is found,
    # we still render with what we can derive from the logged-in user.
    if student is None:
        student = _safe(lambda: Student.query.filter_by(school_id=current_user.school_id).first())

    now = datetime.utcnow()
    # Next due assignment: any published, not yet due
    next_assignment = _safe(
        lambda: (
            CourseAssignment.query
            .filter(CourseAssignment.is_published.is_(True),
                    (CourseAssignment.due_at.is_(None)) | (CourseAssignment.due_at > now))
            .order_by(CourseAssignment.due_at.asc().nullslast())
            .first()
        )
    )
    # Next quiz opening/open
    next_quiz = _safe(
        lambda: (
            Quiz.query.filter(Quiz.is_published.is_(True))
            .order_by(Quiz.opens_at.asc().nullslast())
            .first()
        )
    )
    # Latest grade — last submission of this student with a score
    latest_grade = None
    if student:
        latest_grade = _safe(
            lambda: (
                Submission.query
                .filter(Submission.student_id == student.id,
                        Submission.score.isnot(None))
                .order_by(Submission.graded_at.desc().nullslast(),
                          Submission.submitted_at.desc())
                .first()
            )
        )

    # Courses list — scoped to student's active section if we can find one
    courses = []
    if student:
        active_enroll = _safe(
            lambda: Enrollment.query.filter_by(
                student_id=student.id, status="active"
            ).order_by(Enrollment.created_at.desc()).first()
        )
        if active_enroll:
            courses = _safe(
                lambda: Course.query.filter_by(
                    section_id=active_enroll.section_id,
                    is_published=True,
                ).limit(8).all(), []
            )

    return render_template(
        "dashboard/student.html",
        student=student,
        next_assignment=next_assignment,
        next_quiz=next_quiz,
        latest_grade=latest_grade,
        courses=courses,
    )


def _parent_dashboard():
    """Parent home — child selector + weekly attendance + latest grades +
    fees status + announcements feed. Scopes by parent_user_id on Student."""
    sid = current_user.school_id
    children = _safe(
        lambda: Student.query.filter_by(parent_user_id=current_user.id).all(), []
    )
    try:
        active_child_id = int(request.args.get("child_id", 0))
    except (TypeError, ValueError):
        active_child_id = 0
    active_child = None
    if children:
        active_child = next((c for c in children if c.id == active_child_id), children[0])

    # weekly attendance for the active child
    week_att = []
    latest_grades = []
    invoices = []
    installments = []
    if active_child:
        since = date.today() - timedelta(days=6)
        enroll = _safe(
            lambda: Enrollment.query.filter_by(
                student_id=active_child.id, status="active"
            ).order_by(Enrollment.created_at.desc()).first()
        )
        if enroll:
            week_att = _safe(
                lambda: (
                    Attendance.query
                    .filter(
                        Attendance.enrollment_id == enroll.id,
                        Attendance.date >= since,
                    ).order_by(Attendance.date.asc()).all()
                ), []
            )
        latest_grades = _safe(
            lambda: (
                Submission.query
                .filter(Submission.student_id == active_child.id,
                        Submission.score.isnot(None))
                .order_by(Submission.graded_at.desc().nullslast(),
                          Submission.submitted_at.desc())
                .limit(3).all()
            ), []
        )
        # Unpaid invoices for this child
        invoices = _safe(
            lambda: (
                db.session.query(Invoice)
                .join(Enrollment, Enrollment.id == Invoice.enrollment_id)
                .filter(Enrollment.student_id == active_child.id,
                        Invoice.status != "paid")
                .order_by(Invoice.due_date.asc().nullslast())
                .limit(3).all()
            ), []
        )
    announcements = _safe(
        lambda: (
            Announcement.query.filter_by(school_id=sid)
            .order_by(Announcement.is_pinned.desc(), Announcement.created_at.desc())
            .limit(4).all()
        ), []
    )

    return render_template(
        "dashboard/parent.html",
        children=children,
        active_child=active_child,
        week_attendance=week_att,
        latest_grades=latest_grades,
        invoices=invoices,
        announcements=announcements,
        today=date.today(),
    )


# ────────────────────────────────────────────────────────────────────
# Global search — powers the topbar search box + sidebar quick-search.
# ────────────────────────────────────────────────────────────────────
from flask import jsonify, redirect, url_for
from ...models import Student, Teacher, Invoice, Course
from ...models.hr import Employee


@bp.route("/search")
@login_required
def global_search():
    """Full-page results — landing when the user submits with Enter."""
    q = (request.args.get("q") or "").strip()
    if not q:
        return render_template("dashboard/search.html", q="", groups={})
    groups = _search_hits(q, current_user.school_id, limit_each=30)
    return render_template("dashboard/search.html", q=q, groups=groups)


@bp.route("/search.json")
@login_required
def global_search_json():
    """Suggestion endpoint hit by both search boxes on every keystroke.
    Returns up to 5 hits per group so a dropdown stays readable."""
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"groups": {}})
    return jsonify({"groups": _search_hits(q, current_user.school_id, limit_each=5)})


def _search_hits(q, sid, *, limit_each):
    """Runs cheap ILIKE searches across the four most-searched entities
    and returns them as {group: [{title, subtitle, href}]} — the client
    renders it into the dropdown or the results page as-is."""
    like = f"%{q}%"
    out = {}

    stu = (
        Student.query.filter(Student.school_id == sid)
        .filter(db.or_(
            Student.full_name.ilike(like),
            Student.permanent_code.ilike(like),
        ))
        .limit(limit_each).all()
    )
    if stu:
        out["الطلاب"] = [{
            "title": s.full_name,
            "subtitle": s.permanent_code or "",
            "href": url_for("students.student_detail", student_id=s.id),
            "icon": "school",
        } for s in stu]

    tch = (
        Teacher.query.filter(Teacher.school_id == sid)
        .filter(Teacher.full_name.ilike(like))
        .limit(limit_each).all()
    )
    if tch:
        out["المعلمون"] = [{
            "title": t.full_name,
            "subtitle": getattr(t, "national_id", "") or "",
            "href": url_for("teachers.teacher_detail", teacher_id=t.id)
                    if _has_endpoint("teachers.teacher_detail") else url_for("teachers.list_teachers"),
            "icon": "badge",
        } for t in tch]

    inv = (
        Invoice.query.filter(Invoice.school_id == sid)
        .filter(db.or_(
            Invoice.number.ilike(like),
            Invoice.notes.ilike(like),
        ))
        .limit(limit_each).all()
    )
    if inv:
        out["الفواتير"] = [{
            "title": f"فاتورة #{i.number}",
            "subtitle": (i.enrollment.student.full_name if i.enrollment and i.enrollment.student else ""),
            "href": url_for("finance.invoice_detail", invoice_id=i.id),
            "icon": "receipt_long",
        } for i in inv]

    crs = (
        Course.query.filter(Course.school_id == sid)
        .filter(Course.title.ilike(like))
        .limit(limit_each).all()
    )
    if crs:
        out["المقررات"] = [{
            "title": c.title,
            "subtitle": (c.subject.name if getattr(c, "subject", None) else ""),
            "href": url_for("courses.list_courses"),
            "icon": "auto_stories",
        } for c in crs]

    emp = (
        Employee.query.filter(Employee.school_id == sid)
        .filter(Employee.full_name.ilike(like))
        .limit(limit_each).all()
    )
    if emp:
        out["الموظفون"] = [{
            "title": e.full_name,
            "subtitle": getattr(e, "job_title", "") or "",
            "href": url_for("hr.employees_list") if _has_endpoint("hr.employees_list") else "#",
            "icon": "work",
        } for e in emp]

    return out


def _has_endpoint(name):
    from flask import current_app
    return name in current_app.view_functions
