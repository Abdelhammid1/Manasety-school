import { test, expect } from '@playwright/test';
import { loginAs } from './fixtures/auth';

test('smoke: admin can log in and reach the dashboard', async ({ page }) => {
  await loginAs(page, 'admin', 'admin12345');
  await page.goto('/');
  // Expect either a dashboard-y URL or that we're not sitting on /auth/login
  expect(page.url()).not.toContain('/auth/login');
});

test('smoke: sidebar shows main navigation items', async ({ page }) => {
  await loginAs(page, 'admin', 'admin12345');
  await page.goto('/');
  const sidebar = page.locator('aside.sidebar');
  await expect(sidebar).toContainText('الطلاب');
  await expect(sidebar).toContainText('المعلمون');
  await expect(sidebar).toContainText('الحضور');
});
