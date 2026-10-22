# صيغة نسخة المدرسة الاحتياطية (SAAS-046)

الكود: `app/services/school_backup.py`. أي ميزة نسخ أو استرجاع أو استخراج بتستخدم الصيغة والمحرك ده بس.

## الملف

```
<slug>-<school_id>-<UTC stamp>.tar.gz
  manifest.json
  school.json
  data/<table>.copy
  files/<key>
  checksums.sha256
```

| العضو | المحتوى |
|---|---|
| `manifest.json` | `format` = `manasety-school-backup`، `schema_version` (رقم الصيغة، حاليًا 1)، `alembic_version` (مراجعة قاعدة البيانات وقت التصدير)، `school_id`، `slug`، `name`، `created_at`، ولكل جدول `{rows, columns, sha256}`، ولكل ملف `{path, bytes, sha256}` |
| `school.json` | إعدادات المدرسة نفسها — **قائمة مسموحة** بس (`SCHOOL_ROW_RESTORABLE`): الحقول اللي الأدمن بيعدّلها من صفحة الإعدادات أصلًا، من غير SMTP. أي حقل تاني = الحزمة مرفوضة |
| `data/<table>.copy` | صفوف المدرسة دي بس، بصيغة PostgreSQL `COPY ... TO` النصية: الأعمدة بترتيب `columns` في الـ manifest، مفصولة بـ tab، `\N` = NULL، `t`/`f` للـ boolean، التواريخ ISO، الـ JSON نص، الـ bytes `\\x<hex>`، والـ `\` و tab و newline و CR متهرّبين. الصفوف مرتبة بالـ primary key |
| `files/<key>` | الملفات المرفوعة من التخزين المحمي (`UPLOAD_ROOT/<school_id>/…`) بنفس مفاتيحها |
| `checksums.sha256` | `sha256  <member>` لكل عضو تاني في الحزمة (نفس صيغة `sha256sum`) |

## الجداول

- بتتحدد تلقائيًا: كل جدول فيه عمود `school_id` (`backup_tables()`) — مفيش قائمة يدوية، وأي جدول جديد بيدخل النسخة الجاية لوحده.
- المستثنى، بسبب مكتوب:
  - جداول المنصة (`tenant_guard.PLATFORM_TABLES`): الخطط، الاشتراكات، فواتير المنصة، جلسات الدعم، الـ jobs، ملاحظات وجهات اتصال المنصة، …
  - `BACKUP_EXCLUDED`: `account_setup_tokens` (روابط مؤقتة)، `device_tokens` (أجهزة مسجّلة = جلسات).
  - صف `schools` بيتحفظ في `school.json` من غير الحقول اللي فوق.
- حسابات الدعم (`users.is_platform_support`) ما بتدخلش النسخة أبدًا.
- `users` بتتحفظ (منها `password_hash`) عشان الحزمة ممكن ترجّع الحسابات — الاسترجاع (SAAS-048) ما بيرجّعهاش إلا باختيار صريح.

## لقطة متسقة

التصدير كله من connection واحدة جوه transaction واحدة: `REPEATABLE READ` + `SET TRANSACTION READ ONLY` على PostgreSQL. كل الجداول بتتقري من نفس اللحظة.

## التشفير (الحزمة اللي بتخرج من السيرفر)

كلمة مرور يحددها الأدمن، 12 حرف على الأقل، وما بتتخزنش في أي مكان.

```
MAGIC "MNSTBK1\0" (8) | scrypt log2(n) (1) | r (1) | p (1) | salt (16) | nonce prefix (8)
chunk*: length (4, big endian) | AES-256-GCM ciphertext + tag
```

- المفتاح: scrypt (n = 2^15, r = 8, p = 1) على كلمة المرور مع salt عشوائي.
- الـ chunk رقم i (حتى 1 MiB): nonce = prefix + i، والـ AAD = الـ header + i + علامة "آخر chunk". أي chunk اتشال أو اتبدّل أو الملف اتقصّ = فشل.
- كلمة مرور غلط وملف تالف بيدّوا نفس الرسالة العامة (من غير ما نقول أنهي فيهم).

## التحقق — `verify_package(path, passphrase=None, expect_school_id=None)`

ما بيكتبش أي حاجة في قاعدة البيانات. بيرفض الحزمة لو:

1. أي عضو مساره مش آمن (`..`، مسار مطلق، `\`، `:`، link، مكرر).
2. `checksums.sha256` ما بيغطيش كل الأعضاء بالظبط، أو أي checksum مختلف.
3. `format` مش `manasety-school-backup` أو `schema_version` غير مدعوم.
4. `alembic_version` مش معروفة للكود الشغال (حزمة من إصدار أحدث).
5. `school_id` مختلف عن المتوقع (`expect_school_id`).
6. جدول مش في `backup_tables()`، أو عمود مش موجود في الـ schema.
7. **أي صف** `school_id` بتاعه ≠ `manifest.school_id` — الحزمة كلها بتترفض، الصف ما بيتجاهلش.
8. عدد الصفوف أو قائمة الملفات مختلفة عن الـ manifest.

بيرجّع تقرير: `ok`, `problems`, `school_id`, `slug`, `name`, `created_at`, `alembic_version`, `tables` (عدد الصفوف لكل جدول), `files`.

## الأوامر

```bash
flask school-backup --school <slug> [--out <file>] [--encrypt [--passphrase-env VAR]]
flask school-backup --from-queue                       # jobs من نوع school_backup
flask school-backup-verify <file> [--school <slug>] [--passphrase-env VAR]   # exit 1 لو مرفوضة
```

كلمة المرور بتتقري من prompt مخفي أو من متغير بيئة (مش قيمة في سطر الأوامر). الحزم الداخلية في `instance/school_backups/<school_id>/` (صلاحيات 700 للمجلد و600 للملف)، والحد الأقصى للحجم `SCHOOL_BACKUP_MAX_MB` (الافتراضي 2048).
