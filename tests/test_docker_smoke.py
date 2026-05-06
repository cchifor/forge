"""Docker smoke tests — validate that the generated ``docker-compose.yml``
is syntactically valid YAML and contains the services each scenario is
supposed to render.

Pure-YAML structural validation (no Docker subprocess). Catches generator
regressions like a service block disappearing, a missing dependency
declaration, or a malformed Jinja interpolation. Compose-spec semantic
validation (env-var interpolation, volume references resolving, etc.)
is covered by ``matrix-nightly`` lane C, which runs ``docker compose
up --wait`` against generated projects.

The previous incarnation of this file shelled out to
``docker compose config --quiet``; on Windows hosted runners the Docker
Desktop CLI's named-pipe handshake intermittently blocked for the
full 120-second timeout. Removing the subprocess gets us cross-platform
stability for ~free.
"""

from pathlib import Path

import yaml

from forge.config import BackendConfig, FrontendConfig, FrontendFramework, ProjectConfig
from forge.generator import generate


def _assert_compose_valid(project_root: Path, *, expect_services: set[str]) -> None:
    """Parse ``docker-compose.yml`` and assert it has the expected services.

    Raises ``AssertionError`` with a detailed message on any of:
    - file missing
    - YAML syntax error (via ``yaml.safe_load``)
    - top-level not a mapping
    - one of ``expect_services`` not present under ``services:``
    """
    compose_path = project_root / "docker-compose.yml"
    assert compose_path.is_file(), f"compose file missing: {compose_path}"

    raw = compose_path.read_text(encoding="utf-8")
    doc = yaml.safe_load(raw)
    assert isinstance(doc, dict), f"compose root must be a mapping, got {type(doc).__name__}"

    services = doc.get("services") or {}
    assert isinstance(services, dict), "compose 'services' must be a mapping"

    missing = expect_services - services.keys()
    assert not missing, (
        f"compose missing expected services: {missing}. Found: {sorted(services.keys())}"
    )


class TestDockerComposeConfig:
    def test_backend_only_compose_is_valid(self, tmp_path):
        """Backend-only scenario renders ``backend`` + database services."""
        config = ProjectConfig(
            project_name="smoke-test",
            output_dir=str(tmp_path),
            backends=[BackendConfig(project_name="smoke-test", server_port=5000)],
        )
        project_root = generate(config, quiet=True)
        # ``backend`` is the BackendConfig.name default; ``backend-migrate``
        # is the alembic sidecar that runs before the api can start;
        # ``postgres`` and ``traefik`` are the always-rendered shared
        # services in this compose template.
        _assert_compose_valid(
            project_root,
            expect_services={"backend", "backend-migrate", "postgres", "traefik"},
        )

    def test_fullstack_compose_is_valid(self, tmp_path):
        """Backend + Vue frontend renders the ``frontend`` service too."""
        config = ProjectConfig(
            project_name="smoke-test",
            output_dir=str(tmp_path),
            backends=[BackendConfig(project_name="smoke-test", server_port=5000)],
            frontend=FrontendConfig(
                framework=FrontendFramework.VUE,
                project_name="smoke-test",
                server_port=5173,
                features=["items"],
            ),
        )
        project_root = generate(config, quiet=True)
        _assert_compose_valid(
            project_root,
            expect_services={"backend", "frontend", "postgres", "traefik"},
        )

    def test_keycloak_compose_is_valid(self, tmp_path):
        """Keycloak-enabled scenario renders auth-stack services."""
        config = ProjectConfig(
            project_name="smoke-test",
            output_dir=str(tmp_path),
            backends=[BackendConfig(project_name="smoke-test", server_port=5000)],
            include_keycloak=True,
            keycloak_port=8080,
        )
        project_root = generate(config, quiet=True)
        _assert_compose_valid(
            project_root,
            expect_services={"backend", "postgres", "keycloak", "gatekeeper", "redis", "traefik"},
        )
