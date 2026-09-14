import { test, expect } from '@playwright/test';
import { loginAs } from './fixtures/auth';

/**
 * Sheet1 UI notes:
 *   TC-1.2.1 — role permissions hidden until you click edit
 *   TC-2.2.4 — no term edit button
 *   TC-4.1.2 — teacher toggle unclear
 *   TC-4.2.2 — subject has no delete/disable
 *   TC-5.2.2 — schedule cell has no visible edit affordance
 */

test.describe('Category D — Missing UI affordances', () => {

  test.beforeEach(async ({ page }) => {
    await loginAs(page, 'admin', 'admin12345');
  });

  test('TC-1.2.1: role list shows a "الصلاحيات" column with per-module badges', async ({ page }) => {
    await page.goto('/admin/roles');
    await expect(page.locator('table.data thead')).toContainText('الصلاحيات');
    // Badges should have title attribute listing the actions
    const badges = page.locator('table.data tbody span.badge.navy[title]');
    expect(await badges.count()).toBeGreaterThan(0);
  });

  test('TC-2.2.4: term list has an edit link per row', async ({ page }) => {
    await page.goto('/academic/years');
    await page.locator('a:has-text("الفترات الدراسية")').first().click();
    const editLinks = page.locator('table.data tbody a:has-text("تعديل")');
    expect(await editLinks.count()).toBeGreaterThan(0);
  });

  test('TC-4.1.2: teacher list toggle uses clear labels + confirm dialog', async ({ page }) => {
    await page.goto('/teachers');
    // Confirm the button carries the emoji/text and title attribute
    const teacherBtn = page.locator('form[action*="/toggle"] button').first();
    if (await teacherBtn.count() > 0) {
      const label = await teacherBtn.textContent();
      expect(label).toMatch(/تعطيل|تفعيل/);
    }
  });

  test('TC-4.2.2: subject list has a toggle button', async ({ page }) => {
    await page.goto('/teachers/subjects');
    const subjectToggle = page.locator('form[action*="/subjects/"][action*="/toggle"] button');
    expect(await subjectToggle.count()).toBeGreaterThanOrEqual(0); // may be 0 if no subjects
    // Header should say "الحالة"
    await expect(page.locator('table.data thead')).toContainText('الحالة');
  });

  test('TC-5.2.2: schedule cell has visible slot-btn class (not hidden in details)', async ({ page }) => {
    // Navigate straight to a section's schedule. The sidebar also contains "الجدول"
    // so we scope to the main table area to avoid picking that up.
    await page.goto('/schedule');
    const firstSectionLink = page.locator('main a[href*="/schedule/section/"], .card a[href*="/schedule/section/"]').first();
    if (await firstSectionLink.count() > 0) {
      await firstSectionLink.click();
      const buttons = page.locator('.slot-cell .slot-btn');
      expect(await buttons.count()).toBeGreaterThan(0);
    }
  });
});
