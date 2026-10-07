import { expect, test } from '@playwright/test';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

test.afterEach(async ({ page }, testInfo) => {
  const coverage = await page.evaluate(() => (window as any).__coverage__);
  expect(coverage, 'Browser instrumentation must produce real coverage').toBeTruthy();
  const directory = process.env.FORGE_BROWSER_COVERAGE!;
  await mkdir(directory, { recursive: true });
  await writeFile(path.join(directory, String(testInfo.parallelIndex) + '-' + Date.now() + '.json'), JSON.stringify(coverage));
});

test('application boots and navigates preferences in a real browser', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
    await page.goto('/');
    await expect(page.locator('body')).not.toBeEmpty();
    await expect(page.locator('body')).not.toHaveText(/Internal Error|500 Internal/);
    await page.locator('a[href="/settings"]').first().click();
    await expect(page.getByRole('heading', { name: 'Settings', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Dark', exact: true }).click();
    await expect(page.locator('html')).toHaveClass(/dark/);
    await page.getByRole('button', { name: 'OLED', exact: true }).click();
    await page.getByRole('button', { name: 'Large', exact: true }).click();
    await page.getByTitle('Green', { exact: true }).click();
    await page.getByRole('button', { name: 'Light', exact: true }).click();
    await expect(page.locator('html')).not.toHaveClass(/dark/);
    await page.locator('a[href="/profile"]').first().click();
    await expect(page.getByRole('button', { name: 'Sign Out' })).toBeVisible();
    expect(errors).toEqual([]);
});
