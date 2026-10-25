from .school import School
from .user import User, Role, AccountSetupToken
from .platform_admin import (
    PlatformUser, PlatformRecoveryCode, PlatformAuditLog, PLATFORM_ROLES,
    Plan, SchoolSubscription, SchoolSubscriptionEvent, PlatformSetting, PlatformJob,
    SchoolModuleOverride, SchoolFeatureOverride, SchoolLimitOverride, SupportSession, SupportSessionEvent,
    SchoolSlugHistory, PlatformSchoolNote, SchoolContact, SchoolTag, PlatformAnnouncement,
    BILLING_CYCLES, SUBSCRIPTION_EVENT_KINDS, PlatformUsageSnapshot, PlatformAlert, SchoolOffboarding,
    PlatformSession, PlatformSetupToken,
)
from .platform_billing import PlatformInvoice, PlatformInvoiceLine, PlatformPayment  # SAAS-033
from .ai_usage import AIUsageEvent, AIPriceCard, AIUsageCharge, AI_OPERATIONS  # AI usage (ticket D)
from .academic import AcademicYear, Term, Grade, Section
from .student import (
    Student, Enrollment, TransferLog,
    StudentNote, StudentTag, PreviousSchool,
    student_tag_links,
)
from .teacher import (
    Teacher, Subject, Assignment, Day, Period, ScheduleSlot,
    subject_grades,
)
from .attendance import (
    Attendance, DeviceToken, NotificationLog,
    AttendanceRule, AttendanceRuleTriggered,
    StudentRiskScore,
)
from .results import PassRule, AssessmentComponent, GradeEntry, YearResult
from .finance import (
    Account, JournalEntry, JournalLine, FeeType, Invoice, InvoiceLine,
    Installment, Payment, Vendor, Expense, PaymentMethod,
    PAYMENT_METHOD_KINDS, RECURRING_FREQUENCIES,
    RecurringFeeSchedule, RecurringInvoiceLog,
    BankStatementLine, CostCenter,
    Budget, ReceiptVoucher,
    RefundRequest, PettyCashTransaction,
)
from .hr import (
    Employee, Payroll, PayrollSettlement, EmployeeAdvance,
    LeaveRequest, LeaveBalance,
)
from .material import Material
from .lms import (
    Course, CourseSection, Unit, Lesson, CourseAssignment, Submission,
    AssignmentQuestion, AssignmentChoice, AssignmentAnswer,
    Quiz, Question, Choice, QuizAttempt, Answer,
    BankQuestion, BankChoice, BankTag,
    Skill, LearningObjective, QuestionStats,
    AssignmentExtension, QuestionCollection, FeedbackTemplate,
    SubjectPrerequisite,
    lms_bank_question_tags,
    lms_bank_question_skills,
    lms_bank_question_objectives,
    lms_attempt_flagged_questions,
    lms_bank_question_collection_items,
    AssignmentTemplate, AssignmentTemplateQuestion, AssignmentTemplateChoice,
    AssessmentTemplate, AssessmentTemplateItem,
    Axis, Indicator, Passage,
    Announcement,
)
# Sprint 16 — school-platform expansion (guardians, calendar, audit,
# health, docs, behavior, messaging, scopes, grading scales, rubrics,
# discounts, transcripts, rooms, staff attendance, imports).
from .school_backup import (SchoolBackup, SchoolRestore, BACKUP_STATUSES, BACKUP_KINDS,
                            RESTORE_STATUSES, RESTORE_MODES)
from .platform import (
    Guardian, StudentGuardian,
    SchoolCalendarDay,
    AuditLog,
    Room,
    StaffAttendance, SubstitutionLog,
    StudentHealthProfile, HealthIncident,
    StudentDocument,
    BehaviorCategory, BehaviorIncident, BehaviorAction,
    Conversation, ConversationParticipant, Message,
    NotificationPreference,
    PickupCall,
    UserScope,
    GradingScale, GradingScaleLevel,
    Rubric, RubricCriterion, RubricScore,
    DiscountType, StudentDiscount,
    TranscriptSnapshot,
    ImportBatch,
)
# NAFIS (ETEC national assessment) — see models/nafis.py.
from .nafis import (
    LearningOutcome,
    NafisCycle, NafisResult, NafisOutcomeScore,
    StudentGap,
    InterventionPlan, InterventionPlanOutcome, InterventionSession,
    NAFIS_LEVELS, NAFIS_SUBJECTS, NAFIS_BANDS, NAFIS_CYCLE_STATUS,
    GAP_SEVERITY, GAP_SOURCE, INTERVENTION_STATUS,
)

