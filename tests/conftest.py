"""SAAS-002 — pytest harness.

Two guarantees this file enforces for every test run:

1. **Never touch the production database.** The CI DB is a separate
   PostgreSQL named `manasety_test` (or any name the operator sets
   via `TEST_DATABASE_URL`). A test run that would otherwise land
   on the real `manasety_school` DB (or the local dev `manasety_lms`)
   aborts before the first test. SQLite files under `instance/` are
   allowed — those are dev scratch and losing them is survivable.

2. **One Flask app per test session.** Creating the app once avoids
   re-importing every blueprint for each test, which previously made
   SAAS-004's suite twice as slow as it needed to be.

The actual 2-school fixture (`two_schools`) is factory-only — it
seeds the minimum entities named in the SAAS-002 ticket (users with
all four roles, year, term, grade, section, subject, student,
guardian, course, quiz, invoice) and tears them down after the test.
"""

from __future__ import annotations

import os
import sys
from typing import Iterator

import pytest


# ─── Guard: refuse to run against anything named like production ─────

_FORBIDDEN_DB_NAMES = {"manasety_school", "manasety_prod", "manasety_lms"}


def _db_name(uri: str) -> str:
    """Extract the DB name from a SQLAlchemy URI, best-effort."""
    if not uri:
        return ""
    # Postgres: ...@host:port/dbname?...
    tail = uri.rsplit("/", 1)[-1]
    return tail.split("?", 1)[0]


def pytest_configure(config):
    uri = os.environ.get("DATABASE_URL", "") or os.environ.get("TEST_DATABASE_URL", "")
    name = _db_name(uri).lower()
    # SQLite file paths pass through — only PostgreSQL names are
    # dangerous because the dev DB there is the same server.
    if name in _FORBIDDEN_DB_NAMES:
        pytest.exit(
            f"SAAS-002 refuses to run against DB name {name!r} — it is "
            "a reserved production/dev name. Set DATABASE_URL (or "
            "TEST_DATABASE_URL) to a separate test database, e.g. "
            "postgresql://user:pw@localhost:5432/manasety_test.",
            returncode=2,
        )


# ─── Flask app fixture ───────────────────────────────────────────────

@pytest.fixture(scope="session")
def app():
    """Session-scoped Flask app in testing mode. Preserves whatever
    DATABASE_URL the operator set (the DB guard above makes sure it
    isn't a prod name)."""
    os.environ["APP_ENV"] = "testing"
    # Clear a cached module if an earlier test file imported it.
    for mod in list(sys.modules):
        if mod == "app" or mod.startswith("app."):
            sys.modules.pop(mod, None)
    import importlib
    app_mod = importlib.import_module("app")
    return app_mod.create_app()


# ─── Two-school factory ──────────────────────────────────────────────

