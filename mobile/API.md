# Manasety REST API

> Used by the Teacher mobile app and Parent mobile app (Flutter).
> All endpoints under `/api/`. Base URL in production: `https://manasety-school.sd/api`.

## Authentication

JWT-based. Get a token with `POST /api/auth/login`, then send `Authorization: Bearer <token>` on every subsequent request.
Tokens are valid for 24 hours.

### `POST /api/auth/login`
```json
{ "username": "teacher_ahmed", "password": "..." }
```
Response 200:
```json
{
  "token": "eyJhbGc...",
  "user": {
    "id": 3,
    "school_id": 1,
    "school_name": "مؤسسة الشيخ صالح الشريف للتعليم القرآني",
    "username": "teacher_ahmed", "full_name": "أحمد المعلم",
    "role": "teacher", "role_ar": "معلم",
    "is_teacher": true, "teacher_id": 5,
    "children_count": 0,
    "children_ids": []
  }
}
```
For a parent user, `children_ids` is populated so the mobile app can pre-fetch
each child's data without an extra `/parent/children` roundtrip.
401 on bad credentials. 400 on missing fields.

### `GET /api/me`
Returns the current authenticated user (same `user` block as above).

---

## Teacher endpoints (require user linked to a Teacher record)

### `GET /api/teacher/schedule`
Returns teacher's weekly schedule for the active year.
```json
{ "slots": [
  { "day_id": 1, "day_name": "الأحد",
    "period_id": 1, "period_name": "الحصة الأولى",
    "start_time": "08:00", "end_time": "08:45",
    "section_id": 4, "section_name": "الصف الأول / أ",
    "subject_id": 2, "subject_name": "الرياضيات" }
]}
```

### `GET /api/teacher/terms` *(Sprint 7)*
Terms in the active academic year.
```json
{ "terms": [
  { "id": 1, "name": "الفصل الأول", "year_id": 1,
    "start_date": "2025-09-01", "end_date": "2026-01-15" }
]}
```

### `GET /api/teacher/section/<section_id>/schedule` *(Sprint 7)*
Weekly schedule for a specific section (includes every teacher's slot in that section, not just the requester's).
```json
{ "slots": [
  { "day_id": 1, "day_name": "الأحد",
    "period_id": 1, "period_name": "الحصة الأولى",
    "start_time": "08:00", "end_time": "08:45",
    "subject_id": 2, "subject_name": "الرياضيات",
    "teacher_id": 5, "teacher_name": "أحمد المعلم" }
]}
```

### `GET /api/teacher/sections`
Sections the teacher is assigned to, with their subjects.
```json
{ "sections": [
  { "id": 4, "name": "الصف الأول / أ",
    "subjects": [{ "id": 2, "name": "الرياضيات" }] }
]}
```

### `GET /api/teacher/students?section_id=4`
Active enrollments for one of the teacher's sections.
```json
{ "students": [
  { "enrollment_id": 11, "student_id": 7,
    "permanent_code": "SAS-00001", "full_name": "أحمد علي" }
]}
```

### `POST /api/teacher/attendance`
Record daily attendance for a section. Triggers WhatsApp notification on transitions into "absent".
```json
{
  "section_id": 4,
  "date": "2026-03-01",
  "records": [
    { "enrollment_id": 11, "status": "present" },
    { "enrollment_id": 12, "status": "absent", "notes": "بدون إذن" }
  ]
}
```
Response 200:
```json
{ "creates": 2, "updates": 0, "absent_notifications": 1 }
```
403 if teacher is not assigned to the section.

### `POST /api/teacher/grades`
Enter grades for a (section, term, subject). Server-side max validation.
```json
{
  "section_id": 4, "term_id": 1, "subject_id": 2,
  "entries": [
    { "enrollment_id": 11, "component_id": 1, "score": 28 },
    { "enrollment_id": 11, "component_id": 2, "score": 65 }
  ]
}
```
Response: `{ "saved": 2, "rejected": 0 }`
403 if results already approved or teacher not assigned.

### `GET /api/teacher/materials`
List materials uploaded by this teacher.

### `POST /api/teacher/materials`
Upload material (link or video URL; file upload via multipart is roadmap).
```json
{
  "section_id": 4, "subject_id": 2,
  "title": "شرح الدرس الأول",
  "description": "PDF لشرح الجمع والطرح",
  "kind": "link",
  "external_url": "https://example.com/lesson1.pdf"
}
```
Returns 201 with `{ "id": 23, "title": "..." }`.

