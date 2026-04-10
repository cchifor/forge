"""TypeScript spec string templates for per-feature E2E test generation."""

FEATURE_SPEC_TEMPLATE = """\
import {{ test, expect }} from '../e2e-platform/fixtures/app';

test.describe('{Plural}', () => {{
  test.beforeEach(async ({{ app }}) => {{
    await app.auth.loginAs('user');
  }});

  test.describe('List', () => {{
    test('loads and shows items', async ({{ app }}) => {{
      // Create an item via API so the list isn't empty
      await app.api.create('{plural}', {{ name: 'E2E {Singular}', description: 'Created by E2E test' }});
      await app.nav.goTo('{plural}');
      await app.assertions.expectVisible('{plural}-list');
      await app.assertions.expectVisible('{singular}-card');
    }});

    test('search filters items', async ({{ app }}) => {{
      await app.api.create('{plural}', {{ name: 'Searchable {Singular}' }});
      await app.api.create('{plural}', {{ name: 'Other {Singular}' }});
      await app.nav.goTo('{plural}');
      await app.page.getByTestId('{plural}-search-input').fill('Searchable');
      await app.page.waitForTimeout(500); // debounce
      const cards = app.page.getByTestId('{singular}-card');
      await expect(cards).toHaveCount(1);
    }});

    test('empty state when no items match', async ({{ app }}) => {{
      await app.nav.goTo('{plural}');
      await app.page.getByTestId('{plural}-search-input').fill('nonexistent-xyz-12345');
      await app.page.waitForTimeout(500);
      const cards = app.page.getByTestId('{singular}-card');
      await expect(cards).toHaveCount(0);
    }});
  }});

  test.describe('Create', () => {{
    test('fills form and submits', async ({{ app }}) => {{
      await app.nav.goToCreate('{plural}');
      await app.page.getByTestId('{singular}-name-input').fill('New {Singular}');
      await app.page.getByTestId('{singular}-description-input').fill('Test description');
      await app.page.getByTestId('{singular}-submit-btn').click();
      await app.assertions.expectUrl(/\\/{plural}\\/[a-f0-9-]+/);
    }});

    test('validates required name', async ({{ app }}) => {{
      await app.nav.goToCreate('{plural}');
      // Leave name empty, click submit
      await app.page.getByTestId('{singular}-submit-btn').click();
      // Should stay on create page (not redirect)
      await app.assertions.expectUrl(/\\/{plural}\\/new/);
    }});
  }});

  test.describe('Detail', () => {{
    test('displays item data', async ({{ app }}) => {{
      const item = await app.api.create('{plural}', {{ name: 'Detail {Singular}', description: 'Detail desc' }});
      await app.nav.goTo(`{plural}/${{item.id}}`);
      await app.assertions.expectVisible('{singular}-detail');
      await app.assertions.expectText('{singular}-detail', 'Detail {Singular}');
    }});

    test('edit flow', async ({{ app }}) => {{
      const item = await app.api.create('{plural}', {{ name: 'Before Edit' }});
      await app.nav.goTo(`{plural}/${{item.id}}`);
      await app.page.getByTestId('{singular}-edit-btn').click();
      await app.page.getByTestId('{singular}-edit-name-input').clear();
      await app.page.getByTestId('{singular}-edit-name-input').fill('After Edit');
      await app.page.getByTestId('{singular}-save-btn').click();
      await app.assertions.expectText('{singular}-detail', 'After Edit');
    }});

    test('delete flow', async ({{ app }}) => {{
      const item = await app.api.create('{plural}', {{ name: 'To Delete' }});
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

  test('authenticated user accesses protected page', async ({ app }) => {
    await app.auth.loginAs('user');
    await app.nav.goToDashboard();
    await app.page.waitForTimeout(2000);
    const content = await app.page.content();
    expect(content.length).toBeGreaterThan(500);
  });

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
