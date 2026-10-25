"""The activity log (audit_logs) as an administrator reads it: one Arabic
sentence per row and, for an update, only the fields that really changed.

Display only — what is stored stays as it is, old rows included. The
mappings below are the one place to label an action, an entity, a field
or a stored value; anything missing shows by its raw name (the page never
breaks) and is logged once as a warning so the mapping can be completed.
A new audited model (services/audit.py `_WATCHED`) gets its entry in
ENTITY_LABELS and its fields in FIELD_LABELS.

Secrets never reach the template: the route passes only `display_rows()`
output, and a changed secret field becomes the line "تم تغيير كلمة المرور".
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Iterable, Optional

from .audit import BY_PLATFORM, REDACTED, is_secret_field, redact
from .subscription_enforcement import USER_LOGIN_FIELDS

_log = logging.getLogger(__name__)
_warned: set[str] = set()

ACTION_LABELS = {
    "create": "إضافة", "update": "تعديل", "delete": "حذف",
    "login": "تسجيل دخول", "login_failed": "محاولة دخول فاشلة", "login_locked": "قفل الحساب",
    "backup_create": "طلب نسخة احتياطية", "backup_pending": "نسخة احتياطية قيد الانتظار",
    "backup_running": "نسخة احتياطية قيد التنفيذ", "backup_succeeded": "نسخة احتياطية جاهزة",
    "backup_failed": "فشل النسخة الاحتياطية", "backup_delete": "حذف نسخة احتياطية",
    "backup_dl": "تنزيل نسخة احتياطية", "backup_dl_ready": "تجهيز تنزيل نسخة احتياطية",
    "backup_dl_denied": "رفض تنزيل نسخة احتياطية", "backup_pruned": "حذف نسخ احتياطية قديمة",
    "backup_browse": "تصفّح نسخة احتياطية", "extract_denied": "رفض استخراج من نسخة احتياطية",
    "restore_request": "طلب استرجاع", "restore_uploaded": "رفع نسخة للاسترجاع",
    "restore_confirm": "تأكيد الاسترجاع", "restore_ok": "تم الاسترجاع",
    "restore_failed": "فشل الاسترجاع", "restore_denied": "رفض الاسترجاع",
    "restore_cli": "استرجاع من الخادم",
}
# The badge: login / create / update / delete / anything else.
ACTION_KIND = {"create": "create", "update": "update", "delete": "delete",
               "login": "login", "login_failed": "danger", "login_locked": "danger",
               "backup_failed": "danger", "restore_failed": "danger", "backup_dl_denied": "danger",
               "restore_denied": "danger", "extract_denied": "danger"}

ENTITY_LABELS = {
    "GradeEntry": "درجة", "YearResult": "نتيجة سنوية", "Attendance": "سجل حضور",
    "Enrollment": "قيد دراسي", "Student": "طالب", "Guardian": "ولي أمر",
    "Invoice": "فاتورة", "Payment": "دفعة", "User": "مستخدم", "Role": "دور وظيفي",
    "Assignment": "إسناد تدريس", "PassRule": "قاعدة النجاح", "PaymentMethod": "طريقة دفع",
    "JournalEntry": "قيد محاسبي", "ScheduleSlot": "حصة في الجدول",
    "School": "المدرسة", "SchoolBackup": "نسخة احتياطية", "SchoolRestore": "استرجاع نسخة",
    # academic structure
    "AcademicYear": "سنة دراسية", "Term": "فترة دراسية", "Grade": "صف دراسي", "Section": "فصل",
    "Subject": "مادة", "Teacher": "معلم", "Day": "يوم دراسي", "Period": "حصة",
    "SchoolCalendarDay": "يوم في التقويم", "Room": "قاعة",
    # students
    "StudentDocument": "مستند طالب", "StudentHealthProfile": "ملف صحي", "HealthIncident": "حالة صحية",
    "BehaviorIncident": "ملاحظة سلوكية", "BehaviorCategory": "تصنيف سلوك", "StudentDiscount": "خصم طالب",
    "StudentGuardian": "ربط ولي أمر", "StudentNote": "ملاحظة على طالب",
    # finance
    "Account": "حساب", "FeeType": "نوع رسوم", "DiscountType": "نوع خصم", "Expense": "مصروف",
    "Vendor": "مورد", "CostCenter": "مركز تكلفة", "Budget": "بند موازنة",
    "RecurringFeeSchedule": "رسوم متكررة", "RefundRequest": "طلب استرداد", "PettyCashTransaction": "حركة عهدة",
    # HR
    "Employee": "موظف", "EmployeeAdvance": "سلفة موظف", "LeaveRequest": "طلب إجازة", "Payroll": "مسير رواتب",
    "PayrollSettlement": "صرف رواتب",
    # assessment / learning
    "AssessmentComponent": "مكوّن تقييم", "GradingScale": "سلم درجات", "Rubric": "معيار تقييم",
    "Course": "مقرر", "CourseAssignment": "واجب", "Quiz": "اختبار", "Announcement": "إعلان",
    "BankQuestion": "سؤال في البنك", "AssessmentTemplate": "نموذج تقييم",
    "AttendanceRule": "قاعدة حضور", "NafisCycle": "دورة نافس", "Material": "مادة في المكتبة",
    "UserScope": "نطاق مستخدم",
}

FIELD_LABELS = {
    # people
    "full_name": "الاسم الكامل", "username": "اسم المستخدم", "email": "البريد الإلكتروني",
    "phone": "رقم الهاتف", "phone_alt": "رقم هاتف إضافي", "is_active": "حالة الحساب",
    "role_id": "الدور الوظيفي", "password_hash": "كلمة المرور", "national_id": "الرقم القومي",
    "dob": "تاريخ الميلاد", "gender": "الجنس", "address": "العنوان", "notes": "ملاحظات",
    "occupation": "المهنة", "is_guardian": "ولي أمر رسمي", "photo_url": "الصورة",
    "permanent_code": "كود الطالب", "parent_name": "اسم ولي الأمر", "parent_phone": "هاتف ولي الأمر",
    "parent_email": "بريد ولي الأمر", "parent_user_id": "حساب ولي الأمر", "user_id": "الحساب",
    "mother_name": "اسم الأم", "mother_phone": "هاتف الأم", "ar_account_id": "حساب الذمم",
    "is_platform_support": "حساب دعم المنصة",
    # roles
    "name": "الاسم", "name_ar": "الاسم بالعربي", "is_system": "دور نظامي", "permissions": "الصلاحيات",
    # academic
    "student_id": "الطالب", "year_id": "السنة الدراسية", "grade_id": "الصف", "section_id": "الفصل",
    "subject_id": "المادة", "term_id": "الفترة", "teacher_id": "المعلم", "period_id": "الحصة",
    "day_id": "اليوم", "room_id": "القاعة", "enrollment_id": "الطالب", "component_id": "مكوّن التقييم",
    "schedule_slot_id": "الحصة في الجدول", "weekly_periods": "عدد الحصص الأسبوعية",
    "status": "الحالة", "final_result": "النتيجة النهائية", "enrolled_at": "تاريخ القيد",
    "status_changed_at": "تاريخ تغيير الحالة", "status_reason": "سبب تغيير الحالة",
    "graduation_date": "تاريخ التخرج", "exit_checklist": "إجراءات الخروج",
    "date": "التاريخ", "excuse_reason": "سبب العذر", "excuse_document": "مستند العذر",
    "score": "الدرجة", "recorded_by_user_id": "رصدها",
    "average": "المعدل", "failed_subjects": "مواد الرسوب", "subject_scores": "درجات المواد",
    "rule_snapshot": "قاعدة النجاح المطبّقة", "approved_by_user_id": "اعتمدها", "approved_at": "تاريخ الاعتماد",
    "gpa": "المعدل التراكمي", "grade_letter": "التقدير", "rank_in_section": "الترتيب في الفصل",
    "rank_in_grade": "الترتيب في الصف",
    "subject_pass_threshold": "درجة نجاح المادة", "overall_pass_threshold": "درجة نجاح المعدل",
    "method": "الطريقة", "allowed_failed_subjects": "عدد المواد المسموح برسوبها", "is_frozen": "مجمّدة",
    # finance
    "number": "رقم الفاتورة", "issue_date": "تاريخ الإصدار", "due_date": "تاريخ الاستحقاق",
    "total_amount": "الإجمالي", "paid_amount": "المدفوع", "tax_rate": "نسبة الضريبة",
    "tax_amount": "قيمة الضريبة", "invoice_id": "الفاتورة", "payment_date": "تاريخ الدفع",
    "amount": "المبلغ", "cash_account_id": "حساب الخزينة", "reference": "المرجع",
    "is_refund": "استرداد", "journal_entry_id": "القيد المحاسبي", "kind": "النوع",
    "account_id": "الحساب المحاسبي", "entry_date": "تاريخ القيد", "description": "الوصف",
    "related_kind": "مرتبط بـ", "related_id": "رقم المرجع", "created_by_user_id": "أنشأه",
    # backups / restores (their meta rows)
    "file": "الملف", "modules": "الأجزاء", "mode": "الوضع", "reason": "السبب", "via": "من خلال",
    "size": "الحجم", "error": "الخطأ", "result": "النتيجة",
    # the school's settings (School)
    "code": "كود المدرسة", "slug": "عنوان المدرسة", "legal_name_ar": "الاسم القانوني بالعربي",
    "legal_name_en": "الاسم القانوني بالإنجليزي", "logo_url": "اللوجو", "primary_color": "اللون الأساسي",
    "license_number": "رقم الترخيص", "tax_number": "الرقم الضريبي", "website": "الموقع الإلكتروني",
    "attendance_mode": "طريقة رصد الحضور", "default_tax_rate": "نسبة الضريبة الافتراضية",
    "currency": "العملة", "currency_symbol": "رمز العملة", "fiscal_year_start_month": "شهر بداية السنة المالية",
    "invoice_prefix": "بادئة رقم الفاتورة", "invoice_start_number": "رقم أول فاتورة",
    "rounding_policy": "سياسة التقريب", "invoice_header_text": "رأس الفاتورة",
    "invoice_footer_text": "تذييل الفاتورة", "invoice_policy_text": "سياسة الفاتورة",
    "show_logo_on_prints": "اللوجو على المطبوعات", "day_start_time": "بداية اليوم الدراسي",
    "day_end_time": "نهاية اليوم الدراسي", "blocked_message": "رسالة الإيقاف",
    "notify_on_support_access": "إشعار عند دخول الدعم", "reminder_days_before": "أيام التذكير قبل الاستحقاق",
    "notify_channels": "قنوات الإشعار", "smtp_host": "خادم البريد (SMTP)", "smtp_port": "منفذ البريد",
    "smtp_username": "مستخدم البريد", "smtp_password_encrypted": "كلمة مرور البريد",
    "smtp_use_tls": "تشفير البريد (TLS)", "smtp_from_name": "اسم المرسل", "smtp_from_email": "بريد المرسل",
    "approval_threshold": "حد الاعتماد", "installment_reminder_days_before": "أيام تذكير الأقساط",
    # academic structure
    "start_date": "تاريخ البداية", "end_date": "تاريخ النهاية", "weight": "الوزن", "order_index": "الترتيب",
    "stage": "المرحلة", "capacity": "السعة", "status_mode": "طريقة الحالة", "manual_status": "الحالة اليدوية",
    "start_time": "وقت البداية", "end_time": "وقت النهاية", "is_break": "استراحة", "duration_minutes": "المدة (دقائق)",
    "day_type": "نوع اليوم", "room_type": "نوع القاعة", "specialization": "التخصص", "hire_date": "تاريخ التعيين",
    "academic_year_id": "السنة الدراسية", "gregorian_year": "السنة الميلادية", "hijri_year": "السنة الهجرية",
    # students
    "document_type": "نوع المستند", "document_number": "رقم المستند", "expiry_date": "تاريخ الانتهاء",
    "blood_type": "فصيلة الدم", "allergies": "الحساسية", "chronic_conditions": "الأمراض المزمنة",
    "regular_medications": "الأدوية المنتظمة", "special_needs": "الاحتياجات الخاصة", "doctor_name": "اسم الطبيب",
    "doctor_phone": "هاتف الطبيب", "insurance_provider": "شركة التأمين", "insurance_number": "رقم التأمين",
    "emergency_instructions": "تعليمات الطوارئ", "incident_date": "التاريخ", "incident_type": "نوع الحالة",
    "action_taken": "الإجراء المتخذ", "referred_to_hospital": "تحويل للمستشفى", "guardian_notified": "إبلاغ ولي الأمر",
    "category_id": "التصنيف", "points": "النقاط", "default_points": "النقاط الافتراضية", "severity": "الدرجة",
    "action": "الإجراء", "guardian_id": "ولي الأمر", "relationship": "صلة القرابة", "is_primary": "أساسي",
    "is_emergency_contact": "جهة طوارئ", "can_pickup_student": "يستلم الطالب",
    "can_receive_notifications": "يستقبل الإشعارات", "can_view_academic_data": "يرى البيانات الدراسية",
    "can_view_financial_data": "يرى البيانات المالية", "note": "ملاحظة", "body": "النص",
    "discount_type_id": "نوع الخصم", "value": "القيمة", "calc_method": "طريقة الحساب",
    "approval_status": "حالة الاعتماد", "reject_reason": "سبب الرفض",
    # finance
    "type": "النوع", "parent_id": "الحساب الأب", "is_postable": "قابل للترحيل", "account_role": "دور الحساب",
    "default_amount": "المبلغ الافتراضي", "revenue_account_id": "حساب الإيراد", "is_taxable": "خاضع للضريبة",
    "installable": "يقبل التقسيط", "installment_count": "عدد الأقساط", "expense_account_id": "حساب المصروف",
    "counter_account_id": "الحساب المقابل", "override_account_id": "حساب بديل", "ap_account_id": "حساب الذمم الدائنة",
    "vendor_id": "المورد", "cost_center_id": "مركز التكلفة", "payment_method_id": "طريقة الدفع",
    "payment_id": "الدفعة", "contact_person": "مسؤول التواصل", "bank_account": "الحساب البنكي",
    "planned_amount": "المبلغ المخطط", "period": "الفترة", "period_month": "الشهر", "period_year": "السنة",
    "frequency": "التكرار", "day_of_period": "يوم الاستحقاق", "fee_type_id": "نوع الرسوم",
    "applies_to_fee_type_id": "يطبَّق على الرسوم", "applies_to_grade_id": "يطبَّق على الصف",
    "applies_to_stage": "يطبَّق على المرحلة", "requires_approval": "يحتاج اعتماد", "tx_date": "التاريخ",
    "custodian_employee_id": "أمين العهدة", "warn_pct": "نسبة التنبيه", "threshold": "الحد",
    # HR
    "job_title": "المسمى الوظيفي", "base_salary": "الراتب الأساسي", "allowances": "البدلات",
    "deductions": "الخصومات", "net_pay": "صافي الراتب", "employee_id": "الموظف", "date_given": "تاريخ الصرف",
    "deduction_plan": "طريقة الخصم", "remaining_balance": "المتبقي", "leave_type": "نوع الإجازة",
    "days_count": "عدد الأيام", "payroll_id": "مسير الرواتب", "paid_at": "تاريخ الصرف",
    "settled_at": "تاريخ التسوية",
    # assessment / learning
    "title": "العنوان", "course_id": "المقرر", "lesson_id": "الدرس", "unit_id": "الوحدة",
    "max_score": "الدرجة العظمى", "is_published": "منشور", "is_pinned": "مثبّت", "is_archived": "مؤرشف",
    "is_default": "افتراضي", "is_template": "قالب", "due_at": "موعد التسليم", "opens_at": "يفتح في",
    "closes_at": "يغلق في", "instructions": "التعليمات", "max_attempts": "عدد المحاولات",
    "allow_late": "يقبل التأخير", "allow_resubmit": "يسمح بإعادة التسليم", "allow_review": "يسمح بالمراجعة",
    "allow_partial_credit": "درجات جزئية", "late_penalty_per_day": "خصم التأخير اليومي",
    "late_penalty_percent": "نسبة خصم التأخير", "max_penalty_percent": "أقصى خصم",
    "shuffle_questions": "ترتيب عشوائي للأسئلة", "shuffle_choices": "ترتيب عشوائي للاختيارات",
    "show_answers_after": "عرض الإجابات بعد", "result_publish_mode": "طريقة نشر النتيجة",
    "result_publish_at": "موعد نشر النتيجة", "retake_policy": "سياسة الإعادة",
    "retake_cooldown_minutes": "مهلة الإعادة (دقائق)", "navigation_mode": "طريقة التنقل",
    "negative_marking_value": "الدرجة السالبة", "prompt": "نص السؤال", "difficulty": "الصعوبة",
    "cognitive_level": "المستوى المعرفي", "hint_text": "التلميح", "correct_short": "الإجابة الصحيحة",
    "explanation_video_url": "فيديو الشرح", "review_state": "حالة المراجعة", "review_notes": "ملاحظات المراجعة",
    "tags": "الوسوم", "source": "المصدر", "source_type": "نوع المصدر", "source_id": "رقم المصدر",
    "source_template_id": "القالب المصدر", "passage_id": "القطعة", "axis_id": "المحور", "indicator_id": "المؤشر",
    "outcome_id": "ناتج التعلم", "nafis_level": "مستوى نافس", "rubric_id": "معيار التقييم",
    "scale_type": "نوع السلم", "levels": "المستويات", "difficulty_mix": "توزيع الصعوبة",
    "visibility": "الظهور", "cover_url": "الغلاف", "external_url": "الرابط", "internal_label": "التسمية الداخلية",
    "author_id": "الكاتب", "auto_rule": "قاعدة تلقائية", "auto_sync": "مزامنة تلقائية", "window": "المدة",
    "scope_type": "نوع النطاق", "scope_value": "قيمة النطاق", "stage_value": "المرحلة",
    "state": "الحالة", "override_value": "قيمة بديلة",
    # who
    "created_by_id": "أنشأه", "approved_by_id": "اعتمده", "reported_by_user_id": "سجّله",
    "requested_by_user_id": "طلبه", "updated_by_user_id": "عدّله", "uploaded_by_user_id": "رفعه",
    "notified_at": "وقت الإشعار",
}

# Never part of "what changed": bookkeeping, not something the reader acts on.
HIDDEN_FIELDS = frozenset({
    "id", "school_id", "created_at", "recorded_at", "deleted_at", "deleted_by_id",
    "uuid", "updated_at", "last_updated_at", "last_run_at", "file_path", "mime_type", "file_size",
    "auth_epoch", BY_PLATFORM,
} | USER_LOGIN_FIELDS)
# A changed secret: one line saying so, never the value.
SECRET_NOTES = {"smtp_password_encrypted": ("كلمة مرور البريد", "تم تغيير كلمة مرور البريد")}
# Booleans that read as a state, not yes/no.
STATE_FIELDS = frozenset({"is_active"})

VALUE_LABELS = {
    "status": {"present": "حاضر", "absent": "غائب", "late": "متأخر", "excused": "غياب بعذر",
               "left_early": "انصراف مبكر", "draft": "مسودة", "sent": "مرسلة", "partial": "مدفوعة جزئيًا",
               "paid": "مدفوعة", "overdue": "متأخرة", "refunded": "مستردة", "active": "نشط",
               "withdrawn": "منسحب", "transferred": "محوّل", "promoted_out": "منقول لسنة تالية",
               "graduated": "متخرج", "pending": "قيد الانتظار", "pass": "ناجح", "fail": "راسب",
               "incomplete": "غير مكتمل", "running": "قيد التنفيذ", "succeeded": "تم بنجاح",
               "failed": "فشل"},
    "final_result": {"pending": "قيد الانتظار", "pass": "ناجح", "fail": "راسب"},
    "gender": {"male": "ذكر", "female": "أنثى"},
    "method": {"cash": "نقدي", "bank": "تحويل بنكي", "card": "بطاقة", "cheque": "شيك",
               "overall_only": "المعدل الكلي فقط", "per_subject": "كل مادة على حدة", "mixed": "مختلطة"},
    "kind": {"immediate_cash": "نقدي فوري", "immediate_bank": "بنكي فوري", "deferred": "آجل"},
    "type": {"asset": "أصول", "liability": "خصوم", "equity": "حقوق ملكية", "revenue": "إيرادات",
             "expense": "مصروفات"},
    "via": {"web": "الموقع", "api": "تطبيق الموبايل"},
    "rounding_policy": {"normal": "تقريب عادي", "up": "لأعلى", "down": "لأسفل"},
    "attendance_mode": {"daily": "يومي", "per_period": "بالحصة"},
    "reason": {"password": "كلمة مرور غير صحيحة", "inactive": "الحساب معطّل", "locked": "الحساب مقفول"},
}

# field → (model name, attribute shown). `enrollment_id` shows its student.
FK_TARGETS = {
    "role_id": ("Role", "name_ar"), "user_id": ("User", "full_name"),
    "parent_user_id": ("User", "full_name"), "recorded_by_user_id": ("User", "full_name"),
    "approved_by_user_id": ("User", "full_name"), "created_by_user_id": ("User", "full_name"),
    "student_id": ("Student", "full_name"), "enrollment_id": ("Enrollment", "student"),
    "year_id": ("AcademicYear", "name"), "grade_id": ("Grade", "name"),
    "section_id": ("Section", "name"), "subject_id": ("Subject", "name"), "term_id": ("Term", "name"),
    "teacher_id": ("Teacher", "full_name"), "period_id": ("Period", "name"), "day_id": ("Day", "name"),
    "room_id": ("Room", "name"), "invoice_id": ("Invoice", "number"),
    "account_id": ("Account", "name"), "ar_account_id": ("Account", "name"),
    "cash_account_id": ("Account", "name"), "journal_entry_id": ("JournalEntry", "reference"),
    "component_id": ("AssessmentComponent", "name"),
    # the tables audited since the activity-log follow-up
    "parent_id": ("Account", "name"), "revenue_account_id": ("Account", "name"),
    "expense_account_id": ("Account", "name"), "counter_account_id": ("Account", "name"),
    "override_account_id": ("Account", "name"), "ap_account_id": ("Account", "name"),
    "academic_year_id": ("AcademicYear", "name"), "course_id": ("Course", "title"),
    "employee_id": ("Employee", "full_name"), "custodian_employee_id": ("Employee", "full_name"),
    "vendor_id": ("Vendor", "name"), "fee_type_id": ("FeeType", "name"), "applies_to_fee_type_id": ("FeeType", "name"),
    "applies_to_grade_id": ("Grade", "name"), "guardian_id": ("Guardian", "full_name"),
    "cost_center_id": ("CostCenter", "name"), "payment_method_id": ("PaymentMethod", "name"),
    "discount_type_id": ("DiscountType", "name"), "rubric_id": ("Rubric", "name"),
    "created_by_id": ("User", "full_name"), "approved_by_id": ("User", "full_name"),
    "author_id": ("User", "full_name"), "reported_by_user_id": ("User", "full_name"),
    "requested_by_user_id": ("User", "full_name"), "updated_by_user_id": ("User", "full_name"),
    "uploaded_by_user_id": ("User", "full_name"),
}
DELETED = "غير متاح (محذوف)"
EMPTY = "—"
# The row's subject, from its snapshot, first match wins.
_NAME_KEYS = ("full_name", "name_ar", "name", "title", "number", "reference", "username")
# Rows about a student through their enrollment.
_ENROLLMENT_ENTITIES = frozenset({"GradeEntry", "YearResult", "Attendance", "Enrollment", "Invoice"})

_MONTHS = ("يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس",
           "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر")


def _warn(kind: str, name: str) -> None:
    key = f"{kind}:{name}"
    if key not in _warned:
        _warned.add(key)
        _log.warning("audit display: no Arabic label for %s %r — add it to services/audit_display.py",
                     kind, name)


def action_label(action: str) -> str:
    if action not in ACTION_LABELS:
        _warn("action", action)
    return ACTION_LABELS.get(action, action)


def entity_label(entity: str) -> str:
    if entity not in ENTITY_LABELS:
        _warn("entity", entity)
    return ENTITY_LABELS.get(entity, entity)


def field_label(field: str) -> str:
    if field not in FIELD_LABELS:
        _warn("field", field)
    return FIELD_LABELS.get(field, field)


# ─── dates ──────────────────────────────────────────────────────────

def _tz():
    from zoneinfo import ZoneInfo
    try:
        from .subscriptions import get_settings
        name = get_settings().get("platform_timezone") or "Africa/Cairo"
    except Exception:  # noqa: BLE001 — a display must not fail on a setting
        name = "Africa/Cairo"
    try:
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001
        return ZoneInfo("Africa/Cairo")


def format_datetime(dt: datetime, tz=None) -> str:
    """24 أكتوبر 2026 – 10:14 ص (stored times are UTC, naive or aware)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(tz or _tz())
    hour = local.hour % 12 or 12
    return f"{local.day} {_MONTHS[local.month - 1]} {local.year} – {hour}:{local.minute:02d} " \
           f"{'ص' if local.hour < 12 else 'م'}"


