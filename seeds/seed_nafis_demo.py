"""Seed a full NAFIS demo dataset: one cycle, per-student results for
grades 3/6/9, outcome-level scores, derived gaps, and intervention plans.

Run with:  python -m seeds.seed_nafis_demo
"""
import random
import sys
from datetime import date, datetime, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

from app import create_app
from app.extensions import db
from app.models import School, AcademicYear, Grade, Enrollment, Teacher
from app.models.nafis import (
    LearningOutcome, NafisCycle, NafisResult, NafisOutcomeScore,
    StudentGap, InterventionPlan, InterventionPlanOutcome, InterventionSession,
)

random.seed(33)

LEVEL_GRADE_ORDER = {"g3": 3, "g6": 6, "g9": 9}
SUBJECTS = ["reading", "math", "science"]
BAND_BY_PCT = [
    (85, "mastered"), (70, "above"), (50, "minimum"), (0, "below"),
]


def band_for(pct):
    for threshold, band in BAND_BY_PCT:
        if pct >= threshold:
            return band
    return "below"


def run():
    app = create_app()
    with app.app_context():
        school = School.query.first()
        year = AcademicYear.query.filter_by(school_id=school.id, status="active").first()

        cycle = NafisCycle.query.filter_by(school_id=school.id, name_ar="دورة نافس 1447/2026").first()
        if not cycle:
            cycle = NafisCycle(
                school_id=school.id, academic_year_id=year.id,
                name_ar="دورة نافس 1447/2026", hijri_year="1447", gregorian_year=2026,
                start_date=date(2026, 3, 1), end_date=date(2026, 3, 20),
                levels="g3,g6,g9", status="completed",
            )
            db.session.add(cycle)
            db.session.flush()
            print("OK cycle created")
        db.session.commit()

        outcomes_cache = {}
        for level in LEVEL_GRADE_ORDER:
            for subj in SUBJECTS:
                rows = LearningOutcome.query.filter_by(subject=subj, level=level).all()
                leaves = [o for o in rows if o.kind in ("indicator", "standard")]
                outcomes_cache[(subj, level)] = leaves or rows

        total_results = 0
        total_outcome_scores = 0
        total_gaps = 0
        total_plans = 0
        total_sessions = 0

        teachers = Teacher.query.filter_by(school_id=school.id).all()

        for level, grade_order in LEVEL_GRADE_ORDER.items():
            grade = Grade.query.filter_by(school_id=school.id, order_index=grade_order).first()
            if not grade:
                continue
            enrollments = (
                Enrollment.query.filter_by(school_id=school.id, year_id=year.id, grade_id=grade.id)
                .all()
            )
            for enr in enrollments:
                student = enr.student
                gap_outcome_ids = []

                for subj in SUBJECTS:
                    existing = NafisResult.query.filter_by(
                        cycle_id=cycle.id, student_id=student.id, subject=subj,
                    ).first()
                    if existing:
                        result = existing
                    else:
                        total_q = random.choice([30, 40, 50])
                        pct = round(random.uniform(35, 98), 2)
                        raw = round(total_q * pct / 100)
                        result = NafisResult(
                            school_id=school.id, cycle_id=cycle.id, student_id=student.id,
                            level=level, subject=subj,
                            raw_score=raw, total_questions=total_q,
                            percentage=pct, band=band_for(pct),
                            national_percentile=round(random.uniform(10, 99), 2),
                        )
                        db.session.add(result)
                        db.session.flush()
                        total_results += 1

                    pool = outcomes_cache.get((subj, level), [])
                    if not pool:
                        continue
                    sample = random.sample(pool, min(5, len(pool)))
                    for outcome in sample:
                        exists = NafisOutcomeScore.query.filter_by(
                            result_id=result.id, outcome_id=outcome.id,
                        ).first()
                        if exists:
                            continue
                        score_pct = round(random.uniform(20, 100), 2)
                        mastered = score_pct >= 60
                        db.session.add(NafisOutcomeScore(
                            result_id=result.id, outcome_id=outcome.id,
                            mastered=mastered, score_pct=score_pct,
                        ))
                        total_outcome_scores += 1
                        if not mastered:
                            gap_outcome_ids.append(outcome.id)

                for outcome_id in gap_outcome_ids[:2]:
                    exists = StudentGap.query.filter_by(
                        student_id=student.id, outcome_id=outcome_id,
                    ).first()
                    if exists:
                        continue
                    severity = random.choice(["critical", "moderate", "mild"])
                    db.session.add(StudentGap(
                        school_id=school.id, student_id=student.id, outcome_id=outcome_id,
                        severity=severity, source="nafis",
                        evidence_ref=f"nafis_result:{result.id}",
                    ))
                    total_gaps += 1

                db.session.commit()

                if gap_outcome_ids and random.random() < 0.25:
                    plan = InterventionPlan(
                        school_id=school.id, student_id=student.id,
                        owner_teacher_id=random.choice(teachers).id if teachers else None,
                        title_ar=f"خطة علاجية — {student.full_name}",
                        description="خطة لمعالجة الفجوات التعليمية الناتجة عن نتائج نافس.",
                        start_date=date(2026, 4, 1), end_date=date(2026, 5, 15),
                        status=random.choice(["draft", "active", "completed"]),
                    )
                    db.session.add(plan)
                    db.session.flush()
                    total_plans += 1

                    for outcome_id in gap_outcome_ids[:2]:
                        db.session.add(InterventionPlanOutcome(
                            plan_id=plan.id, outcome_id=outcome_id,
                        ))

                    n_sessions = random.randint(2, 4)
                    for s_idx in range(n_sessions):
                        db.session.add(InterventionSession(
                            plan_id=plan.id,
                            session_date=date(2026, 4, 1) + timedelta(days=s_idx * 7),
                            duration_minutes=random.choice([30, 45, 60]),
                            attended=random.choice([True, True, False, None]),
                            notes="ملاحظات الجلسة العلاجية.",
                        ))
                        total_sessions += 1
                    db.session.commit()

            print(f"OK {grade.name} ({level}): {len(enrollments)} enrollment(s)")

        print(
            f"\nDone. Results: {total_results} | Outcome scores: {total_outcome_scores} | "
            f"Gaps: {total_gaps} | Plans: {total_plans} | Sessions: {total_sessions}"
        )


if __name__ == "__main__":
    run()
