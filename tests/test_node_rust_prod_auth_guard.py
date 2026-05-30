"""Fail-closed PRODUCTION auth-config validation for Node and Rust templates.

These are forge-level STRUCTURAL source-assertion tests (the same style as
``tests/test_security_config_guards.py`` and ``tests/test_features_auth_gatekeeper.py``).
forge's CI has no Node/cargo toolchain and ``npm install`` fails in the
sandbox, so we cannot run the generated services' own vitest/cargo suites
here; behavioural verification of the guards is e2e-deferred. Instead we read
the edited template source and assert the guard exists, mirrors the Python
WS-2.1 scope/exemptions, and is wired into the config load path.

Parity target — ``SecurityConfig._reject_default_secret_in_prod`` in
``forge/templates/services/python-service-template/template/src/app/core/config/domain.py``:
  * resolves the effective env (``ENV`` / ``ENVIRONMENT`` / ``NODE_ENV`` /
    ``APP_ENV``) with a PRODUCTION fallback when unset;
  * EXEMPTS exactly {development, dev, local, test, testing};
  * fails closed when the env is production-like AND auth is enabled.

For Node/Rust the auth MIDDLEWARE reads the OIDC issuer/audience from the
``GATEKEEPER_ISSUER`` / ``SERVICE_AUDIENCE`` env vars (NOT the loaded config —
see ``forge/features/auth/templates/platform_auth_{node,rust}_middleware``), so
the config-layer guard validates those env vars directly.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATES = _REPO_ROOT / "forge" / "templates" / "services"

_NODE_SCHEMA = _TEMPLATES / "node-service-template" / "template" / "src" / "config" / "schema.ts"
_NODE_LOADER = _TEMPLATES / "node-service-template" / "template" / "src" / "config" / "loader.ts"
_RUST_CONFIG = _TEMPLATES / "rust-service-template" / "template" / "src" / "config.rs"

_RUST_DOCKERFILE = _TEMPLATES / "rust-service-template" / "template" / "Dockerfile.jinja"
_NODE_DOCKERFILE = _TEMPLATES / "node-service-template" / "template" / "Dockerfile.jinja"
_PYTHON_DOCKERFILE = (
    _TEMPLATES / "python-service-template" / "template" / "Dockerfile.jinja"
)

# The five env names that exempt the check, matching Python WS-2.1 exactly.
_EXEMPT = ("development", "dev", "local", "test", "testing")


class TestNodeProdAuthGuard:
    """Node: a zod ``.superRefine`` on the AppConfig schema fails closed when
    production-like + auth.enabled and the middleware's env vars are missing."""

    def test_schema_file_exists(self):
        assert _NODE_SCHEMA.exists(), _NODE_SCHEMA

    def test_superrefine_guard_present(self):
        src = _NODE_SCHEMA.read_text(encoding="utf-8")
        # The guard must run inside the parsed AppConfig schema so it fires in
        # loadConfig() at parse time (idiomatic Node/zod placement).
        assert "superRefine" in src

    def test_production_fallback_present(self):
        """When ENV/NODE_ENV is unset the guard must default to production
        (fail-closed posture), exactly like Python's os.getenv(... "production")."""
        src = _NODE_SCHEMA.read_text(encoding="utf-8")
        assert "production" in src
        # Reads the same env sources the loader uses.
        assert "ENV" in src and "NODE_ENV" in src

    def test_exempt_env_list_present(self):
        src = _NODE_SCHEMA.read_text(encoding="utf-8")
        for name in _EXEMPT:
            assert name in src, f"exempt env {name!r} missing from Node guard"

    def test_validates_middleware_env_vars(self):
        """The middleware reads issuer/audience from these env vars, so the
        config-layer guard must assert they are present in production."""
        src = _NODE_SCHEMA.read_text(encoding="utf-8")
        assert "GATEKEEPER_ISSUER" in src
        assert "SERVICE_AUDIENCE" in src

    def test_guard_keyed_on_auth_enabled(self):
        src = _NODE_SCHEMA.read_text(encoding="utf-8")
        # Only fail closed when auth is actually enabled (production.yaml turns
        # it on); don't over-reject when auth is off.
        assert "enabled" in src

    def test_guard_runs_inside_load_path(self):
        """superRefine is attached to AppConfigSchema, and loader.ts calls
        AppConfigSchema.parse(...), so the guard executes on every load."""
        schema = _NODE_SCHEMA.read_text(encoding="utf-8")
        loader = _NODE_LOADER.read_text(encoding="utf-8")
        # The refinement hangs off the exported AppConfig schema object.
        assert "AppConfigSchema" in schema
        assert "AppConfigSchema.parse" in loader