def format_date(d: date) -> str:
    return f"{d.day} {_MONTHS[d.month - 1]} {d.year}"


def _parse_time(v: str):
    try:
        if len(v) == 10 and v[4] == "-" and v[7] == "-":
            return date.fromisoformat(v)
        if len(v) >= 16 and v[4] == "-" and v[10] in "T ":
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return None


# ─── foreign keys: one query per model per page ─────────────────────

class Names:
    """Names for every id the page shows, scoped to the school."""

    def __init__(self, school_id: int):
        self.sid = school_id
        self.want: dict[str, set] = {}
        self.got: dict[tuple, str] = {}

    def need(self, field: str, value) -> None:
        if field in FK_TARGETS and isinstance(value, int) and not isinstance(value, bool):
            self.want.setdefault(FK_TARGETS[field][0], set()).add(value)

    def load(self) -> None:
        from .. import models as M
        from ..extensions import db
        for model_name, ids in self.want.items():
            model = getattr(M, model_name, None)
            if model is None or not ids:
                continue
            q = model.query.filter(model.id.in_(ids))
            if "school_id" in model.__table__.c:
                q = q.filter(model.school_id == self.sid)
            if model_name == "Enrollment":
                rows = (db.session.query(M.Enrollment.id, M.Student.full_name)
                        .join(M.Student, M.Student.id == M.Enrollment.student_id)
                        .filter(M.Enrollment.id.in_(ids), M.Enrollment.school_id == self.sid).all())
                for i, name in rows:
                    self.got[(model_name, i)] = name
                continue
            attr = next(t[1] for t in FK_TARGETS.values() if t[0] == model_name)
            for row in q.all():
                v = getattr(row, attr, None) or getattr(row, "name", None) or getattr(row, "full_name", None)
                if v:
                    self.got[(model_name, row.id)] = str(v)

    def name(self, field: str, value) -> str:
        model_name = FK_TARGETS[field][0]
        return self.got.get((model_name, value), DELETED)


