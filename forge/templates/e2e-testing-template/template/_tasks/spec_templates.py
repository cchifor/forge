"""TypeScript spec string templates for per-feature E2E test generation."""

FEATURE_SPEC_TEMPLATE = """\
import {{ test, expect }} from '../e2e-platform/fixtures/app';

test.describe('{Plural} List', () => {{
  test('list page loads', async ({{ app }}) => {{
    await app.nav.goTo('{plural}');
    await app.assertions.expectVisible('{plural}-list');
  }});

  test('create button is visible', async ({{ app }}) => {{
    await app.nav.goTo('{plural}');
    await app.assertions.expectVisible('{plural}-create-btn');
  }});

  test('search input exists', async ({{ app }}) => {{
    await app.nav.goTo('{plural}');
    await app.assertions.expectVisible('{plural}-search-input');
  }});
}});

test.describe('{Singular} Create', () => {{
  test('create form loads', async ({{ app }}) => {{
    await app.nav.goToCreate('{plural}');
    await app.assertions.expectVisible('{singular}-name-input');
    await app.assertions.expectVisible('{singular}-submit-btn');
  }});

  test('create flow', async ({{ app }}) => {{
    await app.nav.goToCreate('{plural}');
    await app.page.getByTestId('{singular}-name-input').fill('Test {Singular}');
    await app.page.getByTestId('{singular}-description-input').fill('Test description');
    await app.page.getByTestId('{singular}-submit-btn').click();
    await app.assertions.expectUrl(/\\/{plural}\\/[a-f0-9-]+/);
  }});
}});

test.describe('{Singular} Detail', () => {{
  test('navigate to detail', async ({{ app }}) => {{
    await app.nav.goTo('{plural}');
    await app.page.getByTestId('{singular}-card').first().click();
    await app.assertions.expectVisible('{singular}-detail');
  }});
}});
"""

AUTH_SPEC_TEMPLATE = """\
import { test, expect } from '../e2e-platform/fixtures/app';

test.describe('Login', () => {
  test('unauthenticated redirects to Keycloak', async ({ app }) => {
    await app.nav.goToDashboard();
    await app.page.waitForSelector(
      '#username, #email, input[name="username"]',
      { timeout: 15000 },
    );
    const url = app.page.url();
    expect(
      url.includes('auth') || url.includes('realms') || url.includes('login'),
    ).toBeTruthy();
  });

  test('login with valid credentials', async ({ app }) => {
    await app.nav.goToDashboard();
    await app.page.waitForSelector('#username, input[name="username"]', {
      timeout: 15000,
    });
    await app.page.fill('#username, input[name="username"]', process.env.TEST_USER || 'dev@localhost');
    await app.page.fill('#password, input[name="password"]', process.env.TEST_PASSWORD || 'devpass');
    await app.page.click('#kc-login, input[type="submit"]');
    await app.page.waitForTimeout(3000);
    expect(app.page.url()).not.toContain('realms');
  });

  test('login with invalid credentials', async ({ app }) => {
    await app.nav.goToDashboard();
    await app.page.waitForSelector('#username, input[name="username"]', {
      timeout: 15000,
    });
    await app.page.fill('#username, input[name="username"]', 'wrong@localhost');
    await app.page.fill('#password, input[name="password"]', 'wrongpassword');
    await app.page.click('#kc-login, input[type="submit"]');
    await app.page.waitForTimeout(2000);
    const error = app.page.locator('#input-error, .kc-feedback-text, .alert-error');
    await expect(error.first()).toBeVisible({ timeout: 5000 });
  });
});

test.describe('Protected Access', () => {
  test('authenticated user sees content', async ({ app }) => {
    await app.auth.loginAs('user');
    await app.nav.goToDashboard();
    await app.page.waitForTimeout(2000);
    const content = await app.page.content();
    expect(content.length).toBeGreaterThan(500);
  });
});

test.describe('Logout', () => {
  test('logout ends session', async ({ app }) => {
    await app.auth.loginAs('user');
    await app.auth.logout();
    await app.nav.goToDashboard();
    await app.page.waitForTimeout(3000);
    const url = app.page.url();
    expect(
      url.includes('auth') || url.includes('realms') || url.includes('login'),
    ).toBeTruthy();
  });
});
"""
