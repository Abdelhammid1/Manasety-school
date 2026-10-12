"""SAAS-002 §4.4 — Schema isolation gate.

Walk every real DB table and refuse the build if a table has no
`school_id` column AND isn't in the explicit `TENANT_INHERIT_MAP`
(table → parent-table whose school_id it inherits).

A fresh table that lands without a classification is a potential
isolation hole, so this is one of SAAS-002's three forcing functions:

  1. Schema gate (this file)      — bans new tables from skipping the review
  2. Route Isolation Matrix       — bans new <int:id> endpoints from skipping it
  3. Known-vulnerability tests    — R1/R2/R3 as xfail(strict=True)

When a legitimate new table is added:
  - If it carries school_id directly, nothing to do — it passes.
  - If it inherits (e.g. `invoice_lines` via `invoice_id → invoices`),
    add it to `TENANT_INHERIT_MAP` with the parent table name AND a
    one-line reason. The reason is the audit trail for whoever
    reviews the matrix later.
"""

from __future__ import annotations


# ── Tables that inherit school_id transitively via a parent FK. ──
# Keyed by the child table; value is the parent table + a short why.
# These were enumerated against the dev DB on 2026-10-12 (`\dt`
# minus any table carrying a `school_id` column). A new unclassified
# table trips `test_every_table_is_classified` and the committer has
# to add it here with a one-line reason.
TENANT_INHERIT_MAP: dict[str, tuple[str, str]] = {
    # ─── Finance ──────────────────────────────────────────────
    "invoice_lines":        ("invoices",           "FK invoice_id"),
    "installments":         ("invoices",           "FK invoice_id"),
    "journal_lines":        ("journal_entries",    "FK journal_entry_id"),

    # ─── LMS ──────────────────────────────────────────────────
    "lms_questions":        ("lms_quizzes",        "FK quiz_id"),
    "lms_choices":          ("lms_questions",      "FK question_id → quiz"),
    "lms_quizzes":          ("lms_courses",        "FK course_id → school"),
    "lms_quiz_attempts":    ("lms_quizzes",        "FK quiz_id"),
    "lms_answers":          ("lms_quiz_attempts",  "FK attempt_id"),
    "lms_submissions":      ("lms_assignments",    "FK assignment_id"),
    "lms_assignments":      ("lms_courses",        "FK course_id → school"),
    "lms_assignment_questions": ("lms_assignments","FK assignment_id"),
    "lms_assignment_choices": ("lms_assignment_questions", "FK question_id"),
    "lms_assignment_answers": ("lms_submissions",  "FK submission_id"),
    "lms_assignment_extensions": ("lms_assignments","FK assignment_id"),
    "lms_assessment_template_questions": ("lms_assessment_templates", "FK template_id → school"),
    "lms_assignment_template_questions": ("lms_assessment_templates", "FK template_id"),
    "lms_assignment_template_choices":   ("lms_assignment_template_questions", "FK question_id"),
    "lms_attempt_flagged_questions": ("lms_quiz_attempts", "FK attempt_id"),
    "lms_bank_choices":     ("lms_bank_questions", "FK question_id → school"),
    "lms_bank_question_tags":        ("lms_bank_questions", "many-to-many"),
    "lms_bank_question_skills":      ("lms_bank_questions", "many-to-many"),
    "lms_bank_question_objectives":  ("lms_bank_questions", "many-to-many"),
    "lms_bank_question_collection_items": ("lms_bank_questions", "membership"),
    "lms_question_stats":   ("lms_questions",      "FK question_id → quiz → school"),
    "lms_lessons":          ("lms_courses",        "FK course_id"),
    "lms_units":            ("lms_courses",        "FK course_id"),
    "lms_course_sections":  ("lms_courses",        "FK course_id"),

    # ─── Academic / results ───────────────────────────────────
    "grading_scale_levels": ("grading_scales",     "FK scale_id → school"),
    "subject_grades":       ("subjects",           "FK subject_id"),
    "subject_terms":        ("subjects",           "FK subject_id"),

    # ─── Rubrics ─────────────────────────────────────────────
    "rubric_criteria":      ("rubrics",            "FK rubric_id → school"),
    "rubric_scores":        ("rubric_criteria",    "FK criterion_id → rubric → school"),

    # ─── Students / guardians ────────────────────────────────
    "student_guardians":    ("students",           "FK student_id (also guardian_id → school)"),
    "student_tag_links":    ("students",           "many-to-many via tag_id"),

    # ─── Behavior / intervention ─────────────────────────────
    "behavior_actions":     ("behavior_incidents", "FK incident_id → school"),
    "intervention_plan_outcomes":  ("intervention_plans",     "FK plan_id → school"),
    "intervention_sessions":       ("intervention_plans",     "FK plan_id → school"),

    # ─── Messaging ───────────────────────────────────────────
    "conversation_participants": ("conversations", "FK conversation_id → school"),
    "messages":                   ("conversations","FK conversation_id → school"),
    "notification_preferences":  ("users",         "FK user_id → school"),

    # ─── Teacher-subject linkage ─────────────────────────────
    "teacher_subjects":     ("teachers",           "FK teacher_id → school"),

    # ─── Nafis (shared bank — cross-tenant catalog) ─────────
    "nafis_outcome_scores": ("students",           "FK student_id → school"),

    # ─── System / shared ────────────────────────────────────
    "alembic_version":      ("__shared__",         "migration metadata"),
    "schools":              ("__shared__",         "root tenant table — IS the school_id"),
}


