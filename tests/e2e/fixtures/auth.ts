import { Page, expect } from '@playwright/test';

export async function loginAs(page: Page, username: string, password: string) {
  await page.goto('/auth/login');
  await page.fill('input[name="username"]', username);
  await page.fill('input[name="password"]', password);
  await page.click('button[type="submit"]');
  // On success we get redirected off the login page.
  await expect(page).not.toHaveURL(/auth\/login/, { timeout: 5000 });
}

export async function logout(page: Page) {
  // If a logout link exists, use it. Otherwise clear cookies.
  await page.context().clearCookies();
}
