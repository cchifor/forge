import { expect, test } from '@playwright/test';

test('home page has dashboard heading', async ({ page }) => {
	await page.goto('/');
	await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
});