---

## Parent endpoints (require user linked as `parent_user_id` on Student)

### `GET /api/parent/children`
List children of the authenticated parent.
```json
{ "children": [
  { "id": 7, "permanent_code": "SAS-00001", "full_name": "أحمد علي",
    "current_section": "الصف الأول / أ", "current_year": "2025-2026" }
]}
```

### `GET /api/parent/child/<student_id>/attendance`
Last 60 attendance records + summary.
```json
{
  "summary": { "present": 45, "absent": 3, "late": 2, "total": 50, "rate": 90.0 },
  "records": [
    { "date": "2026-03-01", "status": "present", "notes": null }
  ]
}
```

### `GET /api/parent/child/<student_id>/results`
**Only approved results** (T-10.3 acceptance).
```json
{ "results": [
  { "year": "2024-2025", "grade": "الصف الأول", "section": "أ",
    "status": "pass", "average": 82.5,
    "subject_scores": { "الرياضيات": 85.0, "اللغة العربية": 80.0 },
    "approved_at": "2025-06-25T..." }
]}
```

### `GET /api/parent/child/<student_id>/invoices`
All invoices for the student across years.
```json
{ "invoices": [
  { "id": 4, "number": "INV-2025-2026-00001",
    "issue_date": "2025-09-01", "due_date": "2025-09-30",
    "total_amount": 1300.0, "paid_amount": 700.0, "remaining": 600.0,
    "status": "partial" }
]}
```

### `GET /api/parent/child/<student_id>/schedule` *(Sprint 7)*
Weekly schedule for the child's current section (same shape as `/api/teacher/section/<id>/schedule`).

### `GET /api/parent/child/<student_id>/materials`
Materials uploaded by teachers for the child's current section.

### `GET /api/parent/notifications`
Last 50 notifications routed to any of the parent's phone numbers.
```json
{ "notifications": [
  { "id": 12, "kind": "absence", "status": "sent",
    "payload": "{\"student\":\"...\", \"message\":\"...\"}",
    "created_at": "2026-03-01T..." }
]}
```

---

## Teacher-write pre-fill + upload (Sprint 10 Phase 2)

### `GET /api/teacher/components?subject_id=&term_id=`
List active `AssessmentComponent` records for a (subject, term) pair. Used by grade-entry form to build the component picker.
```json
{ "components": [
  { "id": 4, "name": "أعمال سنة", "max_score": 30.0 },
  { "id": 5, "name": "نهاية الفترة", "max_score": 70.0 }
]}
```

### `GET /api/teacher/grades?section_id=&subject_id=&term_id=&component_id=`
Fetch existing `GradeEntry` values so the grade-entry form pre-fills for edits.
Requires teacher to be assigned to (section, subject).
```json
{ "entries": [
  { "enrollment_id": 42, "score": 27.5 }
]}
```

### `GET /api/teacher/attendance?section_id=&date=YYYY-MM-DD`
Fetch existing `Attendance` records for a (section, date) so the attendance form pre-fills.
Requires teacher to be assigned to section.
```json
{
  "date": "2026-07-19",
  "records": [
    { "enrollment_id": 42, "status": "present", "notes": null }
  ]
}
```

### `POST /api/teacher/upload` — multipart/form-data
Upload a file as a teaching material. Fields:
- `file` (required, PDF or JPG/JPEG/PNG, max 10MB)
- `section_id`, `subject_id` (required)
- `title` (required), `description` (optional)

Returns `201` with:
```json
{
  "id": 8, "title": "ملخص الوحدة 3",
  "file_path": "/static/uploads/materials/1/abc123.pdf",
  "kind": "file",
  "section_name": "الصف الأول / أ"
}
```
`413` on files >10MB. `400` on unsupported extension. `403` if not assigned.

### `POST /api/auth/change-password`
Change the authenticated user's password.
```json
{ "old_password": "current", "new_password": "at least 8 chars" }
```
`200 {"ok": true}` on success. `401` on wrong current password. `400` on new password <8 chars.

---

## Error format

All errors return JSON `{ "error": "message" }` with appropriate HTTP code (400/401/403/404).

## CSRF

`/api/*` is CSRF-exempt (uses JWT). Only the web pages (`/auth`, `/admin`, `/students`, etc.) require CSRF tokens.
