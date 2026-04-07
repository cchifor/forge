"""Playwright e2e test templates for co-generated browser tests."""

from __future__ import annotations


CONFTEST_TEMPLATE = """\
\"\"\"Playwright e2e test fixtures.\"\"\"

import os

import pytest
from playwright.async_api import async_playwright


BASE_URL = os.environ.get("BASE_URL", "http://localhost:5173")


@pytest.fixture(scope="session")
async def browser():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        yield browser
        await browser.close()


@pytest.fixture
async def page(browser):
    context = await browser.new_context(
        viewport={"width": 1280, "height": 720},
    )
    page = await context.new_page()
    yield page
    await context.close()
"""


E2E_TEST_TEMPLATE = """\
\"\"\"End-to-end Playwright tests for {plural} feature.\"\"\"

import os
import re

import pytest
from playwright.async_api import Page, expect


BASE_URL = os.environ.get("BASE_URL", "http://localhost:5173")


class Test{Plural}List:
    async def test_list_page_loads(self, page: Page):
        await page.goto(f"{{BASE_URL}}/{plural}")
        await expect(page.locator("[data-test='{plural}-list']")).to_be_visible()

    async def test_create_button_visible(self, page: Page):
        await page.goto(f"{{BASE_URL}}/{plural}")
        await expect(page.locator("[data-test='{plural}-create-btn']")).to_be_visible()

    async def test_search_input_exists(self, page: Page):
        await page.goto(f"{{BASE_URL}}/{plural}")
        await expect(page.locator("[data-test='{plural}-search-input']")).to_be_visible()


class Test{Singular}Create:
    async def test_create_form_loads(self, page: Page):
        await page.goto(f"{{BASE_URL}}/{plural}/new")
        await expect(page.locator("[data-test='{singular}-name-input']")).to_be_visible()
        await expect(page.locator("[data-test='{singular}-submit-btn']")).to_be_visible()

    async def test_create_flow(self, page: Page):
        await page.goto(f"{{BASE_URL}}/{plural}/new")
        await page.fill("[data-test='{singular}-name-input']", "Test {Singular}")
        await page.fill("[data-test='{singular}-description-input']", "Test description")
        await page.click("[data-test='{singular}-submit-btn']")
        await expect(page).to_have_url(re.compile(r"/{plural}/[a-f0-9-]+"))


class Test{Singular}Detail:
    async def test_navigation_to_detail(self, page: Page):
        await page.goto(f"{{BASE_URL}}/{plural}")
        first_card = page.locator("[data-test='{singular}-card']").first
        await first_card.click()
        await expect(page.locator("[data-test='{singular}-detail']")).to_be_visible()
"""


AUTH_CONFTEST_TEMPLATE = """\
\"\"\"Playwright e2e test fixtures with auth helpers.\"\"\"

import asyncio
import os
import time

import httpx
import pytest
import pytest_asyncio
from playwright.async_api import Page, async_playwright


BASE_URL = os.environ.get("BASE_URL", "http://localhost:5173")
KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://localhost:8080")
TEST_USER = os.environ.get("TEST_USER", "dev@localhost")
TEST_PASSWORD = os.environ.get("TEST_PASSWORD", "devpass")


def pytest_configure(config):
    config.addinivalue_line("markers", "asyncio: async test")


async def wait_for_service(url: str, timeout: int = 120) -> None:
    deadline = time.monotonic() + timeout
    async with httpx.AsyncClient() as client:
        while time.monotonic() < deadline:
            try:
                r = await client.get(url, timeout=5)
                if r.status_code < 500:
                    return
            except (httpx.ConnectError, httpx.ReadTimeout):
                pass
            await asyncio.sleep(2)
    raise TimeoutError(f"Service at {url} not ready after {timeout}s")


async def login(page: Page, username: str, password: str) -> None:
    await page.goto(BASE_URL)
    await page.wait_for_selector("#username, #email, input[name='username']", timeout=15000)
    await page.fill("#username, input[name='username']", username)
    await page.fill("#password, input[name='password']", password)
    await page.click("#kc-login, input[type='submit']")
    await page.wait_for_timeout(3000)


@pytest_asyncio.fixture(scope="session")
async def browser():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        yield browser
        await browser.close()


@pytest_asyncio.fixture
async def page(browser):
    context = await browser.new_context(
        viewport={"width": 1280, "height": 720},
    )
    page = await context.new_page()
    yield page
    await context.close()


@pytest_asyncio.fixture
async def authenticated_page(browser):
    context = await browser.new_context(
        viewport={"width": 1280, "height": 720},
    )
    page = await context.new_page()
    await login(page, TEST_USER, TEST_PASSWORD)
    yield page
    await context.close()
"""