# ─── values ─────────────────────────────────────────────────────────

def format_value(field: str, value: Any, names: Optional[Names] = None, tz=None) -> str:
    if value is None or value == "":
        return EMPTY
    if value == REDACTED:
        return "مخفي"
    if isinstance(value, bool):
        if field in STATE_FIELDS:
            return "مفعّل" if value else "معطّل"
        return "نعم" if value else "لا"
    if field in FK_TARGETS and isinstance(value, int):
        return names.name(field, value) if names else DELETED
    if isinstance(value, (dict, list)):
        return "تم تحديثها" if field == "permissions" else f"{len(value)} عنصر"
    if isinstance(value, str):
        labels = VALUE_LABELS.get(field)
        if labels and value in labels:
            return labels[value]
        t = _parse_time(value)
        if isinstance(t, datetime):
            return format_datetime(t, tz)
        if isinstance(t, date):
            return format_date(t)
        return value
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


# ─── rows ───────────────────────────────────────────────────────────

def _changes(e, names: Names, tz) -> tuple[list[dict], bool]:
    """(changed fields, whether the update was login bookkeeping only)."""
    old = e.old_value if isinstance(e.old_value, dict) else {}
    new = e.new_value if isinstance(e.new_value, dict) else {}
    out, secret_changed, notes = [], False, []
    for field in old:
        if field in SECRET_NOTES:
            label, note = SECRET_NOTES[field]
            notes.append({"field": label, "old": None, "new": None, "note": note})
            continue
        if is_secret_field(field):
            secret_changed = True
            continue
        if field in HIDDEN_FIELDS:
            continue
        if field == "logo_url":
            note = ("تم حذف اللوجو" if not new.get(field) else
                    "تم رفع لوجو جديد" if not old.get(field) else "تم تغيير اللوجو")
            out.append({"field": field_label(field), "old": None, "new": None, "note": note})
            continue
        out.append({"field": field_label(field),
                    "old": format_value(field, old.get(field), names, tz),
                    "new": format_value(field, new.get(field), names, tz)})
    out.extend(notes)
    if secret_changed:
        out.insert(0, {"field": "كلمة المرور", "old": None, "new": None, "note": "تم تغيير كلمة المرور"})
    only_login = bool(old) and set(old) <= USER_LOGIN_FIELDS
    return out, only_login


