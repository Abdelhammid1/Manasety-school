"""NAFIS (اختبارات نافس الوطنية) — models.

ETEC's national assessment applies at three grade levels — end of grade
3, 6, and 9 (called Middle 3) — for Reading, Math, and Science. Every
question is anchored to a Learning Outcome (ناتج تعلّم) with a
hierarchical code like ``6-4-4-2-1``. Schools receive per-student and
per-outcome results after each cycle; this app imports those results,
derives gaps, and drives intervention plans.

Naming stays in English for column/table identifiers so migrations and
SQL stay portable; Arabic labels live in `*_ar` columns.
"""
from datetime import datetime, timezone

from ..extensions import db
from .mixins import SoftDeleteMixin


# ─── Enums (kept as short strings; no CHECK constraints — validated in app) ──

NAFIS_LEVELS = ("g3", "g6", "g9")           # end of grade 3 / 6 / 9
NAFIS_SUBJECTS = ("reading", "math", "science")

# Achievement bands ETEC reports back per subject.
# (متمكّن = mastered, متجاوز = above, حد أدنى = minimum, دون الحد = below)
NAFIS_BANDS = ("mastered", "above", "minimum", "below")

NAFIS_CYCLE_STATUS = ("upcoming", "active", "completed", "results_published")

GAP_SEVERITY = ("critical", "moderate", "mild")
GAP_SOURCE = ("nafis", "diagnostic", "teacher")

INTERVENTION_STATUS = ("draft", "active", "completed", "cancelled")


# ─── Learning Outcomes tree (curriculum spine) ────────────────────────

