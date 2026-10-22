# دليل الطوارئ — استرجاع منصتي (SAAS-050)

الدليل ده لوقت الأزمة: خطوات مرقّمة، كل خطوة بأمرها الكامل والوقت المتوقع. اقرأه كله مرة قبل ما تبدأ.

> **الملفات والمفاتيح:** ملفات النسخ محفوظة مشفّرة في تخزين خارجي، ومفاتيح فكّها عند الإدارة. الدليل ده بيشرح
> شكل الملفات **بعد** فكّها بس — مفيش هنا أي مفتاح أو كلمة مرور أو بيانات اعتماد، وما ينفعش يتضاف.

## الملفات اللي محتاجها (بعد فك التشفير)

| الملف | المحتوى |
|---|---|
| `manasety-YYYYMMDD.sql.gz` | `pg_dump` بصيغة plain text، مضغوط gzip، لقاعدة البيانات كلها |
| `uploads-YYYYMMDD.tar.gz` | محتوى `UPLOAD_ROOT` (ملفات المدارس المرفوعة) |
| `config-YYYYMMDD.tar.gz` | `.env` + ملفات nginx + ملف الـ cron (`/etc/cron.d/manasety-school`) |

الأمر الرئيسي:

```bash
flask system-restore --db-dump <file.sql.gz> --target-db <قاعدة جديدة> \
    [--files <uploads.tar.gz>] [--config <config.tar.gz>] [--apply] [--apply-config]
```

- من غير `--apply`: بيتحقق من الملفات ويطبع الخطة بس — ما بيكتبش أي حاجة.
- الاسترجاع دايمًا في **قاعدة جديدة** (`--target-db`)، عمره ما بيكتب فوق القاعدة الشغالة (بيرفض لو الاسم = الشغالة أو موجودة).
- بيرفض قبل أي تعديل لو: الـ gzip تالف، علامة نهاية `pg_dump` مش موجودة (الملف مقطوع)، أو أي جدول من جداول التطبيق ناقص.
- بعد التحميل: عدد الصفوف في كل جدول = اللي في الملف بالظبط، مراجعة الـ migration، و`tenant-integrity-check` نظيف.
- الملفات المرفوعة بتتفك في فولدر **جديد** جنب الشغال. الإعدادات: بيعرض الفرق (من `.env` أسماء المفاتيح بس، أبدًا القيم)،
  و`--apply-config` بيكتب `.env` المسترجع بعد ما يحفظ الحالي باسم `.env.before-restore-<وقت>`.

---

## السيناريو 1 — قاعدة البيانات تالفة (السيرفر سليم)

الوقت الكلي المتوقع: **15–30 دقيقة** (أغلبه تنزيل الملف وفك تشفيره).

1. **(2 د)** ادخل السيرفر وفعّل البيئة:
   ```bash
   ssh manasety@SERVER_IP
   cd ~/manasety && source .venv/bin/activate
   ```
2. **(5–15 د)** نزّل آخر نسخة من التخزين الخارجي وفكّ تشفيرها (بمفتاح الإدارة) في `~/restore/`.
3. **(1 د)** تحقّق من غير ما تغيّر حاجة:
   ```bash
   flask system-restore --db-dump ~/restore/manasety-YYYYMMDD.sql.gz --target-db manasety_restored
   ```
   لازم كل السطور `OK`. أي `FAIL` = الملف مش صالح: جرّب النسخة اللي قبلها.
4. **(1–5 د)** استرجع في القاعدة الجديدة:
   ```bash
   flask system-restore --db-dump ~/restore/manasety-YYYYMMDD.sql.gz --target-db manasety_restored --apply
   ```
   لو سطر `one migration head` قال إن المراجعة أقدم من الكود: `DATABASE_URL=<رابط manasety_restored> flask db upgrade`.
5. **(2 د)** حوّل التطبيق للقاعدة الجديدة: عدّل `DATABASE_URL` في `.env` لاسم `manasety_restored`، وبعدين:
   ```bash
   sudo systemctl restart manasety
   flask smoke-check
   ```
6. **(دقيقة)** لو `smoke-check` مش أخضر: رجّع `DATABASE_URL` القديم و`sudo systemctl restart manasety` (القاعدة القديمة ما اتلمستش).
7. سيب القاعدة القديمة كما هي لحد ما الإدارة توافق على حذفها (مفيش حذف تلقائي).

## السيناريو 2 — السيرفر ضاع بالكامل (سيرفر جديد من الصفر)

الوقت الكلي المتوقع: **1.5–3 ساعات**.

1. **(30–60 د)** جهّز السيرفر الجديد بخطوات «الجزء الأول» في `DEPLOYMENT.md` (Python، PostgreSQL، nginx، المستخدم `manasety`، الكود).
   أنشئ قاعدة فاضية مؤقتة للتطبيق (`manasety_bootstrap`) واعمل `.env` مؤقت يشاور عليها عشان أوامر `flask` تشتغل.
