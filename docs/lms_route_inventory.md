# جرد مسارات الـ LMS — BUG-008

كل مسار في `lms.*` و `courses.*`، والفحص على الـ server قبل وبعد الإصلاح.
«تسجيل دخول فقط ⚠» = أي مستخدم مسجّل (طالب، ولي أمر…) كان يقدر يوصله.
المسارات: 110 — اتغيّر فحصها: 59. بعد الإصلاح: مفيش مسار «تسجيل دخول فقط».

مسارات الطالب (الحل، التسليم، النتيجة، الحفظ التلقائي، عرض المقرّر والدرس) فضلت بفحوصها:
تسجيل الطالب في شعبة منشور لها المقرّر، أو ملكية المحاولة.

| المسار | Method | الدالة | قبل | بعد |
|---|---|---|---|---|
| `/lms/assignments` | GET | `assignments_home` | القائمة مفلترة: الطالب يرى مقرّرات شعبته المنشورة فقط | القائمة مفلترة: الطالب يرى مقرّرات شعبته المنشورة فقط |
| `/lms/quizzes` | GET | `quizzes_home` | القائمة مفلترة: الطالب يرى مقرّرات شعبته المنشورة فقط | القائمة مفلترة: الطالب يرى مقرّرات شعبته المنشورة فقط |
| `/lms/courses/<hid:cid>/assignments/new` | GET/POST | `assignment_new` | lms.edit | lms.edit |
| `/lms/assignments/<hid:aid>/analytics` | GET | `assignment_analytics` | دور admin/teacher | **lms.edit + دور admin/teacher** |
| `/lms/assignments/<hid:aid>/edit` | GET/POST | `assignment_edit` | lms.edit | lms.edit |
| `/lms/assignments/<hid:aid>/questions` | GET | `assignment_questions` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/assignments/<hid:aid>/questions/add` | POST | `assignment_question_add` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/assignment-questions/<hid:qid>/update` | POST | `assignment_question_update` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/assignment-questions/<hid:qid>/delete` | POST | `assignment_question_delete` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/assignments/<hid:aid>/pick` | GET/POST | `assignment_pick_from_bank` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/templates` | GET | `template_home` | lms.edit | lms.edit |
| `/lms/templates/<hid:tid>/delete` | POST | `template_delete` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/assignments/<hid:aid>/save-as-template` | POST | `assignment_save_as_template` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/courses/<hid:cid>/assignments/from-template` | GET/POST | `assignment_from_template` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/assignments/<hid:aid>/delete` | POST | `assignment_delete` | lms.edit | lms.edit |
| `/lms/courses/<hid:cid>/quizzes/new` | GET/POST | `quiz_new` | lms.edit | lms.edit |
| `/lms/quizzes/<hid:qid>/edit` | GET/POST | `quiz_edit` | lms.edit | lms.edit |
| `/lms/quizzes/<hid:qid>/delete` | POST | `quiz_delete` | lms.edit | lms.edit |
| `/lms/quizzes/<hid:qid>/questions` | GET | `quiz_questions` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/quizzes/<hid:qid>/questions/add` | POST | `quiz_question_add` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/questions/<hid:qid>/update` | POST | `quiz_question_update` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/questions/<hid:qid>/delete` | POST | `quiz_question_delete` | lms.edit | lms.edit |
| `/lms/questions/<hid:qid>/version` | POST | `quiz_question_new_version` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/assignment-questions/<hid:qid>/version` | POST | `assignment_question_new_version` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/bank/dashboard` | GET | `qbank_dashboard` | lms.edit | lms.edit |
| `/lms/assessment-templates` | GET | `templates_gallery` | lms.edit | lms.edit |
| `/lms/assessment-templates/new` | GET/POST | `template_new` | lms.edit | lms.edit |
| `/lms/assessment-templates/<hid:tid>/edit` | GET/POST | `template_edit` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/assessment-templates/<hid:tid>` | GET | `template_detail` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/assessment-templates/<hid:tid>/items/attach` | POST | `template_items_attach` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/assessment-templates/<hid:tid>/items/<hid:iid>/delete` | POST | `template_item_delete` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/assessment-templates/<hid:tid>/items/save` | POST | `template_items_save` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/assessment-templates/<hid:tid>/use` | GET/POST | `template_use` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/exams/blueprint/new` | GET/POST | `blueprint_exam_new` | lms.edit | lms.edit |
| `/lms/exams/blueprint/create` | POST | `blueprint_exam_create` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/bank` | GET | `bank_home` | lms.edit | lms.edit |
| `/lms/bank/new` | GET/POST | `bank_new` | lms.edit | lms.edit |
| `/lms/bank/smart/new` | GET/POST | `bank_smart_new` | lms.edit | lms.edit |
| `/lms/bank/<hid:bid>/edit` | GET/POST | `bank_edit` | lms.edit | lms.edit |
| `/lms/bank/<hid:bid>/delete` | POST | `bank_delete` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/bank/<hid:bid>/archive` | POST | `bank_archive` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/assessment-templates/<hid:tid>/items/<hid:iid>/toggle-hidden` | POST | `template_item_toggle_hidden` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/assessment-templates/<hid:tid>/ai/generate` | POST | `template_ai_generate` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/bank/ai-review` | POST | `bank_ai_review` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/quizzes/<hid:qid>/publish-results` | POST | `quiz_publish_results` | دور admin/teacher | **lms.edit + دور admin/teacher** |
| `/lms/quizzes/<hid:qid>/analysis` | GET | `quiz_analysis` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/bank/<hid:bid>/rewrite` | GET | `bank_rewrite_panel` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/bank/<hid:bid>/ai-rewrite` | POST | `bank_ai_rewrite` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/bank/<hid:bid>/ai-rewrite/save` | POST | `bank_ai_rewrite_save` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/submissions/<hid:sid>/grade` | GET | `submission_grade_panel` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/submissions/<hid:sid>/grade/save` | POST | `submission_grade_save` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/submissions/<hid:sid>/ai-grade` | POST | `submission_ai_grade` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/exams/blueprint/ai-suggest` | POST | `blueprint_ai_suggest` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/assessment-templates/<hid:tid>/print` | GET | `template_print` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/bank/<hid:bid>/state` | POST | `bank_set_state` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/quizzes/<hid:qid>/pick` | GET/POST | `quiz_pick_from_bank` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/assignments/<hid:aid>` | GET | `assignment_detail` | طالب مسجّل في شعبة المقرّر | طالب مسجّل في شعبة المقرّر |
| `/lms/assignments/<hid:aid>/submit` | POST | `assignment_submit` | طالب مسجّل في شعبة المقرّر | طالب مسجّل في شعبة المقرّر |
| `/lms/quizzes/<hid:qid>/take` | GET | `quiz_take` | طالب مسجّل في شعبة المقرّر + دور admin/teacher | طالب مسجّل في شعبة المقرّر + دور admin/teacher |
| `/lms/quizzes/<hid:qid>/submit` | POST | `quiz_submit` | طالب مسجّل في شعبة المقرّر + صاحب المحاولة / المعلم / ولي الأمر | طالب مسجّل في شعبة المقرّر + صاحب المحاولة / المعلم / ولي الأمر |
| `/lms/quizzes/result/<hid:attempt_id>` | GET | `quiz_result` | صاحب المحاولة / المعلم / ولي الأمر | صاحب المحاولة / المعلم / ولي الأمر |
| `/lms/passages` | GET | `passages_home` | lms.edit | lms.edit |
| `/lms/passages/new` | GET/POST | `passage_new` | lms.edit | lms.edit |
| `/lms/passages/<hid:pid>` | GET/POST | `passage_edit` | lms.edit | lms.edit |
| `/lms/passages/<hid:pid>/delete` | POST | `passage_delete` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/quizzes/attempts/<hid:attempt_id>/tab-switch` | POST | `attempt_tab_switch` | صاحب المحاولة فقط | صاحب المحاولة فقط |
| `/lms/quizzes/attempts/<hid:attempt_id>/flag` | POST | `attempt_flag` | صاحب المحاولة فقط | صاحب المحاولة فقط |
| `/lms/quizzes/attempts/<hid:attempt_id>/autosave` | POST | `attempt_autosave` | صاحب المحاولة فقط | صاحب المحاولة فقط |
| `/lms/quizzes/<hid:qid>/live` | GET | `quiz_live_monitor` | دور admin/teacher | **lms.edit + دور admin/teacher** |
| `/lms/quizzes/<hid:qid>/live.json` | GET | `quiz_live_monitor_json` | دور admin/teacher | **lms.edit + دور admin/teacher** |
| `/lms/submissions/<hid:submission_id>/rubric-grade` | GET/POST | `submission_rubric_grade` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/skills/new` | POST | `skill_new` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/skills/<hid:sid>/delete` | POST | `skill_delete` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/objectives/new` | POST | `objective_new` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/objectives/<hid:oid>/delete` | POST | `objective_delete` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/collections/new` | POST | `collection_new` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/collections/<hid:cid>/add` | POST | `collection_add` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/feedback-templates` | GET | `feedback_templates_json` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/feedback-templates/new` | POST | `feedback_template_new` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/feedback-templates/<hid:tid>/delete` | POST | `feedback_template_delete` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/lms/assignments/<hid:aid>/extensions` | POST | `assignment_extension_add` | دور admin/teacher | **lms.edit + دور admin/teacher** |
| `/lms/taxonomy` | GET | `taxonomy_home` | lms.view | lms.view |
| `/lms/taxonomy/skills/new` | POST | `taxonomy_skill_new` | lms.edit | lms.edit |
| `/lms/taxonomy/skills/<hid:sid>/edit` | POST | `taxonomy_skill_edit` | lms.edit | lms.edit |
| `/lms/taxonomy/skills/<hid:sid>/delete` | POST | `taxonomy_skill_delete` | lms.delete | lms.delete |
| `/lms/taxonomy/objectives/new` | POST | `taxonomy_objective_new` | lms.edit | lms.edit |
| `/lms/taxonomy/objectives/<hid:oid>/edit` | POST | `taxonomy_objective_edit` | lms.edit | lms.edit |
| `/lms/taxonomy/objectives/<hid:oid>/delete` | POST | `taxonomy_objective_delete` | lms.delete | lms.delete |
| `/lms/announcements` | GET | `announcements_home` | إعلانات المدرسة (قراءة للجميع؛ زرار الإضافة لمن يملك النشر) | بدون تغيير |
| `/lms/announcements/new` | POST | `announcement_new` | admin/teacher أو portal.add | admin/teacher أو portal.add |
| `/lms/announcements/<hid:aid>/pin` | POST | `announcement_pin` | admin أو كاتب الإعلان | admin أو كاتب الإعلان |
| `/lms/announcements/<hid:aid>/delete` | POST | `announcement_delete` | admin أو كاتب الإعلان | admin أو كاتب الإعلان |
| `/lms/reports/student/<hid:student_id>` | GET | `report_student` | تسجيل دخول فقط ⚠ | **lms.view أو students.view** |
| `/lms/reports/section/<hid:section_id>` | GET | `report_section` | تسجيل دخول فقط ⚠ | **lms.view أو sections.view** |
| `/courses/` | GET | `list_courses` | يعرض حسب lms.edit | يعرض حسب lms.edit |
| `/courses/grade/<hid:grade_id>` | GET | `grade_terms` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/courses/grade/<hid:grade_id>/term/<hid:term_id>` | GET | `grade_term_subjects` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/courses/pick/grade/<hid:grade_id>/subject/<hid:subject_id>` | GET | `course_pick_section` | تسجيل دخول فقط ⚠ | **lms.edit** |
| `/courses/<hid:course_id>` | GET | `detail` | طالب مسجّل في شعبة المقرّر + يعرض حسب lms.edit | طالب مسجّل في شعبة المقرّر + يعرض حسب lms.edit |
| `/courses/<hid:course_id>/sections/link` | POST | `section_link` | — (جديد) | **lms.edit** |
| `/courses/<hid:course_id>/sections/<hid:link_id>/unlink` | POST | `section_unlink` | — (جديد) | **lms.edit** |
| `/courses/new` | GET/POST | `new` | lms.edit | lms.edit |
| `/courses/<hid:course_id>/delete` | POST | `course_delete` | lms.edit | lms.edit |
| `/courses/<hid:course_id>/lessons/new` | GET/POST | `lesson_new` | lms.edit | lms.edit |
| `/courses/lessons/<hid:lesson_id>/edit` | GET/POST | `lesson_edit` | lms.edit | lms.edit |
| `/courses/<hid:course_id>/units/new` | POST | `unit_new` | lms.edit | lms.edit |
| `/courses/units/<hid:unit_id>/edit` | POST | `unit_edit` | lms.edit | lms.edit |
| `/courses/units/<hid:unit_id>/delete` | POST | `unit_delete` | lms.edit | lms.edit |
| `/courses/lessons/<hid:lesson_id>/delete` | POST | `lesson_delete` | lms.edit | lms.edit |
| `/courses/lessons/<hid:lesson_id>` | GET | `lesson_view` | طالب مسجّل في شعبة المقرّر + يعرض حسب lms.edit | طالب مسجّل في شعبة المقرّر + يعرض حسب lms.edit |

## خارج الـ blueprint

| المسار | قبل | بعد |
|---|---|---|
| `GET /api/admin/question_bank/dashboard` | JWT فقط ⚠ | **lms.edit** |
| `GET /api/admin/question_bank/questions` | JWT فقط ⚠ | **lms.edit** |
| `POST /api/admin/question_bank/questions/<id>/state` | JWT فقط ⚠ (أي طالب يغيّر حالة سؤال) | **lms.edit** |

كل رفض بـ `require_permission` بقى يتسجّل في لوج التطبيق (warning: المستخدم، المدرسة، الصلاحية، المسار).