class LearningOutcome(db.Model):
    """ناتج تعلّم — one node in the ETEC standards tree.

    Kept as a single self-referential table so browsers, importers, and
    gap tags all reference the same primary key regardless of the node's
    depth. `code` is the canonical ETEC identifier (e.g. `6-4-4-2-1`)
    and is unique inside a school (`school_id` is nullable so a global
    seed can be shared across schools).
    """
    __tablename__ = "learning_outcomes"

    id = db.Column(db.Integer, primary_key=True)
    # NULL school_id = global seed row shared across every tenant. A school
    # that customises a standard forks the row and sets school_id to itself.
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=True, index=True)

    parent_id = db.Column(db.Integer, db.ForeignKey("learning_outcomes.id"), nullable=True, index=True)

    subject = db.Column(db.String(16), nullable=False)   # reading | math | science
    level   = db.Column(db.String(4),  nullable=False)   # g3 | g6 | g9

    # kind: subject_root | broad_outcome | domain | standard | indicator
    kind    = db.Column(db.String(16), nullable=False)

    code    = db.Column(db.String(64), nullable=True, index=True)     # `6-4-4-2-1` when set
    seq     = db.Column(db.Integer, nullable=True)                    # order among siblings
    text_ar = db.Column(db.Text, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    parent = db.relationship("LearningOutcome", remote_side="LearningOutcome.id",
                             backref=db.backref("children", cascade="all, delete-orphan",
                                                order_by="LearningOutcome.seq"))

    __table_args__ = (
        db.UniqueConstraint("school_id", "code", name="uq_lo_school_code"),
        db.Index("ix_lo_subject_level_kind", "subject", "level", "kind"),
    )


# ─── NAFIS test cycle (one per ETEC round) ────────────────────────────

class NafisCycle(SoftDeleteMixin, db.Model):
    """Dorat نافس — one testing round (typically once per Hijri year)."""
    __tablename__ = "nafis_cycles"

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    academic_year_id = db.Column(db.Integer, db.ForeignKey("academic_years.id"),
                                 nullable=True, index=True)

    name_ar = db.Column(db.String(128), nullable=False)     # e.g. "دورة نافس 1447/2026"
    hijri_year = db.Column(db.String(8), nullable=True)     # "1447"
    gregorian_year = db.Column(db.Integer, nullable=True)   # 2026

    # Test window (across all three levels, whole span).
    start_date = db.Column(db.Date, nullable=True)
    end_date   = db.Column(db.Date, nullable=True)

    # Which levels this cycle actually runs — stored as comma-separated
    # subset of NAFIS_LEVELS so a school that only tests grade 6 can say so.
    levels = db.Column(db.String(32), nullable=False, default="g3,g6,g9",
                       server_default="g3,g6,g9")

    status = db.Column(db.String(24), nullable=False, default="upcoming",
                       server_default="upcoming")

    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    academic_year = db.relationship("AcademicYear")

    __table_args__ = (
        db.UniqueConstraint("school_id", "name_ar", name="uq_nafis_cycle_school_name"),
    )

    @property
    def target_levels(self) -> list[str]:
        return [x for x in (self.levels or "").split(",") if x]


# ─── Per-student subject-level result ─────────────────────────────────

class NafisResult(db.Model):
    """One row per (student, cycle, subject) — the top-line ETEC report.

    Per-outcome detail (which standards the student mastered) lives in
    `NafisOutcomeScore` and rolls up here.
    """
    __tablename__ = "nafis_results"

    id = db.Column(db.Integer, primary_key=True)
    school_id  = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    cycle_id   = db.Column(db.Integer, db.ForeignKey("nafis_cycles.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"),
                           nullable=False, index=True)

    level   = db.Column(db.String(4),  nullable=False)   # g3 | g6 | g9
    subject = db.Column(db.String(16), nullable=False)   # reading | math | science

    raw_score       = db.Column(db.Integer, nullable=True)
    total_questions = db.Column(db.Integer, nullable=True)
    percentage      = db.Column(db.Numeric(5, 2), nullable=True)   # 0..100
    band            = db.Column(db.String(16), nullable=True)      # mastered / above / minimum / below

    # National / regional percentile rank when ETEC provides it.
    national_percentile = db.Column(db.Numeric(5, 2), nullable=True)

    imported_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    imported_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    cycle   = db.relationship("NafisCycle", backref=db.backref("results", cascade="all, delete-orphan"))
    student = db.relationship("Student")

    __table_args__ = (
        db.UniqueConstraint("cycle_id", "student_id", "subject",
                            name="uq_nafis_result_cycle_student_subject"),
        db.Index("ix_nafis_result_level_subject", "level", "subject"),
    )


class NafisOutcomeScore(db.Model):
    """Per-student × per-outcome result — the fine grain ETEC ships.

    Either a boolean `mastered` (early cycles) or a percentage — we keep
    both so different importers can populate what they have.
    """
    __tablename__ = "nafis_outcome_scores"

    id = db.Column(db.Integer, primary_key=True)
    result_id  = db.Column(db.Integer, db.ForeignKey("nafis_results.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    outcome_id = db.Column(db.Integer, db.ForeignKey("learning_outcomes.id"),
                           nullable=False, index=True)

    mastered   = db.Column(db.Boolean, nullable=True)
    score_pct  = db.Column(db.Numeric(5, 2), nullable=True)

    result  = db.relationship("NafisResult",
                              backref=db.backref("outcome_scores", cascade="all, delete-orphan"))
    outcome = db.relationship("LearningOutcome")

    __table_args__ = (
        db.UniqueConstraint("result_id", "outcome_id",
                            name="uq_nafis_outcome_score_result_outcome"),
    )


# ─── Derived gap + intervention plan (phase 3, tables created now) ────

class StudentGap(db.Model):
    """One outstanding weakness per (student, outcome). Derived — regenerated
    from NafisOutcomeScore or DiagnosticAttempt whenever fresh evidence lands."""
    __tablename__ = "student_gaps"

    id = db.Column(db.Integer, primary_key=True)
    school_id  = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    outcome_id = db.Column(db.Integer, db.ForeignKey("learning_outcomes.id"),
                           nullable=False, index=True)

    severity = db.Column(db.String(16), nullable=False)   # critical | moderate | mild
    source   = db.Column(db.String(16), nullable=False)   # nafis | diagnostic | teacher

    # Free-form pointer back to the evidence — e.g. "nafis_result:42".
    evidence_ref = db.Column(db.String(64), nullable=True)

    detected_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    resolved_at = db.Column(db.DateTime, nullable=True)

    student = db.relationship("Student")
    outcome = db.relationship("LearningOutcome")

    __table_args__ = (
        db.UniqueConstraint("student_id", "outcome_id",
                            name="uq_student_gap_student_outcome"),
    )


class InterventionPlan(db.Model):
    """A remedial plan for one student targeting one or more outcomes."""
    __tablename__ = "intervention_plans"

    id = db.Column(db.Integer, primary_key=True)
    school_id  = db.Column(db.Integer, db.ForeignKey("schools.id"), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    owner_teacher_id = db.Column(db.Integer, db.ForeignKey("teachers.id"), nullable=True, index=True)

    title_ar    = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)

    start_date = db.Column(db.Date, nullable=True)
    end_date   = db.Column(db.Date, nullable=True)
    status     = db.Column(db.String(16), nullable=False, default="draft",
                           server_default="draft")

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    student = db.relationship("Student")
    owner_teacher = db.relationship("Teacher")


class InterventionPlanOutcome(db.Model):
    """Join — which outcomes a plan targets."""
    __tablename__ = "intervention_plan_outcomes"

    id = db.Column(db.Integer, primary_key=True)
    plan_id    = db.Column(db.Integer, db.ForeignKey("intervention_plans.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    outcome_id = db.Column(db.Integer, db.ForeignKey("learning_outcomes.id"),
                           nullable=False, index=True)

    plan    = db.relationship("InterventionPlan",
                              backref=db.backref("plan_outcomes", cascade="all, delete-orphan"))
    outcome = db.relationship("LearningOutcome")

    __table_args__ = (
        db.UniqueConstraint("plan_id", "outcome_id",
                            name="uq_plan_outcome_plan_outcome"),
    )


class InterventionSession(db.Model):
    """One remedial session inside a plan — date, attendance, notes."""
    __tablename__ = "intervention_sessions"

    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey("intervention_plans.id", ondelete="CASCADE"),
                        nullable=False, index=True)

    session_date = db.Column(db.Date, nullable=False)
    duration_minutes = db.Column(db.Integer, nullable=True)
    attended = db.Column(db.Boolean, nullable=True)   # tri-state; NULL = not marked
    notes = db.Column(db.Text, nullable=True)

    plan = db.relationship("InterventionPlan",
                           backref=db.backref("sessions", cascade="all, delete-orphan",
                                              order_by="InterventionSession.session_date"))
