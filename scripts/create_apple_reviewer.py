"""Seed / reset the App Store Review demo accounts (parent + teacher).

Run this ONCE on the production server whenever Apple's review team
needs a working login for either app. It is idempotent — safe to
re-run — and creates BOTH accounts:

    apple_reviewer         → parent app (linked to first student)
    apple_reviewer_teacher → teacher app (linked to one active section)

Usage:

    cd /path/to/schoolsudan
    source .venv/bin/activate       # or however you activate on prod
    python scripts/create_apple_reviewer.py

Prints the credentials at the end. Copy them into
App Store Connect → App → App Information → Sign-In Information
for each of the two apps.
"""
from __future__ import annotations

import sys

from app import create_app
from app.extensions import db
from app.models import (
    Assignment,
    Role,
    School,
    Student,
    Teacher,
    User,
)


PARENT_USERNAME = "apple_reviewer"
PARENT_PASSWORD = "AppReview2026!"
PARENT_FULL_NAME = "Apple App Store Reviewer (Parent)"
PARENT_EMAIL = "apple-review-parent@manasety.ai"

TEACHER_USERNAME = "apple_reviewer_teacher"
TEACHER_PASSWORD = "AppReview2026!"
TEACHER_FULL_NAME = "Apple App Store Reviewer (Teacher)"
TEACHER_EMAIL = "apple-review-teacher@manasety.ai"
TEACHER_SPECIALIZATION = "App Review Access"


# ---------- helpers ----------------------------------------------------------

def _get_or_die(school: School, kind: str, name_patterns: list[str]) -> Role:
    """Find a role matching any of the patterns (case-insensitive), or exit."""
    q = Role.query.filter_by(school_id=school.id)
    filters = []
    for pat in name_patterns:
        filters.append(Role.name.ilike(f"%{pat}%"))
        filters.append(Role.name_ar.ilike(f"%{pat}%"))
    role = q.filter(db.or_(*filters)).first()
    if not role:
        sys.exit(
            f"❌ Could not find a {kind} role in the DB "
            f"(searched for {name_patterns}). Create one from the admin UI "
            f"first, then rerun this script."
        )
    return role


def _upsert_user(
    school: School, role: Role, username: str, password: str,
    full_name: str, email: str,
) -> tuple[User, bool]:
    """Insert or update a user; returns (user, was_created)."""
    user = User.query.filter_by(school_id=school.id, username=username).first()
    created = False
    if user:
        print(f"↻ Existing '{username}' found (id={user.id}) — resetting password.")
    else:
        user = User(
            school_id=school.id,
            role_id=role.id,
            username=username,
            full_name=full_name,
            email=email,
        )
        db.session.add(user)
        created = True
        print(f"＋ Creating '{username}' in '{school.name}'.")

    user.role_id = role.id
    user.is_active = True
    user.failed_attempts = 0
    user.locked_until = None
    user.set_password(password)
    db.session.flush()
    return user, created


# ---------- parent -----------------------------------------------------------

def _seed_parent(school: School) -> tuple[str, Student]:
    role = _get_or_die(school, "Parent", ["parent", "أمر"])

    student = (
        Student.query.filter_by(school_id=school.id)
        .order_by(Student.id.asc())
        .first()
    )
    if not student:
        sys.exit(
            "❌ No students in the DB — reviewer needs a child to see the "
            "parent app. Add a student first."
        )

    user, _ = _upsert_user(
        school, role, PARENT_USERNAME, PARENT_PASSWORD,
        PARENT_FULL_NAME, PARENT_EMAIL,
    )

    if student.parent_user_id != user.id:
        student.parent_user_id = user.id
        print(f"🔗 Linked parent reviewer to student '{student.full_name}' (id={student.id}).")
    else:
        print(f"✓ Parent reviewer already linked to student id={student.id}.")

    return user.username, student


# ---------- teacher ----------------------------------------------------------

def _seed_teacher(school: School) -> tuple[str, list[Assignment]]:
    role = _get_or_die(school, "Teacher", ["teacher", "معلم", "مدرس"])

    template_assignment = (
        Assignment.query.filter_by(school_id=school.id, is_active=True)
        .order_by(Assignment.id.asc())
        .first()
    )
    if not template_assignment:
        sys.exit(
            "❌ No active assignments in the DB — the reviewer teacher needs "
            "at least one section+subject to see the teacher app. Assign a "
            "teacher first."
        )

    user, user_created = _upsert_user(
        school, role, TEACHER_USERNAME, TEACHER_PASSWORD,
        TEACHER_FULL_NAME, TEACHER_EMAIL,
    )

    teacher = Teacher.query.filter_by(user_id=user.id).first()
    if not teacher:
        teacher = Teacher(
            school_id=school.id,
            user_id=user.id,
            full_name=TEACHER_FULL_NAME,
            specialization=TEACHER_SPECIALIZATION,
            is_active=True,
        )
        db.session.add(teacher)
        db.session.flush()
        print(f"＋ Created Teacher record (id={teacher.id}) for '{user.username}'.")
    else:
        teacher.is_active = True

    # Clone the template assignment onto the reviewer teacher, if not already.
    existing = Assignment.query.filter_by(
        year_id=template_assignment.year_id,
        section_id=template_assignment.section_id,
        subject_id=template_assignment.subject_id,
        teacher_id=teacher.id,
    ).first()
    if existing:
        assignments = [existing]
        print(f"✓ Reviewer teacher already assigned to section id={template_assignment.section_id}.")
    else:
        cloned = Assignment(
            school_id=school.id,
            year_id=template_assignment.year_id,
            section_id=template_assignment.section_id,
            subject_id=template_assignment.subject_id,
            teacher_id=teacher.id,
            is_active=True,
            weekly_periods=1,
        )
        db.session.add(cloned)
        db.session.flush()
        assignments = [cloned]
        print(
            f"🔗 Assigned reviewer teacher to section id={template_assignment.section_id}, "
            f"subject id={template_assignment.subject_id}."
        )

    return user.username, assignments


# ---------- main -------------------------------------------------------------

def main() -> None:
    app = create_app()
    with app.app_context():
        school = School.query.order_by(School.id.asc()).first()
        if not school:
            sys.exit("❌ No school records found — nothing to attach reviewers to.")

        _, student = _seed_parent(school)
        _, assignments = _seed_teacher(school)

        db.session.commit()

        bar = "=" * 68
        print("\n" + bar)
        print("✅ Apple Reviewer accounts are ready.")
        print("   Paste each block into its App Store Connect app record →")
        print("   App Information → Sign-In Information.")
        print(bar)
        print(f"[PARENT app: مدرسة صالح الشريف]")
        print(f"  Username : {PARENT_USERNAME}")
        print(f"  Password : {PARENT_PASSWORD}")
        print(f"  Linked to student: {student.full_name} (id={student.id})")
        print(bar)
        print(f"[TEACHER app: مدرسة صالح الشريف — معلمين]")
        print(f"  Username : {TEACHER_USERNAME}")
        print(f"  Password : {TEACHER_PASSWORD}")
        for a in assignments:
            print(
                f"  Assigned to section id={a.section_id}, subject id={a.subject_id}, "
                f"year id={a.year_id}"
            )
        print(bar)


if __name__ == "__main__":
    main()
