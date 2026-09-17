from .school import School
from .user import User, Role
from .academic import AcademicYear, Term, Grade, Section
from .student import Student, Enrollment, TransferLog
from .teacher import Teacher, Subject, Assignment, Day, Period, ScheduleSlot
from .attendance import Attendance, DeviceToken, NotificationLog
from .results import PassRule, AssessmentComponent, GradeEntry, YearResult
from .finance import (
    Account, JournalEntry, JournalLine, FeeType, Invoice, InvoiceLine,
    Installment, Payment, Vendor, Expense, PaymentMethod,
    RecurringFeeSchedule, RecurringInvoiceLog,
    BankStatementLine,
)
from .hr import Employee, Payroll, PayrollSettlement, EmployeeAdvance
from .material import Material
from .lms import (
    Course, CourseSection, Unit, Lesson, CourseAssignment, Submission,
    AssignmentQuestion, AssignmentChoice, AssignmentAnswer,
    Quiz, Question, Choice, QuizAttempt, Answer,
    BankQuestion, BankChoice,
    AssignmentTemplate, AssignmentTemplateQuestion, AssignmentTemplateChoice,
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
    UserScope,
    GradingScale, GradingScaleLevel,
    Rubric, RubricCriterion, RubricScore,
    DiscountType, StudentDiscount,
    TranscriptSnapshot,
    ImportBatch,
)

__all__ = [
    "School", "User", "Role",
    "AcademicYear", "Term", "Grade", "Section",
    "Student", "Enrollment", "TransferLog",
    "Teacher", "Subject", "Assignment", "Day", "Period", "ScheduleSlot",
    "Attendance", "DeviceToken", "NotificationLog",
    "PassRule", "AssessmentComponent", "GradeEntry", "YearResult",
    "Account", "JournalEntry", "JournalLine", "FeeType",
    "Invoice", "InvoiceLine", "Installment", "Payment",
    "Vendor", "Expense", "PaymentMethod",
    "RecurringFeeSchedule", "RecurringInvoiceLog", "BankStatementLine",
    "Employee", "Payroll", "PayrollSettlement", "EmployeeAdvance",
    "Material",
    # LMS
    "Course", "CourseSection", "Unit", "Lesson", "CourseAssignment", "Submission",
    "AssignmentQuestion", "AssignmentChoice", "AssignmentAnswer",
    "Quiz", "Question", "Choice", "QuizAttempt", "Answer",
    "BankQuestion", "BankChoice",
    "AssignmentTemplate", "AssignmentTemplateQuestion", "AssignmentTemplateChoice",
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
    "NotificationPreference",
    "UserScope",
    "GradingScale", "GradingScaleLevel",
    "Rubric", "RubricCriterion", "RubricScore",
    "DiscountType", "StudentDiscount",
    "TranscriptSnapshot",
    "ImportBatch",
]