def _summary(snapshot: dict, names: Names, tz, limit: int = 8) -> list[dict]:
    out = []
    for field, value in snapshot.items():
        if field in HIDDEN_FIELDS or is_secret_field(field) or value in (None, "", [], {}):
            continue
        if field == "logo_url":
            out.append({"field": field_label(field), "old": None, "new": "مرفوع"})
            continue
        out.append({"field": field_label(field), "old": None, "new": format_value(field, value, names, tz)})
        if len(out) >= limit:
            break
    return out


def _subject(e, names: Names) -> str:
    snap = e.new_value if isinstance(e.new_value, dict) else None
    if e.action == "delete" or not snap:
        snap = e.old_value if isinstance(e.old_value, dict) else {}
    for key in _NAME_KEYS:
        if snap.get(key):
            return str(snap[key])
    if e.entity_type in _ENROLLMENT_ENTITIES and isinstance(snap.get("enrollment_id"), int):
        n = names.name("enrollment_id", snap["enrollment_id"])
        return n if n != DELETED else ""
    if isinstance(snap.get("student_id"), int):
        n = names.name("student_id", snap["student_id"])
        return n if n != DELETED else ""
    return ""


def _sentence(e, actor: str, entity: str, subject: str) -> str:
    target = f"{entity}{': ' + subject if subject else ''}"
    if e.action == "login":
        return f"{actor} سجّل دخول"
    if e.action == "login_failed":
        return f"محاولة دخول فاشلة على حساب {actor}"
    if e.action == "login_locked":
        return f"اتقفل حساب {actor} بعد محاولات دخول فاشلة"
    if e.action == "create":
        return f"{actor} أضاف {target}"
    if e.action == "update":
        return f"{actor} عدّل بيانات {target}"
    if e.action == "delete":
        return f"{actor} حذف {target}"
    return f"{actor}: {action_label(e.action)}"