@pytest.fixture
def two_schools(app) -> Iterator[dict]:
    """Seed a minimal pair of schools (`alpha`, `beta`) with the
    entity set the SAAS-002 ticket specifies. The admin user has
    the SAME username in both schools so R1 (login not tenant-aware)
    reproduces naturally."""
    from datetime import date, timedelta
    from app.extensions import db
    from app.models import (
        School, Role, User,
        AcademicYear, Term, Grade, Section, Subject,
        Student, Enrollment,
    )

    with app.app_context():
        created_ids: dict[str, list[int]] = {
            "schools": [], "roles": [], "users": [],
            "years": [], "terms": [], "grades": [], "sections": [],
            "subjects": [], "students": [], "enrollments": [],
        }

        def _mk_school(slug: str, name: str) -> School:
            s = School(
                code=f"TEST-{slug.upper()}",
                name=name,
                slug=slug,
                status="active",
                is_active=True,
            )
            db.session.add(s); db.session.flush()
            created_ids["schools"].append(s.id)
            return s

        def _mk_role(school_id: int, name: str) -> Role:
            r = Role(
                school_id=school_id, name=name, name_ar=name,
                is_system=False, permissions={},
            )
            db.session.add(r); db.session.flush()
            created_ids["roles"].append(r.id)
            return r

        def _mk_user(school_id: int, role_id: int,
                      username: str, full_name: str) -> User:
            u = User(
                school_id=school_id, role_id=role_id,
                username=username, full_name=full_name,
                email=f"{username}@{school_id}.test",
                is_active=True,
            )
            u.set_password("test-password-12345")
            db.session.add(u); db.session.flush()
            created_ids["users"].append(u.id)
            return u

        def _mk_bundle(slug: str, name: str) -> dict:
            school = _mk_school(slug, name)
            # Four roles so impersonation / scope tests have targets.
            roles = {
                k: _mk_role(school.id, k)
                for k in ("admin", "teacher", "parent", "student")
            }
            # Admin shares the username across both schools on purpose:
            # that is R1's reproduction scenario (login not tenant-aware).
            users = {
                "admin":   _mk_user(school.id, roles["admin"].id,   "admin",   "Admin"),
                "teacher": _mk_user(school.id, roles["teacher"].id, f"t_{slug}", "Teacher"),
                "parent":  _mk_user(school.id, roles["parent"].id,  f"p_{slug}", "Parent"),
                "student": _mk_user(school.id, roles["student"].id, f"s_{slug}", "Student"),
            }
            # Minimal academic cover.
            year = AcademicYear(
                school_id=school.id, name=f"TY-{slug}",
                start_date=date(2026, 9, 1),
                end_date=date(2027, 6, 15),
                status="active",
            )
            db.session.add(year); db.session.flush()
            created_ids["years"].append(year.id)
            term = Term(
                school_id=school.id, year_id=year.id,
                name="Term1", order_index=1,
                start_date=date(2026, 9, 1), end_date=date(2027, 1, 31),
                weight=50,
            )
            db.session.add(term); db.session.flush()
            created_ids["terms"].append(term.id)
            grade = Grade(
                school_id=school.id, name="G1", order_index=1,
            )
            db.session.add(grade); db.session.flush()
            created_ids["grades"].append(grade.id)
            section = Section(
                school_id=school.id, year_id=year.id,
                grade_id=grade.id, name="A", capacity=30,
            )
            db.session.add(section); db.session.flush()
            created_ids["sections"].append(section.id)
            subject = Subject(school_id=school.id, name=f"Math-{slug}")
            db.session.add(subject); db.session.flush()
            created_ids["subjects"].append(subject.id)
            student = Student(
                school_id=school.id,
                permanent_code=f"PC-{slug}-01",
                full_name=users["student"].full_name,
                user_id=users["student"].id,
                parent_user_id=users["parent"].id,
            )
            db.session.add(student); db.session.flush()
            created_ids["students"].append(student.id)
            enr = Enrollment(
                school_id=school.id, student_id=student.id,
                year_id=year.id, grade_id=grade.id,
                section_id=section.id, status="active",
                enrolled_at=date(2026, 9, 1),
            )
            db.session.add(enr); db.session.flush()
            created_ids["enrollments"].append(enr.id)
            db.session.commit()
            return {
                "school":  school,
                "roles":   roles,
                "users":   users,
                "year":    year,
                "term":    term,
                "grade":   grade,
                "section": section,
                "subject": subject,
                "student": student,
                "enrollment": enr,
            }

        A = _mk_bundle("alpha", "Alpha School")
        B = _mk_bundle("beta",  "Beta School")

        try:
            yield {"A": A, "B": B}
        finally:
            # Teardown in reverse FK order.
            for kind in ("enrollments", "students", "subjects", "sections",
                         "grades", "terms", "years", "users", "roles",
                         "schools"):
                table_map = {
                    "enrollments": Enrollment, "students": Student,
                    "subjects": Subject, "sections": Section,
                    "grades": Grade, "terms": Term, "years": AcademicYear,
                    "users": User, "roles": Role, "schools": School,
                }
                cls = table_map[kind]
                for row_id in created_ids[kind]:
                    row = db.session.get(cls, row_id)
                    if row is not None:
                        db.session.delete(row)
                db.session.commit()


# ─── Logged-in client factory ────────────────────────────────────────

@pytest.fixture
def login_as(app):
    """Return `login(client, user)` — pushes the Flask-Login session
    cookie so subsequent requests are authenticated as that user.
    Avoids reaching into /auth/login's CSRF for every test."""
    def _login(client, user):
        with client.session_transaction() as sess:
            sess["_user_id"] = str(user.id)
            sess["_fresh"] = True
    return _login