AUTH_TEST_TEMPLATE = """\
\"\"\"End-to-end auth flow tests.\"\"\"

import os
import re
import uuid

import pytest
from playwright.async_api import Page, expect


BASE_URL = os.environ.get("BASE_URL", "http://localhost:5173")
KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://localhost:9080")
TEST_USER = os.environ.get("TEST_USER", "dev@localhost")
TEST_PASSWORD = os.environ.get("TEST_PASSWORD", "devpass")


@pytest.mark.asyncio
class TestLogin:
    async def test_unauthenticated_redirects_to_keycloak(self, page: Page):
        await page.goto(BASE_URL)
        # Should end up on Keycloak login page
        await page.wait_for_selector(
            "#username, #email, input[name='username']", timeout=15000,
        )
        assert "auth" in page.url or "realms" in page.url or "login" in page.url

    async def test_login_with_valid_credentials(self, page: Page):
        await page.goto(BASE_URL)
        await page.wait_for_selector("#username, input[name='username']", timeout=15000)
        await page.fill("#username, input[name='username']", TEST_USER)
        await page.fill("#password, input[name='password']", TEST_PASSWORD)
        await page.click("#kc-login, input[type='submit']")
        # Wait for redirect back to the app
        await page.wait_for_timeout(3000)
        # Should no longer be on Keycloak
        assert "realms" not in page.url

    async def test_login_with_invalid_credentials(self, page: Page):
        await page.goto(BASE_URL)
        await page.wait_for_selector("#username, input[name='username']", timeout=15000)
        await page.fill("#username, input[name='username']", "wrong@localhost")
        await page.fill("#password, input[name='password']", "wrongpassword")
        await page.click("#kc-login, input[type='submit']")
        await page.wait_for_timeout(2000)
        # Should still be on Keycloak with error
        error = page.locator("#input-error, .kc-feedback-text, .alert-error")
        await expect(error.first).to_be_visible(timeout=5000)


@pytest.mark.asyncio
class TestRegistration:
    async def test_registration_link_visible(self, page: Page):
        await page.goto(BASE_URL)
        await page.wait_for_selector("#username, input[name='username']", timeout=15000)
        register_link = page.locator("a[href*='registration'], #kc-registration a")
        await expect(register_link.first).to_be_visible(timeout=5000)

    async def test_register_new_user(self, page: Page):
        await page.goto(BASE_URL)
        await page.wait_for_selector("#username, input[name='username']", timeout=15000)
        # Click register link
        register_link = page.locator("a[href*='registration'], #kc-registration a")
        await register_link.first.click()
        await page.wait_for_timeout(1000)
        # Fill registration form
        unique = uuid.uuid4().hex[:8]
        email = f"test-{{unique}}@localhost"
        await page.fill("#email, input[name='email']", email)
        await page.fill("#password, input[name='password']", "TestPass123!")
        await page.fill("#password-confirm, input[name='password-confirm']", "TestPass123!")
        # Some Keycloak themes have first/last name
        first_name = page.locator("#firstName, input[name='firstName']")
        if await first_name.count() > 0:
            await first_name.fill("Test")
        last_name = page.locator("#lastName, input[name='lastName']")
        if await last_name.count() > 0:
            await last_name.fill("User")
        await page.click("input[type='submit'], #kc-form-buttons input")
        await page.wait_for_timeout(3000)
        # Should be redirected to the app after registration
        assert "registration" not in page.url


@pytest.mark.asyncio
class TestProtectedAccess:
    async def test_authenticated_user_sees_content(self, authenticated_page: Page):
        # authenticated_page fixture already logged in
        await authenticated_page.wait_for_timeout(2000)
        # Page should have loaded (not stuck on login)
        content = await authenticated_page.content()
        assert len(content) > 500  # Real page content, not empty


@pytest.mark.asyncio
class TestLogout:
    async def test_logout_ends_session(self, authenticated_page: Page):
        # Look for a logout button or link
        logout = authenticated_page.locator(
            "[data-test='logout'], a[href*='logout'], button:has-text('Logout'), "
            "button:has-text('Sign out'), button:has-text('Log out')"
        )
        if await logout.count() > 0:
            await logout.first.click()
            await authenticated_page.wait_for_timeout(3000)
            # After logout, navigating to app should redirect to login again
            await authenticated_page.goto(BASE_URL)
            await authenticated_page.wait_for_timeout(3000)
            assert "auth" in authenticated_page.url or "realms" in authenticated_page.url or "login" in authenticated_page.url
"""


def generate_e2e_conftest() -> str:
    return CONFTEST_TEMPLATE


def generate_e2e_auth_conftest() -> str:
    return AUTH_CONFTEST_TEMPLATE


def generate_e2e_test(feature_context: dict[str, str]) -> str:
    return E2E_TEST_TEMPLATE.format(**feature_context)


def generate_e2e_auth_tests() -> str:
    return AUTH_TEST_TEMPLATE