2. **(5–15 د)** نزّل وفكّ تشفير الملفات التلاتة في `~/restore/`.
3. **(1 د)** تحقّق (dry run) بالملفات التلاتة:
   ```bash
   flask system-restore --db-dump ~/restore/manasety-YYYYMMDD.sql.gz --target-db manasety \
       --files ~/restore/uploads-YYYYMMDD.tar.gz --config ~/restore/config-YYYYMMDD.tar.gz
   ```
   راجع فرق الإعدادات المطبوع (أسماء المفاتيح بس).
4. **(5–15 د)** نفّذ:
   ```bash
   flask system-restore --db-dump ~/restore/manasety-YYYYMMDD.sql.gz --target-db manasety \
       --files ~/restore/uploads-YYYYMMDD.tar.gz --config ~/restore/config-YYYYMMDD.tar.gz \
       --apply --apply-config
   ```
   `.env` المسترجع بقى مكان المؤقت (والمؤقت محفوظ باسم `.env.before-restore-…`). تأكد إن `DATABASE_URL` فيه بيشاور على `manasety`.
5. **(2 د)** حط الملفات المرفوعة مكانها (الأمر بيطبع السطر بالظبط):
   ```bash
   mv <UPLOAD_ROOT> <UPLOAD_ROOT>.before-<وقت> && mv <UPLOAD_ROOT>.restored-<وقت> <UPLOAD_ROOT>
   ```
6. **(15–30 د)** nginx والشهادات (شغل DevOps — السوبر أدمن ما بيكتبش في nginx): رجّع ملفات nginx والـ certbot من أرشيف
   الإعدادات لأماكنها على السيرفر الجديد (الـ wildcard `wildcard-manasety` تحت `/opt/manasety/certbot/conf/live/` — تفاصيل
   `NGINX_*` في `DEPLOYMENT.md`)، وبعدين:
   ```bash
   flask nginx-sync-units --write /etc/systemd/system   # وحدات المزامنة بمسارات السيرفر الجديد
   sudo systemctl daemon-reload && sudo systemctl enable --now manasety-nginx-sync.timer
   flask nginx-sync --dry-run                           # راجع الفرق قبل أي تطبيق
   flask nginx-sync
   ```
7. **(5 د)** الـ cron: `flask cron-tick-cronfile --at 05:00 | sudo tee /etc/cron.d/manasety-school`
   (بعد `flask cron-tick --dry-run` ومراجعته — زي `DEPLOYMENT.md`).
8. **(5 د)** وجّه الـ DNS للسيرفر الجديد، وبعدين `sudo systemctl restart manasety && flask smoke-check`.

## السيناريو 3 — مدرسة واحدة بوظت (الباقي سليم)

ما تستخدمش `system-restore`. استرجاع المدرسة لوحدها (SAAS-048):

- من جوه المدرسة: أدمن المدرسة ← «النسخ الاحتياطي» ← «استرجاع» (معاينة ← اختيار الوحدات ← تأكيد). نقطة أمان تلقائية قبلها، وزر «تراجع».
- من الكونسول: صفحة المدرسة ← «الاسترجاع بالنيابة عن المدرسة» (سبب إلزامي).
- من السيرفر: `flask school-restore --school <slug> --package <file>` (معاينة) ثم `--apply --reason "…"`.
- لو مفيش نسخة للمدرسة دي لوحدها: استرجع آخر dump في قاعدة جديدة (السيناريو 1 خطوة 4 من غير خطوة 5)، وبعدين
  من القاعدة الجديدة اعمل `flask school-backup --school <slug>` وارفع الحزمة في استرجاع المدرسة.

---

## تجارب الطوارئ (DR drills)

| التاريخ | المكان | البيانات | النتيجة | الزمن |
|---|---|---|---|---|
| 2026-10-22 | جهاز التطوير (PostgreSQL 18، Windows)، قاعدة مهاجرة من الصفر + `flask seed-test-schools` (حجم كامل) | 163 جدول، 8748 صف، dump مضغوط 180 KB | كل الخطوات OK: عدد الصفوف = الملف، المراجعة = آخر head، `tenant-integrity-check` = 0، عدد الطلاب 80 = 80 | dry run ثانية واحدة؛ `--apply` حوالي 4 ث (إنشاء القاعدة 0.25، التحميل 1.74، الفحوص 0.4) |
| — | سيرفر staging (مطلوب قبل الإغلاق) | نسخة الإنتاج الليلية | | |

**مطلوب لإغلاق التذكرة:** تجربة على سيرفر/قاعدة تجريبية بنسخة الإنتاج الحقيقية، بقياس الزمن الكلي (من تنزيل الملف لحد `smoke-check` أخضر)،
وتسجيلها في الجدول ده، وواحد من الفريق ينفّذ الدليل من غير مساعدة.