def _actor(e) -> tuple[str, str]:
    u = getattr(e, "user", None)
    if u is not None:
        role = getattr(u, "role", None)
        return u.full_name or u.username, (getattr(role, "name_ar", None) or "") if role else ""
    if e.support_session_id:
        return "فريق دعم منصتي", ""
    if isinstance(e.new_value, dict) and e.new_value.get(BY_PLATFORM):
        return "فريق منصتي", ""
    if e.action in ("login", "login_failed", "login_locked") and isinstance(e.new_value, dict):
        return "مستخدم", ""
    return "النظام", ""


# ─── logins: where from, on what ─────────────────────────────────────

_BROWSERS = (("Edg/", "Edge"), ("OPR/", "Opera"), ("SamsungBrowser", "Samsung Internet"),
             ("Firefox/", "Firefox"), ("CriOS", "Chrome"), ("Chrome/", "Chrome"), ("Safari/", "Safari"))
_SYSTEMS = (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("Windows", "Windows"),
            ("Mac OS X", "Mac"), ("Macintosh", "Mac"), ("CrOS", "Chromebook"), ("Linux", "Linux"))


def device_label(ua: Optional[str]) -> str:
    """"Chrome على Windows" from a User-Agent; "" when unknown."""
    if not ua:
        return ""
    browser = next((name for key, name in _BROWSERS if key in ua), "")
    system = next((name for key, name in _SYSTEMS if key in ua), "")
    if browser and system:
        return f"{browser} على {system}"
    return browser or system