__all__ = [
    "School", "User", "Role", "AccountSetupToken",
    "AcademicYear", "Term", "Grade", "Section",
    "Student", "Enrollment", "TransferLog",
    "StudentNote", "StudentTag", "PreviousSchool", "student_tag_links",
    "Teacher", "Subject", "Assignment", "Day", "Period", "ScheduleSlot",
    "subject_grades",
    "Attendance", "DeviceToken", "NotificationLog",
    "AttendanceRule", "AttendanceRuleTriggered",
    "StudentRiskScore",
    "PassRule", "AssessmentComponent", "GradeEntry", "YearResult",
    "Account", "JournalEntry", "JournalLine", "FeeType",
    "Invoice", "InvoiceLine", "Installment", "Payment",
    "Vendor", "Expense", "PaymentMethod", "PAYMENT_METHOD_KINDS", "RECURRING_FREQUENCIES",
    "RecurringFeeSchedule", "RecurringInvoiceLog", "BankStatementLine",
    "CostCenter", "Budget", "ReceiptVoucher",
    "RefundRequest", "PettyCashTransaction",
    "Employee", "Payroll", "PayrollSettlement", "EmployeeAdvance",
    "LeaveRequest", "LeaveBalance",
    "Material",
    # LMS
    "Course", "CourseSection", "Unit", "Lesson", "CourseAssignment", "Submission",
    "AssignmentQuestion", "AssignmentChoice", "AssignmentAnswer",
    "Quiz", "Question", "Choice", "QuizAttempt", "Answer",
    "BankQuestion", "BankChoice", "BankTag",
    "Skill", "LearningObjective", "QuestionStats",
    "AssignmentExtension", "QuestionCollection", "FeedbackTemplate",
    "SubjectPrerequisite",
    "AssignmentTemplate", "AssignmentTemplateQuestion", "AssignmentTemplateChoice",
    "AssessmentTemplate", "AssessmentTemplateItem",
    "Axis", "Indicator", "Passage",
    "Announcement",
    # Sprint 16 (platform expansion)
    "Guardian", "StudentGuardian",
    "SchoolCalendarDay",
    "AuditLog",
    "Room",
    "StaffAttendance", "SubstitutionLog",
    "StudentHealthProfile", "HealthIncident",
    "StudentDocument",
    "BehaviorCategory", "BehaviorIncident", "BehaviorAction",
    "Conversation", "ConversationParticipant", "Message",
    "NotificationPreference", "PickupCall",
    "UserScope",
    "GradingScale", "GradingScaleLevel",
    "Rubric", "RubricCriterion", "RubricScore",
    "DiscountType", "StudentDiscount",
    "TranscriptSnapshot",
    "ImportBatch",
    # NAFIS
    "LearningOutcome",
    "NafisCycle", "NafisResult", "NafisOutcomeScore",
    "StudentGap",
    "InterventionPlan", "InterventionPlanOutcome", "InterventionSession",
    "NAFIS_LEVELS", "NAFIS_SUBJECTS", "NAFIS_BANDS", "NAFIS_CYCLE_STATUS",
    "GAP_SEVERITY", "GAP_SOURCE", "INTERVENTION_STATUS",
    "PlatformUser", "PlatformRecoveryCode", "PlatformAuditLog", "PLATFORM_ROLES",
    "Plan", "SchoolSubscription", "SchoolSubscriptionEvent", "PlatformSetting", "PlatformJob",
    "SchoolModuleOverride", "SchoolFeatureOverride", "SchoolLimitOverride", "SupportSession", "SupportSessionEvent",
    "SchoolSlugHistory", "PlatformSchoolNote", "SchoolContact", "SchoolTag", "PlatformAnnouncement",
    "PlatformInvoice", "PlatformInvoiceLine", "PlatformPayment", "PlatformUsageSnapshot", "PlatformAlert",
    "SchoolOffboarding", "PlatformSession", "PlatformSetupToken",
    "BILLING_CYCLES", "SUBSCRIPTION_EVENT_KINDS",
    "AIUsageEvent", "AIPriceCard", "AIUsageCharge", "AI_OPERATIONS",
    "SchoolBackup", "SchoolRestore", "BACKUP_STATUSES", "BACKUP_KINDS",
    "RESTORE_STATUSES", "RESTORE_MODES",
]


# SAAS-048 — every foreign key is DEFERRABLE INITIALLY IMMEDIATE: checked
# at once, as always, except inside a school restore's transaction, which
# defers them so a module's rows can be deleted and re-inserted, then
# checks them before commit (services/school_restore.py). Set here so
# create_all (tests) and the migrations (c4d6f8a0b2c4) agree.
def _deferrable_foreign_keys():
    from ..extensions import db as _db
    for _t in _db.metadata.tables.values():
        for _fk in _t.foreign_key_constraints:
            _fk.deferrable = True
            _fk.initially = "IMMEDIATE"


_deferrable_foreign_keys()
