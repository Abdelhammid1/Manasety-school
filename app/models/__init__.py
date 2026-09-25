from .school import School
from .user import User, Role
from .academic import AcademicYear, Term, Grade, Section
from .student import (
    Student, Enrollment, TransferLog,
    StudentNote, StudentTag, PreviousSchool,
    student_tag_links,
)
from .teacher import Teacher, Subject, Assignment, Day, Period, ScheduleSlot
from .attendance import Attendance, DeviceToken, NotificationLog
from .results import PassRule, AssessmentComponent, GradeEntry, YearResult
from .finance import (
    Account, JournalEntry, JournalLine, FeeType, Invoice, InvoiceLine,
    Installment, Payment, Vendor, Expense, PaymentMethod,
    PAYMENT_METHOD_KINDS,
    RecurringFeeSchedule, RecurringInvoiceLog,
    BankStatementLine, CostCenter,
    Budget, ReceiptVoucher,
)
from .hr import Employee, Payroll, PayrollSettlement, EmployeeAdvance
from .material import Material
from .lms import (
    Course, CourseSection, Unit, Lesson, CourseAssignment, Submission,
    AssignmentQuestion, AssignmentChoice, AssignmentAnswer,
    Quiz, Question, Choice, QuizAttempt, Answer,
    BankQuestion, BankChoice, BankTag,
    Skill, LearningObjective, QuestionStats,
    AssignmentExtension, QuestionCollection, FeedbackTemplate,
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
    "School", "User", "Role",
    "AcademicYear", "Term", "Grade", "Section",
    "Student", "Enrollment", "TransferLog",
    "StudentNote", "StudentTag", "PreviousSchool", "student_tag_links",
    "Teacher", "Subject", "Assignment", "Day", "Period", "ScheduleSlot",
    "Attendance", "DeviceToken", "NotificationLog",
    "PassRule", "AssessmentComponent", "GradeEntry", "YearResult",
    "Account", "JournalEntry", "JournalLine", "FeeType",
    "Invoice", "InvoiceLine", "Installment", "Payment",
    "Vendor", "Expense", "PaymentMethod", "PAYMENT_METHOD_KINDS",
    "RecurringFeeSchedule", "RecurringInvoiceLog", "BankStatementLine",
    "CostCenter", "Budget", "ReceiptVoucher",
    "Employee", "Payroll", "PayrollSettlement", "EmployeeAdvance",
    "Material",
    # LMS
    "Course", "CourseSection", "Unit", "Lesson", "CourseAssignment", "Submission",
    "AssignmentQuestion", "AssignmentChoice", "AssignmentAnswer",
    "Quiz", "Question", "Choice", "QuizAttempt", "Answer",
    "BankQuestion", "BankChoice", "BankTag",
    "Skill", "LearningObjective", "QuestionStats",
    "AssignmentExtension", "QuestionCollection", "FeedbackTemplate",
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
]
