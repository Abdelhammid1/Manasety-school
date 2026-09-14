# دليل النشر على Hetzner Cloud + دليل المسؤول

> **منصتي (Manasety)** — نظام إدارة مدرسية متكامل
> هذا الدليل مرتّب خطوة بخطوة لشخص لم يستخدم خادم Linux من قبل.

---

## الجزء الأول: نشر التطبيق على Hetzner Cloud

### 1) إنشاء الخادم على Hetzner

1. سجّل دخولك إلى [https://console.hetzner.cloud](https://console.hetzner.cloud)
2. أنشئ مشروعًا جديدًا (مثل: `manasety-production`)
3. اضغط **Add Server** واختر:
   - **Location**: Nuremberg (أو أقرب موقع للسودان: Falkenstein)
   - **Image**: Ubuntu 24.04
   - **Type**: CX22 (2 vCPU, 4 GB RAM) — كافٍ للبداية، يمكن الترقية لاحقًا
   - **Networking**: IPv4 + IPv6
   - **SSH Key**: ارفع مفتاحك العام (إن لم يكن لديك أنشئه على جهازك بأمر `ssh-keygen`)
   - **Name**: `manasety-app`
4. اضغط **Create & Buy Now**
5. بعد دقيقة ستحصل على **عنوان IP** للخادم. احفظه (سيُشار إليه بـ `SERVER_IP`).

### 2) ربط نطاق (اختياري لكن مُوصى به)

إذا كان لديك نطاق (مثل `manasety-school.sd`):

1. ادخل لوحة DNS للنطاق
2. أضف سجل `A` يشير إلى `SERVER_IP`
3. أضف سجل `A` ثانٍ لـ `www` يشير إلى نفس الـ IP
4. انتظر 5–30 دقيقة حتى يُنتشر السجل

### 3) الدخول إلى الخادم لأول مرة

من جهازك الشخصي افتح Terminal واكتب:

```bash
ssh root@SERVER_IP
```

عند النجاح ستدخل سطر أوامر الخادم.

### 4) تحديث النظام وإنشاء مستخدم خاص

```bash
apt update && apt upgrade -y
adduser manasety           # ضع كلمة مرور قوية واحفظها
usermod -aG sudo manasety
```

من الآن سنعمل بمستخدم `manasety` بدلًا من `root`:

```bash
su - manasety
```

### 5) تثبيت المتطلبات الأساسية

```bash
sudo apt install -y python3 python3-venv python3-pip postgresql postgresql-contrib \
    nginx git curl ufw certbot python3-certbot-nginx

# مطلوبات WeasyPrint لتصدير التقارير المالية PDF + طباعة الفواتير:
sudo apt install -y libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b \
    libgdk-pixbuf2.0-0 libffi-dev libjpeg-dev libxml2 libxslt1.1
```

> ⚠️ **مهم:** إذا نسيت مكتبات WeasyPrint، سيظهر خطأ 500 عند الضغط على زرّ **تصدير PDF** في التقارير المالية أو **طباعة** الفاتورة. التطبيق ينزل لبديل HTML قابل للطباعة تلقائيًا، لكن التجربة أفضل بكثير مع WeasyPrint مثبَّت.

### 6) إعداد جدار الحماية

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable      # اضغط y عند السؤال
```

### 7) إنشاء قاعدة بيانات PostgreSQL

```bash
sudo -u postgres psql
```

داخل psql نفّذ هذه الأوامر (غيّر `YOUR_STRONG_PASSWORD` لكلمة سرّ قوية):

```sql
CREATE DATABASE manasety;
CREATE USER manasety WITH ENCRYPTED PASSWORD 'YOUR_STRONG_PASSWORD';
GRANT ALL PRIVILEGES ON DATABASE manasety TO manasety;
\c manasety
GRANT ALL ON SCHEMA public TO manasety;
\q
```

### 8) جلب الكود من GitHub

```bash
cd ~
git clone https://github.com/Abdelhammid1/EduSchool.git manasety
cd manasety
```

### 9) إنشاء بيئة Python وتثبيت الحزم

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 10) إنشاء ملف الإعدادات `.env`

```bash
nano .env
```

ضع المحتوى التالي (غيّر القيم الحسّاسة):

```
FLASK_APP=wsgi.py
FLASK_ENV=production
SECRET_KEY=ضع-هنا-سلسلة-عشوائية-طويلة-جدا-32-حرفًا-على-الأقل
DATABASE_URL=postgresql://manasety:YOUR_STRONG_PASSWORD@localhost:5432/manasety
LOCKOUT_MAX_ATTEMPTS=5
LOCKOUT_MINUTES=15
DEFAULT_SCHOOL_NAME=مدرسة صالح الشريف
DEFAULT_SCHOOL_CODE=SAS
WHATSAPP_PROVIDER=stub
```

> **توليد SECRET_KEY قوي**: نفّذ `python3 -c "import secrets; print(secrets.token_hex(32))"` وانسخ الناتج.

احفظ بـ `Ctrl+O` ثم `Enter`، واخرج بـ `Ctrl+X`.

### 11) تطبيق هجرات قاعدة البيانات وزرع البيانات الأولية

```bash
source .venv/bin/activate
export FLASK_APP=wsgi.py
flask db upgrade
python -m seeds.seed
```

بنهاية هذه الخطوة ستكون قاعدة البيانات جاهزة وأنشئ:
- المدرسة الافتراضية
- 6 أدوار افتراضية (مدير، معلم، شؤون طلاب، محاسب، أمين مخزن، ولي أمر)
- 17 حسابًا في دليل الحسابات
- **حساب المدير**: المستخدم `admin` / كلمة المرور `admin12345`

> ⚠️ **مهم**: غيّر كلمة مرور admin فور أول دخول من واجهة المستخدمين.

### 12) إعداد Gunicorn كخدمة نظام (systemd)

```bash
sudo nano /etc/systemd/system/manasety.service
```

ضع المحتوى:

```ini
[Unit]
Description=Manasety Flask App (Gunicorn)
After=network.target

[Service]
User=manasety
Group=www-data
WorkingDirectory=/home/manasety/manasety
Environment="PATH=/home/manasety/manasety/.venv/bin"
EnvironmentFile=/home/manasety/manasety/.env
ExecStart=/home/manasety/manasety/.venv/bin/gunicorn \
    --workers 3 --bind unix:/home/manasety/manasety/manasety.sock \
    --access-logfile /home/manasety/manasety/access.log \
    --error-logfile /home/manasety/manasety/error.log \
    wsgi:app

[Install]
WantedBy=multi-user.target
```

احفظ ثم:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now manasety
sudo systemctl status manasety
```

يجب أن ترى `active (running)`.

### 13) إعداد Nginx كـ Reverse Proxy

```bash
sudo nano /etc/nginx/sites-available/manasety
```

ضع المحتوى (غيّر `manasety-school.sd` لنطاقك، أو `SERVER_IP` إن لم يكن لديك نطاق):

```nginx
server {
    listen 80;
    server_name manasety-school.sd www.manasety-school.sd;
    client_max_body_size 25M;

    location /static/ {
        alias /home/manasety/manasety/app/static/;
        expires 30d;
    }

    location / {
        include proxy_params;
        proxy_pass http://unix:/home/manasety/manasety/manasety.sock;
    }
}
```

فعّل الموقع:

```bash
sudo ln -s /etc/nginx/sites-available/manasety /etc/nginx/sites-enabled/
sudo rm /etc/nginx/sites-enabled/default
sudo nginx -t       # يجب أن يُظهر OK
sudo systemctl restart nginx
```

اختبر من المتصفح: `http://manasety-school.sd` أو `http://SERVER_IP`

### 14) تفعيل HTTPS مجانًا عبر Let's Encrypt

```bash
sudo certbot --nginx -d manasety-school.sd -d www.manasety-school.sd
```

اتبع الأسئلة (اختر redirect HTTP → HTTPS). سيتجدد الشهادة تلقائيًا.

### 15) التحقق النهائي

من المتصفح:
1. افتح `https://manasety-school.sd`
2. ستظهر صفحة تسجيل الدخول بالألوان الرسمية
3. ادخل بـ `admin` / `admin12345`
4. **غيّر كلمة المرور فورًا** من شاشة المستخدمين

---

## الجزء الثاني: دليل المدير لإعداد المدرسة لأول مرة

> الترتيب مهم — كل خطوة تبني على ما قبلها.

### الخطوة 1: تغيير كلمة مرور المدير
- من القائمة الجانبية → **المستخدمون** → اضغط **تعديل** على حساب `admin`
- ضع كلمة مرور قوية (8 أحرف على الأقل)

### الخطوة 2: إنشاء السنة الدراسية (T-2.1)
- **السنوات الدراسية** → **+ سنة جديدة**
- مثال: `2025-2026` من `2025-09-01` إلى `2026-06-30` — حالة **نشطة**
- ⚠️ لا يمكن وجود سنتين نشطتين في وقت واحد

### الخطوة 3: تعريف الفترات الدراسية (T-2.2)
- اضغط **الفترات الدراسية** بجانب السنة
- أضف الفترة الأولى (وزن 50%) والثانية (وزن 50%) — أو ثلاث فترات بأوزان تجمع 100%
- ⚠️ مجموع الأوزان يجب أن يساوي **100%**

### الخطوة 4: إضافة الصفوف (T-2.3)
- **الصفوف** → أضف كل صف باسمه وترتيبه التسلسلي
- مثال: حضانة=0، أول=1، ثاني=2 … سادس=6
- الترتيب يُستخدم لاحقًا في **الترقية الرأسية**

### الخطوة 5: إضافة الفصول (T-2.4)
- **الفصول** → أضف فصلًا لكل صف (مثل: أ، ب)
- ضع **السعة القصوى** (الحد الأقصى للطلاب)

### الخطوة 6: إنشاء حسابات الموظفين (T-1.3)
- **المستخدمون** → **+ مستخدم جديد**
- لكل موظف ضع: الاسم، اسم المستخدم، الدور، كلمة مرور مبدئية
- ⚠️ لا تستخدم دور **مدير** لأكثر من شخص واحد ضروريًا

### الخطوة 7: إعداد المعلمين والمواد (Sprint 3)
1. **المعلمون** → أضف ملف لكل معلم بتخصصه
2. **المواد الدراسية** → أضف كل مادة واربطها بالصف المناسب
3. **الإسناد** → لكل فصل اختر المواد وأسند معلمًا لكل مادة

### الخطوة 8: إعداد جدول الحصص (Sprint 3)
1. **إعدادات الجدول** → أضف أيام الدراسة (مثل: الأحد–الخميس)
2. أضف الحصص (الحصة الأولى 08:00–08:45، استراحة، …)
3. **الجداول** → اختر كل فصل وضع الحصص (المادة + المعلم) في كل خلية
4. ⚠️ النظام **يمنع تعارض المعلم** تلقائيًا (لا يمكن وضعه في فصلين بنفس الوقت)

### الخطوة 9: إعداد قاعدة النجاح (T-7.1)
- **قاعدة النجاح** → اضبط:
  - حد نجاح المادة (مثل: 50%)
  - حد المعدل العام (مثل: 60%)
  - طريقة الدمج (المعدل العام / كل مادة / مختلطة)
- ⚠️ تُجمَّد القاعدة عند إغلاق السنة لحفظ السجلات تاريخيًا

### الخطوة 10: تعريف مكوّنات التقييم (T-7.2)
- **مكوّنات التقييم** → لكل (فترة دراسية × مادة) أضف المكوّنات
- مثال: أعمال سنة (30) + نهاية الفترة (70) = 100
- ⚠️ المجموع يجب أن يكون **100** لكل مادة

### الخطوة 11: إعداد الجانب المالي (Sprint 5)
1. **أنواع الرسوم** → أضف رسوم دراسية، مواصلات، أنشطة...
2. **دليل الحسابات** → موجود مسبقًا. يمكن إضافة حسابات فرعية إن لزم.

### الخطوة 12: إضافة الطلاب وقيدهم
1. **الطلاب** → **+ ملف طالب جديد**
2. عند الحفظ يُولّد كود دائم تلقائي (مثل: `SAS-00001`)
3. من ملف الطالب اضغط **قيد للسنة** واختر الفصل
4. ⚠️ النظام يمنع تجاوز السعة القصوى للفصل

### الخطوة 13: العمليات اليومية
- **الحضور** → اختر الفصل وسجّل الحضور يوميًا
  - عند تسجيل الغياب يُرسل إشعار واتساب تلقائيًا لولي الأمر
- **رصد الدرجات** → اختر الفصل + الفترة الدراسية + المادة وأدخل الدرجات
  - النظام يرفض الدرجات التي تتجاوز الحد الأقصى للمكوّن
- **الفواتير** → أصدر فواتير دورية للطلاب
  - يُولّد قيد محاسبي تلقائي عند الإصدار
  - عند الدفع: يُحدّث المتبقّي تلقائيًا ويُولّد قيد آخر
- **المصروفات** → سجّل مصاريف المدرسة (إيجار، صيانة، فواتير...)
- **الرواتب** → اصرف رواتب الموظفين شهريًا (مع البدلات والخصومات)

### الخطوة 14: نهاية السنة
1. اعتمد نتائج كل فصل من **رصد الدرجات** ← **عرض النتائج**
2. شغّل **الترقية الرأسية** لنقل الطلاب الناجحين للصف الأعلى
3. أغلق السنة من **السنوات الدراسية** → تصبح أرشيف للقراءة فقط
4. أنشئ سنة جديدة وفعّلها

---

## الجزء الثالث: مبادئ تصميم النظام (مفيدة للمدير لفهم السلوك)

### 1) الملف الدائم للطالب
بيانات الطالب الثابتة (الاسم، الميلاد، ولي الأمر) تُحفظ مرة واحدة. أما القيد السنوي (الصف، الفصل، الدرجات، الفواتير) يُربط بسنة محددة. هذا يحفظ تاريخ كل طالب كاملًا عبر السنوات.

### 2) لا حذف للسجلات الحرجة
الموظفون والطلاب والمعلمون لا يُحذفون بل **يُعطّلون**. هذا يحفظ الكشوف والتقارير القديمة سليمة.

### 3) القيود التلقائية
كل عملية مالية تُولّد قيدًا متوازنًا (مدين = دائن). يمكن مراجعة كل القيود من **دفتر اليومية**.

### 4) قابلية التوسّع
أنواع الرسوم، الأدوار، الصفوف، المراحل — كلها تُضاف من واجهة المستخدم دون الحاجة إلى المبرمج.

### 5) الإشعارات (Integration Point)
إشعارات الواتساب تمر عبر طبقة منفصلة. حاليًا تعمل بنمط **stub** (تُسجّل في السجل ولا تُرسل فعليًا). لتفعيل الإرسال الحقيقي:
- إما **Meta Cloud API** (رسمي ومجاني للحد المعقول)
- أو **Twilio WhatsApp** (أسهل ولكن مدفوع لكل رسالة)
- التكلفة على المدرسة مباشرة، والمبرمج يضيف المزوّد في `app/services/notifications.py`

### 6) جاهز لتعدّد المدارس
كل جدول يحوي `school_id` منذ البداية. لو رغبت لاحقًا في إضافة مدرسة ثانية، البنية جاهزة دون إعادة بناء.

---

## الجزء الرابع: الصيانة الدورية

### نسخ احتياطي يومي لقاعدة البيانات

```bash
sudo crontab -e
```

أضف هذا السطر (نسخ احتياطي يومي 02:00 صباحًا):

```
0 2 * * * sudo -u postgres pg_dump manasety | gzip > /home/manasety/backups/manasety-$(date +\%Y\%m\%d).sql.gz
```

أنشئ مجلد النسخ الاحتياطية:

```bash
mkdir -p /home/manasety/backups
```

### تحديث التطبيق بعد تعديل في GitHub

```bash
ssh manasety@SERVER_IP
cd ~/manasety
source .venv/bin/activate
git pull
pip install -r requirements.txt
flask db upgrade
sudo systemctl restart manasety
```

### مراقبة السجلات

```bash
sudo journalctl -u manasety -f       # سجل التطبيق
sudo tail -f /var/log/nginx/error.log  # سجل Nginx
tail -f /home/manasety/manasety/error.log  # أخطاء Gunicorn
```

### إعادة تشغيل عند مشكلة

```bash
sudo systemctl restart manasety
sudo systemctl restart nginx
```

---

## الدعم

- المستودع: https://github.com/Abdelhammid1/EduSchool
- وثيقة المتطلبات الأصلية: `خطة_العمل_مدرسة_صالح_الشريف_منصتي.pdf`
- لأي خطأ في الإنتاج: راجع `sudo journalctl -u manasety -n 100` أولًا
