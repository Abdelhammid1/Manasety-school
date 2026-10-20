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
from pathlib import Path
from typing import Iterator

import pytest


# Set APP_ENV before any test module imports `app.*`. If this runs
# only inside the fixture, test files that `from app.services.tenancy
# import ...` at module level fail collection when the shell lacks
# JWT_SIGNING_KEY (SAAS-007 refuses to boot production without it).
os.environ.setdefault("APP_ENV", "testing")
if os.environ.get("APP_ENV") == "production":
    os.environ["APP_ENV"] = "testing"

# Point the tests at a dedicated SQLite file next to this conftest so
# the SAAS-002 guard can safely stop writes against the dev DB. The
# file is created on first run and migrated to current head.
# If the operator already set DATABASE_URL / TEST_DATABASE_URL, respect it.
if not os.environ.get("DATABASE_URL") and not os.environ.get("TEST_DATABASE_URL"):
    _test_db_path = (Path(__file__).parent / "_test.db").resolve()
    os.environ["DATABASE_URL"] = f"sqlite:///{_test_db_path.as_posix()}"


# ─── Guard: refuse to run against anything named like production ─────

# Postgres DBs — direct name match.
_FORBIDDEN_DB_NAMES = {"manasety_school", "manasety_prod", "manasety_lms"}
# SQLite file names — the dev stack uses instance/manasety.db by
# default. Running tests against it pollutes the dev DB with fixture
# leftovers (orphan Employee rows, duplicate admin users, etc.).
# Discovered the hard way after the 2-school SAAS fixture dumped
# half a dozen hex-tagged users into the dev DB.
_FORBIDDEN_DB_FILENAMES = {"manasety.db"}


def _db_name(uri: str) -> str:
    """Extract the DB name (postgres) or filename (sqlite) from a
    SQLAlchemy URI, best-effort."""
    if not uri:
        return ""
    tail = uri.rsplit("/", 1)[-1]
    return tail.split("?", 1)[0]


def pytest_configure(config):
    uri = os.environ.get("DATABASE_URL", "") or os.environ.get("TEST_DATABASE_URL", "")
    name = _db_name(uri).lower()
    is_sqlite = uri.lower().startswith("sqlite")
    forbidden = (name in _FORBIDDEN_DB_NAMES) or (
        is_sqlite and name in _FORBIDDEN_DB_FILENAMES
    )
    if forbidden:
        pytest.exit(
            f"SAAS-002 refuses to run against DB {name!r} — it is a "
            "reserved production/dev target. Set DATABASE_URL (or "
            "TEST_DATABASE_URL) to a separate test database, e.g. "
            "sqlite:///:memory: for a quick throwaway, or "
            "postgresql://user:pw@localhost:5432/manasety_test.",
            returncode=2,
        )


# ─── Flask app fixture ───────────────────────────────────────────────

@pytest.fixture(scope="session")
def app():
    """Session-scoped Flask app in testing mode. Preserves whatever
    DATABASE_URL the operator set (the DB guard above makes sure it
    isn't a prod name).

    Tenancy is wired to `log` mode with BASE_DOMAIN=manasety.ai so
    SAAS-006's cross-tenant checks engage during tests. Individual
    cases that need a different mode override `app.config` directly."""
    os.environ["APP_ENV"] = "testing"
    for mod in list(sys.modules):
        if mod == "app" or mod.startswith("app."):
            sys.modules.pop(mod, None)
    import importlib
    app_mod = importlib.import_module("app")
    app = app_mod.create_app()
    # Second guard — now that config is resolved (incl. .env loading),
    # check the EFFECTIVE DB URI. pytest_configure can't see this
    # because it runs before dotenv kicks in.
    effective = (app.config.get("SQLALCHEMY_DATABASE_URI") or "").strip()
    _eff_name = _db_name(effective).lower()
    _is_sqlite = effective.lower().startswith("sqlite")
    if (_eff_name in _FORBIDDEN_DB_NAMES) or (
        _is_sqlite and _eff_name in _FORBIDDEN_DB_FILENAMES
    ):
        pytest.exit(
            f"SAAS-002 refuses to run against DB {_eff_name!r} resolved "
            f"from app config — set DATABASE_URL in the environment "
            "(or TEST_DATABASE_URL) to a separate test database. "
            "Example: `DATABASE_URL=sqlite:///./_test.db pytest ...`.",
            returncode=2,
        )
    # Create tables for the throwaway sqlite file on first use. SAAS
    # tests expect every model to exist; without this bootstrap the
    # first fixture insert fails with "no such table".
    with app.app_context():
        from app.extensions import db
        db.create_all()
    app.config["BASE_DOMAIN"] = "manasety.ai"
    app.config["PLATFORM_HOSTS"] = ["lms.manasety.ai"]
    app.config["LEGACY_HOSTS"] = {"school.manasety.ai": "demo"}
    app.config["TENANT_RESOLUTION_MODE"] = "log"
    _register_isolation_canary(app)
    return app


def _register_isolation_canary(app) -> None:
    """SAAS-012 "test of the test": one deliberately leaky endpoint and
    one correctly scoped twin. The harness must flag the first and pass
    the second. Registered before the first request (Flask forbids
    adding routes later) and only ever in the test app."""
    from flask import Blueprint, abort
    from flask_login import login_required
    from app.extensions import db
    from app.models import Student
    from app.services.tenancy import current_school_id

    bp = Blueprint("saas012_canary", __name__, url_prefix="/__canary")

    @bp.route("/leaky/<int:student_id>")
    @login_required
    def leaky(student_id):
        s = db.session.get(Student, student_id)   # no tenant filter
        if s is None:
            abort(404)
        return f"<p>{s.full_name} {s.permanent_code}</p>"

    @bp.route("/scoped/<int:student_id>")
    @login_required
    def scoped(student_id):
        s = Student.query.filter_by(
            id=student_id, school_id=current_school_id()).first_or_404()
        return f"<p>{s.full_name} {s.permanent_code}</p>"

    app.register_blueprint(bp)


