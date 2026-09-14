import { test, expect, Page } from '@playwright/test';
import { loginAs } from './fixtures/auth';
import * as fs from 'fs';
import * as path from 'path';

/**
 * Collects one screenshot per fix and writes an HTML report at
 * report/sprint_9_report.html — the artifact to hand to محمد.
 */

const REPORT_DIR = path.join(process.cwd(), 'report');
const SHOTS_DIR = path.join(REPORT_DIR, 'screenshots');

if (!fs.existsSync(SHOTS_DIR)) fs.mkdirSync(SHOTS_DIR, { recursive: true });

type Shot = { tc: string; title: string; file: string; note: string };
const shots: Shot[] = [];

async function shoot(page: Page, tc: string, title: string, note: string) {
  const file = `${tc.replace(/\./g, '_')}.png`;
  await page.screenshot({ path: path.join(SHOTS_DIR, file), fullPage: true });
  shots.push({ tc, title, file, note });
}

// One long serial test so the same session/context is reused.
test('collect screenshots for the client report', async ({ page, request }) => {
  test.setTimeout(180_000);

  // -------- ADMIN JOURNEY --------
  await loginAs(page, 'admin', 'admin12345');

  // TC-1.2.1 — role permissions column
  await page.goto('/admin/roles');
  await shoot(page, 'TC-1.2.1', 'الصلاحيات ظاهرة مباشرة في قائمة الأدوار',
    'عمود "الصلاحيات" الجديد يعرض كل وحدة كـ badge مع عدد الأفعال، بدون الحاجة لفتح شاشة التعديل.');

  // TC-2.4.2 — grades list section count scoped to year
  await page.goto('/academic/grades');
  await shoot(page, 'TC-2.4.2', 'عدد الفصول لكل صف مربوط بالسنة النشطة',
    'رأس العمود يعرض اسم السنة النشطة، والعدد صفر عندما لا توجد فصول للسنة الجديدة.');

  // TC-2.2.5/6 — try to add a bad term (overlap) and screenshot the error
  await page.goto('/academic/years');
  const termsBtn = page.locator('a:has-text("الفترات الدراسية")').first();
  if (await termsBtn.count()) {
    await termsBtn.click();
    // TC-2.2.4 first (edit button visible)
    await shoot(page, 'TC-2.2.4', 'زر تعديل الفترة الدراسية موجود',
      'كل صف في قائمة الفترات الدراسية عليه زر "تعديل" واضح.');

    const addTerm = page.locator('a:has-text("فترة دراسية")').first();
    if (await addTerm.count()) {
      await addTerm.click();
      await page.fill('input[name="name"]', 'demo-overlap');
      await page.fill('input[name="order_index"]', '99');
      await page.fill('input[name="start_date"]', '2025-10-01');
      await page.fill('input[name="end_date"]', '2025-11-01');
      await page.fill('input[name="weight"]', '5');
      await page.click('button[type="submit"]');
      await page.waitForLoadState('networkidle');
      await shoot(page, 'TC-2.2.5', 'رفض التواريخ المتداخلة برسالة واضحة',
        'النظام يمنع الحفظ ويوضح أي فترة تتعارض مع التواريخ المُدخلة.');

      // TC-2.2.6 — huge weight
      await page.fill('input[name="weight"]', '60');
      await page.fill('input[name="start_date"]', '2099-01-01');
      await page.fill('input[name="end_date"]', '2099-06-30');
      await page.click('button[type="submit"]');
      await page.waitForLoadState('networkidle');
      await shoot(page, 'TC-2.2.6', 'رفض مجموع الأوزان أكثر من 100%',
        'النظام لا يكتفي بالتحذير، بل يمنع الحفظ فعليًا عندما يتجاوز الإجمالي 100%.');
    }
  }

  // TC-5.2.2 — schedule cell visible edit buttons
  await page.goto('/schedule');
  const secLink = page.locator('main a[href*="/schedule/section/"], .card a[href*="/schedule/section/"]').first();
  if (await secLink.count()) {
    await secLink.click();
    await shoot(page, 'TC-5.2.2', 'أزرار تعديل/إضافة ظاهرة في كل خانة جدول',
      'الأزرار "✏️ تعديل" و"➕ إضافة" واضحة بدلًا من نص صغير مخفي داخل details.');
  }

  // TC-4.2.2 — subject toggle button
  await page.goto('/teachers/subjects');
  await shoot(page, 'TC-4.2.2', 'زر تعطيل/تفعيل المادة الدراسية',
    'المواد الآن لها زر تعطيل (soft-disable) بدلًا من الحذف الذي كان سيكسر الدرجات المرصودة.');

  // TC-4.1.2 — teacher toggle clarity
  await page.goto('/teachers');
  await shoot(page, 'TC-4.1.2', 'زر تعطيل المعلم أوضح مع تأكيد',
    'الزر يحمل رمز 🚫/✓ + tooltip + دايالوج تأكيد يوضح أن التعطيل لا يحذف السجل.');

  // TC-7.5.1 — term results page
  await page.goto('/results/grades');
  const termLink = page.locator('a[href*="/term/"]').first();
  if (await termLink.count()) {
    await termLink.click();
    await shoot(page, 'TC-7.5.1', 'صفحة نتيجة الفترة الدراسية',
      'مصفوفة كاملة: الطلاب في الصفوف، المواد في الأعمدة، مع نجاح/رسوب لكل مادة.');
  } else {
    await page.goto('/results/grades');
    await shoot(page, 'TC-7.5.1', 'الوصول لنتائج الفترة الدراسية من شاشة الرصد',
      'شاشة الرصد تعرض روابط "نتيجة الفترة" لكل فترة دراسية.');
  }

  // TC-9.2.2 — export buttons
  await page.goto('/finance/reports');
  await shoot(page, 'TC-9.2.2', 'أزرار تصدير التقرير المالي (PDF + Excel)',
    'زران في أعلى الصفحة: تصدير PDF بالهوية البصرية، وتصدير Excel بتنسيق RTL.');

  // Actually download the PDF & Excel — save them as attachments
  const csrfHtml = await (await request.get('/auth/login')).text();
  const csrf = csrfHtml.match(/name="csrf_token"\s+value="([^"]+)"/)?.[1] || '';
  await request.post('/auth/login', { form: { csrf_token: csrf, username: 'admin', password: 'admin12345' } });
  const pdfResp = await request.get('/finance/reports/export?format=pdf');
  if (pdfResp.ok()) fs.writeFileSync(path.join(SHOTS_DIR, 'financial_report.pdf'), await pdfResp.body());
  const xlsxResp = await request.get('/finance/reports/export?format=excel');
  if (xlsxResp.ok()) fs.writeFileSync(path.join(SHOTS_DIR, 'financial_report.xlsx'), await xlsxResp.body());

  // TC-8.3.1 — invoice print
  await page.goto('/finance/invoices');
  const invLink = page.locator('table.data tbody a[href*="/invoices/"]').first();
  if (await invLink.count()) {
    await invLink.click();
    await shoot(page, 'TC-8.3.1-detail', 'زر الطباعة في صفحة الفاتورة',
      'زر "🖨️ طباعة / PDF" واضح في أعلى الصفحة.');
    // Extract invoice id and open print view directly (avoids auto-print)
    const url = page.url();
    const idMatch = url.match(/\/invoices\/(\d+)/);
    if (idMatch) {
      await page.goto(`/finance/invoices/${idMatch[1]}/print`);
      await page.waitForLoadState('networkidle');
      await shoot(page, 'TC-8.3.1-print', 'تصميم طباعة الفاتورة',
        'صفحة مخصصة بالهوية البصرية للمؤسسة، جاهزة للطباعة أو التنزيل PDF.');
    }
  }

  // F.1 — sections list with student links
  await page.goto('/academic/sections');
  await shoot(page, 'F.1', 'قائمة الفصول مع رابط لطلاب كل فصل',
    'زر "📋 قائمة الطلاب" لكل فصل ينقل مباشرةً لقائمة طلابه المفلترة.');

  // F.2 — student profile fees card (only if any invoice exists)
  await page.goto('/students');
  const stLink = page.locator('table.data tbody a[href*="/students/"]').first();
  if (await stLink.count()) {
    await stLink.click();
    await shoot(page, 'F.2', 'الوضع المالي للطالب في ملفه الشخصي',
      'قسم جديد يجمع كل الفواتير والدفعات والمتبقّي للطالب.');
  }

  // F.3 — year form status hint
  await page.goto('/academic/years/new');
  await shoot(page, 'F.3', 'شرح خانة "الحالة" عند إنشاء سنة',
    'شرح مفصل لمعنى "نشطة" و"مغلقة" مع تنبيه بعدم تفعيل سنتين معًا.');

  // -------- TEACHER JOURNEY (TC-6.1.3, TC-7.3.3) --------
  await page.context().clearCookies();
  await loginAs(page, 'ehab', 'admin12345');

  await page.goto('/attendance');
  await shoot(page, 'TC-6.1.3-list', 'قائمة الحضور للمعلم مفلترة',
    'المعلم إيهاب يرى فقط الفصل المسند إليه (أ-fx)، لا كل الفصول.');

  await page.goto('/attendance/section/1/mark');
  await page.waitForLoadState('networkidle');
  await shoot(page, 'TC-6.1.3-block', 'محاولة دخول رابط فصل غير مسند',
    'الدخول المباشر لرابط فصل غير مسند يُرفض مع رسالة عربية واضحة.');

  await page.goto('/results/grades');
  await shoot(page, 'TC-7.3.3', 'شاشة رصد الدرجات للمعلم مفلترة',
    'الـ pickers تعرض فقط المواد والفصول المسندة للمعلم إيهاب.');

  // Finally, save the shots manifest
  fs.writeFileSync(
    path.join(REPORT_DIR, 'shots.json'),
    JSON.stringify(shots, null, 2),
  );
});
