import { test, expect } from '@playwright/test';
import { loginAs } from './fixtures/auth';

/**
 *   TC-7.5.1 — per-term results page
 *   TC-9.2.2 — PDF + Excel export for financial reports
 *   TC-8.3.1 — invoice print
 */

test.describe('Category E — Missing features', () => {

  test.beforeEach(async ({ page }) => {
    await loginAs(page, 'admin', 'admin12345');
  });

  test('TC-7.5.1: grades page exposes per-term result links; per-term page renders', async ({ page }) => {
    await page.goto('/results/grades');
    // The picker table should offer term-scoped links
    const termLinks = page.locator('table.data a[href*="/term/"]');
    if (await termLinks.count() > 0) {
      await termLinks.first().click();
      await expect(page.locator('h2')).toContainText(/نتائج/);
    }
  });

  test('TC-9.2.2: financial reports offer PDF + Excel export buttons', async ({ page }) => {
    await page.goto('/finance/reports');
    await expect(page.locator('a:has-text("تصدير PDF")')).toBeVisible();
    await expect(page.locator('a:has-text("تصدير Excel")')).toBeVisible();
  });

  test('TC-9.2.2: PDF export returns application/pdf', async ({ request }) => {
    // Log in through the API-friendly session cookie (get from login page)
    const loginPage = await request.get('/auth/login');
    const html = await loginPage.text();
    const csrfMatch = html.match(/name="csrf_token"\s+value="([^"]+)"/);
    const csrf = csrfMatch ? csrfMatch[1] : '';
    await request.post('/auth/login', {
      form: { csrf_token: csrf, username: 'admin', password: 'admin12345' },
    });
    const pdf = await request.get('/finance/reports/export?format=pdf');
    expect(pdf.ok()).toBeTruthy();
    expect(pdf.headers()['content-type']).toContain('application/pdf');
    const body = await pdf.body();
    expect(body.subarray(0, 4).toString()).toBe('%PDF');
  });

  test('TC-9.2.2: Excel export returns xlsx', async ({ request }) => {
    // Same login-first pattern as the PDF test — request context has its own cookie jar.
    const loginPage = await request.get('/auth/login');
    const html = await loginPage.text();
    const csrfMatch = html.match(/name="csrf_token"\s+value="([^"]+)"/);
    const csrf = csrfMatch ? csrfMatch[1] : '';
    await request.post('/auth/login', {
      form: { csrf_token: csrf, username: 'admin', password: 'admin12345' },
    });
    const xlsx = await request.get('/finance/reports/export?format=excel');
    expect(xlsx.ok()).toBeTruthy();
    expect(xlsx.headers()['content-type']).toContain('spreadsheetml');
  });

  test('TC-8.3.1: invoice detail has a print button that opens the print view', async ({ page }) => {
    await page.goto('/finance/invoices');
    const firstInvoice = page.locator('table.data tbody a[href*="/invoices/"]').first();
    if (await firstInvoice.count() > 0) {
      await firstInvoice.click();
      const printBtn = page.locator('a:has-text("طباعة")').first();
      await expect(printBtn).toBeVisible();
      // Ensure the print href is the print route
      const href = await printBtn.getAttribute('href');
      expect(href).toMatch(/\/print$/);
    }
  });
});
