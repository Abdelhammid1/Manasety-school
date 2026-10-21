# منصتي — عقد أكواد أخطاء الـAPI (SAAS-037)

تطبيقات الموبايل بتعتمد على الأكواد دي **حرفيًا**. أي تغيير في كود أو في شكل الرد بيكسر
`tests/test_saas037_api_contract.py` عن قصد: التغيير محتاج نسخة API جديدة واتفاق مع فريق التطبيقات.

## شكل الرد

كل رد خطأ JSON بالشكل:

```json
{"error": "<code>", "message_ar": "<رسالة للعرض>", ...}
```

- `error` ثابت (snake_case إنجليزي) — التطبيق بيقرّر سلوكه منه **بس**.
- `message_ar` (لو موجود) نص للعرض كما هو؛ ممكن يتغيّر من غير إشعار.
- الحقول الإضافية مذكورة تحت كل كود.
- **أكواد قديمة (قبل SAAS-027):** أخطاء التحقق من المدخلات في `/api/*` بترجع `{"error": "<رسالة عربية>"}`
  بحالة 400 / 404 / 403. التطبيق يعرض النص كما هو. أي قيمة `error` مش في الجدول = "كود غير معروف" ← رسالة عامة بدون تعطّل.

## الأكواد

| الكود | HTTP | الحقول الإضافية | امتى | سلوك التطبيق المطلوب |
|---|---|---|---|---|
| `unauthorized` | 401 | — | توكن ناقص / غلط / منتهي / اتلغى (kill-switch، تغيير باسورد، مدرسة تانية) | يمسح التوكن ويرجع لشاشة الدخول لنفس المدرسة |
| `subscription_blocked` | 403 | `reason`, `message_ar` | المدرسة موقوفة أو اشتراكها منتهي (`reason`: suspended / expired / not_started / no_subscription) | شاشة كاملة برسالة المدرسة وبيانات الدعم (من `school-info`) |
| `subscription_read_only` | 403 | `reason` = `grace`, `message_ar` | فترة السماح: أي كتابة مرفوضة، القراءة شغالة | بانر + تعطيل أزرار الكتابة |
| `module_disabled` | 403 | `module` | القسم مش مفعّل في باقة المدرسة | إخفاء القسم من القايمة |
| `limit_reached` | 403 | `limit` (students / users / storage), `message_ar` | وصلت لحد الباقة | رسالة `message_ar`، من غير إعادة محاولة |
| `school_moved` | 410 | `new_host` | كود المدرسة (slug) اتغيّر | تحديث الـbaseUrl المحفوظ لـ`https://<new_host>` وإعادة المحاولة **مرة واحدة** |
| `upgrade_required` | 426 | `app`, `min_version`, `message_ar` | نسخة التطبيق أقدم من الحد الأدنى | شاشة تحديث تفتح المتجر |
| `rate_limited` | 429 | `message_ar` | طلبات `school-info` كتير من نفس العنوان | انتظار دقيقة |

ملاحظات:

- `/files/<key>` لمدرسة محجوبة بيرجّع 404 (مش 403) — مش بنأكّد وجود الملف.
- host مش معروف أو مدرسة مؤرشفة ← 404 من غير JSON مخصوص (مش بنكشف وجود المدرسة).

## الواجهات العامة (من غير توكن)

### `GET /api/public/school-info`

على host المدرسة (`https://<slug>.<BASE_DOMAIN>`). بترد حتى لو المدرسة محجوبة (`state = blocked`) عشان
التطبيق يعرض رسالة واضحة. host مش معروف / مؤرشف ← 404. محدودة بـ20 طلب في الدقيقة لكل IP (`rate_limited`).

```json
{
  "name_ar": "مدرسة النور",
  "logo_url": "/files/…?exp=…&sig=…",
  "state": "ok",
  "reason": null,
  "message_ar": "",
  "api_version": "1",
  "support": {"email": "", "phone": ""}
}
```

- `state`: `ok` / `read_only` / `blocked`. `reason` و`message_ar` زي أكواد الاشتراك فوق.
- `logo_url`: رابط موقّع صالح 10 دقايق (نسبي على نفس الـhost)، أو `null` (مفيش شعار أو المدرسة محجوبة).
- مفيش أي بيانات شخصية ولا أرقام (اختبار بقايمة بيضا للحقول).

### `GET /api/public/app-config`

```json
{"api_version": "1", "min_app_version": {"student": "1.0.0", "teacher": null, "parent": null}}
```

`null` = مفيش حد أدنى. القيم بتتظبط من اللوحة: إعدادات التطبيقات (`/superadmin/settings/apps`).

## هيدرز التطبيق

كل طلب من التطبيقات المنشورة يبعت:

- `X-App-Name`: `student` / `teacher` / `parent`
- `X-App-Version`: `MAJOR.MINOR.PATCH` (أرقام بس)

لو النسخة أقدم من `min_app_version` للتطبيق ده ← `426 upgrade_required` على أي `/api/*`
(ما عدا `/api/public/*`). نسخة بصيغة غلط بتتعامل كأنها أقدم. طلب من غير `X-App-Version` ما بيتفحصش
(سلوك الـAPI الحالي من غير تغيير).
