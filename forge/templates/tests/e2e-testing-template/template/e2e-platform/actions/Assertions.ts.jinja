import type { Page } from '@playwright/test';
import { expect } from '@playwright/test';

export class Assertions {
  constructor(private readonly page: Page) {}

  async expectVisible(testId: string): Promise<void> {
    try {
      await expect(this.page.getByTestId(testId)).toBeVisible();
    } catch (e) {
      console.log(`[assert] FAIL expectVisible('${testId}') at ${this.page.url()}`);
      throw e;
    }
  }

  async expectHidden(testId: string): Promise<void> {
    try {
      await expect(this.page.getByTestId(testId)).toBeHidden();
    } catch (e) {
      console.log(`[assert] FAIL expectHidden('${testId}') at ${this.page.url()}`);
      throw e;
    }
  }

  async expectToast(message: string): Promise<void> {
    await expect(
      this.page.getByRole('status').filter({ hasText: message }),
    ).toBeVisible({ timeout: 5000 });
  }

  async expectUrl(pattern: RegExp): Promise<void> {
    await expect(this.page).toHaveURL(pattern);
  }

  async expectCount(testId: string, count: number): Promise<void> {
    await expect(this.page.getByTestId(testId)).toHaveCount(count);
  }

  async expectText(testId: string, text: string): Promise<void> {
    await expect(this.page.getByTestId(testId)).toContainText(text);
  }
}
