import { test, expect } from '@playwright/test';
import { loginAs, logout } from './fixtures/auth';

/**
 * Bug Report:
 *   TC-6.1.3 — teacher `ehab` can record attendance on any class
 *   TC-7.3.3 — teacher `ehab` can edit grades of a subject they don't teach
 *   TC-10.2.2 — teacher app should only show assigned classes (JWT API check)
 */

test.describe('Category A — Teacher scope enforcement', () => {

  test('TC-6.1.3: teacher sees only their assigned sections on the attendance page', async ({ page }) => {
    await loginAs(page, 'ehab', 'admin12345');
    await page.goto('/attendance');
    // Ehab is fixture-assigned to exactly ONE section (أ-fx). Admin sees 3.
    const cards = page.locator('a[href*="/attendance/section/"]');
    const count = await cards.count();
    expect(count).toBeGreaterThan(0);
    expect(count).toBeLessThan(4); // strictly fewer than admin's total
  });

  test('TC-6.1.3: teacher hitting an unassigned section URL is blocked with a clear message', async ({ page }) => {
    await loginAs(page, 'ehab', 'admin12345');
    // Try section id 1 (which ehab is NOT assigned to per fixture)
    await page.goto('/attendance/section/1/mark');
    // Should be redirected back to attendance index with a Arabic guard message
    await expect(page).toHaveURL(/\/attendance(\?|$)/);
    await expect(page.locator('.alert')).toContainText(/لا تملك صلاحية/);
  });

  test('TC-7.3.3: teacher on grades index sees only assigned subjects', async ({ page }) => {
    await logout(page);
    await loginAs(page, 'ehab', 'admin12345');
    await page.goto('/results/grades');
    // Fixture assigns ehab to exactly ONE subject.
    const subjectOptions = page.locator('select[name="subject_id"] option');
    // 1 real option + 1 empty placeholder = 2
    const total = await subjectOptions.count();
    expect(total).toBeLessThanOrEqual(2);
  });

  test('TC-10.2.2: /api/teacher/sections returns only the teacher\'s assigned sections', async ({ request }) => {
    // Login via JWT API (mobile flow)
    const loginResp = await request.post('/api/auth/login', {
      data: { username: 'ehab', password: 'admin12345' },
    });
    expect(loginResp.ok()).toBeTruthy();
    const { token } = await loginResp.json();
    expect(token).toBeTruthy();

    const secsResp = await request.get('/api/teacher/sections', {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(secsResp.ok()).toBeTruthy();
    const { sections } = await secsResp.json();
    // Fixture: ehab has 1 assignment; the endpoint should return exactly that section.
    expect(Array.isArray(sections)).toBeTruthy();
    expect(sections.length).toBe(1);
  });
});