def _login_details(e) -> list[dict]:
    """How the user signed in: the website or the mobile app, the browser /
    device, and — for a failure — why."""
    detail = e.new_value if isinstance(e.new_value, dict) else {}
    out = []
    via = detail.get("via")
    if via:
        out.append({"field": "الدخول من", "old": None, "new": VALUE_LABELS["via"].get(via, via)})
    # rows before 2026-10-25 never stored the browser (a bug): say so
    out.append({"field": "الجهاز", "old": None, "new": device_label(e.user_agent) or "غير مسجّل"})
    reason = detail.get("reason")
    if reason:
        out.append({"field": "السبب", "old": None, "new": VALUE_LABELS["reason"].get(reason, reason)})
    return out


def display_rows(entries: Iterable, school_id: int) -> list[dict]:
    """Readable rows for the page; login-only updates are left out (the
    `login` event covers them). Nothing raw is returned."""
    from types import SimpleNamespace
    # the same choke point as before (audit.redact: secret names AND any
    # bcrypt hash under an unexpected key), on a read-only copy of each row
    entries = [SimpleNamespace(id=e.id, action=e.action, entity_type=e.entity_type,
                               old_value=redact(e.old_value), new_value=redact(e.new_value),
                               created_at=e.created_at, ip_address=e.ip_address,
                               support_session_id=e.support_session_id, user=e.user,
                               user_agent=getattr(e, "user_agent", None))
               for e in entries]
    names = Names(school_id)
    for e in entries:
        for snap in (e.old_value, e.new_value):
            if isinstance(snap, dict):
                for k, v in snap.items():
                    names.need(k, v)
    names.load()
    tz = _tz()
    rows = []
    for e in entries:
        actor, role = _actor(e)
        entity = entity_label(e.entity_type)
        details, only_login = [], False
        if e.action == "update":
            details, only_login = _changes(e, names, tz)
            if only_login:
                continue
        elif e.action == "create" and isinstance(e.new_value, dict):
            details = _summary(e.new_value, names, tz)
        elif e.action == "delete" and isinstance(e.old_value, dict):
            details = _summary(e.old_value, names, tz, limit=6)
        elif e.action in ("login", "login_failed", "login_locked"):
            details = _login_details(e)
        elif isinstance(e.new_value, dict):
            details = _summary(e.new_value or {}, names, tz)
        if e.action in ("login", "login_failed", "login_locked") and e.user is not None:
            subject = ""
        else:
            subject = _subject(e, names)
        rows.append({
            "id": e.id,
            "kind": ACTION_KIND.get(e.action, "other"),
            "action": action_label(e.action),
            "sentence": _sentence(e, actor, entity, subject),
            "actor_role": role,
            "when": format_datetime(e.created_at, tz) if e.created_at else "",
            "ip": e.ip_address or "",
            "details": details,
            "is_update": e.action == "update",
        })
    return rows