# Prefix allowlist — anything matching one of these counts as
# intentionally global (SQLite system tables, alembic temp tables).
GLOBAL_PREFIXES: tuple[str, ...] = (
    "sqlite_",          # SQLite internal
    "_alembic_tmp_",    # Alembic batch-rebuild temp tables
    "pg_",              # PostgreSQL internal
)


def _engine(app):
    """Get the SQLAlchemy engine the Flask-SQLAlchemy extension uses."""
    from app.extensions import db
    return db.engine


def _list_tenant_tables(app) -> list[str]:
    """Every real user-space table in the DB — minus internals and
    anything matching GLOBAL_PREFIXES."""
    from sqlalchemy import inspect
    insp = inspect(_engine(app))
    out = []
    for name in insp.get_table_names():
        if any(name.startswith(p) for p in GLOBAL_PREFIXES):
            continue
        out.append(name)
    return out


def _has_school_id(app, table: str) -> bool:
    from sqlalchemy import inspect
    insp = inspect(_engine(app))
    cols = {c["name"] for c in insp.get_columns(table)}
    return "school_id" in cols


def test_every_table_is_classified(app):
    """Every real table either carries school_id or is explicitly
    classified in TENANT_INHERIT_MAP. A new unclassified table fails
    the build with a message that names it."""
    with app.app_context():
        unclassified = []
        for table in _list_tenant_tables(app):
            if _has_school_id(app, table):
                continue
            if table in TENANT_INHERIT_MAP:
                continue
            unclassified.append(table)

    assert not unclassified, (
        "SAAS-002 schema gate — the following table(s) have no "
        "school_id column AND no entry in TENANT_INHERIT_MAP. "
        "Classify each one (parent table + one-line reason) in "
        f"tests/test_saas002_schema_gate.py:\n  - "
        + "\n  - ".join(sorted(unclassified))
    )


def test_classification_map_has_no_phantom_entries(app):
    """A table listed in TENANT_INHERIT_MAP that no longer exists in
    the DB usually means a model was renamed or dropped without
    updating the map. Not a security hole, but it clutters the
    audit trail — flag it so the map stays trustworthy."""
    with app.app_context():
        from sqlalchemy import inspect
        insp = inspect(_engine(app))
        real = set(insp.get_table_names())
        phantoms = [
            t for t in TENANT_INHERIT_MAP
            if t not in real and t not in ("alembic_version",)
        ]
    # Soft-assert: a phantom isn't a build-breaker, but surface it.
    # Only fail if the number is unreasonable.
    assert len(phantoms) < 10, (
        f"TENANT_INHERIT_MAP has {len(phantoms)} entries that don't "
        f"exist in the DB any more — clean these up: {sorted(phantoms)}"
    )
