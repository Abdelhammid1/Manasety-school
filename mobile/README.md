# تطبيقات الموبايل — مدارس الشيخ صالح الشريف للتعليم القرآني

تطبيقان Flutter — **بوابة المعلم** و**بوابة ولي الأمر** — لمنظومة مدارس الشيخ صالح الشريف للتعليم القرآني.

## الحالة الحالية (Sprint 10)

| المكوّن | الحالة |
|---|---|
| تطبيق ولي الأمر (قراءة كاملة) | ✅ 100% |
| تطبيق المعلم (قراءة كاملة) | ✅ 100% |
| تطبيق المعلم — تسجيل الحضور + رصد الدرجات + رفع مواد + تغيير كلمة السر | ✅ 100% (Sprint 10 Phase 2) |
| خدمات Backend للأشعارات FCM | ✅ 100% (Sprint 10 Phase 3A) |
| كود Flutter لاستقبال الإشعارات | ✅ 100% (Sprint 10 Phase 3B — يحتاج ملفات Firebase من العميل) |
| نشر على المتجر (Play + TestFlight) | ⏳ يحتاج إجراء من العميل |

**نسبة الاكتمال الحالية: ~85%** — الـ 15% المتبقية كلها إجراءات على جانب العميل (تسجيل Firebase، Apple Developer، Play Console).

---

## خطوات إعداد Firebase (Push Notifications) — يقوم بها العميل

الإشعارات لن تعمل حتى تُنجز هذه الخطوات على حساب Google الخاص بالمؤسسة.

### 1. إنشاء مشروع Firebase
1. افتح https://console.firebase.google.com
2. اضغط **Add project**
3. الاسم: `Manasety` (أو أي اسم)

### 2. إضافة 4 تطبيقات تحت المشروع

| المنصة | Bundle/Package ID | مكان الملف |
|---|---|---|
| Android — المعلم | `com.salehsharif.manasety.teacher` | `mobile/teacher_app/android/app/google-services.json` |
| Android — ولي الأمر | `com.salehsharif.manasety.parent` | `mobile/parent_app/android/app/google-services.json` |
| iOS — المعلم | `com.salehsharif.manasety.teacher` | `mobile/teacher_app/ios/Runner/GoogleService-Info.plist` |
| iOS — ولي الأمر | `com.salehsharif.manasety.parent` | `mobile/parent_app/ios/Runner/GoogleService-Info.plist` |

> ⚠️ هذه الملفات في `.gitignore` — لا تدفعها إلى GitHub.

### 3. تفعيل APNs (لإشعارات iOS)
1. https://developer.apple.com/account/resources/authkeys/list
2. أنشئ مفتاح **APNs** (`.p8`)
3. Firebase → Project Settings → Cloud Messaging → Apple app → ارفع `.p8` + Key ID + Team ID

### 4. Service Account للسيرفر
1. Firebase → Project Settings → Service accounts → **Generate new private key**
2. احفظه على السيرفر: `/opt/manasety/manasety-fcm-service-account.json`
3. في `.env`:
   ```
   FCM_SERVICE_ACCOUNT_PATH=/opt/manasety/manasety-fcm-service-account.json
   ```
4. `sudo systemctl restart manasety`

### 5. تفعيل Android google-services plugin
في `mobile/{teacher_app,parent_app}/android/build.gradle.kts` (root):
```kotlin
plugins {
  id("com.google.gms.google-services") version "4.4.2" apply false
}
```
في `mobile/{teacher_app,parent_app}/android/app/build.gradle.kts`:
```kotlin
plugins {
  ...
  id("com.google.gms.google-services")
}
```

### 6. تفعيل iOS Push capability
افتح كل من `mobile/{teacher_app,parent_app}/ios/Runner.xcworkspace` في Xcode → Runner target → **Signing & Capabilities**:
- **+ Push Notifications**
- **+ Background Modes** → فعّل **Remote notifications**

---

## البناء والنشر

### Android — Play Internal Test

```bash
# مرّة واحدة لكل تطبيق: أنشئ upload keystore
keytool -genkey -v -keystore ~/keys/manasety-teacher-upload.jks \
  -keyalg RSA -keysize 2048 -validity 9125 -alias upload

# أضف android/key.properties (في .gitignore) بمحتوى:
#   storePassword=...
#   keyPassword=...
#   keyAlias=upload
#   storeFile=/absolute/path/to/manasety-teacher-upload.jks

# البناء:
cd mobile/teacher_app
flutter build appbundle --release --dart-define=API_BASE=https://manasety-school.sd/api
# → build/app/outputs/bundle/release/app-release.aab

# ارفع الـ .aab إلى Play Console → Internal testing
```
Play Console: $25 مرة واحدة. مراجعة Internal Test فورية.

### iOS — TestFlight
يشترط اشتراك Apple Developer Program ($99/سنة).
```bash
cd mobile/teacher_app
flutter build ipa --release --dart-define=API_BASE=https://manasety-school.sd/api
```
افتح `build/ios/archive/Runner.xcarchive` في Xcode Organizer → **Distribute App** → **App Store Connect**.

### سكريبت جاهز
`scripts/build_mobile.sh` يبني الاثنين دفعة واحدة.

---

## البنية

```
mobile/
├── teacher_app/          # تطبيق المعلم
│   └── lib/
│       ├── core/         # env, api, storage, router, theme, push (FCM)
│       ├── features/     # auth, sections, students, materials, schedule,
│       │                 # notifications, profile, attendance (Sprint 10),
│       │                 # grades (Sprint 10)
│       └── shared/       # models + widgets
├── parent_app/           # نفس الهيكل
├── API.md                # وثائق REST API
└── README.md             # هذا الملف
```

## الروابط

- **Backend production**: `https://manasety-school.sd/api`
- **Backend staging**: `http://localhost:5050/api`
- **GitHub**: https://github.com/Abdelhammid1/EduSchool
