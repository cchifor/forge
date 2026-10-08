import { expect, type Page } from '@playwright/test';

export async function mockHealth(page: Page) {
  await page.route(/\/api\/[^/]+\/v1\/(info|health\/ready|health\/live)(\?.*)?$/, async route => {
    const url = new URL(route.request().url());
    const json = url.pathname.endsWith('/info')
      ? { title: 'Quality service', version: '1.0.0', description: 'Browser contract fixture' }
      : { status: 'UP', details: 'Running', components: { database: { status: 'UP', latency_ms: 2, details: null } }, system_info: { runtime: 'test' } };
    await route.fulfill({ json });
  });
}

export async function expectHealthyDashboard(page: Page) {
  await expect(page.getByText('Quality service', { exact: true })).toBeVisible();
  await expect(page.getByText('database', { exact: true }).first()).toBeVisible();
}
