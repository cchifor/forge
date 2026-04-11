"""TypeScript spec string templates for per-feature E2E test generation."""

FEATURE_SPEC_TEMPLATE = """\
import {{ test, expect }} from '../e2e-platform/fixtures/app';

test.describe('{Plural}', () => {{
  test.beforeEach(async ({{ app }}) => {{
    await app.nav.goToDashboard();
    await app.auth.loginAs('user');
  }});

  test.describe('List', () => {{
    test('loads and shows items', async ({{ app }}) => {{
      const suffix = Date.now().toString(36);
      await app.api.create('{plural}', {{ name: `E2E {Singular} ${{suffix}}` }});
      await app.nav.goTo('{plural}');
      await app.assertions.expectVisible('{plural}-list');
      await app.page.getByTestId('{singular}-card').first().waitFor({{ timeout: 5000 }});
    }});

    test('search filters items', async ({{ app }}) => {{
      const suffix = Date.now().toString(36);
      await app.api.create('{plural}', {{ name: `Find ${{suffix}}` }});
      await app.api.create('{plural}', {{ name: `Skip ${{suffix}}` }});
      await app.nav.goTo('{plural}');
      await app.page.getByTestId('{plural}-search-input').fill(`Find ${{suffix}}`);
      await app.page.waitForTimeout(500);
      const cards = app.page.getByTestId('{singular}-card');
      await expect(cards).toHaveCount(1);
    }});

    test('empty state when no items match', async ({{ app }}) => {{
      await app.nav.goTo('{plural}');
      await app.page.getByTestId('{plural}-search-input').fill(`nonexistent-${{Date.now()}}`);
      await app.page.waitForTimeout(500);
      const cards = app.page.getByTestId('{singular}-card');
      await expect(cards).toHaveCount(0);
    }});
  }});

  test.describe('Create', () => {{
    test('fills form and submits', async ({{ app }}) => {{
      const name = `New {Singular} ${{Date.now().toString(36)}}`;
      await app.nav.goToCreate('{plural}');
      await app.page.getByTestId('{singular}-name-input').fill(name);
      await app.page.getByTestId('{singular}-description-input').fill('Test description');
      await app.page.getByTestId('{singular}-submit-btn').click();
      await app.page.waitForURL(/\\/{plural}\\/[a-f0-9-]+/, {{ timeout: 10000 }});
    }});

    test('validates required name', async ({{ app }}) => {{
      await app.nav.goToCreate('{plural}');
      await app.page.getByTestId('{singular}-submit-btn').click();
      await app.assertions.expectUrl(/\\/{plural}\\/new/);
    }});
  }});

  test.describe('Detail', () => {{
    test('displays item data', async ({{ app }}) => {{
      const suffix = Date.now().toString(36);
      const item = await app.api.create('{plural}', {{ name: `Detail ${{suffix}}`, description: 'Detail desc' }});
      await app.nav.goTo(`{plural}/${{item.id}}`);
      await app.assertions.expectVisible('{singular}-detail');
      await app.assertions.expectText('{singular}-detail', `Detail ${{suffix}}`);
    }});

    test('edit flow', async ({{ app }}) => {{
      const suffix = Date.now().toString(36);
      const item = await app.api.create('{plural}', {{ name: `Before ${{suffix}}` }});
      await app.nav.goTo(`{plural}/${{item.id}}`);
      await app.page.getByTestId('{singular}-edit-btn').click();
      await app.page.getByTestId('{singular}-edit-name-input').clear();
      await app.page.getByTestId('{singular}-edit-name-input').fill(`After ${{suffix}}`);
      await app.page.getByTestId('{singular}-save-btn').click();
      await app.assertions.expectText('{singular}-detail', `After ${{suffix}}`);
    }});

    test('delete flow', async ({{ app }}) => {{
      const item = await app.api.create('{plural}', {{ name: `Delete ${{Date.now().toString(36)}}` }});
      await app.nav.goTo(`{plural}/${{item.id}}`);
      await app.page.getByTestId('{singular}-delete-btn').click();
      await app.page.getByTestId('confirm-dialog-confirm').click();
      await app.assertions.expectUrl(/\\/{plural}$/);
    }});
  }});
}});
"""

AUTH_SPEC_TEMPLATE = """\
import { test, expect } from '../e2e-platform/fixtures/app';

test.describe('Authentication', () => {
  test('unauthenticated user redirected to login', async ({ app }) => {
    await app.nav.goToDashboard();
    await app.page.waitForTimeout(3000);
    const url = app.page.url();
    expect(
      url.includes('auth') || url.includes('realms') || url.includes('login'),
    ).toBeTruthy();
  });

  test('login with valid credentials', async ({ app, baseURL }) => {
    // Navigate to Gatekeeper login (like clicking "Sign in" on the Vue login page)
    await app.page.goto(`${baseURL}/auth/login?redirect_uri=/`);
    await app.page.waitForSelector('#username, input[name="username"]', {
      timeout: 15000,
    });
    await app.page.fill('#username, input[name="username"]', process.env.TEST_USER || 'dev@localhost');
    await app.page.fill('#password, input[name="password"]', process.env.TEST_PASSWORD || 'devpass');
    await app.page.click('#kc-login, input[type="submit"]');
    await app.page.waitForURL((url) => !url.href.includes('/realms/'), { timeout: 15000 });
    expect(app.page.url()).toContain('app.localhost');
  });

  test('authenticated user accesses protected page', async ({ app }) => {
    await app.nav.goToDashboard();
    await app.auth.loginAs('user');
    await app.nav.goToDashboard();
    await app.page.waitForTimeout(2000);
    const content = await app.page.content();
    expect(content.length).toBeGreaterThan(500);
  });

  test('logout ends session', async ({ app }) => {
    await app.nav.goToDashboard();
    await app.auth.loginAs('user');
    await app.nav.goToDashboard();
    // Logout via Gatekeeper endpoint
    await app.page.goto('/logout', { waitUntil: 'networkidle' }).catch(() => {});
    await app.page.waitForTimeout(2000);
    // Navigate back — should be redirected to login
    await app.nav.goToDashboard();
    await app.page.waitForURL(
      (url) => url.href.includes('auth') || url.href.includes('realms') || url.href.includes('login'),
      { timeout: 10000 },
    );
  });
});
"""