# ─── Harness role permissions ────────────────────────────────────────

def _all_permission_modules() -> list[str]:
    """Every module name the app checks, so the harness admin is never
    stopped by a permission gate — a 403 must mean isolation held."""
    import re as _re
    from app.models.user import PERMISSION_MODULES
    mods = set(PERMISSION_MODULES)
    pat = _re.compile(r"""(?:require_permission|\.can)\(\s*["']([a-z_]+)["']""")
    for f in (Path(__file__).parents[1] / "app").rglob("*.py"):
        mods.update(pat.findall(f.read_text(encoding="utf-8")))
    for f in (Path(__file__).parents[1] / "app" / "templates").rglob("*.html"):
        mods.update(pat.findall(f.read_text(encoding="utf-8")))
    return sorted(mods)


def harness_role_permissions(role: str) -> dict:
    """Realistic grants per role. An empty dict (the old default) made
    every cross-tenant request 403 on permissions, so the isolation
    sweep passed without testing isolation at all."""
    from app.models.user import PERMISSION_ACTIONS
    if role == "admin":
        return {m: list(PERMISSION_ACTIONS) for m in _all_permission_modules()}
    if role == "teacher":
        return {
            "attendance": ["view", "add", "edit"],
            "results":    ["view", "add", "edit"],
            "schedule":   ["view"],
            "portal":     ["view", "add", "edit"],
            "students":   ["view"],
            "teachers":   ["view"],
            "lms":        ["view", "add", "edit", "delete"],
        }
    if role == "parent":
        return {"portal": ["view"], "finance": ["view"]}
    if role == "student":
        return {"portal": ["view"]}
    return {}


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
                is_system=False, permissions=harness_role_permissions(name),
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
                "admin":   _mk_user(school.id, roles["admin"].id,   "admin",   f"Admin-{slug}"),
                "teacher": _mk_user(school.id, roles["teacher"].id, f"t_{slug}", f"Teacher-{slug}"),
                "parent":  _mk_user(school.id, roles["parent"].id,  f"p_{slug}", f"Parent-{slug}"),
                "student": _mk_user(school.id, roles["student"].id, f"s_{slug}", f"Student-{slug}"),
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
                name=f"Term1-{slug}", order_index=1,
                start_date=date(2026, 9, 1), end_date=date(2027, 1, 31),
                weight=50,
            )
            db.session.add(term); db.session.flush()
            created_ids["terms"].append(term.id)
            grade = Grade(
                school_id=school.id, name=f"G1-{slug}", order_index=1,
            )
            db.session.add(grade); db.session.flush()
            created_ids["grades"].append(grade.id)
            section = Section(
                school_id=school.id, year_id=year.id,
                grade_id=grade.id, name=f"Sec-{slug}", capacity=30,
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
                # Strings unique to this school — a cross-tenant sweep
                # fails if any of them shows up in another school's response.
                "markers": (
                    f"PC-{slug}-01", f"Math-{slug}", f"Student-{slug}",
                    f"TY-{slug}", f"Sec-{slug}", f"G1-{slug}",
                ),
            }

        A = _mk_bundle("alpha", "Alpha School")
        B = _mk_bundle("beta",  "Beta School")

        # Load every column, then detach. Yielding while this app context
        # is still pushed made test-client requests reuse it — and its
        # session — so requests saw stale identity-map rows (e.g. role
        # permissions changed elsewhere read back as the old value).
        for bundle in (A, B):
            for v in bundle.values():
                for obj in (v.values() if isinstance(v, dict) else [v]):
                    if isinstance(obj, db.Model):
                        db.session.refresh(obj)
        db.session.expunge_all()
        db.session.remove()

    try:
        yield {"A": A, "B": B}
    finally:
        with app.app_context():
            # Teardown in reverse FK order.
            table_map = {
                "enrollments": Enrollment, "students": Student,
                "subjects": Subject, "sections": Section,
                "grades": Grade, "terms": Term, "years": AcademicYear,
                "users": User, "roles": Role, "schools": School,
            }
            for kind in ("enrollments", "students", "subjects", "sections",
                         "grades", "terms", "years", "users", "roles",
                         "schools"):
                cls = table_map[kind]
                for row_id in created_ids[kind]:
                    row = db.session.get(cls, row_id)
                    if row is not None:
                        db.session.delete(row)
                db.session.commit()
            db.session.remove()


# ─── Logged-in client factory ────────────────────────────────────────

@pytest.fixture
def login_as(app):
    """Return `login(client, user, base_url=None)` — pushes the
    Flask-Login session cookie so subsequent requests are authenticated
    as that user. Avoids reaching into /auth/login's CSRF for every
    test.

    When `base_url` is passed, the session cookie is scoped to that
    host — required when tests use `base_url="http://alpha.manasety.ai"`
    on their actual requests, otherwise Werkzeug stores the cookie
    under `localhost` and no subsequent host-scoped request sees it."""
    def _login(client, user, base_url=None):
        kwargs = {"base_url": base_url} if base_url else {}
        with client.session_transaction(**kwargs) as sess:
            sess["_user_id"] = str(user.id)
            sess["_fresh"] = True
    return _login