class TestRustProdAuthGuard:
    """Rust: ``AppConfig::validate`` is called at the end of ``load_with`` and
    returns the template's ``ConfigError`` when production-like + auth.enabled
    and the middleware's env vars are missing."""

    def test_config_file_exists(self):
        assert _RUST_CONFIG.exists(), _RUST_CONFIG

    def test_validate_fn_present(self):
        src = _RUST_CONFIG.read_text(encoding="utf-8")
        assert "fn validate" in src

    def test_validate_returns_configerror(self):
        src = _RUST_CONFIG.read_text(encoding="utf-8")
        block = src.split("fn validate", 1)[1].split("\n    pub fn ", 1)[0]
        # Reuse the template's existing error type rather than a new one.
        assert "ConfigError" in block

    def test_production_fallback_present(self):
        src = _RUST_CONFIG.read_text(encoding="utf-8")
        block = src.split("fn validate", 1)[1].split("\n    pub fn ", 1)[0]
        assert "production" in block
        # Resolves env the same way load_with does (ENV / APP_ENV).
        assert "ENV" in block and "APP_ENV" in block

    def test_exempt_env_list_present(self):
        src = _RUST_CONFIG.read_text(encoding="utf-8")
        block = src.split("fn validate", 1)[1].split("\n    pub fn ", 1)[0]
        for name in _EXEMPT:
            assert name in block, f"exempt env {name!r} missing from Rust guard"

    def test_validates_middleware_env_vars(self):
        src = _RUST_CONFIG.read_text(encoding="utf-8")
        block = src.split("fn validate", 1)[1].split("\n    pub fn ", 1)[0]
        assert "GATEKEEPER_ISSUER" in block
        assert "SERVICE_AUDIENCE" in block

    def test_guard_keyed_on_auth_enabled(self):
        src = _RUST_CONFIG.read_text(encoding="utf-8")
        block = src.split("fn validate", 1)[1].split("\n    pub fn ", 1)[0]
        assert "self.security.auth.enabled" in block or "auth.enabled" in block

    def test_validate_called_in_load_path(self):
        """load_with must invoke validate() before returning, so a bad prod
        config fails at load (fail-fast), ahead of middleware bootstrap."""
        src = _RUST_CONFIG.read_text(encoding="utf-8")
        load_with = src.split("pub fn load_with", 1)[1]
        assert ".validate()" in load_with or "validate()?" in load_with


class TestDockerfileEnvParity:
    """All three production service images must set the runtime env explicitly.

    The config loader treats an UNSET env as the ``development`` profile, which
    ships auth disabled. Python sets ``ENV=production`` and Node sets
    ``NODE_ENV=production`` in their Dockerfiles; the Rust image previously set
    only ``PORT``, so a containerized Rust service silently booted in
    development (fail-open). Pin the env in all three so the prod profile +
    fail-closed guard apply by default."""

    def test_python_dockerfile_sets_prod_env(self):
        src = _PYTHON_DOCKERFILE.read_text(encoding="utf-8")
        assert "ENV ENV=production" in src

    def test_node_dockerfile_sets_prod_env(self):
        src = _NODE_DOCKERFILE.read_text(encoding="utf-8")
        assert "ENV NODE_ENV=production" in src

    def test_rust_dockerfile_sets_prod_env(self):
        """Regression guard for the parity gap: the Rust image must pin the
        runtime env so it does not default to the development profile."""
        src = _RUST_DOCKERFILE.read_text(encoding="utf-8")
        assert "ENV ENV=production" in src, (
            "Rust Dockerfile must set ENV=production (else the container loads "
            "the development profile and fails open with auth disabled)"
        )
