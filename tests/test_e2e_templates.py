"""Tests for E2E platform Copier template structure and spec generation."""

from pathlib import Path

import yaml

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "forge" / "templates" / "e2e-testing-template"


class TestCopierConfig:
    def test_copier_yml_exists(self):
        assert (TEMPLATE_DIR / "copier.yml").exists()

    def test_copier_yml_parses(self):
        cfg = yaml.safe_load((TEMPLATE_DIR / "copier.yml").read_text())
        assert cfg["_subdirectory"] == "template"
        assert cfg["_templates_suffix"] == ".jinja"

    def test_required_questions(self):
        cfg = yaml.safe_load((TEMPLATE_DIR / "copier.yml").read_text())
        for key in ("project_name", "features", "include_auth", "base_url", "frontend_framework"):
            assert key in cfg, f"Missing question: {key}"

    def test_hidden_variables(self):
        cfg = yaml.safe_load((TEMPLATE_DIR / "copier.yml").read_text())
        for key in ("backend_features", "keycloak_url", "keycloak_realm", "keycloak_client_id"):
            assert key in cfg, f"Missing hidden variable: {key}"
            assert cfg[key].get("when") is False


class TestTemplateStructure:
    def test_platform_fixtures(self):
        assert (TEMPLATE_DIR / "template" / "e2e-platform" / "fixtures" / "app.ts.jinja").exists()

    def test_platform_actions(self):
        actions_dir = TEMPLATE_DIR / "template" / "e2e-platform" / "actions"
        assert (actions_dir / "Navigation.ts.jinja").exists()
        assert (actions_dir / "ApiHelper.ts.jinja").exists()
        assert (actions_dir / "Assertions.ts.jinja").exists()

    def test_platform_auth(self):
        auth_dir = TEMPLATE_DIR / "template" / "e2e-platform" / "auth"
        assert (auth_dir / "AuthManager.ts.jinja").exists()
        assert (auth_dir / "global-setup.ts.jinja").exists()

    def test_playwright_config(self):
        assert (TEMPLATE_DIR / "template" / "playwright.config.ts.jinja").exists()

    def test_agent_context(self):
        assert (TEMPLATE_DIR / "template" / ".agent-context" / "prompt.md.jinja").exists()

    def test_dockerfile(self):
        assert (TEMPLATE_DIR / "template" / "Dockerfile.jinja").exists()

    def test_tests_dir(self):
        assert (TEMPLATE_DIR / "template" / "tests").is_dir()

    def test_post_generate_scripts(self):
        tasks_dir = TEMPLATE_DIR / "template" / "_tasks"
        assert (tasks_dir / "post_generate.py").exists()
        assert (tasks_dir / "answers.json.jinja").exists()
        assert (tasks_dir / "spec_templates.py").exists()


class TestSpecTemplates:
    def test_feature_spec_has_test_sections(self):
        import importlib.util
        spec_path = TEMPLATE_DIR / "template" / "_tasks" / "spec_templates.py"
        spec = importlib.util.spec_from_file_location("spec_templates", spec_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        ctx = {"plural": "items", "singular": "item", "Plural": "Items", "Singular": "Item"}
        output = mod.FEATURE_SPEC_TEMPLATE.format(**ctx)
        assert "Items List" in output
        assert "Item Create" in output
        assert "Item Detail" in output
        assert "items-list" in output
        assert "item-name-input" in output
        assert "item-submit-btn" in output
        assert "from '../e2e-platform/fixtures/app'" in output

    def test_auth_spec_has_test_sections(self):
        import importlib.util
        spec_path = TEMPLATE_DIR / "template" / "_tasks" / "spec_templates.py"
        spec = importlib.util.spec_from_file_location("spec_templates", spec_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        output = mod.AUTH_SPEC_TEMPLATE
        assert "Login" in output
        assert "Protected Access" in output
        assert "Logout" in output
        assert "from '../e2e-platform/fixtures/app'" in output
