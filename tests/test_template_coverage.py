"""Tests that verify the python-service-template includes valid coverage config."""

import tomllib
from pathlib import Path

import pytest
from jinja2 import Environment

TEMPLATE_DIR = (
    Path(__file__).resolve().parent.parent
    / "forge" / "templates" / "services" / "python-service-template" / "template"
)
PYPROJECT_JINJA = TEMPLATE_DIR / "pyproject.toml.jinja"


class TestTemplateCoverageConfig:
    """Verify the template's pyproject.toml.jinja produces valid coverage config."""

    @pytest.fixture(scope="class")
    def rendered_toml(self):
        """Render the Jinja template with sample values and parse as TOML."""
        raw = PYPROJECT_JINJA.read_text(encoding="utf-8")
        env = Environment()
        template = env.from_string(raw)
        rendered = template.render(
            project_name="test-service",
            project_description="A test service",
            python_version="3.13",
        )
        return tomllib.loads(rendered)

    def test_rendered_toml_is_valid(self, rendered_toml):
        assert "project" in rendered_toml

    def test_coverage_run_source(self, rendered_toml):
        run = rendered_toml["tool"]["coverage"]["run"]
        assert "src/app" in run["source"]
        assert "src/service" in run["source"]

    def test_coverage_omit_patterns(self, rendered_toml):
        omit = rendered_toml["tool"]["coverage"]["run"]["omit"]
        assert any("migrations" in p or "alembic" in p for p in omit)

    def test_coverage_report_fail_under(self, rendered_toml):
        report = rendered_toml["tool"]["coverage"]["report"]
        assert report["fail_under"] >= 40

    def test_coverage_report_show_missing(self, rendered_toml):
        report = rendered_toml["tool"]["coverage"]["report"]
        assert report["show_missing"] is True

    def test_coverage_html_directory(self, rendered_toml):
        html = rendered_toml["tool"]["coverage"]["html"]
        assert html["directory"] == "htmlcov"

    def test_pytest_cov_in_dev_deps(self, rendered_toml):
        dev_deps = rendered_toml["dependency-groups"]["dev"]
        assert any("pytest-cov" in dep for dep in dev_deps)

    def test_no_pytest_ini_conflict(self):
        """pytest.ini should not exist alongside pyproject.toml config."""
        pytest_ini = TEMPLATE_DIR / "pytest.ini"
        assert not pytest_ini.exists(), (
            "pytest.ini should be removed to avoid conflict with "
            "[tool.pytest.ini_options] in pyproject.toml"
        )
