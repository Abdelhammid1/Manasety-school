# Sprint 10 — تقرير قبول تطبيقات الموبايل

**التاريخ:** 2026-07-19
**الهدف:** إكمال تطبيقَي Flutter (المعلم + ولي الأمر) من 40% إلى 100%
**النتيجة الفعلية:** **~85% مكتمل** — الـ 15% المتبقية هي إجراءات على العميل (Firebase / متاجر التطبيقات)

---

## نطاق Sprint 10 — Phase 2 + Phase 3

### ✅ Phase 2 — عمليات الكتابة للمعلم (100% مكتمل)

**Backend — 5 endpoints جديدة:**
| Endpoint | الغرض |
|---|---|
| `GET /api/teacher/components` | مكوّنات التقييم لـ (مادة، فترة) |
| `GET /api/teacher/grades` | الدرجات الحالية لتعبئة النموذج (لتعديل) |
| `GET /api/teacher/attendance` | الحضور الحالي لتعبئة النموذج (لتعديل) |
| `POST /api/teacher/upload` | رفع ملف (PDF/صورة، حد أقصى 10MB) |
| `POST /api/auth/change-password` | تغيير كلمة المرور |

**تطبيق المعلم — 4 شاشات كتابة كاملة:**
| الشاشة | المسار | الوصف |
|---|---|---|
| تسجيل الحضور | `/sections/:id/attendance` | 3 أزرار حاضر/غائب/متأخّر + swipe + notes + عدّاد ذكي |
| رصد الدرجات | `/sections/:id/grades` | Picker ثلاثي (فترة → مادة → مكوّن) + جدول رصد |
| رفع مادة | `/materials/upload` | ملف (PDF/صورة) أو رابط + progress bar |
| تغيير كلمة المرور | `/profile/change-password` | نموذج بـ 3 حقول + تحقق فوري |

### ✅ Phase 3A — Backend للإشعارات (100% مكتمل)

- ✅ نموذج `DeviceToken` جديد + migration
- ✅ عمود `NotificationLog.read_at` جديد
- ✅ خدمة `send_push()` باستخدام `firebase-admin` (تُنظّف tokens غير الصالحة تلقائيًا)
- ✅ `send_notification()` الآن يُرسل إشعار push تلقائيًا لولي الأمر بجانب رسالة WhatsApp
- ✅ 3 endpoints جديدة:
  - `POST /api/auth/device-token` — تسجيل token
  - `DELETE /api/auth/device-token` — إلغاء عند الخروج
  - `POST /api/notifications/<id>/read` — تعليم كمقروء
- ✅ ربط تلقائي مع: الغياب، إصدار الفاتورة، الدفع، الاسترداد، اعتماد النتيجة

### ✅ Phase 3B — تكامل FCM في Flutter (100% مكتمل — يحتاج ملفات Firebase من العميل)

- ✅ `FcmService` في كلا التطبيقين — تهيئة آمنة (no-op إذا كانت ملفات Firebase غير موجودة)
- ✅ `LocalNotifications` لعرض الرسائل عندما يكون التطبيق في الواجهة
- ✅ تسجيل token تلقائي بعد تسجيل الدخول
- ✅ إلغاء token تلقائي عند تسجيل الخروج
- ✅ Deep linking عند النقر على الإشعار (يفتح شاشة الحضور/النتائج/الفواتير المناسبة)
- ✅ التعليم كمقروء تلقائيًا عند فتح الإشعار

### ✅ Phase 3C — بنية النشر (100% مكتمل)

- ✅ `mobile/README.md` — دليل عربي شامل للعميل (Firebase setup + بناء + نشر)
- ✅ `scripts/build_mobile.sh` — سكريبت آلي لبناء `.aab` + `.ipa`
- ✅ `.gitignore` يحمي ملفات Firebase من الرفع

### ⏳ Phase 3D — نشر المتاجر (يحتاج إجراءات من العميل)

| الخطوة | الحالة | من يقوم بها |
|---|---|---|
| إنشاء مشروع Firebase | ⏳ | العميل (10 دقائق) |
| تحميل 4 ملفات config | ⏳ | العميل بعد إنشاء المشروع |
| APNs `.p8` key | ⏳ | العميل (يحتاج Apple Dev) |
| تسجيل في Google Play Console ($25) | ⏳ | العميل |
| تسجيل في Apple Developer Program ($99/سنة) | ⏳ | العميل (1 أسبوع مراجعة) |
| إنشاء keystore + توقيع Android | ⏳ | العميل / أنا (بعد تجهيز الحساب) |
| رفع `.aab` لـ Play Internal Test | ⏳ | بعد إنشاء الحساب |
| رفع `.ipa` لـ TestFlight | ⏳ | بعد اشتراك Apple Dev |

---

## نسبة الاكتمال النهائية

| المكوّن | Phase 0 | Phase 1 | Phase 2 | Phase 3 | إجمالي |
|---|---|---|---|---|---|
| **تطبيق المعلم** | ✅ | ✅ | ✅ | ✅ (كود) / ⏳ (نشر) | **90%** |
| **تطبيق ولي الأمر** | ✅ | ✅ | — | ✅ (كود) / ⏳ (نشر) | **85%** |
| **Backend API** | — | ✅ | ✅ | ✅ | **100%** |
| **الإجمالي** | | | | | **~85%** |

**الـ 15% المتبقية** = إجراءات على جانب العميل حصريًا:
- تسجيل حسابات Firebase / Apple Developer / Google Play Console
- تحميل ملفات config
- إنشاء keystores
- رفع الملفات النهائية للمتاجر

بمجرّد إنجاز هذه الإجراءات، النظام يعمل 100% بدون أي تعديل في الكود.

---

## Commits

| Commit | Sprint | الوصف |
|---|---|---|
| `66a09e9` | 7 Phase 0 | Foundation (Riverpod, GoRouter, Dio, JWT) |
| `b243bac` | 7 Phase 1 | Read-only screens for both apps |
| `ddea61f` | **10 Phase 2** | Teacher write actions |
| `(new)` | **10 Phase 3** | FCM + build infrastructure |

---

## للتحقق

### Backend
```bash
FLASK_APP=wsgi.py .venv/bin/flask run --port 5050 --no-reload
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5050/api/auth/login
# → 405 (POST-only) = صحيح
```

### Flutter (المعلم)
```bash
cd mobile/teacher_app
flutter analyze         # → No issues found
flutter test            # → All tests passed
flutter run             # على emulator/device — سيعمل بدون Firebase config
```

### Flutter (ولي الأمر)
```bash
cd mobile/parent_app
flutter analyze         # → No issues found
flutter test            # → All tests passed
```

## للنشر بعد إنجاز إجراءات العميل

راجع `mobile/README.md` — الدليل الكامل بالعربي:
- إنشاء مشروع Firebase
- تحميل ملفات config
- تفعيل APNs
- Service account للسيرفر
- إعداد Android google-services plugin
- تفعيل iOS Push capability
- إنشاء keystores + توقيع
- بناء ورفع للمتاجر
