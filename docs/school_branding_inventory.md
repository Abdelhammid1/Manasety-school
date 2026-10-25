# School Branding — الجرد (البند 1)

تاريخ: 2026-10-25

## اللوجو والاسم والـ meta

| النقطة | الأماكن | التعامل |
|---|---|---|
| `img/logo.svg` | `partials/stitch_sidebar`، `auth/{login,forgot,otp,reset,set_password,app_landing}`، `errors/{error,subscription_blocked}`، `lms/quiz_take`، `finance/invoice_detail`، `landing`، `partials/stitch_base` (favicon) | كلها بقت `brand.logo_src` (لوجو المدرسة من `/branding/logo?v=…` أو `logo.svg`). الـ favicon: لوجو المدرسة لو موجود، والـ SVG بيتشال من الـ head وقتها |
| مستبعد | `superadmin/*` (base، app_card، error) | الـ console بهوية منصتي — خارج النطاق |
| `app_name` / `school_name` | الـ sidebar، login، invoice_detail، error، dashboards | اسم المدرسة جنب لوجوها (`brand.name` لو `own_logo`)؛ `school_name` في `inject_globals` بقى اسم المدرسة الحالية (من الـ tenant أو المستخدم) بدل `DEFAULT_SCHOOL_NAME` |
| `<title>` / `og:*` / `application-name` / `theme-color` | `partials/stitch_base.html` بس | باسم المدرسة ولونها ولوجوها لما يكون ليها هوية (لوجو أو لون)، وإلا زي ما هي |
| «© منصتي»، «تطبيق منصتي»، «تواصل مع إدارة منصتي» | login footer، app_landing، tenant_suspended، error footer | اسم المنتج — فضل زي ما هو |

## الألوان

- Tailwind tokens في `stitch_base.html`: عيلة primary / secondary / navy / surface-tint / inverse-primary / sidebar-icon (18 token) بقت `rgb(var(--c-x, <القيمة الحالية بالظبط>) / <alpha-value>)` — `/10` و`/20` شغالين، والمدرسة من غير لون مطابقة بكسل بكسل. tertiary والأسطح والألوان الدلالية (success / warning / error / danger) ما اتغيرتش. اتضاف `brand-mid` و`brand-end` (منتصف ونهاية الـ gradient).
- الـ hex في الـ templates (مصنّفة):
  - **brand**: الـ gradient `#1E3A8A → #2563EB → #0099CC` (175 مرة في 123 ملف) + الـ gradient الغامق `#0C2461 → …` (17) + 3 حالات فردية → `var(--brand-gradient[-deep], <الأصلي>)` (195 في 132 ملف). ألوان نص/أيقونات: `#1E3A8A` / `#00236F` / `#001556` / `#0C2461` في المطبوعات والصفحة المحجوبة والـ id card، و`[#0099CC]` / `[#2563EB]` في 5 classes → متغيرات بنفس القيمة كـ fallback.
  - **semantic** (فضلت): `#10B981` `#065F46` `#ECFDF5` `#EF4444` `#F59E0B` `#B91C1C` `#DC2626` …، وحالات نافس (`'active': '#2563EB'`).
  - **data / chart** (فضلت): ألوان الكروت في قوائم Jinja (`('…', icon, '#0099CC')`) وألوان الرسوم البيانية — ألوان فئات مش هوية.
- `partials/base.html` (النظام القديم `app.css` / `--c-orange`): **مفيش صفحة بتستخدمه** — اتساب.
- الصفحات المستقلة (مش بتورث stitch_base): `finance/invoice_print`، `finance/reports_pdf`، `lms/template_print`، `attendance/periodic_report`، `errors/subscription_blocked`، `students/id_card` → `partials/brand_theme.html`.

## الصفحات العامة

- `landing.html` بيظهر على `/` لكل host (من ضمنها hosts المدارس) → اللوجو بقى لوجو المدرسة لو موجود.
- `auth/app_landing.html` على host المدرسة بس (`/app`).

## الـ PDF والملفات

- WeasyPrint: `file_storage.pdf_url_fetcher(school_id)` بيقرأ مفاتيح `/files/` من الديسك (من غير session)، فـ`school.logo_url` بيظهر في الـ PDF فعلًا. اللوجو في المطبوعات من `partials/print_logo.html` بنفس قاعدة `show_logo_on_prints` (ولوجو خارجي قديم = بدون لوجو).
- `fs.save` بيولّد اسم ملف جديد (`uuid`) مع كل رفع → **مفيش داعي لـ `branding_version`**: النسخة = hash للـ `logo_url`.
- Pillow كانت موجودة (dependency لـ WeasyPrint) واتثبّتت صراحة: `Pillow==10.4.0`.

## قاعدة البيانات

- `schools.primary_color` (String(7)، nullable، بدون default) — migration `e6f8a0b2c4d6`. اتضاف لـ backup (`SCHOOL_ROW_RESTORABLE`)، والـ restore بيعمل validation للـ hex، والـ purge (`WIPE_FIELDS`).
- **لازم يتنفذ على السيرفر قبل الـ deploy** (معرفة اللوجوهات الخارجية / SVG القديمة):
  `SELECT id, slug, logo_url FROM schools;`
  اللوجو الخارجي (http…) بيتعامل كـ «بدون لوجو» في كل الأماكن الجديدة. الـ SVG القديمة بتتخدم زي ما هي.

## ما اتعملش بعد

- screenshots بالثلاث ألوان (غامق / متوسط / فاتح جدًا) والـ default: سيرفر التطوير المحلي اتوقف بسبب الذاكرة — محتاجة تتعمل على test-a / test-b قبل الـ merge.
